"""Stage 5: the post-match coach. A hand-made game (journal + GSI recording) with known mistakes, the
analyst with a mocked DeepSeek, and the API. Nothing here reaches the network."""

from __future__ import annotations

import gzip
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from d2bg import apikeys
from d2bg.api.app import create_app
from d2bg.copilot import analyst, coach
from d2bg.copilot.models import CopilotEvent, GameContext
from d2bg.copilot.providers import AdvisorClient, ProviderError
from d2bg.copilot.store import CopilotStore

MATCH = "8100000001"
URL = "https://api.forgetapi.ru/v1/chat/completions"
CERTAINTY = {"verified", "likely", "insufficient_data"}


def payload(t: int, *, alive: bool, gold: int, reliable: int, lh: int, deaths: int) -> dict:
    return {
        "map": {
            "matchid": MATCH,
            "clock_time": t,
            "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
            "win_team": "none",
        },
        "player": {
            "team_name": "radiant",
            "gold": gold,
            "gold_reliable": reliable,
            "gpm": 300,
            "xpm": 400,
            "last_hits": lh,
            "kills": 0,
            "deaths": deaths,
            "assists": 0,
        },
        "hero": {"id": 8, "alive": alive, "level": 1 + t // 120, "buyback_cost": 600, "buyback_cooldown": 0},
    }


def make_game(store: CopilotStore, recordings, *, rich_death: bool = True) -> None:
    """A normal-mode Juggernaut game: deaths at 3:20 and 6:40 (the second with 2,500 gold on hand),
    skill points left for over a minute twice, Power Treads very late."""
    frames, deaths = [], 0
    for t in range(0, 1500, 2):
        dead = 200 <= t < 230 or 400 <= t < 430
        if t in (200, 400):
            deaths += 1
        gold = 2500 if rich_death and 380 <= t < 400 else 300
        frames.append(payload(t, alive=not dead, gold=gold, reliable=int(t * 1.5), lh=t // 30, deaths=deaths))
    recordings.mkdir(parents=True, exist_ok=True)
    name = f"20261108-000000_{MATCH}.jsonl.gz"
    with gzip.open(recordings / name, "wt", encoding="utf-8") as f:
        for i, p in enumerate(frames):
            f.write(json.dumps({"t": i * 2.0, "p": p}) + "\n")
    store.upsert_match(GameContext(match_id=MATCH, hero_id=8, team="radiant", time_s=0), "game", 1.0, name)

    def ev(kind: str, t: float, detail: str = "") -> CopilotEvent:
        return CopilotEvent(type=kind, match_id=MATCH, game_time_s=t, detail=detail)

    store.add_events(
        [
            ev("death", 200),
            ev("death", 400),
            ev("skill_point_gained", 240, "3"),
            ev("skill_leveled", 320, "juggernaut_blade_fury:2"),
            ev("skill_point_gained", 480, "5"),
            ev("skill_leveled", 560, "juggernaut_healing_ward:1"),
            ev("item_changed", 1300, "+power_treads"),
            ev("item_changed", 1400, "+battle_fury"),
        ],
        2.0,
        name,
        0,
    )


@pytest.fixture
def game(ctx, tmp_path):
    store = CopilotStore(tmp_path / "copilot.sqlite3")
    make_game(store, tmp_path / "recordings")
    return store, tmp_path / "recordings"


def test_the_report_finds_the_mistakes_with_evidence(ctx, game):
    store, recordings = game
    r = coach.build(ctx, store, MATCH, recordings)
    assert r["mode"] == "normal" and r["hero"] == "Juggernaut" and r["stats"]["deaths"] == 2
    ids = {f["id"] for f in r["findings"]}
    assert {"deaths_early", "death_with_gold", "skill_delay"} <= ids
    rich = next(f for f in r["findings"] if f["id"] == "death_with_gold")
    assert rich["actual"] == 2500 and rich["review_anchor"] == "6:40" and rich["certainty"] == "verified"
    for f in r["findings"]:  # every finding is complete and cites only what the report holds
        assert f["certainty"] in CERTAINTY and f["comparison_group"] and f["evidence_ids"]
        assert set(f["evidence_ids"]) <= set(r["evidence_ids"])
    assert len(r["goals"]) <= 3 and r["goals"][0]["text"].startswith("Не умирать с запасом")
    assert any("OpenDota" in m for m in r["missing"])  # the missing source is said, not filled in


def test_without_a_recording_the_report_is_partial(ctx, tmp_path):
    store = CopilotStore(tmp_path / "copilot.sqlite3")
    store.upsert_match(GameContext(match_id=MATCH, hero_id=8, time_s=0), "game", 1.0, None)
    store.add_events([CopilotEvent(type="death", match_id=MATCH, game_time_s=100)], 2.0, None, None)
    r = coach.build(ctx, store, MATCH, tmp_path)
    assert r["stats"] is None and any("Нет записи GSI" in m for m in r["missing"])
    assert "death_with_gold" not in {f["id"] for f in r["findings"]}  # needs the recording: not guessed


def test_problems_that_come_back(ctx, game):
    store, recordings = game
    r = coach.build(ctx, store, MATCH, recordings)
    store.save_report(MATCH, "facts", 1.0, coach.REPORT_VERSION, r)
    store.save_report("8100000002", "facts", 2.0, coach.REPORT_VERSION, r)
    again = {x["metric"]: x for x in coach.recurring(store)}
    assert again["death_with_gold"]["matches"] == 2 and again["death_with_gold"]["of"] == 2


def answer(findings: list[dict]) -> httpx.Response:
    body = {
        "summary": "Две ранние смерти и золото, потерянное при смерти.",
        "strengths": ["Нет смертей после 7-й минуты."],
        "findings": findings,
        "practice_goals": ["Не умирать с запасом больше 1000 золота"],
        "unknowns": ["Нет данных OpenDota."],
    }
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 200},
        },
    )


