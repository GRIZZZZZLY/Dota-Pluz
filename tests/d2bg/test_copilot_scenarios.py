"""GSI scenarios for the Copilot (spec acceptance 3): starting mid-match, levels and skills, item
changes, lost and repeated packets, the match end, back-to-back matches, and a recording replayed
from JSON lines. Each one runs the whole pipeline and checks that

- it never raises and every new match starts with ``match_started``;
- no recommendation shown at any moment is an action the game would refuse (spec acceptance 5);
- running the same packets again stores nothing new.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

import pytest

from d2bg.copilot import baseline
from d2bg.copilot.pipeline import Copilot
from d2bg.copilot.store import CopilotStore
from d2bg.gsi import recorder
from d2bg.gsi.demo import DEMO_MATCH_ID, demo_frames
from d2bg.live.engine import LiveEngine

FIXTURES = Path(__file__).parent / "fixtures"
Payloads = list[dict]


def clock(p: dict) -> float:
    return (p.get("map") or {}).get("clock_time") or -999


def renamed(payloads: Payloads, match_id: str) -> Payloads:
    out = copy.deepcopy(payloads)
    for p in out:
        if p.get("map", {}).get("matchid"):
            p["map"]["matchid"] = match_id
    return out


@pytest.fixture(scope="module")
def sources(shared_ctx) -> dict[str, Callable[[], Payloads]]:
    cache: dict[str, Payloads] = {}

    def demo(hero: str = "juggernaut") -> Payloads:
        if hero not in cache:
            cache[hero] = [p for _, p in demo_frames(shared_ctx, hero, minutes=36)]
        return cache[hero]

    def real(name: str) -> Payloads:
        if name not in cache:
            cache[name] = [p for _, p in recorder.read(FIXTURES / name)]
        return cache[name]

    draft, pre = "player_draft_ranked.jsonl.gz", "player_pre_game.jsonl.gz"
    largo = "player_lobby_largo.jsonl.gz"
    return {
        "demo full match": demo,
        "start at 5:00": lambda: [p for p in demo() if clock(p) >= 300],
        "start at 10:00": lambda: [p for p in demo() if clock(p) >= 600],
        "start at 15:00": lambda: [p for p in demo() if clock(p) >= 900],
        "start at 20:00": lambda: [p for p in demo() if clock(p) >= 1200],
        "start at 30:00 (buyback guard window)": lambda: [p for p in demo() if clock(p) >= 1800],
        "every 2nd packet lost": lambda: demo()[::2],
        "4 of 5 packets lost": lambda: demo()[::5],
        "a minute of packets lost": lambda: [p for p in demo() if not 300 <= clock(p) < 420],
        "every packet twice": lambda: [p for p in demo() for _ in range(2)],
        "two matches back to back": lambda: demo() + renamed(demo(), "9000000002"),
        "menu between two matches": lambda: demo() + [{}] * 5 + renamed(demo(), "9000000003"),
        "support hero (Lion)": lambda: demo("lion"),
        "Invoker: orbs break the rank pattern": lambda: demo("invoker"),
        "Anti-Mage": lambda: demo("antimage"),
        "Pudge": lambda: demo("pudge"),
        "real ranked draft, cancelled": lambda: real(draft),
        "real game from the showcase": lambda: real(pre),
        "real draft then real game": lambda: real(draft) + real(pre),
        "real game, every 3rd packet": lambda: real(pre)[::3],
        "real game repeated": lambda: real(pre) + real(pre),
        "real lobby game as Largo (10 min)": lambda: real(largo),
        "real lobby game as Largo, every 2nd packet": lambda: real(largo)[::2],
    }


SCENARIOS = [
    "demo full match",
    "start at 5:00",
    "start at 10:00",
    "start at 15:00",
    "start at 20:00",
    "start at 30:00 (buyback guard window)",
    "every 2nd packet lost",
    "4 of 5 packets lost",
    "a minute of packets lost",
    "every packet twice",
    "two matches back to back",
    "menu between two matches",
    "support hero (Lion)",
    "Invoker: orbs break the rank pattern",
    "Anti-Mage",
    "Pudge",
    "real ranked draft, cancelled",
    "real game from the showcase",
    "real draft then real game",
    "real game, every 3rd packet",
    "real game repeated",
    "real lobby game as Largo (10 min)",
    "real lobby game as Largo, every 2nd packet",
]


def run(app, payloads: Payloads, store: CopilotStore, check: bool = True) -> tuple[list, int]:
    """Feed payloads; after each one, check every shown recommendation against the validator."""
    now = [0.0]
    engine = LiveEngine(app, clock=lambda: now[0])
    copilot = Copilot(app, store, clock=lambda: now[0])
    events, checked = [], 0
    for payload in payloads:
        now[0] += 1
        engine.ingest(payload, source="replay")
        events += copilot.observe(engine, "replay")
        if check and copilot.context.match_id:
            for r in store.recommendations(copilot.context.match_id, 50, "suggested"):
                assert baseline.rejection(r, copilot.context, app) is None, (r.type, r.candidate_id)
                checked += 1
    return events, checked


def test_there_are_at_least_twenty_scenarios(sources):
    assert len(SCENARIOS) >= 20 and set(SCENARIOS) == set(sources)


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario(shared_ctx, sources, name):
    payloads = sources[name]()
    store = CopilotStore(":memory:")
    events, _ = run(shared_ctx, payloads, store)
    matches = {p["map"]["matchid"] for p in payloads if (p.get("map") or {}).get("matchid")}
    assert sum(e.type == "match_started" for e in events) >= len(matches)
    assert store.counts()["matches"] == len(matches)
    counts = store.counts()
    run(shared_ctx, payloads, store, check=False)  # the same packets again
    assert store.counts() == counts


def test_mid_match_start_restores_state_and_advises(shared_ctx, sources):
    store = CopilotStore(":memory:")
    events, checked = run(shared_ctx, sources["start at 15:00"](), store)
    assert events[0].type == "match_started" and events[0].game_time_s == 900
    assert checked > 0


def test_invoker_orbs_get_no_skill_guess(shared_ctx, sources):
    store = CopilotStore(":memory:")
    run(shared_ctx, sources["Invoker: orbs break the rank pattern"](), store)
    skills = [r for r in store.recommendations(DEMO_MATCH_ID, 500) if r.type == "SKILL_LEVEL"]
    assert all(r.candidate_id not in {"invoker_quas", "invoker_wex", "invoker_exort"} for r in skills)


def test_buyback_guard_appears_late_in_a_match(shared_ctx, sources):
    """Late demo frames with gold raised so the next item is affordable but would spend the buyback."""
    payloads = copy.deepcopy(sources["start at 30:00 (buyback guard window)"]())
    for p in payloads:
        if p.get("player") and p.get("hero"):
            p["hero"]["buyback_cost"] = 2000
            p["player"]["gold"] = 6000  # Butterfly needs about 5,450 more; buyback 2,000
    store = CopilotStore(":memory:")
    run(shared_ctx, payloads, store)
    guard = [r for r in store.recommendations(DEMO_MATCH_ID, 500) if r.type == "ITEM_BUYBACK_GUARD"]
    assert guard and guard[0].category == "buyback" and "2000" in guard[0].reason_ru


def test_a_recorded_match_replays_to_the_same_journal(shared_ctx, sources, tmp_path):
    """Live packets -> Recorder (.jsonl.gz) -> read back -> the same recommendations."""
    payloads = sources["demo full match"]()
    rec = recorder.Recorder(tmp_path / "rec", clock=iter(range(10**6)).__next__)
    for p in payloads:
        rec.write({**p, "auth": {"token": "secret"}})
    rec.close()
    (path,) = (tmp_path / "rec").glob("*.jsonl.gz")
    replayed = [p for _, p in recorder.read(path)]
    assert all("auth" not in p for p in replayed)

    def journal(store):
        return sorted(
            (r.type, r.category, r.candidate_id, r.status) for r in store.recommendations(DEMO_MATCH_ID, 500)
        )

    live, again = CopilotStore(":memory:"), CopilotStore(":memory:")
    run(shared_ctx, payloads, live)
    run(shared_ctx, replayed, again)
    assert journal(again) == journal(live) and journal(live)


def test_real_lobby_game_journal(shared_ctx, sources):
    """His bot lobby as Largo (2026-11-07, anonymised): the teams from the minimap, advice he took marked
    as followed, one row per piece of advice, and no fake levelling while Amphibian Rhapsody hides the
    basic abilities behind its songs."""
    payloads = sources["real lobby game as Largo (10 min)"]()
    engine = LiveEngine(shared_ctx)
    for p in payloads:
        engine.ingest(p, source="replay")
    draft = engine.snapshot()["draft"]
    name = shared_ctx.data.heroes.name
    assert {name(h) for h in draft["allies"]} == {
        "Largo",
        "Drow Ranger",
        "Witch Doctor",
        "Phantom Assassin",
        "Luna",
    }
    assert {name(h) for h in draft["enemies"]} == {
        "Kunkka",
        "Oracle",
        "Death Prophet",
        "Bloodseeker",
        "Jakiro",
    }

    store = CopilotStore(":memory:")
    events, _ = run(shared_ctx, payloads, store)
    journal = store.recommendations("1000000003", 500)
    statuses = {(r.type, r.status) for r in journal}
    assert ("SKILL_LEVEL", "followed") in statuses and ("ITEM_NEXT", "followed") in statuses
    levelled = [e.detail for e in events if e.type == "skill_leveled" and not e.detail.startswith("talent")]
    assert len(levelled) == len(set(levelled)) and not any("song" in d for d in levelled)
    items = [
        r.candidate_id for r in sorted(journal, key=lambda r: r.game_time_s or 0) if r.type == "ITEM_NEXT"
    ]
    assert all(a != b for a, b in pairwise(items))  # one row per piece of advice
