"""Copilot status and its journal of recommendations. Read only; nothing here talks to the game."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from d2bg.api.services import Services, services

router = APIRouter(prefix="/api/copilot")
Svc = Annotated[Services, Depends(services)]


@router.get("/status")
def status(svc: Svc) -> dict[str, Any]:
    """GSI health, data freshness, the current GameContext with its sources, and the providers."""
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
        "error": svc.copilot_error,
    }


@router.get("/recommendations")
def recommendations(
    svc: Svc, match_id: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 50
) -> list[dict[str, Any]]:
    """Newest first, for ``match_id`` or the current match."""
    match = match_id or svc.copilot.context.match_id
    if match is None:
        return []
    return [r.model_dump() for r in svc.copilot.store.recommendations(match, limit)]
