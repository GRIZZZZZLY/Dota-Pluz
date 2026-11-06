"""d2bg-cv commands.

- ``run``: while d2bg reports the draft of a real game, read the draft screen twice a second and post
  what changed to d2bg. Outside the draft nothing is captured.
- ``templates``: download every hero's portrait from Valve's public CDN (the pictures the d2bg UI
  shows) as recognition templates.
- ``snap``: save a draft-screen frame every few seconds while the draft runs, for calibration and
  for recognition tests.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2
import httpx
import mss
import numpy as np
import typer

from d2bg import paths
from d2bg.datastore import DataStore
from d2bg.settings import SettingsStore
from d2bg_cv import calibrate
from d2bg_cv.recognize import Image, Recognizer, Votes, read_screen

DRAFT_PHASES = frozenset({"hero_selection", "strategy"})
DEFAULT_SERVER = "http://127.0.0.1:4242"
app = typer.Typer(add_completion=False, no_args_is_help=True, help="Read the Dota 2 draft screen for d2bg.")


def cv_dir() -> Path:
    return paths.user_dir() / "cv"


def draft_running(status: dict[str, Any]) -> bool:
    """Capture only during the draft of a real game, never for a demo or a replay."""
    return status.get("mode") == "game" and status.get("phase") in DRAFT_PHASES


def waiting_reason(status: dict[str, Any] | None, server: str) -> str:
    """Why nothing is captured yet, in words he can act on."""
    if status is None:
        return f"Сервер d2bg не отвечает ({server}). Запустите run.cmd."
    fresh = status.get("state") == "ok"
    if fresh and status.get("mode") in ("demo", "replay"):
        return "Сейчас идёт демо-матч или запись, а не игра. Остановите их на странице «Матч»."
    if not fresh or status.get("mode") != "game":
        return (
            "Игра пока не присылает данные (GSI). В главном меню Dota может молчать: начните матч или "
            "лобби. Если и там тишина, проверьте конфиг на странице «Подключение» и перезапустите Dota."
        )
    return f"Игра на связи, фаза «{status.get('phase')}». Жду выбор героев."


class Reader:
    """Recognition, votes and per-slot memory for one ``run``."""

    def __init__(self, recognizer: Recognizer, hero_ids: dict[str, int]) -> None:
        self.recognizer = recognizer
        self.hero_ids = hero_ids
        self.votes = Votes()
        self.memo: dict[tuple[str, int], Any] = {}
        self.message = ""

    def read(self, img: Image) -> dict[str, Any] | None:
        cal = calibrate.topbar(img)
        if cal is None:
            self.message = "Карточки пиков на экране не найдены."
            return None
        self.message = ""
        return read_screen(img, cal, self.recognizer, self.votes, self.hero_ids, self.memo)


def grab(sct: Any, monitor: int) -> Image:
    monitors = sct.monitors
    shot = sct.grab(monitors[monitor] if monitor < len(monitors) else monitors[1])
    return np.ascontiguousarray(np.asarray(shot)[:, :, :3])  # BGRA -> BGR


@app.command()
def run(
    server: str = DEFAULT_SERVER,
    monitor: int = typer.Option(1, help="mss monitor number: 1 is the main screen."),
    interval: float = 0.5,
) -> None:  # pragma: no cover - needs a screen and a running game
    """Read the draft screen during real drafts and send the picks to d2bg."""
    recognizer = Recognizer.from_dir(cv_dir() / "templates")
    if not recognizer.templates:
        typer.echo("Первый запуск: скачиваю портреты героев с CDN Valve (около минуты)…")
        templates()
        recognizer = Recognizer.from_dir(cv_dir() / "templates")
    token = SettingsStore().get().gsi_token
    reader = Reader(recognizer, {h.key: h.id for h in DataStore().heroes})
    last: tuple[Any, ...] | None = None
    typer.echo("Жду драфт. Ctrl+C — остановить.")
    said = ""
    with httpx.Client(base_url=server, timeout=3) as client, mss.mss() as sct:
        while True:
            status = _status(client)
            if status is None or not draft_running(status):
                said = _say(waiting_reason(status, server), said)
                reader.votes.reset()
                reader.memo.clear()
                last = None
                time.sleep(1)
                continue
            said = _say("Драфт идёт, читаю экран.", said)
            obs = reader.read(grab(sct, monitor))
            key = (obs["radiant"], obs["dire"], obs["bans"], obs["unknown_slots"]) if obs else None
            if obs and key != last:
                r = client.post("/api/copilot/draft/observation", json=obs, headers={"x-d2bg-token": token})
                if r.status_code == 200:
                    last = key
                typer.echo(f"{time.strftime('%H:%M:%S')} {r.status_code} {key} {reader.message}")
            time.sleep(interval)


@app.command()
def templates() -> None:  # pragma: no cover - downloads from the CDN
    """Download hero portraits from Valve's public CDN into <user folder>/cv/templates."""
    target = cv_dir() / "templates"
    got = 0
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for hero in DataStore().heroes:
            out = target / hero.key / "cdn.png"
            if not hero.img or out.exists():
                continue
            r = client.get(hero.img)
            if r.status_code == 200:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(r.content)
                got += 1
            time.sleep(0.05)
    typer.echo(f"Новых шаблонов: {got}. Папка: {target}")


@app.command()
def snap(
    server: str = DEFAULT_SERVER,
    monitor: int = 1,
    wait: float = 600.0,
    every: float = typer.Option(5.0, help="Seconds between frames while the draft runs."),
    count: int = typer.Option(30, help="At most this many frames."),
) -> None:  # pragma: no cover - needs a screen and a running game
    """Wait for a draft, then save a frame every few seconds until it ends (for calibration and tests)."""
    deadline = time.time() + wait
    said, saved = "", 0
    typer.echo(f"Жду драфт до {int(wait // 60)} мин. Ctrl+C — остановить.")
    with httpx.Client(base_url=server, timeout=3) as client, mss.mss() as sct:
        while saved < count:
            status = _status(client)
            if status is not None and draft_running(status):
                path = cv_dir() / "snaps" / f"draft-{time.strftime('%Y%m%d-%H%M%S')}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(path), grab(sct, monitor))
                saved += 1
                typer.echo(f"{time.strftime('%H:%M:%S')} Сохранено ({saved}): {path}")
                time.sleep(every)
                continue
            if saved:
                break  # the draft is over
            if time.time() > deadline:
                typer.echo("Драфт так и не начался, ничего не сохранено.", err=True)
                raise typer.Exit(1)
            said = _say(waiting_reason(status, server), said)
            time.sleep(1)
    typer.echo(f"Готово, кадров: {saved}.")


def _status(client: httpx.Client) -> dict[str, Any] | None:
    try:
        doc: dict[str, Any] = client.get("/api/copilot/status", headers={"x-d2bg-client": "cv"}).json()
    except (httpx.HTTPError, ValueError):
        return None
    return doc


def _say(text: str, said: str) -> str:
    """Print a status line only when it changes."""
    if text != said:
        typer.echo(f"{time.strftime('%H:%M:%S')} {text}")
    return text


def main() -> None:  # pragma: no cover - console entry point
    app()
