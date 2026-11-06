"""Copilot status, its journal of recommendations, and the draft read from the screen or corrected by
hand. Nothing here talks to the game."""

from __future__ import annotations

import hmac
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from d2bg.api.services import Services, services
from d2bg.copilot.models import DraftObservation, ManualDraft, RecStatus

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
        "providers": {"baseline": {"configured": True, "online": True}},
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


@router.post("/recommendations/{rec_id}/dismiss")
def dismiss(svc: Svc, rec_id: str) -> dict[str, bool]:
    """The player hid this advice. It stays hidden until the candidate changes."""
    if not svc.copilot.store.set_status(rec_id, "dismissed"):
        raise HTTPException(404, "Нет показанного совета с таким id")
    return {"ok": True}
