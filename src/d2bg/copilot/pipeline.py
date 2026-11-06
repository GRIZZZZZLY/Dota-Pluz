"""Copilot pipeline, stage 1: live state -> GameContext -> events -> baseline recommendations -> SQLite.

It runs after each LiveEngine update (the engine's ``on_payload`` hook) and changes nothing the engine
does. Recommendations are recomputed only when an event happens, never on every tick, and stored
only when the candidate changes. The baseline here re-labels what LiveEngine already computes (the pro
item order and the most common pro skill at each step); the checks that a skill can be levelled and
the item rules arrive with the stage 2 validator.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from d2bg.context import AppContext
from d2bg.copilot.models import (
    ConfidenceKind,
    CopilotEvent,
    EventType,
    GameContext,
    Recommendation,
    RecType,
    Source,
)
from d2bg.copilot.store import CopilotStore
from d2bg.gsi.state import unspent_skill_points
from d2bg.live.engine import LiveEngine

BASELINE_VERSION = "baseline-0.1"


def build_context(engine: LiveEngine, app: AppContext, now: float) -> GameContext:
    """The engine's current state as a GameContext, each field group tagged with its source."""
    patch = app.data.patch
    s = engine.state
    if s is None:
        return GameContext(patch=patch, sources=_sources(patch="snapshot"))
    # The engine keeps the last draft after a match ends; outside a match it is not this context's.
    draft = (engine.snapshot().get("draft") or {}) if s.match_id else {}
    allies, enemies = list(draft.get("allies") or []), list(draft.get("enemies") or [])
    positions = app.settings.get().positions
    position = positions[0] if len(positions) == 1 else None
    hero = s.hero if s.hero and s.hero.id else None
    st = s.stats
    c = GameContext(
        match_id=s.match_id,
        patch=patch,
        phase=s.phase,
        time_s=s.clock,
        team=s.team,
        hero_id=hero.id if hero else None,
        hero_key=hero.key if hero else None,
        position=position,
        level=hero.level if hero else None,
        alive=hero.alive if hero else None,
        available_skill_points=unspent_skill_points(s) if hero else None,
        learned_skills={a.key: a.level for a in s.abilities} if hero else {},
        allies=allies,
        enemies_visible=enemies,
        inventory=[i.key for i in s.inventory],
        backpack=[i.key for i in s.backpack],
        stash=[i.key for i in s.stash],
        gold=st.gold if st else None,
        buyback_cost=hero.buyback_cost if hero else None,
        gpm=st.gpm if st else None,
        xpm=st.xpm if st else None,
        last_hits=st.last_hits if st else None,
        data_age_s=None if engine.last_packet_at is None else round(now - engine.last_packet_at, 3),
        sources=_sources(
            match="gsi" if s.match_id else "unknown",
            patch="snapshot",
            hero="gsi" if hero else "unknown",
            position="manual" if position else "unknown",
            draft="gsi" if allies or enemies else "unknown",
            economy="gsi" if st else "unknown",
        ),
    )
    c.evidence_ids = _evidence(c, app)
    return c


def _sources(**known: Source) -> dict[str, Source]:
    return {**GameContext().sources, **known}


def _evidence(c: GameContext, app: AppContext) -> list[str]:
    """Ids of the facts a recommendation may cite. A citation outside this list is rejected."""
    out = []
    if c.hero_key and c.hero_id:
        out.append(f"hero:{c.hero_key}")
        if app.data.per_hero("pro_builds.json", c.hero_id):
            out.append(f"build:{c.hero_key}")
    if c.level:
        out.append(f"level:{c.level}")
    out += [f"inventory:{k}" for k in sorted(set(c.owned))]
    for prefix, ids in (("ally", c.allies), ("enemy", c.enemies_visible)):
        for hero_id in ids:
            hero = app.data.heroes.get(hero_id)
            if hero:
                out.append(f"{prefix}:{hero.key}")
    return out


def diff_events(prev: GameContext | None, cur: GameContext) -> list[CopilotEvent]:
    """What changed between two contexts. A new match yields only ``match_started``: when the app
    starts in the middle of a game, the state is restored as it is, not replayed as old events."""
    if not cur.match_id:
        return []
    out: list[CopilotEvent] = []

    def add(kind: EventType, detail: str = "") -> None:
        out.append(
            CopilotEvent(type=kind, match_id=cur.match_id or "", game_time_s=cur.time_s, detail=detail)
        )

    if prev is None or prev.match_id != cur.match_id:
        add("match_started", cur.phase or "")
        return out
    if cur.phase != prev.phase:
        add("phase_changed", cur.phase or "")
    if cur.hero_id and cur.hero_id != prev.hero_id:
        add("hero_selected", cur.hero_key or str(cur.hero_id))
    if cur.level and prev.level and cur.level > prev.level:
        add("skill_point_gained", str(cur.level))
    for key, level in cur.learned_skills.items():
        if level > prev.learned_skills.get(key, 0):
            add("skill_leveled", f"{key}:{level}")
    now_owned, before = Counter(cur.owned), Counter(prev.owned)
    out_items = [f"+{k}" for k in sorted(now_owned - before)] + [f"-{k}" for k in sorted(before - now_owned)]
    for detail in out_items:
        add("item_changed", detail)
    if set(cur.allies) != set(prev.allies) or set(cur.enemies_visible) != set(prev.enemies_visible):
        add("draft_changed", f"allies={len(cur.allies)} enemies={len(cur.enemies_visible)}")
    if prev.alive is True and cur.alive is False:
        add("death")
    elif prev.alive is False and cur.alive is True:
        add("respawn")
    if cur.phase == "post_game" and prev.phase != "post_game":
        add("match_finished")
    return out


