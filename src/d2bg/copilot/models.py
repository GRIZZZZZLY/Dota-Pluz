"""Copilot contracts: one normalized game context, the events derived from it, and recommendations.

Every context field is optional because GSI leaves blocks out depending on the moment. Each group of
fields carries the source it came from, so nothing unknown is shown as known. A recommendation's
``confidence`` is whatever its source measures (``confidence_kind`` says what); it is never a win
probability.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["gsi", "cv", "opendota", "manual", "snapshot", "unknown"]
# Field groups of GameContext; ``sources`` maps each one to where its values came from.
GROUPS = ("match", "patch", "hero", "position", "draft", "economy")

EventType = Literal[
    "match_started",
    "phase_changed",
    "hero_selected",
    "skill_point_gained",
    "skill_leveled",
    "item_changed",
    "draft_changed",
    "death",
    "respawn",
    "gold_threshold_crossed",
    "match_finished",
]
RecType = Literal[
    "PICK_HERO",
    "SKILL_LEVEL",
    "TALENT",
    "ITEM_NEXT",
    "ITEM_SITUATIONAL",
    "ITEM_BUYBACK_GUARD",
    "POSTMATCH_FINDING",
]
RecSource = Literal["baseline", "jev", "groq", "hybrid", "deepseek"]
RecStatus = Literal["suggested", "seen", "dismissed", "followed", "unknown", "expired"]
ConfidenceKind = Literal["none", "pro_pick_share", "unverified_model_score"]
# How items are grouped for the player (spec F4.2). Skills and talents have no category.
Category = Literal["core", "situational", "defensive", "buyback"]


def _all_unknown() -> dict[str, Source]:
    unknown: Source = "unknown"
    return dict.fromkeys(GROUPS, unknown)


class GameContext(BaseModel):
    match_id: str | None = None
    patch: str | None = None
    phase: str | None = None
    # The game clock as the player sees it (negative before the horn); system time is never mixed in.
    time_s: float | None = None
    team: str | None = None
    hero_id: int | None = None
    hero_key: str | None = None
    position: int | None = None
    level: int | None = None
    alive: bool | None = None
    available_skill_points: int | None = None
    # The hero's own abilities with their rank (0 = not learned yet); cosmetic and event abilities
    # that GSI also lists are left out.
    learned_skills: dict[str, int] = Field(default_factory=dict)
    ultimates: list[str] = Field(default_factory=list)
    # GSI talent_1 .. talent_8: two per tier, from level 10 up.
    talents: list[bool] = Field(default_factory=list)
    allies: list[int] = Field(default_factory=list)
    enemies_visible: list[int] = Field(default_factory=list)
    # Per-slot recognition confidence; stays None until a CV draft source exists.
    draft_confidence: float | None = None
    inventory: list[str] = Field(default_factory=list)
    backpack: list[str] = Field(default_factory=list)
    stash: list[str] = Field(default_factory=list)
    gold: int | None = None
    buyback_cost: int | None = None
    gpm: int | None = None
    xpm: int | None = None
    last_hits: int | None = None
    # Gold amounts that change a recommendation when crossed: the next item, and the next item plus
    # the buyback reserve. Crossing one is a ``gold_threshold_crossed`` event.
    gold_targets: dict[str, int] = Field(default_factory=dict)
    data_age_s: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    sources: dict[str, Source] = Field(default_factory=_all_unknown)

    @property
    def owned(self) -> list[str]:
        return [*self.inventory, *self.backpack, *self.stash]


class CopilotEvent(BaseModel):
    type: EventType
    match_id: str
    game_time_s: float | None
    detail: str = ""


class Recommendation(BaseModel):
    id: str
    match_id: str
    game_time_s: float | None
    type: RecType
    category: Category | None = None
    candidate_id: str
    alternatives: list[str] = Field(default_factory=list)
    reason_ru: str
    source: RecSource
    confidence: float | None = None
    confidence_kind: ConfidenceKind = "none"
    evidence_ids: list[str] = Field(default_factory=list)
    context_hash: str
    model_version: str
    data_patch: str | None = None
    status: RecStatus = "suggested"
    expires_at: float | None = None
