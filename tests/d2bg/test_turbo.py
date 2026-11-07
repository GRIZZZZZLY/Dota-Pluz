"""Turbo builds from strong players' public matches, against a fake OpenDota."""

from __future__ import annotations

import json
from typing import Any

import pytest

from d2bg import paths
from d2bg.api.services import Services
from d2bg.opendota import BudgetExhaustedError, NotFoundError
from d2bg.pipeline import turbo
from d2bg.pipeline.refresh import Refresher, read_matches_gz


@pytest.fixture(scope="module")
def ids(data) -> dict[str, int]:
    return {key: int(i) for i, key in data.load("ids.json")["items"].items()}


@pytest.fixture(scope="module")
def item_keys(data) -> dict[str, str]:
    return data.load("ids.json")["items"]


def player(
    slot: int, hero: int, items: list[int], buys: list[tuple[int, str]] | None = None
) -> dict[str, Any]:
    p: dict[str, Any] = {
        "player_slot": slot,
        "hero_id": hero,
        **{f"item_{i}": v for i, v in enumerate(items)},
    }
    if buys is not None:
        p["purchase_log"] = [{"time": t, "key": k} for t, k in buys]
    return p


def match(mid: int, radiant_win: bool, players: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "match_id": mid,
        "start_time": 1_800_000_000 + mid,
        "radiant_win": radiant_win,
        "duration": 1500,
        "players": players,
    }


def test_a_match_keeps_hero_result_final_items_and_purchases(ids, item_keys):
    m = match(
        1,
        True,
        [
            player(
                0,
                8,
                [ids["bfury"], ids["phase_boots"], 0],
                [(-80, "tango"), (-80, "branches"), (420, "bfury")],
            ),
            player(128, 2, [ids["blink"]]),
        ],
    )
    row = turbo.normalize(m, {"match_id": 1, "avg_rank_tier": 75}, item_keys)
    jugg, axe = row["players"]
    assert (jugg["hero"], jugg["win"], jugg["final"]) == (8, True, ["bfury", "phase_boots"])
    assert jugg["buys"] == [[-80, "tango"], [-80, "branches"], [420, "bfury"]]
    assert (axe["win"], axe["buys"]) == (False, None)  # Dire lost; not parsed
    assert row["avg_rank_tier"] == 75
    assert turbo.normalize({"players": []}, {"match_id": 2}, item_keys) is None


def test_aggregate_per_hero(data):
    def play(win: bool, final: list[str], buys: list[list[Any]] | None) -> dict[str, Any]:
        return {"hero": 8, "win": win, "final": final, "buys": buys}

    games = [
        {
            "players": [
                play(
                    True,
                    ["bfury", "manta"],
                    [[-90, "tango"], [-90, "branches"], [-90, "branches"], [400, "bfury"]],
                )
            ]
        },
        {
            "players": [
                play(False, ["bfury"], [[-90, "tango"], [300, "magic_wand"], [600, "bfury"], [1200, "manta"]])
            ]
        },
        {"players": [play(True, ["manta"], None)]},
    ]
    doc = turbo.aggregate(games, data.items.cost)
    jugg = doc["heroes"]["8"]
    assert (doc["matches"], jugg["games"], jugg["wins"], jugg["parsed"]) == (3, 3, 2, 2)
    starting = {s["item"]: s for s in jugg["starting"]}
    assert starting["tango"]["share"] == 1.0 and starting["branches"] == {
        "item": "branches",
        "share": 0.5,
        "avg_count": 2.0,
    }
    first_big = {f["item"]: f for f in jugg["first_big"]}
    assert first_big["bfury"] == {"item": "bfury", "share": 1.0, "median_time": 500}
    assert "magic_wand" not in first_big  # cheaper than 1,000 gold
    assert "manta" not in first_big  # bought after the first 15 minutes
    final = {f["item"]: f for f in jugg["final"]}
    assert final["manta"] == {"item": "manta", "share": 0.667, "win_rate": 1.0}
    assert final["bfury"]["win_rate"] == 0.5


class FakeOpenDota:
    """``get`` like OpenDotaClient: public match pages, then match details."""

    def __init__(
        self, pages: list[list[dict[str, Any]]], matches: dict[int, dict[str, Any]], budget: int = 10**6
    ):
        self.pages, self.matches, self.budget = pages, matches, budget
        self.requests_made = 0
        self.asked: list[str] = []

    def get(self, path: str, params: dict[str, Any] | None = None, *, ttl: float | None = None) -> Any:
        if self.requests_made >= self.budget:
            raise BudgetExhaustedError("allowance used")
        self.requests_made += 1
        self.asked.append(path)
        if path == "publicMatches":
            assert params and params["min_rank"] == turbo.MIN_RANK
            cursor = params.get("less_than_match_id")
            page = next(
                (p for p in self.pages if cursor is None or max(r["match_id"] for r in p) < cursor), []
            )
            return page if cursor is None or page != self.pages[0] else []
        mid = int(path.split("/")[1])
        if mid not in self.matches:
            raise NotFoundError(path)
        return self.matches[mid]


def feed(ids) -> FakeOpenDota:
    pages = [
        [
            {"match_id": 30, "game_mode": 23, "avg_rank_tier": 72},
            {"match_id": 29, "game_mode": 22},
            {"match_id": 28, "game_mode": 23},
        ],
        [{"match_id": 20, "game_mode": 23}, {"match_id": 19, "game_mode": 23}],
    ]
    matches = {
        mid: match(
            mid,
            True,
            [player(0, 8, [ids["bfury"]], [(-60, "tango"), (500, "bfury")]), player(128, 2, [ids["blink"]])],
        )
        for mid in (30, 20, 19)
    }  # 28 is gone from OpenDota
    return FakeOpenDota(pages, matches)


def test_collect_takes_only_new_turbo_games_within_the_budget(ids, item_keys):
    client = feed(ids)
    got = turbo.collect(client, {20}, item_keys, max_calls=100)
    assert [m["match_id"] for m in got] == [30, 19]  # 29 is not Turbo, 28 is missing, 20 was there already
    assert "matches/29" not in client.asked and "matches/20" not in client.asked
    small = feed(ids)
    assert [m["match_id"] for m in turbo.collect(small, set(), item_keys, max_calls=2)] == [30]
    assert small.requests_made == 2


def test_collect_stops_quietly_when_the_daily_allowance_is_used(ids, item_keys):
    client = feed(ids)
    client.budget = 3  # one page and two matches
    assert [m["match_id"] for m in turbo.collect(client, set(), item_keys, max_calls=100)] == [30]


def test_refresh_step_writes_builds_and_never_counts_a_game_twice(ids, tmp_path):
    client = feed(ids)
    refresher = Refresher(client, tmp_path)  # type: ignore[arg-type]
    first = refresher.turbo(max_calls=100)
    assert first.files == ["turbo_builds.json", "turbo_matches.jsonl.gz"] and first.rows == 3
    builds = json.loads((tmp_path / "turbo_builds.json").read_text(encoding="utf-8"))
    assert builds["matches"] == 3 and builds["heroes"]["8"]["parsed"] == 3
    assert builds["heroes"]["8"]["starting"][0]["item"] == "tango"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["files"][
        "turbo_builds.json"
    ]
    assert "Turbo" in manifest["source"] and manifest["parsed"] == 3
    again = Refresher(feed(ids), tmp_path).turbo(max_calls=100)  # type: ignore[arg-type]
    assert again.rows == 3 and len(read_matches_gz(tmp_path / "turbo_matches.jsonl.gz")) == 3


def test_background_collection_runs_once_a_day_and_can_be_switched_off(ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("D2BG_HOME", str(tmp_path / "home"))
    svc = Services(ctx, 4242)
    assert svc.turbo_due()  # never collected
    manifest = paths.refreshed_data_dir() / "manifest.json"
    manifest.write_text(
        json.dumps({"files": {"turbo_builds.json": {"generated_at": 4_000_000_000}}}), encoding="utf-8"
    )
    assert not svc.turbo_due()  # collected "just now"
    manifest.write_text(json.dumps({"files": {"turbo_builds.json": {"generated_at": 1}}}), encoding="utf-8")
    assert svc.turbo_due()
    ctx.settings.update({"turbo_collect": False})
    assert not svc.turbo_due()
    svc.close()
