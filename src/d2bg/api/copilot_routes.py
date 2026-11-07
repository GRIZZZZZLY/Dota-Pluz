"""Copilot status, its journal of recommendations, and the draft read from the screen or corrected by
hand. Nothing here talks to the game."""

from __future__ import annotations

import hmac
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from d2bg.api.services import Services, services
from d2bg.copilot import coach, hud
from d2bg.copilot.models import DraftObservation, ManualDraft, RecStatus
from d2bg.copilot.providers import ProviderError

router = APIRouter(prefix="/api/copilot")
Svc = Annotated[Services, Depends(services)]
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


def _check_heroes(svc: Services, *groups: list[int]) -> None:
    unknown = sorted({h for g in groups for h in g if svc.ctx.data.heroes.get(h) is None})
    if unknown:
        raise HTTPException(422, f"Неизвестные id героев: {unknown}")


@router.post("/draft/observation")
def draft_observation(
    request: Request,
    svc: Svc,
    body: DraftObservation,
    x_d2bg_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    """d2bg-cv posts what it read on the draft screen. Only from this computer, with the GSI token,
    so no other program can feed the app a draft (the same rule as /gsi)."""
    if request.client is None or request.client.host not in LOOPBACK:
        raise HTTPException(403, "Драфт с экрана принимается только с этого компьютера")
    if not x_d2bg_token or not hmac.compare_digest(x_d2bg_token, svc.ctx.settings.get().gsi_token):
        raise HTTPException(403, "Неверный токен")
    _check_heroes(svc, body.radiant, body.dire, body.bans)
    if svc.player is not None and svc.player.running:
        return {"ok": True, "used": False}  # a replay owns the live view
    if not svc.engine.add_screen_draft(
        body.radiant, body.dire, body.bans, body.unknown_slots, body.confidence
    ):
        raise HTTPException(409, "Матч сейчас не идёт")
    state = svc.engine.state
    match_id = svc.engine.match_id or ""
    svc.copilot.store.add_draft_observation(
        match_id, time.time(), state.clock if state else None, "cv", body.model_dump()
    )
    svc.refresh_copilot(svc.engine.source)
    return {"ok": True, "used": True}


@router.post("/draft/manual")
def draft_manual(svc: Svc, body: ManualDraft) -> dict[str, bool]:
    """His board on the Draft page. Heroes he removed stop counting for the Copilot's advice."""
    if body.match_id != svc.engine.match_id:
        raise HTTPException(409, "Эта доска драфта относится к другому матчу")
    _check_heroes(svc, body.allies, body.enemies, body.bans, body.removed)
    if not svc.engine.correct_draft(body.allies, body.enemies, body.bans, body.removed):
        raise HTTPException(409, "Матч сейчас не идёт")
    state = svc.engine.state
    svc.copilot.store.add_draft_observation(
        body.match_id, time.time(), state.clock if state else None, "manual", body.model_dump()
    )
    svc.refresh_copilot(svc.engine.source)
    return {"ok": True}


@router.get("/status")
def status(svc: Svc, x_d2bg_client: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """GSI health, data freshness, the current GameContext with its sources, and the providers."""
    now = time.time()
    if x_d2bg_client == "cv":
        svc.cv_seen_at = now
    conn = svc.engine.connection()
    if not conn["packets"]:
        state = "no_data"
    elif not conn["connected"]:
        state = "stale"  # no GSI for 30 s: earlier advice may only be shown as outdated
    else:
        state = "ok"
    context = svc.copilot.context.model_copy(update={"data_age_s": conn["last_packet_age"]})
    heroes_file = svc.ctx.data.status()["files"].get("heroes.json", {})
    return {
        "state": state,
        "mode": svc.engine.source,  # game, demo, replay or none: demo data is never shown as real
        "connection": conn,
        "match_id": context.match_id,
        "phase": context.phase,
        "patch": {"data": svc.ctx.data.patch, "timers": svc.ctx.timer_patch},
        "snapshot_generated_at": heroes_file.get("generated_at"),
        "context": context.model_dump(),
        "providers": svc.hybrid.status(context.match_id),
        "journal": svc.copilot.store.counts(),
        "rejected": svc.copilot.rejected,
        "screen_reader": {"running": svc.cv_seen_at is not None and now - svc.cv_seen_at < 5},
        "error": svc.copilot_error,
    }


@router.get("/recommendations")
def recommendations(
    svc: Svc,
    match_id: str | None = None,
    status: RecStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict[str, Any]]:
    """Newest first, for ``match_id`` or the current match. ``status=suggested`` is what to show now."""
    match = match_id or svc.copilot.context.match_id
    if match is None:
        return []
    return [r.model_dump() for r in svc.copilot.store.recommendations(match, limit, status)]


@router.post("/providers/test")
def providers_test(request: Request, svc: Svc) -> dict[str, Any]:
    """One tiny real call to each cloud model, by his button only (it costs a fraction of a cent)."""
    if request.client is None or request.client.host not in LOOPBACK:
        raise HTTPException(403, "Проверка облачных моделей — только с этого компьютера")
    return svc.hybrid.test()


@router.get("/hud")
def hud_hints(svc: Svc) -> dict[str, Any]:
    """What the overlay's small widgets show now; a None widget stays hidden."""
    match = svc.copilot.context.match_id
    recs = svc.copilot.store.recommendations(match, 20, "suggested") if match else []
    mode, mode_source = svc.game_mode()
    return hud.build(svc.ctx, svc.engine, svc.ctx.settings.get(), recs, mode, mode_source)


class SeenBody(BaseModel):
    ids: list[str] = Field(max_length=50)


@router.post("/recommendations/seen")
def recommendations_seen(svc: Svc, body: SeenBody) -> dict[str, int]:
    """The UI put this advice on his screen (the coach tells advice he saw from advice he never saw)."""
    return {"marked": svc.copilot.store.mark_seen(body.ids, time.time())}


@router.get("/matches")
def journal_matches(svc: Svc, limit: Annotated[int, Query(ge=1, le=200)] = 30) -> list[dict[str, Any]]:
    """His matches in the Copilot journal, newest first, with the reports each one has."""
    out = []
    for m in svc.copilot.store.matches(limit):
        hero = svc.ctx.data.heroes.get(m["hero_id"]) if m.get("hero_id") else None
        out.append({**m, "hero": hero.name if hero else None})
    return out


@router.get("/matches/{match_id}/review")
def match_review(svc: Svc, match_id: str, rebuild: bool = False) -> dict[str, Any]:
    """The coach's report (facts), the analyst's reading (ai, if any) and problems that keep coming back."""
    if svc.copilot.store.match(match_id) is None and svc.copilot.store.report(match_id, "facts") is None:
        raise HTTPException(404, "Этого матча нет в журнале Copilot")
    return svc.review(match_id, rebuild=rebuild)


@router.post("/matches/{match_id}/analyze")
def match_analyze(request: Request, svc: Svc, match_id: str) -> dict[str, Any]:
    """Ask the analyst again (by his button; it costs a fraction of a rouble)."""
    if request.client is None or request.client.host not in LOOPBACK:
        raise HTTPException(403, "Разбор через DeepSeek — только с этого компьютера")
    if svc.copilot.store.match(match_id) is None:
        raise HTTPException(404, "Этого матча нет в журнале Copilot")
    try:
        return svc.analyze(match_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(502, f"DeepSeek: {exc.kind}: {exc}") from exc


@router.get("/goals")
def goals(svc: Svc) -> dict[str, Any]:
    """His latest practice goals and the problems that came back in recent games."""
    return {"goals": svc.copilot.store.goals(10), "recurring": coach.recurring(svc.copilot.store)}


@router.get("/diagnostics")
def diagnostics(svc: Svc) -> dict[str, Any]:
    """What a bug report needs, without secrets: no tokens, no keys, the home folder shown as ~."""
    import json
    import platform
    import sys
    from dataclasses import asdict
    from pathlib import Path

    from d2bg import __version__

    report = {
        "generated_at": time.time(),
        "app_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "patch": svc.ctx.data.patch,
        "settings": svc.ctx.settings.get().public_view(),
        "data": svc.ctx.data.status(),
        "gsi": svc.engine.connection(),
        "copilot": {
            "journal": svc.copilot.store.counts(),
            "rejected": svc.copilot.rejected,
            "error": svc.copilot_error,
            "providers": svc.hybrid.status(svc.copilot.context.match_id),
            "provider_usage": svc.copilot.store.provider_usage(),
            "hybrid_error": svc.hybrid.last_error,
        },
        "screen_reader": {"running": svc.cv_seen_at is not None and time.time() - svc.cv_seen_at < 5},
        "refresh": asdict(svc.refresh),
        "postgame": svc.postgame.status(),
    }
    text = json.dumps(report, ensure_ascii=False, default=str)
    for secret in (svc.ctx.settings.get().gsi_token, svc.ctx.settings.get().lan_token):
        text = text.replace(secret, "***")
    home = str(Path.home())
    text = text.replace(json.dumps(home)[1:-1], "~").replace(home, "~")
    out: dict[str, Any] = json.loads(text)
    return out


@router.delete("/history")
def delete_history(request: Request, svc: Svc) -> dict[str, bool]:
    """Forget every match, piece of advice, report and goal in the journal (recordings stay)."""
    if request.client is None or request.client.host not in LOOPBACK:
        raise HTTPException(403, "Удалить историю можно только с этого компьютера")
    svc.copilot.store.delete_history()
    return {"ok": True}


@router.post("/recommendations/{rec_id}/dismiss")
def dismiss(svc: Svc, rec_id: str) -> dict[str, bool]:
    """The player hid this advice. It stays hidden until the candidate changes."""
    if not svc.copilot.store.set_status(rec_id, "dismissed"):
        raise HTTPException(404, "Нет показанного совета с таким id")
    return {"ok": True}
