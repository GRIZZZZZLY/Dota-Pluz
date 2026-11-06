"""Stage 2: the offline baseline. Skill and talent rules, item groups, the buyback guard, the validator,
and what became of each recommendation. Hand-made contexts pin the rules; the demo match and the two
real recordings check that no shown recommendation is ever an action the game would refuse.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from d2bg.api.app import create_app
from d2bg.builds.skills import blocked, data_ranks, next_skill, next_talent
from d2bg.copilot import baseline
from d2bg.copilot.models import GameContext
from d2bg.copilot.pipeline import Copilot, _evidence
from d2bg.copilot.store import CopilotStore
from d2bg.gsi import recorder
from d2bg.gsi.demo import DEMO_MATCH_ID, demo_frames
from d2bg.gsi.state import parse, unspent_skill_points
from d2bg.knowledge.counters import situational_items
from d2bg.live.engine import LiveEngine

FIXTURES = Path(__file__).parent / "fixtures"
JUGG = ["juggernaut_blade_fury", "juggernaut_healing_ward", "juggernaut_blade_dance", "juggernaut_omni_slash"]


@pytest.fixture(scope="module")
def abilities(shared_ctx):
    return shared_ctx.data.load("abilities.json")


def recording(name):
    return [p for _, p in recorder.read(FIXTURES / name)]


def context(app, **fields) -> GameContext:
    base = {
        "match_id": "1",
        "phase": "in_game",
        "time_s": 600.0,
        "patch": app.data.patch,
        "hero_id": app.data.heroes.require("juggernaut").id,
        "hero_key": "juggernaut",
        "level": 7,
        "learned_skills": dict.fromkeys(JUGG, 0),
        "ultimates": ["juggernaut_omni_slash"],
        "talents": [False] * 8,
    }
    c = GameContext(**{**base, **fields})
    c.evidence_ids = _evidence(c, app)
    return c


def rec(c, kind, candidate, evidence=None, category=None):
    return baseline._rec(
        c,
        baseline.context_hash(c),
        kind,
        candidate,
        reason_ru="тест",
        evidence=evidence if evidence is not None else ["build:juggernaut"],
        category=category,
    )


# ── levelling rules ────────────────────────────────────────────────


def test_rank_count_comes_from_the_ability_data(abilities):
    assert data_ranks(abilities["juggernaut_blade_fury"]) == 4
    assert data_ranks(abilities["juggernaut_omni_slash"]) == 3
    assert data_ranks(None) is None and data_ranks({"cd": "10"}) is None
    # Invoker's orbs list more values than the 4 ranks of a basic ability: not checkable, so never advised.
    assert blocked(0, 30, False, data_ranks(abilities["invoker_quas"])) == "unknown"


@pytest.mark.parametrize(
    ("rank", "hero_level", "ultimate", "ranks", "why"),
    [
        (0, 1, False, 4, None),
        (1, 2, False, 4, "level"),  # rank 2 of a basic ability needs hero level 3
        (1, 3, False, 4, None),
        (3, 7, False, 4, None),
        (4, 25, False, 4, "max"),
        (0, 5, True, 3, "level"),  # ultimate at 6, 12, 18
        (0, 6, True, 3, None),
        (1, 11, True, 3, "level"),
        (2, 18, True, 3, None),
        (3, 30, True, 3, "max"),
        (0, 30, False, None, "unknown"),
        (0, 30, True, 4, "unknown"),  # data and the GSI flag disagree
    ],
)
def test_levelling_rules(rank, hero_level, ultimate, ranks, why):
    assert blocked(rank, hero_level, ultimate, ranks) == why


def test_next_skill_follows_the_pro_order_from_where_he_is(abilities):
    q, w, e, r = JUGG
    order = [{"ability": k, "share": 0.9, "n": 60} for k in (q, w, q, e, q, r, q, e, e, e)]
    ult = {r}
    # He matches the pros so far: the next step is theirs.
    assert next_skill({q: 2, w: 1, e: 0, r: 0}, ult, 4, order, abilities)["ability"] == e
    # He took E early instead of W: W is still owed and comes first.
    got = next_skill({q: 1, w: 0, e: 1, r: 0}, ult, 3, order, abilities)
    assert got["ability"] == w and got["rank"] == 1
    # At level 5 the pros' ultimate (needs 6) and Q rank 4 (needs 7) are not legal yet; E rank 2 is.
    got = next_skill({q: 3, w: 1, e: 1, r: 0}, ult, 5, order, abilities)
    assert (got["ability"], got["rank"]) == (e, 2)
    # Nothing legal left in the pro order: no suggestion rather than a guess.
    assert next_skill({q: 4, w: 1, e: 4, r: 1}, ult, 11, order, abilities) is None
    # An ability he does not have (another facet) is passed over.
    assert next_skill({w: 0}, ult, 1, order, abilities)["ability"] == w


def test_next_talent_tiers():
    tiers = {"a": 1, "b": 1, "c": 2, "d": 2, "e": 3, "f": 3, "g": 4, "h": 4}
    pro = {"a": {"share": 0.3, "n": 20}, "b": {"share": 0.7, "n": 40}, "c": {"share": 0.6, "n": 30}}
    assert next_talent([False] * 8, 9, tiers, pro) is None
    got = next_talent([False] * 8, 10, tiers, pro)
    assert (got["talent"], got["alternative"], got["level"], got["n"]) == ("b", "a", 10, 40)
    taken = [True] + [False] * 7
    assert next_talent(taken, 14, tiers, pro) is None
    assert next_talent(taken, 15, tiers, pro)["talent"] == "c"
    assert next_talent([False] * 2, 30, tiers, pro) is None  # unknown shape
    assert (
        next_talent([True, False, True, False, False, False, False, False], 20, tiers, pro) is None
    )  # no pro data


def test_cosmetic_abilities_no_longer_hide_skill_points(shared_ctx):
    """His real game: GSI lists plus_high_five, the guild banner and three seasonal abilities with
    levels up to 5. Counting them made every skill point look spent."""
    payload = copy.deepcopy(recording("player_pre_game.jsonl.gz")[-1])
    payload["hero"]["level"] = 3
    s = parse(payload, 0.0, {h.key: h.id for h in shared_ctx.data.heroes})
    own = {a.key for a in shared_ctx.data.heroes.require("necrolyte").abilities}
    assert unspent_skill_points(s) == 0  # the old count
    assert unspent_skill_points(s, own) == 2
    engine = LiveEngine(shared_ctx)
    engine.ingest(payload, source="replay")
    skills = engine.snapshot()["skills"]
    assert skills["unspent"] == 2
    assert {a["key"] for a in skills["abilities"]} <= own
    assert skills["next"] and skills["next"]["ability"] in own


# ── items ──────────────────────────────────────────────────────────


def situational(app, enemies, owned=()):
    """What LiveEngine puts in its snapshot for this enemy lineup."""
    rules = situational_items(
        enemies, app.traits, app.counter_rules, app.data.items, app.data.heroes.name, owned
    )
    return {"situational_items": rules}


def test_counter_items_are_split_into_situational_and_defensive(shared_ctx):
    enemy_keys = ["riki", "lion", "lina", "shadow_shaman"]
    enemies = [shared_ctx.data.heroes.require(k).id for k in enemy_keys]
    c = context(shared_ctx, enemies_visible=enemies)
    recs = baseline.recommendations(c, situational(shared_ctx, enemies), shared_ctx)
    by_cat = {r.category: r for r in recs if r.type == "ITEM_SITUATIONAL"}
    assert set(by_cat) == {"situational", "defensive"}
    for r in by_cat.values():
        assert r.reason_ru and "Против:" in r.reason_ru
        assert r.evidence_ids and all(e.startswith("enemy:") for e in r.evidence_ids)
        assert baseline.rejection(r, c, shared_ctx) is None
    assert by_cat["situational"].candidate_id in {"dust", "ward_sentry", "gem"}  # Riki is invisible


def test_owning_one_answer_settles_the_rule(shared_ctx):
    enemies = [shared_ctx.data.heroes.require("riki").id]
    c = context(shared_ctx, enemies_visible=enemies, inventory=["dust"])
    recs = baseline.recommendations(c, situational(shared_ctx, enemies, c.owned), shared_ctx)
    assert all(r.candidate_id not in {"dust", "ward_sentry", "gem"} for r in recs)


def test_no_second_pair_of_upgraded_boots(shared_ctx):
    enemies = [shared_ctx.data.heroes.require(k).id for k in ("lion", "lina", "shadow_shaman")]
    c = context(shared_ctx, enemies_visible=enemies, inventory=["phase_boots"])
    snap = situational(shared_ctx, enemies, c.owned)
    snap["situational_items"].insert(
        0,
        {
            "id": "x",
            "reason": "x",
            "reason_ru": "тест",
            "category": "defensive",
            "heroes": ["Lion"],
            "hero_ids": enemies[:1],
            "items": [{"key": "power_treads", "owned": False}, {"key": "ghost", "owned": False}],
        },
    )
    recs = baseline.recommendations(c, snap, shared_ctx)
    defensive = next(r for r in recs if r.category == "defensive")
    assert defensive.candidate_id == "ghost" and "power_treads" not in defensive.alternatives


def test_buyback_guard(shared_ctx):
    c = context(shared_ctx, time_s=35 * 60.0, gold=5000, buyback_cost=3000)
    snap = {
        "next_items": [{"item": "butterfly", "name": "Butterfly", "remaining": 4000}],
        "buyback_warning": "Buying Butterfly leaves 1000 gold; buyback costs 3000.",
    }
    guard = next(r for r in baseline.recommendations(c, snap, shared_ctx) if r.type == "ITEM_BUYBACK_GUARD")
    assert guard.category == "buyback" and "1000" in guard.reason_ru and "3000" in guard.reason_ru
    assert baseline.rejection(guard, c, shared_ctx) is None
    early = c.model_copy(update={"time_s": 20 * 60.0})
    assert baseline.rejection(guard.model_copy(update={"match_id": "1"}), early, shared_ctx) is not None


# ── talents ────────────────────────────────────────────────────────


def test_talent_advice_from_pro_pick_rates(shared_ctx):
    c = context(shared_ctx, level=11)
    talent = next(r for r in baseline.recommendations(c, {}, shared_ctx) if r.type == "TALENT")
    assert talent.candidate_id == "special_bonus_unique_juggernaut_3"  # 83% of pro games
    assert talent.alternatives == ["special_bonus_unique_juggernaut_5"]
    assert talent.confidence_kind == "pro_pick_share" and talent.confidence == pytest.approx(0.828)
    assert baseline.rejection(talent, c, shared_ctx) is None
    done = c.model_copy(update={"talents": [False, True] + [False] * 6})
    assert baseline.rejection(talent, done, shared_ctx) == "tier already taken"
    assert not [
        r
        for r in baseline.recommendations(context(shared_ctx, level=9), {}, shared_ctx)
        if r.type == "TALENT"
    ]


# ── validator ──────────────────────────────────────────────────────


def test_validator_refuses_illegal_actions(shared_ctx):
    q, _, _, r = JUGG
    c = context(
        shared_ctx, level=5, available_skill_points=1, learned_skills={**dict.fromkeys(JUGG, 0), q: 2}
    )
    assert baseline.rejection(rec(c, "SKILL_LEVEL", q), c, shared_ctx) is None
    assert baseline.rejection(rec(c, "SKILL_LEVEL", r), c, shared_ctx) == "cannot level: level"
    maxed = c.model_copy(update={"level": 9, "learned_skills": {**c.learned_skills, q: 4}})
    assert baseline.rejection(rec(maxed, "SKILL_LEVEL", q), maxed, shared_ctx) == "cannot level: max"
    no_point = c.model_copy(update={"available_skill_points": 0})
    assert baseline.rejection(rec(no_point, "SKILL_LEVEL", q), no_point, shared_ctx) == "no skill point"
    assert (
        baseline.rejection(rec(c, "SKILL_LEVEL", "plus_high_five"), c, shared_ctx)
        == "not one of his abilities"
    )
    owned = context(shared_ctx, inventory=["black_king_bar"])
    assert baseline.rejection(rec(owned, "ITEM_NEXT", "black_king_bar"), owned, shared_ctx) == "already owned"
    assert baseline.rejection(rec(c, "ITEM_NEXT", "not_an_item"), c, shared_ctx) == "unknown item"
    ghost = rec(c, "ITEM_NEXT", "manta", evidence=["enemy:lion"])
    assert baseline.rejection(ghost, c, shared_ctx) == "cites facts that are not in the context"
    other = c.model_copy(update={"match_id": "2"})
    assert baseline.rejection(rec(c, "ITEM_NEXT", "manta"), other, shared_ctx) == "another match"
    assert baseline.rejection(rec(c, "PICK_HERO", "lion"), c, shared_ctx) is not None


def test_no_advice_outside_playable_phases(shared_ctx):
    assert baseline.recommendations(context(shared_ctx, phase="post_game"), {}, shared_ctx) == []
    assert baseline.recommendations(context(shared_ctx, phase="hero_selection"), {}, shared_ctx) == []


@pytest.mark.parametrize("name", ["demo", "player_draft_ranked.jsonl.gz", "player_pre_game.jsonl.gz"])
def test_no_shown_recommendation_is_ever_an_illegal_action(shared_ctx, name):
    payloads = (
        [p for _, p in demo_frames(shared_ctx, "juggernaut", minutes=36)]
        if name == "demo"
        else recording(name)
    )
    now = [0.0]
    engine = LiveEngine(shared_ctx, clock=lambda: now[0])
    store = CopilotStore(":memory:")
    copilot = Copilot(shared_ctx, store, clock=lambda: now[0])
    checked = 0
    for payload in payloads:
        now[0] += 1
        engine.ingest(payload, source="replay")
        copilot.observe(engine, "replay")
        if copilot.context.match_id:
            for r in store.recommendations(copilot.context.match_id, 50, "suggested"):
                assert baseline.rejection(r, copilot.context, shared_ctx) is None, (r.type, r.candidate_id)
                checked += 1
    assert checked > 0 or name == "player_draft_ranked.jsonl.gz"


# ── lifecycle and API ──────────────────────────────────────────────


@pytest.fixture
def client(ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("D2BG_HOME", str(tmp_path / "home"))
    with TestClient(create_app(ctx, static_dir=tmp_path / "no-ui")) as c:
        yield c


def test_dismiss_hides_a_recommendation_for_good(client, shared_ctx):
    svc = client.app.state.services
    for _, payload in demo_frames(shared_ctx, "juggernaut", minutes=5):
        if payload["map"].get("game_state") != "DOTA_GAMERULES_STATE_POST_GAME":
            svc.engine.ingest(payload, source="demo")
    shown = client.get("/api/copilot/recommendations", params={"status": "suggested"}).json()
    assert shown and all(r["status"] == "suggested" and r["match_id"] == DEMO_MATCH_ID for r in shown)
    target = shown[0]["id"]
    assert client.post(f"/api/copilot/recommendations/{target}/dismiss").json() == {"ok": True}
    assert client.post(f"/api/copilot/recommendations/{target}/dismiss").status_code == 404
    again = client.get("/api/copilot/recommendations", params={"status": "suggested"}).json()
    assert target not in {r["id"] for r in again}
    status = client.get("/api/copilot/status").json()
    assert isinstance(status["rejected"], list)
    assert client.get("/api/copilot/recommendations", params={"status": "nonsense"}).status_code == 422
