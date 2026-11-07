"""Turbo builds from strong players' public matches.

Pro builds come from the normal mode, and neither OpenDota's nor STRATZ's item statistics separate
Turbo (checked 2026-11-07: STRATZ filters item purchases by bracket and position only). So this pages
OpenDota's public match feed for recent Turbo games whose players average Divine or better, and keeps
for every hero its final items and, for the games OpenDota has parsed (about one in eight), what was
bought and when. ``aggregate`` turns that into per-hero starting items, first big items and final items,
each with its sample size.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from d2bg.opendota import BudgetExhaustedError, NotFoundError, OpenDotaClient

TURBO = 23
MIN_RANK = 70  # rank tier = 10 * medal + stars: 70 is Divine
BIG_ITEM = 1000  # gold: an item at least this dear is a "first big item"
EARLY_S = 15 * 60  # Turbo games are short; the first big items come within 15 minutes


def normalize(
    match: Mapping[str, Any], row: Mapping[str, Any], item_keys: Mapping[str, str]
) -> dict[str, Any] | None:
    """One OpenDota match as the few facts kept: per player the hero, the result, the final items and,
    when parsed, the purchases as ``[time, item]``."""
    radiant_win = match.get("radiant_win")
    players = []
    for p in match.get("players") or []:
        hero = p.get("hero_id")
        if not hero or radiant_win is None:
            continue
        slots = [f"item_{i}" for i in range(6)] + [f"backpack_{i}" for i in range(3)]
        # An empty slot is 0, which the id table maps to "ability_base".
        final = [k for s in slots if p.get(s) and (k := item_keys.get(str(p[s])))]
        buys = [
            [int(e["time"]), str(e["key"])]
            for e in p.get("purchase_log") or []
            if isinstance(e, Mapping) and isinstance(e.get("time"), int | float) and e.get("key")
        ]
        players.append(
            {
                "hero": int(hero),
                "win": bool(radiant_win) == (int(p.get("player_slot") or 0) < 128),
                "final": final,
                "buys": buys or None,
            }
        )
    if not players:
        return None
    return {
        "match_id": int(match.get("match_id") or row["match_id"]),
        "start_time": int(match.get("start_time") or row.get("start_time") or 0),
        "avg_rank_tier": row.get("avg_rank_tier"),
        "duration": match.get("duration"),
        "players": players,
    }


def collect(
    client: OpenDotaClient,
    have: set[int],
    item_keys: Mapping[str, str],
    max_calls: int,
    min_rank: int = MIN_RANK,
    progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """New Turbo matches, newest first, until ``max_calls`` requests or the daily allowance runs out."""
    start = client.requests_made
    out: list[dict[str, Any]] = []
    cursor: int | None = None

    def spent() -> int:
        return client.requests_made - start

    try:
        while spent() < max_calls:
            params: dict[str, Any] = {"min_rank": min_rank}
            if cursor:
                params["less_than_match_id"] = cursor
            rows = client.get("publicMatches", params, ttl=365 * 86400 if cursor else 0)
            if not rows:
                break
            cursor = min(int(r["match_id"]) for r in rows)
            for r in rows:
                mid = int(r["match_id"])
                if r.get("game_mode") != TURBO or mid in have:
                    continue
                if spent() >= max_calls:
                    break
                try:
                    match = client.get(f"matches/{mid}", ttl=30 * 86400)
                except NotFoundError:
                    continue
                kept = normalize(match, r, item_keys)
                have.add(mid)
                if kept:
                    out.append(kept)
            if progress is not None:
                progress(spent(), max_calls)
    except BudgetExhaustedError:
        pass  # what was collected so far is kept; the rest waits for tomorrow's allowance
    return out


def aggregate(matches: Iterable[Mapping[str, Any]], cost: Callable[[str], int]) -> dict[str, Any]:
    """Per hero: starting items and first big items from parsed games, final items from all games."""
    games: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    n_matches = 0
    for m in matches:
        n_matches += 1
        for p in m["players"]:
            games[p["hero"]].append(p)
    heroes: dict[str, Any] = {}
    for hero, plays in games.items():
        parsed = [p for p in plays if p["buys"]]
        start: Counter[str] = Counter()
        start_qty: Counter[str] = Counter()
        first_big: dict[str, list[int]] = defaultdict(list)
        for p in parsed:
            pre = [k for t, k in p["buys"] if t <= 0]
            start.update(set(pre))
            start_qty.update(pre)
            seen: set[str] = set()
            for t, k in p["buys"]:
                if 0 < t <= EARLY_S and k not in seen and cost(k) >= BIG_ITEM:
                    first_big[k].append(t)
                    seen.add(k)
        final: Counter[str] = Counter()
        final_wins: Counter[str] = Counter()
        for p in plays:
            for k in set(p["final"]):
                final[k] += 1
                final_wins[k] += p["win"]
        heroes[str(hero)] = {
            "games": len(plays),
            "wins": sum(p["win"] for p in plays),
            "parsed": len(parsed),
            "starting": [
                {"item": k, "share": round(n / len(parsed), 3), "avg_count": round(start_qty[k] / n, 2)}
                for k, n in start.most_common()
            ],
            "first_big": sorted(
                (
                    {
                        "item": k,
                        "share": round(len(ts) / len(parsed), 3),
                        "median_time": int(statistics.median(ts)),
                    }
                    for k, ts in first_big.items()
                ),
                key=lambda r: r["median_time"],
            ),
            "final": [
                {"item": k, "share": round(n / len(plays), 3), "win_rate": round(final_wins[k] / n, 3)}
                for k, n in final.most_common(15)
            ],
        }
    return {"min_rank": MIN_RANK, "matches": n_matches, "heroes": heroes}