def context_hash(c: GameContext) -> str:
    """Hash of the inputs a recommendation depends on (not the clock, not gold)."""
    key = {
        "hero": c.hero_id,
        "level": c.level,
        "skills": c.learned_skills,
        "owned": sorted(c.owned),
        "allies": sorted(c.allies),
        "enemies": sorted(c.enemies_visible),
        "position": c.position,
        "patch": c.patch,
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def baseline(c: GameContext, snap: dict[str, Any], app: AppContext) -> list[Recommendation]:
    """LiveEngine's own suggestions as Recommendations. No network, no model."""
    if not c.match_id or not c.hero_key:
        return []
    h = context_hash(c)
    out = []
    items = snap.get("next_items") or []
    if items:
        first = items[0]
        item = app.data.items.get(first["item"])
        parts = set(item.components or []) if item else set()
        out.append(
            _rec(
                c,
                h,
                "ITEM_NEXT",
                first["item"],
                alternatives=[i["item"] for i in items[1:]],
                reason_ru=(
                    f"Следующий предмет в порядке pro-сборки героя; с учётом собранных частей "
                    f"осталось {first['remaining']} золота"
                ),
                evidence=[f"build:{c.hero_key}", *(f"inventory:{k}" for k in sorted(set(c.owned) & parts))],
            )
        )
    skills = snap.get("skills") or {}
    nxt = skills.get("next")
    # ponytail: only "has a point and the ability exists"; max rank and level gates come with stage 2.
    if nxt and (skills.get("unspent") or 0) > 0 and nxt["ability"] in c.learned_skills:
        out.append(
            _rec(
                c,
                h,
                "SKILL_LEVEL",
                nxt["ability"],
                reason_ru=f"Профессионалы на этом шаге чаще всего берут {nxt['name']} ({nxt['share']:.0%})",
                confidence=nxt["share"],
                confidence_kind="pro_pick_share",
                evidence=[f"build:{c.hero_key}", f"level:{c.level}"],
            )
        )
    return out


def _rec(
    c: GameContext,
    h: str,
    kind: RecType,
    candidate: str,
    *,
    reason_ru: str,
    evidence: list[str],
    alternatives: list[str] | None = None,
    confidence: float | None = None,
    confidence_kind: ConfidenceKind = "none",
) -> Recommendation:
    match_id = c.match_id or ""
    rid = hashlib.sha256(f"{match_id}|{kind}|{candidate}|{h}".encode()).hexdigest()[:20]
    return Recommendation(
        id=rid,
        match_id=match_id,
        game_time_s=c.time_s,
        type=kind,
        candidate_id=candidate,
        alternatives=alternatives or [],
        reason_ru=reason_ru,
        source="baseline",
        confidence=confidence,
        confidence_kind=confidence_kind,
        evidence_ids=evidence,
        context_hash=h,
        model_version=BASELINE_VERSION,
        data_patch=c.patch,
    )


class Copilot:
    """Keeps the latest GameContext and journals events and recommendations for one app."""

    def __init__(self, app: AppContext, store: CopilotStore, clock: Callable[[], float] = time.time) -> None:
        self.app = app
        self.store = store
        self._clock = clock
        self._lock = threading.Lock()
        self.context = GameContext(patch=app.data.patch)
        self._active: dict[str, str] = {}  # type -> candidate shown now

    def observe(
        self, engine: LiveEngine, source: str, recording: tuple[str, int] | None = None
    ) -> list[CopilotEvent]:
        with self._lock:
            now = self._clock()
            prev = self.context if self.context.match_id else None
            cur = build_context(engine, self.app, now)
            events = diff_events(prev, cur)
            self.context = cur
            if not events:
                return events
            if any(e.type == "match_started" for e in events):
                self._active.clear()
            file, frame = recording or (None, None)
            self.store.upsert_match(cur, source, now, file)
            self.store.add_events(events, now, file, frame)
            # A recommendation may only cite facts that exist.
            recs = [
                r
                for r in baseline(cur, engine.snapshot(), self.app)
                if set(r.evidence_ids) <= set(cur.evidence_ids)
            ]
            for rec in recs:
                if self._active.get(rec.type) != rec.candidate_id:
                    self.store.save_recommendation(rec, now)
                    self._active[rec.type] = rec.candidate_id
            for kind in set(self._active) - {r.type for r in recs}:
                self.store.expire(cur.match_id or "", kind)  # e.g. the skill point was spent
                del self._active[kind]
            return events
