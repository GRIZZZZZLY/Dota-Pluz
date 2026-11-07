"""The long-lived objects the API routes share, kept on ``app.state.services``."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi import Request

from d2bg import paths
from d2bg.context import AppContext
from d2bg.copilot import hud
from d2bg.copilot.pipeline import Copilot
from d2bg.copilot.store import CopilotStore
from d2bg.gsi.recorder import Player, Recorder
from d2bg.live.engine import LiveEngine
from d2bg.matches.postgame import PostGame


@dataclass
class RefreshJob:
    running: bool = False
    steps: list[str] = field(default_factory=list)
    progress: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class Services:
    def __init__(self, ctx: AppContext, port: int) -> None:
        self.ctx = ctx
        self.port = port
        self.lock = threading.Lock()
        self.recorder = Recorder(paths.recordings_dir(), keep=ctx.settings.get().keep_recordings)
        self.postgame = PostGame(ctx)
        self.player: Player | None = None
        self.refresh = RefreshJob()
        self.copilot = Copilot(ctx, CopilotStore(paths.copilot_db_file()))
        self.copilot_error: str | None = None
        # When d2bg-cv last asked for the status: the screen reader is running if that was recent.
        self.cv_seen_at: float | None = None
        # (match id, mode) told by the gold rate; the last real game's mode survives a restart.
        self.mode_file = paths.user_dir() / "last_game_mode.txt"
        last = self.mode_file.read_text(encoding="utf-8").strip() if self.mode_file.exists() else ""
        self.detected_mode: tuple[str | None, hud.Mode] | None = (
            (None, "turbo" if last == "turbo" else "normal") if last in ("turbo", "normal") else None
        )
        self._probe: tuple[str | None, hud.ModeProbe] = (None, hud.ModeProbe())
        self.engine = LiveEngine(
            ctx, on_post_game=self._post_game, on_account=self._account, on_payload=self._on_payload
        )

    def _post_game(self, match_id: str) -> None:
        if self.ctx.settings.get().auto_post_game:
            self.postgame.start(match_id)

    def _account(self, account_id: int) -> None:
        self.ctx.settings.set_account_if_missing(account_id)

    def _record(self, payload: Mapping[str, Any], source: str) -> None:
        if source == "game" and self.ctx.settings.get().record_gsi:
            self.recorder.write(payload)

    def _on_payload(self, payload: Mapping[str, Any], source: str) -> None:
        self._record(payload, source)
        self._detect_mode(source)
        recording = self.recorder.current if source == "game" and self.ctx.settings.get().record_gsi else None
        self.refresh_copilot(source, (recording.name, self.recorder.lines) if recording else None)

    def _detect_mode(self, source: str) -> None:
        s, match = self.engine.state, self.engine.match_id
        if s is None or s.stats is None or s.clock is None or s.phase != "in_game" or s.clock < 0:
            return
        if self.detected_mode and self.detected_mode[0] == match:
            return
        if self._probe[0] != match:
            self._probe = (match, hud.ModeProbe())
        mode = self._probe[1].feed(s.clock, s.stats.gold_reliable, s.stats.kills + s.stats.assists)
        if mode is not None:
            self.detected_mode = (match, mode)
            if source == "game":
                self.mode_file.write_text(mode, encoding="utf-8")

    def game_mode(self) -> tuple[hud.Mode | None, str]:
        """Turbo or normal, and how that is known: his setting, this game's gold rate, or the last game."""
        setting = self.ctx.settings.get().game_mode
        if setting != "auto":
            return setting, "setting"
        if self.detected_mode is None:
            return None, "unknown"
        match, mode = self.detected_mode
        return mode, "gold_rate" if match is not None and match == self.engine.match_id else "last_game"

    def refresh_copilot(self, source: str, recording: tuple[str, int] | None = None) -> None:
        try:
            self.copilot.observe(self.engine, source, recording)
        except Exception as exc:  # the Copilot is an add-on: its failure never stops the live view
            self.copilot_error = f"{type(exc).__name__}: {exc}"

    def start_refresh(self, steps: list[str], **kwargs: Any) -> RefreshJob:
        """Run refresh steps on a thread; the Setup page follows ``self.refresh``. One job at a time."""
        from d2bg.pipeline.refresh import Refresher

        with self.lock:
            if self.refresh.running:
                raise RuntimeError("Обновление уже идёт")
            self.refresh = RefreshJob(running=True, steps=steps)
        job = self.refresh

        def progress(step: str, done: int, total: int, message: str) -> None:
            job.progress = {"step": step, "done": done, "total": total, "message": message}

        def run() -> None:
            try:
                refresher = Refresher(
                    self.ctx.client, paths.refreshed_data_dir(), progress, seed_dir=paths.snapshot_dir()
                )
                for result in refresher.run(steps, **kwargs):
                    job.results.append(asdict(result))
                self.ctx.reload()
            except Exception as exc:  # reported to the UI, not swallowed
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.running = False

        threading.Thread(target=run, name="data-refresh", daemon=True).start()
        return job

    def turbo_due(self, every_s: float = 20 * 3600) -> bool:
        """Background Turbo collection is on and the last one is older than ``every_s``."""
        if not self.ctx.settings.get().turbo_collect:
            return False
        manifest = paths.refreshed_data_dir() / "manifest.json"
        try:
            last = json.loads(manifest.read_text(encoding="utf-8"))["files"]["turbo_builds.json"][
                "generated_at"
            ]
        except (OSError, ValueError, KeyError):
            return True
        return time.time() - float(last) > every_s

    def start_player(self, frames: list[tuple[float, dict[str, Any]]], source: str, speed: float) -> None:
        with self.lock:
            if self.player is not None:
                self.player.stop()
            self.engine.reset()

            def feed(payload: dict[str, Any]) -> None:
                self.engine.ingest(payload, source=source)

            self.player = Player(frames, feed, speed=speed)
            self.player.start()

    def stop_player(self) -> None:
        with self.lock:
            if self.player is not None:
                self.player.stop()
                self.player = None

    def close(self) -> None:
        self.stop_player()
        self.recorder.close()
        self.copilot.store.close()


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc
