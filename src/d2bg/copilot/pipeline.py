"""Copilot pipeline: live state -> GameContext -> events -> checked recommendations -> SQLite journal.

It runs after each LiveEngine update (the engine's ``on_payload`` hook). Recommendations are recomputed
only when an event happens, never on every tick, and a new row is stored only when the candidate of a
type and category changes. A replaced recommendation is closed as ``followed`` when the game shows he
did it, ``unknown`` when that cannot be checked, otherwise ``expired``.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from d2bg.context import AppContext
from d2bg.copilot import baseline
from d2bg.copilot.hybrid import Hybrid, Job
from d2bg.copilot.models import CopilotEvent, EventType, GameContext, Recommendation, RecStatus, Source
from d2bg.copilot.store import CopilotStore
from d2bg.live.engine import LiveEngine


def build_context(engine: LiveEngine, app: AppContext, now: float) -> GameContext:
    """The engine's current state as a GameContext, each field group tagged with its source."""
    patch = app.data.patch
    s = engine.state
    if s is None:
        return GameContext(patch=patch, sources=_sources(patch="snapshot"))
    snap = engine.snapshot()
    # The engine keeps the last draft after a match ends; outside a match it is not this context's.
    draft = (snap.get("draft") or {}) if s.match_id else {}
    allies, enemies = list(draft.get("allies") or []), list(draft.get("enemies") or [])
    screen = draft.get("screen") or {}
    draft_sources = draft.get("sources") or {}
    # The weakest source names the group: his corrections, else the screen reading, else the game.
    draft_source: Source = (
        "manual"
        if "manual" in draft_sources
        else "cv"
        if "screen" in draft_sources
        else "gsi"
        if allies or enemies
        else "unknown"
    )
    positions = app.settings.get().positions
    position = positions[0] if len(positions) == 1 else None
    hero = s.hero if s.hero and s.hero.id else None
    # Ranks, the ultimate and free points as the engine counts them (it remembers hidden abilities).
    skills = (snap.get("skills") or {}) if hero else {}
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
        available_skill_points=skills.get("unspent"),
        learned_skills=dict(skills.get("ranks") or {}),
        ultimates=list(skills.get("ultimates") or []),
        talents=list(hero.talents) if hero else [],
        allies=allies,
        enemies_visible=enemies,
        draft_confidence=screen.get("confidence"),
        draft_unknown_slots=screen.get("unknown"),
        inventory=[i.key for i in s.inventory],
        backpack=[i.key for i in s.backpack],
        stash=[i.key for i in s.stash],
        gold=st.gold if st else None,
        buyback_cost=hero.buyback_cost if hero else None,
        gpm=st.gpm if st else None,
        xpm=st.xpm if st else None,
        last_hits=st.last_hits if st else None,
        gold_targets=_gold_targets(snap, s.clock, hero.buyback_cost if hero else None),
        data_age_s=None if engine.last_packet_at is None else round(now - engine.last_packet_at, 3),
        sources=_sources(
            match="gsi" if s.match_id else "unknown",
            patch="snapshot",
            hero="gsi" if hero else "unknown",
            position="manual" if position else "unknown",
            draft=draft_source,
            economy="gsi" if st else "unknown",
        ),
    )
    c.evidence_ids = _evidence(c, app)
    return c


def _sources(**known: Source) -> dict[str, Source]:
    return {**GameContext().sources, **known}


def _gold_targets(snap: dict[str, Any], clock: float | None, buyback: int | None) -> dict[str, int]:
    """Where the buyback guard flips: once he can afford the next item, and once he can afford it and
    still keep the buyback. Only from minute 30, when the guard applies."""
    items = snap.get("next_items") or []
    if not items or not buyback or clock is None or clock < baseline.BUYBACK_FROM_S:
        return {}
    remaining = int(items[0]["remaining"])
    return {"next_item": remaining, "next_item_and_buyback": remaining + buyback}


def _evidence(c: GameContext, app: AppContext) -> list[str]:
    """Ids of the facts a recommendation may cite. A citation outside this list is rejected."""
    out = []
    if c.hero_key and c.hero_id:
        out.append(f"hero:{c.hero_key}")
        if app.data.per_hero("pro_builds.json", c.hero_id):
            out.append(f"build:{c.hero_key}")
    if c.level:
        out.append(f"level:{c.level}")
    if c.gold is not None:
        out.append(f"gold:{c.gold}")
    if c.buyback_cost:
        out.append(f"buyback_cost:{c.buyback_cost}")
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
    for i, (was, now) in enumerate(zip(prev.talents, cur.talents, strict=False)):
        if now and not was:
            add("skill_leveled", f"talent_{i + 1}")
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
    if cur.gold is not None and prev.gold is not None:
        for name, target in cur.gold_targets.items():
            before_target = prev.gold_targets.get(name)
            reached_before = before_target is not None and prev.gold >= before_target
            if reached_before != (cur.gold >= target):
                add("gold_threshold_crossed", f"{name}:{'up' if cur.gold >= target else 'down'}")
    if cur.phase == "post_game" and prev.phase != "post_game":
        add("match_finished")
    return out


def _closing_status(
    kind: str, candidate: str, events: list[CopilotEvent], changed_talents: bool
) -> RecStatus:
    """What became of a recommendation that is no longer the current one."""
    seen = {(e.type, e.detail) for e in events}
    if kind in ("ITEM_NEXT", "ITEM_SITUATIONAL") and ("item_changed", f"+{candidate}") in seen:
        return "followed"
    if kind == "SKILL_LEVEL" and any(t == "skill_leveled" and d.startswith(f"{candidate}:") for t, d in seen):
        return "followed"
    if kind == "TALENT" and changed_talents:
        return "unknown"  # GSI says a talent of the tier was taken, not which of the two
    return "expired"


class Copilot:
    """Keeps the latest GameContext and journals events and recommendations for one app."""

    def __init__(
        self,
        app: AppContext,
        store: CopilotStore,
        clock: Callable[[], float] = time.time,
        hybrid: Hybrid | None = None,
    ) -> None:
        self.app = app
        self.store = store
        self._clock = clock
        self._lock = threading.Lock()
        self.context = GameContext(patch=app.data.patch)
        # "TYPE:category" -> (recommendation id, candidate, evidence) shown now.
        self._active: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        # A cloud model's opinion on the advice in the same slot: "TYPE:category" -> (row id, candidate).
        self._models: dict[str, tuple[str, str]] = {}
        # Candidates the validator refused at the last recompute, for the status page.
        self.rejected: list[dict[str, str]] = []
        self.hybrid = hybrid
        if hybrid is not None:
            hybrid.copilot = self

    def _close_all(self, events: list[CopilotEvent] | None = None) -> None:
        """Close what is shown. At the end of a match, advice he carried out in the last packets is
        ``followed``, not ``expired``."""
        seen = events or []
        for key, (rec_id, candidate, _) in self._active.items():
            self.store.set_status(rec_id, _closing_status(key.split(":")[0], candidate, seen, False))
        for key, (rec_id, candidate) in self._models.items():
            self.store.set_status(rec_id, _closing_status(key.split(":")[0], candidate, seen, False))
        self._active.clear()
        self._models.clear()

    # Called by the hybrid policy from its own thread.

    def is_current(self, key: str, rec_id: str) -> bool:
        return self._active.get(key, ("",))[0] == rec_id

    def adopt(self, key: str, rec_id: str, opinion: Recommendation) -> bool:
        """Journal a model's opinion on the advice ``rec_id``, if that advice is still the shown one."""
        with self._lock:
            if not self.is_current(key, rec_id):
                return False
            old = self._models.pop(key, None)
            if old is not None:
                self.store.set_status(old[0], "expired")
            self.store.save_recommendation(opinion, self._clock())
            self._models[key] = (opinion.id, opinion.candidate_id)
            return True

    def revise(self, key: str, opinion_id: str, candidate: str, reason_ru: str) -> None:
        """The advisor settled a disagreement: its pick and reason replace the opinion's."""
        with self._lock:
            if self._models.get(key, ("",))[0] == opinion_id:
                self.store.revise(opinion_id, candidate, reason_ru, "hybrid")
                self._models[key] = (opinion_id, candidate)

    def observe(
        self, engine: LiveEngine, source: str, recording: tuple[str, int] | None = None
    ) -> list[CopilotEvent]:
        with self._lock:
            now = self._clock()
            prev = self.context if self.context.match_id else None
            cur = build_context(engine, self.app, now)
            events = diff_events(prev, cur)
            self.context = cur
            if prev is not None and cur.match_id is None:
                self._close_all()  # back in the menu: a cancelled or finished match
            if not events:
                return events
            if any(e.type == "match_started" for e in events):
                self._close_all()
                # Advice left open by an earlier run (the app was closed mid-match) is not current.
                self.store.expire_open()
            elif any(e.type == "match_finished" for e in events):
                self._close_all(events)
            file, frame = recording or (None, None)
            self.store.upsert_match(cur, source, now, file)
            self.store.add_events(events, now, file, frame)
            produced = {}
            self.rejected = []
            for rec in baseline.recommendations(cur, engine.snapshot(), self.app):
                why = baseline.rejection(rec, cur, self.app)
                if why is None:
                    produced[f"{rec.type}:{rec.category or ''}"] = rec
                else:
                    self.rejected.append({"type": rec.type, "candidate": rec.candidate_id, "reason": why})
            changed_talents = prev is not None and prev.talents != cur.talents
            for key, (rec_id, candidate, evidence) in list(self._active.items()):
                new = produced.get(key)
                if new is not None and new.candidate_id == candidate:
                    # Same advice: it stays one row. New reasons (a part bought or sold, a level
                    # gained) are written into it, so it never cites a fact that is gone.
                    if tuple(new.evidence_ids) != evidence:
                        self.store.refresh_recommendation(rec_id, new)
                        self._active[key] = (rec_id, candidate, tuple(new.evidence_ids))
                    continue
                kind = key.split(":")[0]
                self.store.set_status(rec_id, _closing_status(kind, candidate, events, changed_talents))
                del self._active[key]
                if key in self._models:
                    model_id, model_candidate = self._models.pop(key)
                    self.store.set_status(
                        model_id, _closing_status(kind, model_candidate, events, changed_talents)
                    )
            for key, rec in produced.items():
                if key not in self._active:
                    self.store.save_recommendation(rec, now)
                    self._active[key] = (rec.id, rec.candidate_id, tuple(rec.evidence_ids))
                    if self.hybrid is not None:
                        self.hybrid.submit(Job(key, rec, cur, source))
            return events
