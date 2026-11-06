"""The draft read from the screen (d2bg-cv) and corrected by hand, end to end through the API: it fills
the live draft, reaches the Copilot's context with its source, and his corrections win."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from d2bg.api.app import create_app
from d2bg.gsi.demo import DEMO_MATCH_ID, demo_frames


@pytest.fixture
def client(ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("D2BG_HOME", str(tmp_path / "home"))
    with TestClient(create_app(ctx, static_dir=tmp_path / "no-ui")) as c:
        yield c


def ids(ctx, *keys):
    return [ctx.data.heroes.require(k).id for k in keys]


def start_draft(client, shared_ctx, minutes_into=0):
    """The demo's first packets: his hero is picked, the draft is under way."""
    svc = client.app.state.services
    for _, payload in demo_frames(shared_ctx, "juggernaut", minutes=3)[:3]:
        svc.engine.ingest(payload, source="game")
    return svc


def observation(ctx, **extra):
    return {
        "radiant": [],
        "dire": ids(ctx, "lion", "pudge"),
        "bans": [],
        "unknown_slots": 1,
        "confidence": 0.81,
        "capture_resolution": [1920, 1080],
        **extra,
    }


def test_screen_draft_reaches_the_live_draft_and_the_copilot(client, ctx, shared_ctx):
    svc = start_draft(client, shared_ctx)
    token = ctx.settings.get().gsi_token
    r = client.post("/api/copilot/draft/observation", json=observation(ctx), headers={"x-d2bg-token": token})
    assert r.json() == {"ok": True, "used": True}
    draft = client.get("/api/live").json()["draft"]
    assert set(ids(ctx, "lion", "pudge")) <= set(draft["enemies"])
    assert draft["screen"] == {"unknown": 1, "confidence": 0.81}
    assert "не распознано: 1" in draft["sources"]["screen"]
    status = client.get("/api/copilot/status").json()
    context = status["context"]
    assert context["sources"]["draft"] == "cv" and context["draft_confidence"] == 0.81
    assert context["draft_unknown_slots"] == 1
    assert status["journal"]["draft_observations"] == 1
    assert svc.copilot.context.match_id == DEMO_MATCH_ID


def test_observations_need_this_computer_and_the_token(client, ctx, shared_ctx):
    start_draft(client, shared_ctx)
    body = observation(ctx)
    assert client.post("/api/copilot/draft/observation", json=body).status_code == 403
    bad = {"x-d2bg-token": "nope"}
    assert client.post("/api/copilot/draft/observation", json=body, headers=bad).status_code == 403
    good = {"x-d2bg-token": ctx.settings.get().gsi_token}
    unknown_hero = observation(ctx, dire=[99999])
    assert client.post("/api/copilot/draft/observation", json=unknown_hero, headers=good).status_code == 422
    too_many = observation(ctx, dire=ids(ctx, "lion", "pudge", "lina", "axe", "riki", "sniper"))
    assert client.post("/api/copilot/draft/observation", json=too_many, headers=good).status_code == 422


def test_no_match_no_draft(client, ctx):
    good = {"x-d2bg-token": ctx.settings.get().gsi_token}
    assert (
        client.post("/api/copilot/draft/observation", json=observation(ctx), headers=good).status_code == 409
    )
    manual = {"match_id": "1", "enemies": ids(ctx, "lion")}
    assert client.post("/api/copilot/draft/manual", json=manual).status_code == 409


def test_his_corrections_win_over_the_screen(client, ctx, shared_ctx):
    start_draft(client, shared_ctx)
    good = {"x-d2bg-token": ctx.settings.get().gsi_token}
    client.post("/api/copilot/draft/observation", json=observation(ctx), headers=good)
    lion, pudge, lina = ids(ctx, "lion", "pudge", "lina")
    me = ctx.data.heroes.require("juggernaut").id
    # The screen misread Pudge; he removes it and adds Lina.
    body = {
        "match_id": DEMO_MATCH_ID,
        "allies": [me],
        "enemies": [lion, lina],
        "bans": [],
        "removed": [pudge],
    }
    assert client.post("/api/copilot/draft/manual", json=body).json() == {"ok": True}
    draft = client.get("/api/live").json()["draft"]
    assert draft["enemies"][:2] == [lion, lina] and pudge not in draft["enemies"]
    assert client.get("/api/copilot/status").json()["context"]["sources"]["draft"] == "manual"
    # A later screen reading of the hero he removed does not bring it back.
    client.post("/api/copilot/draft/observation", json=observation(ctx), headers=good)
    assert pudge not in client.get("/api/live").json()["draft"]["enemies"]
    # A hero the game reports after his last sync is new, not removed.
    client.post("/api/copilot/draft/observation", json=observation(ctx, bans=ids(ctx, "axe")), headers=good)
    assert ids(ctx, "axe")[0] in client.get("/api/live").json()["draft"]["bans"]
    wrong_match = {**body, "match_id": "123"}
    assert client.post("/api/copilot/draft/manual", json=wrong_match).status_code == 409


def test_a_replay_owns_the_live_view(client, ctx, shared_ctx):
    start_draft(client, shared_ctx)
    client.post("/api/demo", json={"hero": "juggernaut", "speed": 1, "minutes": 3})
    good = {"x-d2bg-token": ctx.settings.get().gsi_token}
    r = client.post("/api/copilot/draft/observation", json=observation(ctx), headers=good)
    assert r.json() == {"ok": True, "used": False}
    client.post("/api/replay/stop")


def test_the_status_says_whether_the_screen_reader_runs(client):
    assert client.get("/api/copilot/status").json()["screen_reader"] == {"running": False}
    client.get("/api/copilot/status", headers={"x-d2bg-client": "cv"})
    assert client.get("/api/copilot/status").json()["screen_reader"] == {"running": True}
