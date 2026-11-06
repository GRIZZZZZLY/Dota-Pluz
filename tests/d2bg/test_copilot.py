"""The Copilot pipeline (stage 1): GameContext, events, the SQLite journal and its API.

Driven by the synthetic demo match, by the two real recordings in ``fixtures/`` and by hand-made
contexts. Nothing here touches the network or a paid API.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from d2bg.api.app import create_app
from d2bg.copilot import baseline
from d2bg.copilot.models import GameContext
from d2bg.copilot.pipeline import Copilot, build_context, diff_events
from d2bg.copilot.store import MIGRATIONS, CopilotStore
from d2bg.gsi import recorder
from d2bg.gsi.demo import DEMO_MATCH_ID, demo_frames
from d2bg.live.engine import LiveEngine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def frames(shared_ctx):
    return [p for _, p in demo_frames(shared_ctx, "juggernaut", minutes=30)]


def feed(app, payloads, store, source="demo"):
    """Run payloads through a fresh LiveEngine and Copilot on a fake clock, one second per payload."""
    now = [1_000.0]
    engine = LiveEngine(app, clock=lambda: now[0])
    copilot = Copilot(app, store, clock=lambda: now[0])
    events = []
    for payload in payloads:
        now[0] += 1
        engine.ingest(payload, source=source)
        events += copilot.observe(engine, source)
    return engine, copilot, events


def clock_of(payload) -> float | None:
    return (payload.get("map") or {}).get("clock_time")


def journal(store, match_id=DEMO_MATCH_ID):
    return sorted(
        (r.type, r.candidate_id, r.context_hash, r.status, r.game_time_s)
        for r in store.recommendations(match_id, 500)
    )


# ── store ──────────────────────────────────────────────────────────


def test_store_migrates_once_and_uses_wal(tmp_path):
    path = tmp_path / "copilot.sqlite3"
    store = CopilotStore(path)
    assert store.version == len(MIGRATIONS)
    assert store._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.close()
    again = CopilotStore(path)  # reopening runs nothing twice
    assert again.version == len(MIGRATIONS)
    assert again.counts() == {"matches": 0, "gsi_events_index": 0, "recommendations": 0}
    again.close()


# ── context ────────────────────────────────────────────────────────


def test_context_before_any_data_is_unknown(shared_ctx):
    c = build_context(LiveEngine(shared_ctx), shared_ctx, now=0.0)
    assert c.match_id is None and c.hero_id is None and c.gold is None and c.data_age_s is None
    assert c.patch == shared_ctx.data.patch
    assert c.sources == {
        "match": "unknown",
        "patch": "snapshot",
        "hero": "unknown",
        "position": "unknown",
        "draft": "unknown",
        "economy": "unknown",
    }


def test_context_mid_game_from_gsi(shared_ctx, frames):
    _, copilot, _ = feed(
        shared_ctx, [p for p in frames if (clock_of(p) or 0) <= 600], CopilotStore(":memory:")
    )
    c = copilot.context
    assert c.match_id == DEMO_MATCH_ID and c.phase == "in_game" and c.time_s == 600
    assert c.hero_key == "juggernaut" and c.level and c.level > 1
    assert c.learned_skills and sum(c.learned_skills.values()) > 0
    assert c.inventory and c.gold is not None and c.gpm and c.buyback_cost
    assert len(c.allies) == 5 and len(c.enemies_visible) == 5
    assert c.sources["hero"] == c.sources["economy"] == c.sources["draft"] == "gsi"
    assert c.position is None and c.sources["position"] == "unknown"
    assert {"hero:juggernaut", "build:juggernaut", f"level:{c.level}"} <= set(c.evidence_ids)
    assert all(f"inventory:{k}" in c.evidence_ids for k in c.owned)


def test_position_comes_only_from_one_chosen_position(ctx, frames):
    ctx.settings.update({"positions": [1]})
    _, copilot, _ = feed(ctx, frames[:5], CopilotStore(":memory:"))
    assert copilot.context.position == 1 and copilot.context.sources["position"] == "manual"


# ── events ─────────────────────────────────────────────────────────


def test_events_between_two_contexts():
    prev = GameContext(
        match_id="1", phase="in_game", time_s=100, level=5, alive=True,
        learned_skills={"a": 2, "b": 1}, inventory=["tango", "boots"],
    )  # fmt: skip
    cur = prev.model_copy(
        update={
            "time_s": 101,
            "level": 6,
            "alive": False,
            "learned_skills": {"a": 3, "b": 1},
            "inventory": ["boots", "magic_wand"],
            "enemies_visible": [4],
        }
    )
    got = {(e.type, e.detail) for e in diff_events(prev, cur)}
    assert got == {
        ("skill_point_gained", "6"),
        ("skill_leveled", "a:3"),
        ("item_changed", "+magic_wand"),
        ("item_changed", "-tango"),
        ("draft_changed", "allies=0 enemies=1"),
        ("death", ""),
    }
    assert all(e.game_time_s == 101 for e in diff_events(prev, cur))


def test_moving_an_item_to_the_stash_is_not_a_change():
    prev = GameContext(match_id="1", inventory=["boots"])
    assert diff_events(prev, prev.model_copy(update={"inventory": [], "stash": ["boots"]})) == []


def test_new_match_restores_state_without_replaying_it():
    cur = GameContext(match_id="2", phase="in_game", level=12, inventory=["bfury"])
    assert [e.type for e in diff_events(None, cur)] == ["match_started"]
    assert [e.type for e in diff_events(GameContext(match_id="1", level=3), cur)] == ["match_started"]
    assert diff_events(None, GameContext()) == []  # menu: no match, nothing to journal


# ── journal ────────────────────────────────────────────────────────


def test_demo_match_is_journaled(shared_ctx, frames):
    store = CopilotStore(":memory:")
    _, _, events = feed(shared_ctx, frames, store)
    kinds = {e.type for e in events}
    assert {"match_started", "hero_selected", "skill_leveled", "item_changed", "match_finished"} <= kinds
    counts = store.counts()
    assert counts["matches"] == 1 and counts["gsi_events_index"] == len(events)
    recs = store.recommendations(DEMO_MATCH_ID, 500)
    assert {r.type for r in recs} == {"ITEM_NEXT", "ITEM_SITUATIONAL", "SKILL_LEVEL"}
    assert {r.category for r in recs if r.type == "ITEM_SITUATIONAL"} == {"situational", "defensive"}
    for r in recs:
        assert r.source == "baseline" and r.data_patch == shared_ctx.data.patch and r.reason_ru
        assert r.evidence_ids and all(
            e.split(":")[0] in {"build", "level", "inventory", "enemy"} for e in r.evidence_ids
        )
        if r.type == "SKILL_LEVEL":
            assert r.confidence_kind == "pro_pick_share" and 0 < (r.confidence or 0) <= 1
        else:
            assert r.confidence is None and r.confidence_kind == "none"
    # Every item and skill he took while it was advised is marked as followed; the match end closes the rest.
    assert {r.status for r in recs} == {"followed", "expired"}
    assert {r.type for r in recs if r.status == "followed"} == {"ITEM_NEXT", "SKILL_LEVEL"}
    row = store._db.execute("SELECT source, hero_id FROM matches").fetchone()
    assert tuple(row) == ("demo", shared_ctx.data.heroes.require("juggernaut").id)


def test_replaying_a_match_is_idempotent_and_deterministic(shared_ctx, frames, tmp_path):
    store = CopilotStore(tmp_path / "a.sqlite3")
    feed(shared_ctx, frames, store)
    first, counts = journal(store), store.counts()
    feed(shared_ctx, frames, store)  # the same match again: nothing is stored twice
    assert store.counts() == counts and journal(store) == first
    other = CopilotStore(tmp_path / "b.sqlite3")
    feed(shared_ctx, frames, other)  # and a fresh journal ends up identical
    assert journal(other) == first


def test_starting_in_the_middle_of_a_match(shared_ctx, frames):
    store = CopilotStore(":memory:")
    late = [p for p in frames if (clock_of(p) or 0) >= 15 * 60]
    _, copilot, events = feed(shared_ctx, late, store)
    assert events[0].type == "match_started" and events[0].game_time_s == 15 * 60
    assert copilot.context.level and copilot.context.inventory
    recs = store.recommendations(DEMO_MATCH_ID, 50)
    assert recs and all((r.game_time_s or 0) >= 15 * 60 for r in recs)


def test_a_recommendation_citing_unknown_facts_is_dropped(shared_ctx, frames, monkeypatch):
    real = baseline.recommendations

    def citing_ghosts(c, snap, app):
        return [r.model_copy(update={"evidence_ids": ["enemy:not_in_this_game"]}) for r in real(c, snap, app)]

    monkeypatch.setattr(baseline, "recommendations", citing_ghosts)
    store = CopilotStore(":memory:")
    feed(shared_ctx, frames[:200], store)
    assert store.counts()["recommendations"] == 0 and store.counts()["gsi_events_index"] > 0


def test_real_ranked_draft_that_ends_in_the_menu(shared_ctx):
    """His recording: loading, hero selection, strategy time, then back to the menu with no post-game."""
    store = CopilotStore(":memory:")
    payloads = [p for _, p in recorder.read(FIXTURES / "player_draft_ranked.jsonl.gz")]
    in_draft = [p for p in payloads if (p.get("map") or {}).get("game_state")]
    _, copilot, events = feed(shared_ctx, in_draft, store, source="replay")
    assert events[0].type == "match_started" and "hero_selected" in {e.type for e in events}
    c = copilot.context
    assert c.phase == "strategy" and c.hero_id and c.sources["hero"] == "gsi"
    assert c.enemies_visible == []  # a player's GSI never carries the enemy draft
    _, after, _ = feed(shared_ctx, payloads, CopilotStore(":memory:"), source="replay")
    assert after.context.match_id is None and after.context.allies == []
    assert after.context.sources["draft"] == "unknown"


def test_real_game_from_showcase_into_the_first_minute(shared_ctx):
    store = CopilotStore(":memory:")
    payloads = [p for _, p in recorder.read(FIXTURES / "player_pre_game.jsonl.gz")]
    _, copilot, events = feed(shared_ctx, payloads, store, source="replay")
    c = copilot.context
    assert events[0].type == "match_started" and c.phase == "in_game" and c.hero_id
    assert c.allies and c.sources["draft"] == "gsi"  # allies come from the minimap after loading
    recs = store.recommendations(c.match_id, 100)
    assert recs and all(set(r.evidence_ids) <= set(c.evidence_ids) for r in recs if r.status == "suggested")


# ── API ────────────────────────────────────────────────────────────


@pytest.fixture
def client(ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("D2BG_HOME", str(tmp_path / "home"))
    with TestClient(create_app(ctx, static_dir=tmp_path / "no-ui")) as c:
        yield c


def test_status_without_data(client, ctx):
    r = client.get("/api/copilot/status")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "no_data" and body["mode"] == "none" and body["match_id"] is None
    assert body["providers"] == {"baseline": {"configured": True, "online": True}}
    assert body["journal"] == {"matches": 0, "gsi_events_index": 0, "recommendations": 0}
    assert body["patch"]["data"] == ctx.data.patch and body["error"] is None
    settings = ctx.settings.get()
    assert settings.gsi_token not in r.text and settings.lan_token not in r.text
    assert client.get("/api/copilot/recommendations").json() == []


def test_gsi_post_flows_into_the_journal(client, ctx, frames):
    token = ctx.settings.get().gsi_token
    assert client.post("/gsi", json={**frames[0], "auth": {"token": token}}).status_code == 200
    svc = client.app.state.services
    for payload in frames[1:400]:
        svc.engine.ingest(payload, source="demo")
    body = client.get("/api/copilot/status").json()
    assert body["state"] == "ok" and body["mode"] == "demo" and body["match_id"] == DEMO_MATCH_ID
    assert body["context"]["hero_key"] == "juggernaut" and body["journal"]["recommendations"] > 0
    assert token not in str(body)
    recs = client.get("/api/copilot/recommendations", params={"limit": 3}).json()
    assert 0 < len(recs) <= 3 and recs[0]["match_id"] == DEMO_MATCH_ID
    assert client.get("/api/copilot/recommendations", params={"match_id": "nope"}).json() == []


def test_a_copilot_failure_never_stops_the_live_view(client, frames, monkeypatch):
    svc = client.app.state.services

    def broken(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(svc.copilot, "observe", broken)
    svc.engine.ingest(frames[0], source="demo")
    assert client.get("/api/live").json()["match_id"] == DEMO_MATCH_ID
    assert client.get("/api/copilot/status").json()["error"] == "RuntimeError: disk full"
