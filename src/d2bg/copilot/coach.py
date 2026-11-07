"""The post-match coach (stage 5), deterministic part: what happened in his game, measured against a
named comparison group, with the evidence each finding rests on.

Facts and interpretations stay apart. Every finding names its metric, his value, the baseline and where
the baseline comes from, the journal entries it rests on (``evidence_ids``), how sure it is (verified,
likely, insufficient_data) and the moment to rewatch. No finding claims it decided the game.

Each source is optional: the Copilot journal (deaths, level-ups, skills, items, advice and what became of
it), the local GSI recording (gold, last hits and buyback over time), and OpenDota's match document when
the match is public. A missing source is listed under ``missing``, never filled in.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from d2bg.builds.benchmarks import percentile_of, value_at
from d2bg.context import AppContext
from d2bg.copilot.hud import ModeProbe
from d2bg.copilot.store import CopilotStore
from d2bg.gsi import recorder

REPORT_VERSION = "coach-1"
# Where a normal game and a Turbo game draw their lines (Turbo runs about twice as fast).
LIMITS = {
    "normal": {"early": 600, "gold": 1000, "late": 1800, "item_late": 180, "hoard": 2000},
    "turbo": {"early": 300, "gold": 1500, "late": 1200, "item_late": 120, "hoard": 3000},
}
SKILL_DELAY_S = 45
STATUS_RU = {
    "followed": "выполнен",
    "expired": "не выполнен",
    "dismissed": "скрыт",
    "unknown": "не проверить",
    "suggested": "ещё показан",
    "seen": "показан",
}


def mmss(t: float | None) -> str:
    if t is None:
        return "?"
    s = int(t)
    return f"{'-' if s < 0 else ''}{abs(s) // 60}:{abs(s) % 60:02d}"


@dataclass
class Frame:
    t: float
    alive: bool | None
    gold: int
    gpm: int
    xpm: int
    lh: int
    kills: int
    deaths: int
    assists: int
    reliable: int
    level: int | None
    buyback_cost: int | None
    buyback_cd: int | None
    team: str | None
    win_team: str | None


def frames(path: Path) -> list[Frame]:
    """The in-game frames of a GSI recording (the post-game frame too, for the result)."""
    out = []
    for _, p in recorder.read(path):
        m, pl, h = p.get("map") or {}, p.get("player") or {}, p.get("hero") or {}
        state = str(m.get("game_state", ""))
        if (
            not state.endswith(("GAME_IN_PROGRESS", "POST_GAME"))
            or m.get("clock_time") is None
            or "gold" not in pl
        ):
            continue
        out.append(
            Frame(
                t=float(m["clock_time"]),
                alive=h.get("alive"),
                gold=int(pl.get("gold") or 0),
                gpm=int(pl.get("gpm") or 0),
                xpm=int(pl.get("xpm") or 0),
                lh=int(pl.get("last_hits") or 0),
                kills=int(pl.get("kills") or 0),
                deaths=int(pl.get("deaths") or 0),
                assists=int(pl.get("assists") or 0),
                reliable=int(pl.get("gold_reliable") or 0),
                level=h.get("level"),
                buyback_cost=h.get("buyback_cost"),
                buyback_cd=h.get("buyback_cooldown"),
                team={"team2": "radiant", "team3": "dire"}.get(str(pl.get("team_name")), pl.get("team_name")),
                win_team=m.get("win_team"),
            )
        )
    return out


def detect_mode(fs: list[Frame]) -> str | None:
    probe = ModeProbe()
    for f in fs:
        if f.t >= 0:
            mode = probe.feed(f.t, f.reliable, f.kills + f.assists)
            if mode:
                return mode
    return None


def _before(fs: list[Frame], t: float) -> Frame | None:
    """The last frame where he was alive, at or before ``t``."""
    best = None
    for f in fs:
        if f.t > t:
            break
        if f.alive is not False:
            best = f
    return best


def _finding(
    fid: str,
    metric: str,
    title: str,
    *,
    t: float | None,
    actual: Any,
    baseline: Any,
    group: str,
    evidence: list[str],
    certainty: str,
    advice: str,
    goal: str | None = None,
    priority: int = 5,
) -> dict[str, Any]:
    return {
        "id": fid,
        "metric": metric,
        "title": title,
        "event_time_s": t,
        "actual": actual,
        "baseline": baseline,
        "comparison_group": group,
        "evidence_ids": evidence,
        "certainty": certainty,
        "review_anchor": mmss(t) if t is not None else None,
        "recommendation": advice,
        "goal": goal,
        "priority": priority,
    }


def build(
    app: AppContext,
    store: CopilotStore,
    match_id: str,
    recordings_dir: Path,
    opendota: dict[str, Any] | None = None,
    account_id: int | None = None,
) -> dict[str, Any]:
    """The deterministic report for ``match_id`` from whatever sources exist."""
    row = store.match(match_id) or {}
    events = store.events(match_id)
    recs = store.recommendations(match_id, 1000)
    path = recordings_dir / row["recording"] if row.get("recording") else None
    fs = frames(path) if path and path.exists() else []
    hero_id = row.get("hero_id")
    hero = app.data.heroes.get(hero_id) if hero_id else None
    mode = detect_mode(fs)
    lim = LIMITS[mode or "normal"]
    missing: list[str] = []
    if not row:
        missing.append("Матча нет в журнале Copilot: приложение не было запущено во время игры.")
    if not fs:
        missing.append(
            "Нет записи GSI: золото, добивания и выкуп по времени неизвестны (включите запись игр)."
        )
    if mode is None and fs:
        missing.append("Режим игры не определён: пороги взяты для обычной игры.")

    findings: list[dict[str, Any]] = []
    strengths: list[str] = []
    deaths = [e for e in events if e["type"] == "death"]
    bench = app.data.per_hero("benchmarks.json", hero_id) if hero_id else None
    last = fs[-1] if fs else None
    in_game = [f for f in fs if f.t >= 0]
    duration = max((f.t for f in in_game), default=row.get("last_game_time_s"))

    # Deaths early in the game.
    early = [e for e in deaths if (e["game_time_s"] or 0) < lim["early"]]
    if len(early) >= 2:
        expected = None
        if bench and mode != "turbo" and "deaths_per_min" in bench:
            median = value_at(0.5, bench["deaths_per_min"])
            expected = round((median or 0) * lim["early"] / 60, 1)
        findings.append(
            _finding(
                "deaths_early",
                "deaths_before_" + str(lim["early"] // 60),
                f"{len(early)} смерти до {lim['early'] // 60}-й минуты",
                t=early[0]["game_time_s"],
                actual=len(early),
                baseline=expected if expected is not None else "≤ 1",
                group="медиана героя в публичных играх (OpenDota)"
                if expected is not None
                else "ориентир тренера",
                evidence=[f"ev:{e['id']}" for e in early],
                certainty="verified",
                advice="Пересмотрите эти смерти: где стоял герой, был ли обзор, кто из врагов пропал с карты.",
                goal=f"До {lim['early'] // 60}-й минуты — не больше одной смерти",
                priority=2,
            )
        )
    elif deaths and not early:
        strengths.append(f"Ни одной смерти до {lim['early'] // 60}-й минуты.")

    # Deaths with gold in the pocket, and late deaths without a buyback he could afford.
    rich, no_buyback = [], []
    for e in deaths:
        t = e["game_time_s"]
        if t is None:
            continue
        f = _before(fs, t)
        if f is None:
            continue
        if f.gold >= lim["gold"]:
            rich.append((e, f))
        if t >= lim["late"] and f.buyback_cost and f.gold >= f.buyback_cost and not f.buyback_cd:
            after = [x for x in fs if t <= x.t <= t + 120]
            if not any(x.buyback_cd for x in after):
                no_buyback.append((e, f))
    if rich:
        e, f = max(rich, key=lambda p: p[1].gold)
        findings.append(
            _finding(
                "death_with_gold",
                "gold_at_death",
                f"Смерть с {f.gold} золота в кармане ({len(rich)} раз)",
                t=e["game_time_s"],
                actual=f.gold,
                baseline=f"< {lim['gold']}",
                group="ориентир тренера: при смерти теряется часть ненадёжного золота",
                evidence=[f"ev:{x['id']}" for x, _ in rich],
                certainty="verified",
                advice="Покупайте предмет до драки или отправляйте золото курьером: так оно не теряется при смерти.",
                goal=f"Не умирать с запасом больше {lim['gold']} золота",
                priority=1,
            )
        )
    if no_buyback:
        e, f = no_buyback[0]
        findings.append(
            _finding(
                "no_buyback",
                "buyback_not_used",
                "Смерть в поздней игре без выкупа, хотя золота хватало",
                t=e["game_time_s"],
                actual=f"{f.gold} золота, выкуп {f.buyback_cost}",
                baseline="выкуп при важной драке",
                group="ориентир тренера",
                evidence=[f"ev:{x['id']}" for x, _ in no_buyback],
                certainty="likely",
                advice="Проверьте в записи, что происходило у ваших башен: возможно, выкуп спас бы базу.",
                goal="В поздней игре держать золото на выкуп и решать сразу после смерти",
                priority=4,
            )
        )

    # Skill points left unspent after a level-up.
    ups = [e for e in events if e["type"] == "skill_point_gained" and str(e["detail"]).isdigit()]
    learned = [e for e in events if e["type"] == "skill_leveled"]
    slow = []
    for e in ups:
        if int(e["detail"]) > 16 or e["game_time_s"] is None:
            continue  # some late levels give no point
        nxt = next((x for x in learned if (x["game_time_s"] or -1e9) >= e["game_time_s"]), None)
        if nxt is not None and nxt["game_time_s"] - e["game_time_s"] > SKILL_DELAY_S:
            slow.append((e, nxt["game_time_s"] - e["game_time_s"]))
    if len(slow) >= 2:
        findings.append(
            _finding(
                "skill_delay",
                "skill_point_delay",
                f"Очко способностей лежало дольше {SKILL_DELAY_S} с ({len(slow)} раз)",
                t=slow[0][0]["game_time_s"],
                actual=f"до {int(max(s for _, s in slow))} с",
                baseline=f"≤ {SKILL_DELAY_S} с",
                group="ориентир тренера",
                evidence=[f"ev:{e['id']}" for e, _ in slow],
                certainty="likely",
                advice="Вкладывайте очко сразу после нового уровня, если не бережёте его намеренно.",
                goal="Вкладывать очко способностей сразу после уровня",
                priority=5,
            )
        )

    # Item timings against pro players (normal) or strong Turbo players.
    got: dict[str, tuple[float, int]] = {}
    for e in events:
        if e["type"] == "item_changed" and str(e["detail"]).startswith("+") and e["game_time_s"] is not None:
            got.setdefault(str(e["detail"])[1:], (e["game_time_s"], e["id"]))
    base: dict[str, float] = {}
    group = ""
    if hero_id and mode == "turbo":
        th = ((app.data.load("turbo_builds.json") or {}).get("heroes") or {}).get(str(hero_id))
        if th:
            base = {r["item"]: r["median_time"] for r in th["first_big"] if r["share"] >= 0.2}
            group = f"Turbo, ранг «Божество» и выше, игр с закупками: {th['parsed']}"
    elif hero_id:
        pro = (app.data.per_hero("pro_builds.json", hero_id) or {}).get("items") or {}
        base = {
            k: float(v)
            for k, v in (pro.get("median_timings") or {}).items()
            if app.data.items.cost(k) >= 1000
        }
        group = f"про-игроки, медиана, матчей: {pro.get('rows', '?')}"
    late_items: list[tuple[str, float, int, float]] = []
    on_time: list[tuple[str, float, int, float]] = []
    for key, (t, ev) in got.items():
        if key in base and t > 0:
            delta = t - base[key]
            (late_items if delta >= lim["item_late"] else on_time).append((key, t, ev, delta))
    for key, t, ev, delta in sorted(late_items, key=lambda x: -x[3])[:3]:
        name = app.data.items.name(key)
        findings.append(
            _finding(
                f"item_late:{key}",
                "item_timing",
                f"{name} на {int(delta // 60)}:{int(delta % 60):02d} позже ориентира",
                t=t,
                actual=mmss(t),
                baseline=mmss(base[key]),
                group=group,
                evidence=[f"ev:{ev}"],
                certainty="likely",  # GSI sees the item in his inventory, not the purchase itself
                advice=f"Разберите, на что ушло время до {name}: фарм-маршрут, лишние покупки, смерти.",
                goal=f"{name} к {mmss(base[key])}",
                priority=3,
            )
        )
    if on_time:
        names = ", ".join(app.data.items.name(k) for k, *_ in on_time[:3])
        strengths.append(f"Вовремя по сравнению с ориентиром: {names}.")

    # Economy against the hero's public benchmarks (normal games only).
    if bench and last is not None and duration and duration >= 600:
        if mode == "turbo":
            missing.append("Сравнения GPM и добиваний для Turbo нет: база OpenDota — обычные игры.")
        else:
            minutes = duration / 60
            for metric, value, label in (
                ("gold_per_min", float(last.gpm), "GPM"),
                ("last_hits_per_min", last.lh / minutes, "добиваний в минуту"),
            ):
                pct = percentile_of(value, bench.get(metric) or [])
                if pct is None:
                    continue
                median = value_at(0.5, bench[metric])
                if pct <= 0.25:
                    findings.append(
                        _finding(
                            f"bench:{metric}",
                            metric,
                            f"{label}: {value:.0f} — ниже {pct:.0%} игр на этом герое",
                            t=None,
                            actual=round(value, 1),
                            baseline=round(median or 0, 1),
                            group="публичные игры на герое (OpenDota benchmarks), медиана",
                            evidence=["stat:" + metric],
                            certainty="verified",
                            advice="Посмотрите первые 10 минут: добивания, отводы, когда начали фармить лес.",
                            goal=f"{label}: подняться до медианы героя ({median:.0f})"
                            if metric == "gold_per_min"
                            else f"{label}: цель {median:.1f}",
                            priority=3,
                        )
                    )
                elif pct >= 0.75:
                    strengths.append(f"{label} {value:.0f} — лучше {pct:.0%} игр на этом герое.")
            at10 = next((f for f in fs if f.t >= 600), None)
            lh_med = value_at(0.5, bench.get("last_hits_per_min") or [])
            if at10 and lh_med and at10.lh < 0.7 * lh_med * 10:
                findings.append(
                    _finding(
                        "lh_10",
                        "last_hits_at_10",
                        f"Добивания к 10:00: {at10.lh} при медиане {lh_med * 10:.0f}",
                        t=600,
                        actual=at10.lh,
                        baseline=round(lh_med * 10),
                        group="публичные игры на герое (OpenDota benchmarks), медиана",
                        evidence=["stat:last_hits_at_10"],
                        certainty="verified",
                        advice="Тренируйте добивание в лобби: 10 минут без героев, цель — медиана героя.",
                        goal=f"Добивания к 10:00: {lh_med * 10:.0f}",
                        priority=2,
                    )
                )

    # Gold kept idle while alive.
    late = [f for f in fs if f.t >= 300 and f.alive]
    if len(late) >= 20:
        idle = sum(f.gold >= lim["hoard"] for f in late) / len(late)
        if idle >= 0.25:
            findings.append(
                _finding(
                    "gold_idle",
                    "gold_hoarded_share",
                    f"Больше {lim['hoard']} золота на руках {idle:.0%} времени",
                    t=next(f.t for f in late if f.gold >= lim["hoard"]),
                    actual=f"{idle:.0%}",
                    baseline="< 25%",
                    group="ориентир тренера",
                    evidence=["stat:gold_over_time"],
                    certainty="likely",
                    advice="Золото без дела не усиливает героя: заранее решайте, что покупать дальше.",
                    goal=f"Не держать больше {lim['hoard']} золота без цели покупки",
                    priority=4,
                )
            )

    # His advice and what became of it: the agent's record as much as his.
    shown = [r for r in recs if r.source == "baseline"]
    models = [r for r in recs if r.source != "baseline"]
    advice_items: list[dict[str, Any]] = [
        {
            "id": f"rec:{r.id}",
            "t": r.game_time_s,
            "type": r.type,
            "candidate": r.candidate_id,
            "name": app.data.items.name(r.candidate_id) if r.type.startswith("ITEM_") else r.candidate_id,
            "status": STATUS_RU.get(r.status, r.status),
            "source": r.source,
        }
        for r in sorted(recs, key=lambda r: r.game_time_s or 0)
    ][:80]
    advice = {
        "outcomes": _outcomes(app, shown, got),
        "total": len(shown),
        "by_status": {STATUS_RU.get(k, k): v for k, v in Counter(r.status for r in shown).items()},
        "seen": sum(1 for r in shown if r.seen_at is not None),
        "models": {
            "total": len(models),
            "agreed": sum(
                1
                for m in models
                if any(
                    b.type == m.type and b.candidate_id == m.candidate_id
                    for b in shown
                    if b.category == m.category
                )
            ),
        },
        "items": advice_items,
    }

    timeline = [
        {"t": e["game_time_s"], "kind": "death", "text": "Смерть", "id": f"ev:{e['id']}"} for e in deaths
    ] + [
        {"t": t, "kind": "item", "text": app.data.items.name(k), "id": f"ev:{ev}"}
        for k, (t, ev) in got.items()
        if app.data.items.cost(k) >= 1000
    ]
    timeline.sort(key=lambda x: x["t"] or 0)

    od: dict[str, Any] | None = None
    if opendota is not None and opendota.get("players"):
        from d2bg.matches.review import is_parsed, review

        me = review(app, opendota, account_id).get("me")
        od = {"parsed": is_parsed(opendota), "me": me}
        if me:
            for i, note in enumerate(me.get("notes") or []):
                findings.append(
                    _finding(
                        f"opendota:{i}",
                        "opendota_note",
                        str(note),
                        t=None,
                        actual=None,
                        baseline=None,
                        group="OpenDota: публичные игры на герое",
                        evidence=["opendota:match"],
                        certainty="verified",
                        advice="",
                        priority=6,
                    )
                )
        if not is_parsed(opendota):
            missing.append("OpenDota ещё не разобрал запись матча: таймингов покупок оттуда нет.")
    else:
        missing.append("OpenDota: матча нет (лобби, приватная игра или ещё не загружен).")

    findings.sort(key=lambda f: f["priority"])
    won = None
    end = next((f for f in reversed(fs) if f.win_team in ("radiant", "dire")), None)
    if end is not None and end.team in ("radiant", "dire"):
        won = end.win_team == end.team
    goals = [{"metric": f["metric"], "text": f["goal"]} for f in findings if f.get("goal")][:3]
    evidence = sorted(
        {e for f in findings for e in f["evidence_ids"]}
        | {str(a["id"]) for a in advice_items}
        | {x["id"] for x in timeline}
    )
    return {
        "match_id": match_id,
        "version": REPORT_VERSION,
        "hero_id": hero_id,
        "hero": hero.name if hero else None,
        "mode": mode,
        "duration_s": duration,
        "won": won,
        "source": row.get("source"),
        "stats": (
            {
                "kills": last.kills,
                "deaths": last.deaths,
                "assists": last.assists,
                "last_hits": last.lh,
                "gpm": last.gpm,
                "xpm": last.xpm,
                "level": last.level,
            }
            if last
            else None
        ),
        "findings": findings,
        "strengths": strengths,
        "goals": goals,
        "advice": advice,
        "timeline": timeline,
        "opendota": od,
        "missing": missing,
        "evidence_ids": evidence,
    }


def _outcomes(app: AppContext, shown: list[Any], got: dict[str, tuple[float, int]]) -> list[dict[str, Any]]:
    """One line per piece of advice, not per journal row: the rules re-issue the same advice as the
    game changes, so ten rows can be one "buy Phase Boots". Done, done later (he bought it after the
    advice was replaced) or not done; not doing it may be his right call."""
    groups: dict[tuple[str, str], list[Any]] = {}
    for r in sorted(shown, key=lambda r: r.game_time_s or 0):
        groups.setdefault((r.type, r.candidate_id), []).append(r)
    out = []
    for (kind, candidate), rows in groups.items():
        statuses = {r.status for r in rows}
        first = rows[0].game_time_s
        bought = got.get(candidate)
        if "followed" in statuses:
            outcome = "выполнен"
        elif kind.startswith("ITEM_") and bought is not None and bought[0] >= (first or -1e9):
            outcome = f"выполнен позже ({mmss(bought[0])})"
        elif statuses == {"dismissed"}:
            outcome = "скрыт"
        elif statuses <= {"unknown"}:
            outcome = "не проверить"
        else:
            outcome = "не выполнен"
        is_item = kind.startswith("ITEM_")
        name = app.data.items.name(candidate) if is_item else candidate
        if kind == "SKILL_LEVEL":
            followed = sum(r.status == "followed" for r in rows)
            outcome = f"выполнен {followed} из {len(rows)} раз"
        out.append(
            {
                "type": kind,
                "candidate": candidate,
                "name": name,
                "first_t": mmss(first),
                "times_shown": len(rows),
                "outcome": outcome,
                "evidence": f"rec:{rows[0].id}",
            }
        )
    return out


def recurring(store: CopilotStore, last: int = 10) -> list[dict[str, Any]]:
    """Problems that came back in his last ``last`` reports, most frequent first."""
    reports = store.recent_reports("facts", last)
    seen: Counter[str] = Counter()
    titles: dict[str, str] = {}
    for r in reports:
        for f in r.get("findings") or []:
            key = f["id"].split(":")[0] if f["id"].startswith(("item_late", "bench")) else f["id"]
            if key.startswith("opendota"):
                continue
            seen[key] += 1
            titles.setdefault(key, f["title"])
    return [
        {"metric": k, "title": titles[k], "matches": n, "of": len(reports)}
        for k, n in seen.most_common()
        if n >= 2
    ]