@respx.mock
def test_the_analyst_cites_only_real_evidence(ctx, game):
    store, recordings = game
    r = coach.build(ctx, store, MATCH, recordings)
    real = next(f for f in r["findings"] if f["id"] == "death_with_gold")["evidence_ids"]
    route = respx.post(URL).mock(
        return_value=answer(
            [
                {"text": "Смерть с золотом на 6:40.", "evidence_ids": real, "certainty": "verified"},
                {"text": "Проиграли из-за Roshan.", "evidence_ids": ["ev:999999"], "certainty": "likely"},
            ]
        )
    )
    client = AdvisorClient("fgt-test", "https://api.forgetapi.ru/v1", "deepseek-v4-flash")
    ai, call = analyst.analyze(r, client)
    assert [f["text"] for f in ai["findings"]] == ["Смерть с золотом на 6:40."] and ai[
        "blocked_findings"
    ] == 1
    sent = json.loads(json.loads(route.calls[0].request.content)["messages"][1]["content"])
    assert "allowed_evidence_ids" in sent and "frames" not in json.dumps(sent)  # facts only, no raw data
    assert call.input_tokens == 900


@respx.mock
def test_a_broken_analyst_answer_is_an_error_not_a_report(ctx, game):
    store, recordings = game
    r = coach.build(ctx, store, MATCH, recordings)
    bad = {"choices": [{"message": {"content": '{"summary": "x"'}}], "usage": {}}
    respx.post(URL).mock(return_value=httpx.Response(200, json=bad))
    with pytest.raises(ProviderError) as err:
        analyst.analyze(r, AdvisorClient("fgt-test", "https://api.forgetapi.ru/v1", "m"))
    assert err.value.kind == "bad_response"


@pytest.fixture
def client(ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("D2BG_HOME", str(tmp_path / "home"))
    with TestClient(create_app(ctx, static_dir=tmp_path / "no-ui")) as c:
        yield c


def test_the_review_api(client, tmp_path, monkeypatch):
    from d2bg import paths

    svc = client.app.state.services
    asked = []
    monkeypatch.setattr(svc, "opendota_match", asked.append)  # not public
    make_game(svc.copilot.store, paths.recordings_dir())
    assert [m["match_id"] for m in client.get("/api/copilot/matches").json()] == [MATCH]
    assert client.get("/api/copilot/matches/123/review").status_code == 404
    first = client.get(f"/api/copilot/matches/{MATCH}/review").json()
    assert first["facts"]["findings"] and first["ai"] is None and asked == [MATCH]
    again = client.get(f"/api/copilot/matches/{MATCH}/review").json()
    assert again["facts"]["created_at"] == first["facts"]["created_at"]  # stored once, not rebuilt
    goals = client.get("/api/copilot/goals").json()["goals"]
    assert 1 <= len(goals) <= 3
    client.get(f"/api/copilot/matches/{MATCH}/review", params={"rebuild": True})
    assert len(client.get("/api/copilot/goals").json()["goals"]) == len(goals)  # replaced, not duplicated
    # The analyst needs a key; without one the button says so.
    assert client.post(f"/api/copilot/matches/{MATCH}/analyze").status_code == 409
    monkeypatch.setenv(apikeys.ADVISOR_KEY, "fgt-test")
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="testserver").pass_through()
        mock.post(URL).mock(return_value=answer([]))
        ai = client.post(f"/api/copilot/matches/{MATCH}/analyze").json()
    assert ai["summary"] and client.get(f"/api/copilot/matches/{MATCH}/review").json()["ai"]["summary"]
    assert svc.copilot.store.provider_usage(MATCH)["advisor"]["calls"] == 1
    assert client.delete("/api/copilot/history").json() == {"ok": True}
    assert client.get("/api/copilot/matches").json() == []


def test_seen_marks_advice_once(client):
    store = client.app.state.services.copilot.store
    from d2bg.copilot.models import Recommendation

    rec = Recommendation(
        id="r1",
        match_id=MATCH,
        game_time_s=10,
        type="ITEM_NEXT",
        candidate_id="power_treads",
        reason_ru="x",
        source="baseline",
        context_hash="h",
        model_version="v",
    )
    store.upsert_match(GameContext(match_id=MATCH, hero_id=8, time_s=0), "game", 1.0, None)
    store.save_recommendation(rec, 1.0)
    assert client.post("/api/copilot/recommendations/seen", json={"ids": ["r1"]}).json() == {"marked": 1}
    assert client.post("/api/copilot/recommendations/seen", json={"ids": ["r1"]}).json() == {"marked": 0}
    assert store.recommendations(MATCH)[0].seen_at is not None


def test_an_unparsed_opendota_match_is_asked_again_sooner(client, monkeypatch):
    svc = client.app.state.services
    calls = []

    def get(path, params=None, *, ttl=None):
        calls.append(ttl)
        return {"players": [{}], "duration": 1800}  # no "version": not parsed yet

    monkeypatch.setattr(svc.ctx.client, "get", get)
    assert svc.opendota_match("8100000001") is not None and calls == [3600, 300]
    assert svc.opendota_match("0") is None and svc.opendota_match("demo-1") is None and len(calls) == 2
