"""Small hints for the overlay's widgets: the skill to learn, heroes to pick, items to buy. A hint is None
when there is nothing to say right now, so the overlay keeps that widget hidden.

GSI does not say the game mode, and nothing it sends before the horn differs. Turbo is told by passive
gold after the horn (see ModeProbe); the GPM figure does not tell it (300-440 at 0:25-1:00 in a real
Turbo game).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Literal

from d2bg.context import AppContext
from d2bg.copilot.models import Recommendation
from d2bg.draft import advisor
from d2bg.draft.service import DraftRequest, analyze
from d2bg.live.engine import LiveEngine
from d2bg.settings import Settings

Mode = Literal["turbo", "normal"]
# Reliable gold a minute from passive income: 180 in his Turbo games (measured in 4 recordings), about
# half in a normal game (Turbo doubles it; not measured).
TURBO_PASSIVE = 135
PROBE_WINDOW = 12  # seconds of passive gold alone that decide
# Radiant's fountain measured at (-6700, -6700); Dire's assumed mirrored. The base shop is in reach.
FOUNTAIN = {"radiant": (-6700, -6700), "dire": (6700, 6700)}
BASE_RADIUS = 2600
BEFORE_HORN = {"strategy", "showcase", "loading", "pre_game"}
SMALL_SAMPLE = 20
_draft_cache: dict[tuple[Any, ...], dict[str, list[Any]]] = {}


class ModeProbe:
    """Turbo or normal from his reliable gold after the horn. A kill or assist, a purchase, or a jump
    bigger than passive gold can make (a bounty rune) starts the window again."""

    def __init__(self) -> None:
        self.start: tuple[float, int, int] | None = None
        self.last: tuple[float, int, int] | None = None

    def feed(self, clock: float, gold: int, kills: int) -> Mode | None:
        last, self.last = self.last, (clock, gold, kills)
        if (
            self.start is None
            or last is None
            or kills != last[2]
            or gold < last[1]
            or clock < last[0]
            or gold - last[1] > 4 * max(clock - last[0], 1) + 4
        ):
            self.start = self.last
            return None
        t0, g0, _ = self.start
        if clock - t0 < PROBE_WINDOW:
            return None
        return "turbo" if (gold - g0) / (clock - t0) * 60 >= TURBO_PASSIVE else "normal"


def in_base(team: str | None, x: int | None, y: int | None) -> bool:
    if team not in FOUNTAIN or x is None or y is None:
        return False
    fx, fy = FOUNTAIN[team]
    return math.hypot(x - fx, y - fy) <= BASE_RADIUS


def _skill(app: AppContext, hero_id: int | None, snap: dict[str, Any], recs: list[Recommendation]) -> Any:
    hero = app.data.heroes.get(hero_id) if hero_id else None
    rec = next((r for r in recs if r.type in ("SKILL_LEVEL", "TALENT")), None)
    if hero is None or rec is None:
        return None
    if rec.type == "TALENT":
        names = {t.key: t.name for t in hero.talents}
        return {
            "kind": "talent",
            "key": rec.candidate_id,
            "name": names.get(rec.candidate_id, rec.candidate_id),
            "instead": [names.get(a, a) for a in rec.alternatives],
            "reason": rec.reason_ru,
        }
    names = {a.key: a.name for a in hero.abilities}
    shown = [a["key"] for a in (snap.get("skills") or {}).get("abilities", [])]
    return {
        "kind": "skill",
        "key": rec.candidate_id,
        "name": names.get(rec.candidate_id, rec.candidate_id),
        # Its place on the ability bar, counted from the left, as GSI lists the abilities.
        "slot": shown.index(rec.candidate_id) + 1 if rec.candidate_id in shown else None,
        "reason": rec.reason_ru,
    }


def _draft(app: AppContext, settings: Settings, draft: dict[str, Any]) -> Any:
    position = settings.positions[0] if settings.positions else None
    key = (
        tuple(draft["allies"]),
        tuple(draft["enemies"]),
        tuple(draft["bans"]),
        draft["side"],
        position,
        settings.model_dump_json(),
    )
    if key not in _draft_cache:
        if len(_draft_cache) > 32:  # ponytail: drop all, one draft only needs a few entries
            _draft_cache.clear()
        bucket = app.data.matchup_bucket(settings.rank_bucket)
        picks = _picks(app, settings, draft, position)
        mine = {p["hero"] for p in picks}  # never advise banning a hero he is advised to pick
        bans = advisor.ban_suggestions(bucket, draft["allies"], draft["enemies"], draft["bans"], n=6)
        _draft_cache[key] = {
            "picks": picks,
            "bans": [
                {"hero": b["hero"], "name": app.data.heroes.name(b["hero"])}
                for b in bans
                if b["hero"] not in mine
            ][:3],
        }
    # During a player's draft GSI sends no heroes; only the screen reader (d2bg-cv) sees them.
    known = len(draft["allies"]) + len(draft["enemies"])
    return {"position": position, "heroes_known": known, **_draft_cache[key]}


def _picks(app: AppContext, settings: Settings, draft: dict[str, Any], position: int | None) -> list[Any]:
    name = app.data.heroes.name
    if not draft["allies"] and not draft["enemies"]:
        # Nothing to match against yet: every matchup score is zero, so the meta decides.
        bucket = app.data.matchup_bucket(settings.rank_bucket)
        skip = {*draft["bans"], *settings.blacklist}
        return [
            {"hero": h, "name": name(h), "why": f"винрейт {wr:.0%}"}
            for h, wr in advisor.meta(bucket, 200, exclude=skip)
            if position is None or position in app.playable.get(h, set())
        ][:3]
    req = DraftRequest(
        allies=draft["allies"],
        enemies=draft["enemies"],
        bans=draft["bans"],
        side=draft["side"] if draft["side_known"] else None,
        my_position=position,
        n=3,
    )
    res = analyze(app, req, settings)
    picks = []
    for c in (res["by_position"][str(position)] if position else res["suggestions"])[:3]:
        why = c["why"]
        if why["good_against"]:
            reason = f"силён против {name(why['good_against'][0]['hero'])}"
        elif why["with"]:
            reason = f"хорош с {name(why['with'][0]['hero'])}"
        else:
            reason = ""
        picks.append({"hero": c["hero"], "name": name(c["hero"]), "why": reason})
    return picks


def _row(app: AppContext, key: str, detail: str) -> dict[str, str]:
    return {"key": key, "name": app.data.items.name(key), "detail": detail}


def _small(n: int) -> str:
    return " Выборка маленькая." if n < SMALL_SAMPLE else ""


def _starting(app: AppContext, hero_id: int, mode: Mode | None) -> Any:
    turbo = (app.data.load("turbo_builds.json") or {}).get("heroes", {}).get(str(hero_id))
    if mode == "turbo" and turbo and turbo["parsed"]:
        rows = [s for s in turbo["starting"] if s["share"] >= 0.3][:6]
        return {
            "title": "Старт в Turbo",
            "note": f"Чаще всего у сильных игроков, игр с закупками: {turbo['parsed']}.{_small(turbo['parsed'])}",
            "items": [
                _row(
                    app,
                    s["item"],
                    f"{s['share']:.0%}" + (f", ×{s['avg_count']:g}" if s["avg_count"] >= 1.5 else ""),
                )
                for s in rows
            ],
        }
    pro = (app.data.per_hero("pro_builds.json", hero_id) or {}).get("items") or {}
    if not pro.get("starting"):
        return None
    top = pro["starting"][0]
    note = f"Самый частый набор про-игроков: {top['n']} из {pro['rows']} игр."
    if mode == "turbo":
        note += " Для Turbo по этому герою данных пока нет."
    elif mode is None:
        note += " Режим игры ещё не определён."
    return {
        "title": "Старт",
        "note": note,
        "items": [_row(app, k, f"×{n}" if n > 1 else "") for k, n in Counter(top["items"]).items()],
    }


def _next(app: AppContext, hero_id: int, mode: Mode | None, snap: dict[str, Any], owned: set[str]) -> Any:
    turbo = (app.data.load("turbo_builds.json") or {}).get("heroes", {}).get(str(hero_id))
    if mode == "turbo" and turbo and turbo["parsed"]:
        early = [r for r in turbo["first_big"] if r["share"] >= 0.15 and r["item"] not in owned][:3]
        if early:
            return {
                "title": "Turbo: первые крупные предметы",
                "note": f"Игр с закупками: {turbo['parsed']}.{_small(turbo['parsed'])}",
                "items": [
                    _row(
                        app,
                        r["item"],
                        f"{r['share']:.0%}, к {r['median_time'] // 60}:{r['median_time'] % 60:02d}",
                    )
                    for r in early
                ],
            }
        late = [r for r in turbo["final"] if r["share"] >= 0.2 and r["item"] not in owned][:3]
        if late:
            return {
                "title": "Turbo: предметы к концу игры",
                "note": f"Игр: {turbo['games']}.{_small(turbo['games'])}",
                "items": [_row(app, r["item"], f"{r['share']:.0%} игр") for r in late],
            }
    nxt = snap.get("next_items") or []
    if not nxt:
        return None
    gold = (snap.get("stats") or {}).get("gold") or 0
    return {
        "title": "Следующие предметы",
        "note": "Сборка про-игроков."
        + (" Для Turbo по этому герою данных пока нет." if mode == "turbo" else ""),
        "items": [
            _row(app, i["item"], "можно купить" if gold >= i["remaining"] else f"ещё {i['remaining'] - gold}")
            for i in nxt[:3]
        ],
    }


def build(
    app: AppContext,
    engine: LiveEngine,
    settings: Settings,
    recs: list[Recommendation],
    mode: Mode | None,
    mode_source: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source": engine.source,
        "mode": mode,
        "mode_source": mode_source,
        "skill": None,
        "draft": None,
        "items": None,
    }
    s = engine.state
    if s is None or s.spectating or not engine.connection()["connected"]:
        return out
    snap = engine.snapshot()
    hero_id = engine.own_hero
    hidden = set(settings.hidden_hints)
    if s.phase == "hero_selection" and hero_id is None and "draft" in snap and "draft" not in hidden:
        out["draft"] = _draft(app, settings, snap["draft"])
    if hero_id is None:
        return out
    if "items" in hidden:
        pass
    elif s.phase in BEFORE_HORN or s.phase == "hero_selection":
        out["items"] = _starting(app, hero_id, mode)
    elif (
        s.phase == "in_game"
        and s.hero is not None
        and (s.hero.alive is False or in_base(s.team, s.hero.xpos, s.hero.ypos))
    ):
        # GSI does not say when the shop is open: dead or in base is when he can shop.
        out["items"] = _next(app, hero_id, mode, snap, set(s.owned_items))
    if s.phase in ("pre_game", "in_game") and "skills" not in hidden:
        out["skill"] = _skill(app, hero_id, snap, recs)
    return out
