"""The next ability rank and talent to take: the pro order matched to what is already learned, and only
what the game allows right now.

Levelling rules (standard Dota 2): a basic ability has 4 ranks and rank ``r`` needs hero level
``2r - 1``; an ultimate has 3 ranks at hero levels 6, 12 and 18. An ability is checked only when the
number of ranks in its data agrees with the GSI ``ultimate`` flag. Abilities that break the pattern
(Invoker's orbs, abilities with one value for every rank) get no suggestion instead of a guess.
Talents use their own points since 7.40 (see ``unspent_skill_points``); a tier opens at level 10, 15,
20 or 25 and is taken once either of its two talents is.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from d2bg.builds.guide import TALENT_LEVELS

BASIC_RANKS = 4
ULT_RANKS = 3
ULT_LEVELS = (6, 12, 18)


def data_ranks(doc: Mapping[str, Any] | None) -> int | None:
    """How many ranks the ability data lists values for; None when every value is a single number."""
    if not doc:
        return None
    n = 0
    for name in ("cd", "mc"):
        value = doc.get(name)
        if isinstance(value, list):
            n = max(n, len(value))
    for attrib in doc.get("attrib") or []:
        value = attrib.get("value") if isinstance(attrib, Mapping) else None
        if isinstance(value, list):
            n = max(n, len(value))
    return n or None


def blocked(rank: int, hero_level: int, ultimate: bool, ranks: int | None) -> str | None:
    """Why the next rank cannot be learned now: ``unknown``, ``max`` or ``level``; None when it can."""
    if ranks != (ULT_RANKS if ultimate else BASIC_RANKS):
        return "unknown"
    if rank >= ranks:
        return "max"
    need = ULT_LEVELS[rank] if ultimate else 2 * rank + 1
    return None if hero_level >= need else "level"


def next_skill(
    learned: Mapping[str, int],
    ultimates: Collection[str],
    hero_level: int,
    by_level: Sequence[Mapping[str, Any]],
    abilities: Mapping[str, Any],
) -> dict[str, Any] | None:
    """The earliest step of the pro order he has not matched yet and can take now.

    ``learned`` holds only the hero's own abilities (rank 0 = not learned). Steps for abilities he does
    not have, or cannot level now, are passed over, so a different order than the pros' still works.
    """
    taken: Counter[str] = Counter()
    for step in by_level:
        key = step["ability"]
        taken[key] += 1
        if key not in learned or taken[key] <= learned[key]:
            continue
        if blocked(learned[key], hero_level, key in ultimates, data_ranks(abilities.get(key))) is None:
            return {**step, "rank": learned[key] + 1}
    return None


def next_talent(
    picked: Sequence[bool], hero_level: int, tiers: Mapping[str, int], pro: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    """The talent pros take most in the lowest open tier, or None.

    ``picked`` is GSI's ``talent_1`` .. ``talent_8``, two per tier from level 10 up; anything else
    means the shape is unknown and nothing is suggested. ``tiers`` maps talent keys to tiers 1-4.
    """
    if len(picked) != 2 * len(TALENT_LEVELS):
        return None
    for tier, level in TALENT_LEVELS.items():
        if hero_level < level:
            return None
        if picked[2 * tier - 2] or picked[2 * tier - 1]:
            continue
        options = sorted(
            (k for k, t in tiers.items() if t == tier), key=lambda k: -(pro.get(k) or {}).get("share", 0)
        )
        if len(options) != 2 or not pro.get(options[0]):
            return None
        best = pro[options[0]]
        return {
            "talent": options[0],
            "alternative": options[1],
            "tier": tier,
            "level": level,
            "share": best.get("share"),
            "n": best.get("n", 0),
        }
    return None
