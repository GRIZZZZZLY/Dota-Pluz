"""The offline baseline: candidate recommendations from the pro build and the known enemy draft, and the
validator every recommendation must pass before it is shown.

No network and no model. Later providers may only re-rank or explain what passes ``rejection``; they
cannot add an action it refuses. Every number in a reason comes from the context or the data snapshot.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from d2bg.builds.guide import MIN_ROWS, TALENT_LEVELS, next_items
from d2bg.builds.skills import blocked, data_ranks, next_talent
from d2bg.context import AppContext
from d2bg.copilot.models import Category, ConfidenceKind, GameContext, Recommendation, RecType

BASELINE_VERSION = "baseline-0.2"
# Phases in which advice can still be acted on.
ADVICE_PHASES = frozenset({"strategy", "showcase", "pre_game", "in_game"})
BUYBACK_FROM_S = 30 * 60  # the engine's buyback guard starts here too


def context_hash(c: GameContext) -> str:
    """Hash of the inputs a recommendation depends on (not the clock, not gold)."""
    key = {
        "hero": c.hero_id,
        "level": c.level,
        "skills": c.learned_skills,
        "talents": c.talents,
        "owned": sorted(c.owned),
        "allies": sorted(c.allies),
        "enemies": sorted(c.enemies_visible),
        "position": c.position,
        "patch": c.patch,
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def recommendations(c: GameContext, snap: dict[str, Any], app: AppContext) -> list[Recommendation]:
    """Every candidate for this moment, at most one per type and category."""
    if not c.match_id or not c.hero_id or not c.hero_key or c.phase not in ADVICE_PHASES:
        return []
    pro = app.data.per_hero("pro_builds.json", c.hero_id) or {}
    small = (
        f" Мало pro-игр на герое ({pro.get('n', 0)}), совет ориентировочный."
        if pro.get("n", 0) < MIN_ROWS
        else ""
    )
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
                category="core",
                alternatives=[i["item"] for i in items[1:]],
                reason_ru=f"Следующий основной предмет по pro-сборке героя.{small}",
                evidence=[f"build:{c.hero_key}", *(f"inventory:{k}" for k in sorted(set(c.owned) & parts))],
            )
        )
    out += _counter_items(c, h, snap, app)
    guard = snap.get("buyback_warning")
    if guard and items and c.gold is not None and c.buyback_cost:
        left = c.gold - items[0]["remaining"]
        out.append(
            _rec(
                c,
                h,
                "ITEM_BUYBACK_GUARD",
                "buyback",
                category="buyback",
                alternatives=[items[0]["item"]],
                reason_ru=(
                    f"Покупка {items[0]['name']} оставит {left} золота, а выкуп стоит {c.buyback_cost}. "
                    "После 30-й минуты смерть без выкупа обходится дорого: подумайте, не отложить ли покупку."
                ),
                evidence=[f"gold:{c.gold}", f"buyback_cost:{c.buyback_cost}"],
            )
        )
    nxt = (snap.get("skills") or {}).get("next")
    if nxt and (c.available_skill_points or 0) > 0:
        out.append(
            _rec(
                c,
                h,
                "SKILL_LEVEL",
                nxt["ability"],
                reason_ru=(
                    f"{nxt['name']}, уровень {nxt['rank']}: профессионалы на этом шаге чаще всего берут его "
                    f"({nxt['share']:.0%} из {nxt.get('n') or '?'} игр).{small}"
                ),
                confidence=nxt["share"],
                confidence_kind="pro_pick_share",
                evidence=[f"build:{c.hero_key}", f"level:{c.level}"],
            )
        )
    hero = app.data.heroes.get(c.hero_id)
    talent = (
        next_talent(
            c.talents,
            c.level or 0,
            {t.key: t.level for t in hero.talents},
            (pro.get("skills") or {}).get("talents") or {},
        )
        if hero
        else None
    )
    if talent and hero:
        names = {t.key: t.name for t in hero.talents}
        out.append(
            _rec(
                c,
                h,
                "TALENT",
                talent["talent"],
                alternatives=[talent["alternative"]],
                reason_ru=(
                    f"Талант {talent['level']} уровня: профессионалы чаще берут «{names[talent['talent']]}» "
                    f"({talent['share']:.0%} из {talent['n']} игр), а не «{names[talent['alternative']]}»."
                    + (" Выборка маленькая." if talent["n"] < MIN_ROWS else "")
                ),
                confidence=talent["share"],
                confidence_kind="pro_pick_share",
                evidence=[f"build:{c.hero_key}", f"level:{c.level}"],
            )
        )
    return out


def _counter_items(c: GameContext, h: str, snap: dict[str, Any], app: AppContext) -> list[Recommendation]:
    """One situational and one defensive item against the enemies he has seen.

    A rule is answered once he owns any of its items. Owned items, parts of owned items and a second
    pair of upgraded boots are never suggested (``next_items`` already skips them).
    """
    out = []
    seen: set[str] = set()
    for rule in snap.get("situational_items") or []:
        category = rule.get("category", "situational")
        if category in seen or any(i["owned"] for i in rule["items"]):
            continue
        options = next_items([{"key": i["key"]} for i in rule["items"]], c.owned, app.data.items, n=6)
        if not options:
            continue
        seen.add(category)
        keys = [app.data.heroes.get(e).key for e in rule["hero_ids"] if app.data.heroes.get(e)]  # type: ignore[union-attr]
        out.append(
            _rec(
                c,
                h,
                "ITEM_SITUATIONAL",
                options[0]["item"],
                category=category,
                alternatives=[o["item"] for o in options[1:]],
                reason_ru=f"{rule.get('reason_ru') or rule['reason']}. Против: {', '.join(rule['heroes'])}.",
                evidence=[f"enemy:{k}" for k in keys],
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
    category: Category | None = None,
    alternatives: list[str] | None = None,
    confidence: float | None = None,
    confidence_kind: ConfidenceKind = "none",
) -> Recommendation:
    match_id = c.match_id or ""
    rid = hashlib.sha256(f"{match_id}|{kind}|{category}|{candidate}|{h}".encode()).hexdigest()[:20]
    return Recommendation(
        id=rid,
        match_id=match_id,
        game_time_s=c.time_s,
        type=kind,
        category=category,
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


def rejection(rec: Recommendation, c: GameContext, app: AppContext) -> str | None:
    """Why ``rec`` may not be shown in context ``c``; None when it is a legal, supported action.

    This is the last check for every source: the baseline, and later Jev, Groq or a hybrid.
    """
    if rec.match_id != c.match_id:
        return "another match"
    if not set(rec.evidence_ids) <= set(c.evidence_ids):
        return "cites facts that are not in the context"
    if rec.type == "SKILL_LEVEL":
        rank = c.learned_skills.get(rec.candidate_id)
        if rank is None:
            return "not one of his abilities"
        if (c.available_skill_points or 0) <= 0:
            return "no skill point"
        ability = app.data.load("abilities.json").get(rec.candidate_id)
        why = blocked(rank, c.level or 0, rec.candidate_id in c.ultimates, data_ranks(ability))
        return None if why is None else f"cannot level: {why}"
    if rec.type == "TALENT":
        hero = app.data.heroes.get(c.hero_id) if c.hero_id else None
        tier = next((t.level for t in hero.talents if t.key == rec.candidate_id), None) if hero else None
        if tier is None or len(c.talents) != 8:
            return "unknown talent"
        if (c.level or 0) < TALENT_LEVELS[tier]:
            return "tier not open"
        return "tier already taken" if c.talents[2 * tier - 2] or c.talents[2 * tier - 1] else None
    if rec.type in ("ITEM_NEXT", "ITEM_SITUATIONAL"):
        if app.data.items.get(rec.candidate_id) is None:
            return "unknown item"
        return "already owned" if rec.candidate_id in c.owned else None
    if rec.type == "ITEM_BUYBACK_GUARD":
        if c.time_s is None or c.time_s < BUYBACK_FROM_S:
            return "too early for a buyback guard"
        return None if c.gold is not None and c.buyback_cost else "no gold or buyback data"
    return f"{rec.type} is not produced by the baseline"
