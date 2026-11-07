"""Stage 4: the cloud models. Every paid API is mocked (respx); nothing here reaches the network.

Covers the spec's provider cases (401, 402, 429, 5xx, timeout, invalid JSON, a pick outside the list,
a Jev/advisor conflict) and the rule that the local rules keep working through all of them.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from d2bg import apikeys
from d2bg.api.app import create_app
from d2bg.copilot.hybrid import Hybrid
from d2bg.copilot.pipeline import Copilot
from d2bg.copilot.providers import JEV_URL, AdvisorClient, JevClient, ProviderError
from d2bg.copilot.store import CopilotStore
from d2bg.gsi.demo import DEMO_MATCH_ID, demo_frames
from d2bg.live.engine import LiveEngine

ADVISOR_URL = "https://api.forgetapi.ru/v1/chat/completions"
JEV_SECRET = "jev-secret-key-1234567890"
ADVISOR_SECRET = "fgt-secret-key-1234567890"


def jev_reply(choice: str, confidence: float = 0.8) -> dict:
    return {
        "model": "jev-1.14.0",
        "answers": {
            "pick": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {}}
        },
        "usage": {"input_tokens": 400, "output_tokens": 40},
    }


def advisor_reply(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 40},
    }


# ── clients ────────────────────────────────────────────────────────


@respx.mock
def test_jev_choice_and_its_cost():
    route = respx.post(JEV_URL).mock(return_value=httpx.Response(200, json=jev_reply("bkb", 0.74)))
    answer, call = JevClient(JEV_SECRET).choice(
        {"hero": "Juggernaut"}, "Which item", {"bkb": "BKB", "manta": "Manta"}
    )
    assert (answer.choice, answer.confidence) == ("bkb", 0.74)
    assert (
        call.model == "jev-1.14.0"
        and call.input_tokens == 400
        and call.cost_usd == pytest.approx(400 * 0.042 / 1e6)
    )
    sent = json.loads(route.calls[0].request.content)
    assert sent["questions"]["pick"]["criteria"] == {"bkb": "BKB", "manta": "Manta"}
    assert route.calls[0].request.headers["authorization"] == f"Bearer {JEV_SECRET}"


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(401, text="bad key"), "auth"),
        (httpx.Response(403, text="disabled"), "auth"),
        (httpx.Response(402, text="no credit"), "payment"),
        (httpx.Response(429, text="slow down"), "rate"),
        (httpx.Response(503, text="down"), "server"),
        (httpx.Response(200, text="<html>not json</html>"), "bad_response"),
        (httpx.Response(200, json=jev_reply("battle_fury")), "bad_response"),  # not one of the options
        (httpx.ReadTimeout("slow"), "timeout"),
    ],
)
@respx.mock
def test_jev_failures_become_provider_errors(response, kind):
    route = respx.post(JEV_URL)
    route.mock(side_effect=response) if isinstance(response, Exception) else route.mock(return_value=response)
    with pytest.raises(ProviderError) as err:
        JevClient(JEV_SECRET).choice({}, "Which item", {"bkb": "BKB", "manta": "Manta"})
    assert err.value.kind == kind


@respx.mock
def test_an_echoed_key_never_reaches_the_error_message():
    respx.post(JEV_URL).mock(return_value=httpx.Response(401, text=f"key {JEV_SECRET} is invalid"))
    with pytest.raises(ProviderError) as err:
        JevClient(JEV_SECRET).choice({}, "q", {"a": "A", "b": "B"})
    assert JEV_SECRET not in str(err.value)


@respx.mock
def test_advisor_retries_once_on_a_bad_answer():
    route = respx.post(ADVISOR_URL).mock(
        side_effect=[
            httpx.Response(200, json=advisor_reply("Конечно! BKB лучше.")),  # not JSON
            httpx.Response(
                200, json=advisor_reply('{"choice": "bkb", "reason_ru": "Lion и Lina контролируют."}')
            ),
        ]
    )
    client = AdvisorClient(ADVISOR_SECRET, "https://api.forgetapi.ru/v1", "deepseek-v4-flash")
    answer, call = client.advise("sys", {"hero": "Juggernaut"}, {"bkb": "BKB", "manta": "Manta"})
    assert answer.choice == "bkb" and route.call_count == 2 and call.input_tokens == 600


@respx.mock
def test_advisor_gives_up_after_two_picks_outside_the_list():
    respx.post(ADVISOR_URL).mock(
        return_value=httpx.Response(200, json=advisor_reply('{"choice": "rapier", "reason_ru": "Урон."}'))
    )
    client = AdvisorClient(ADVISOR_SECRET, "https://api.forgetapi.ru/v1", "deepseek-v4-flash")
    with pytest.raises(ProviderError) as err:
        client.advise("sys", {}, {"bkb": "BKB", "manta": "Manta"})
    assert err.value.kind == "bad_response"


def test_env_file_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        f'﻿# comment\nTYPESAFE_API_KEY="{JEV_SECRET}"\nFORGETAPI_API_KEY=\nOTHER=x\n', encoding="utf-8"
    )
    apikeys.load_env([env])
    assert apikeys.key(apikeys.JEV_KEY) == JEV_SECRET and not apikeys.configured(apikeys.ADVISOR_KEY)
    monkeypatch.setenv(apikeys.ADVISOR_KEY, "from-environment")
    env.write_text(f"FORGETAPI_API_KEY={ADVISOR_SECRET}\n", encoding="utf-8")
    apikeys.load_env([env])
    assert apikeys.key(apikeys.ADVISOR_KEY) == "from-environment"  # the environment wins
    assert "OTHER" not in __import__("os").environ


# ── the hybrid policy over a whole demo match ──────────────────────


@pytest.fixture(scope="module")
def payloads(shared_ctx):
    return [p for _, p in demo_frames(shared_ctx, "juggernaut", minutes=30)]


def play(ctx, tmp_path, payloads, source="game"):
    """The demo match through the engine, the Copilot and the hybrid policy, one second per payload."""
    now = [1_000.0]
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = CopilotStore(tmp_path / "copilot.sqlite3")
    engine = LiveEngine(ctx, clock=lambda: now[0])
    hybrid = Hybrid(ctx, store, mode_of=lambda: "normal", clock=lambda: now[0], http=httpx.Client())
    copilot = Copilot(ctx, store, clock=lambda: now[0], hybrid=hybrid)
    for p in payloads:
        now[0] += 1
        engine.ingest(p, source=source)
        copilot.observe(engine, source)
        hybrid.drain()
    return store, hybrid, copilot


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv(apikeys.JEV_KEY, JEV_SECRET)
    monkeypatch.setenv(apikeys.ADVISOR_KEY, ADVISOR_SECRET)


def jev_picks(position: int, confidence: float = 0.8):
    """A Jev that picks the option at ``position`` (0 = the rules' own candidate)."""

    def answer(request: httpx.Request) -> httpx.Response:
        options = list(json.loads(request.content)["questions"]["pick"]["criteria"])
        return httpx.Response(200, json=jev_reply(options[min(position, len(options) - 1)], confidence))

    return answer


def rows(store, source=None):
    return [r for r in store.recommendations(DEMO_MATCH_ID, 500) if source is None or r.source == source]


def test_without_keys_the_rules_answer_alone(ctx, tmp_path, payloads):
    with respx.mock(assert_all_called=False) as mock:
        jev = mock.post(JEV_URL)
        store, hybrid, _ = play(ctx, tmp_path, payloads)
    assert jev.call_count == 0 and rows(store) and not rows(store, "jev")
    assert hybrid.status(DEMO_MATCH_ID)["jev"]["configured"] is False


def test_demo_and_replays_spend_nothing_unless_allowed(ctx, tmp_path, payloads, keys):
    with respx.mock(assert_all_called=False) as mock:
        jev = mock.post(JEV_URL).mock(side_effect=jev_picks(0))
        play(ctx, tmp_path, payloads, source="demo")
    assert jev.call_count == 0


def test_jev_agrees_and_its_opinion_sits_beside_the_advice(ctx, tmp_path, payloads, keys):
    with respx.mock(assert_all_called=False) as mock:
        jev = mock.post(JEV_URL).mock(side_effect=jev_picks(0))
        advisor = mock.post(ADVISOR_URL)
        store, _, _ = play(ctx, tmp_path, payloads)
    opinions = rows(store, "jev")
    assert 0 < jev.call_count <= 20 and opinions and advisor.call_count == 0  # no conflict, no advisor
    assert all("согласен" in r.reason_ru and r.confidence_kind == "unverified_model_score" for r in opinions)
    usage = store.provider_usage(DEMO_MATCH_ID)["jev"]
    assert usage["calls"] == jev.call_count and usage["cost_usd"] > 0
    # Opinions close with the advice they belong to: none is left open after the match.
    assert not [r for r in opinions if r.status == "suggested"]


def test_a_conflict_goes_to_the_advisor_who_explains(ctx, tmp_path, payloads, keys):
    def advise(request: httpx.Request) -> httpx.Response:
        options = json.loads(json.loads(request.content)["messages"][1]["content"])["options"]
        pick = list(options)[1]
        return httpx.Response(
            200, json=advisor_reply(json.dumps({"choice": pick, "reason_ru": "Против контроля."}))
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.post(JEV_URL).mock(side_effect=jev_picks(1))
        advisor = mock.post(ADVISOR_URL).mock(side_effect=advise)
        store, _, _ = play(ctx, tmp_path, payloads)
    hybrid_rows = rows(store, "hybrid")
    assert 0 < advisor.call_count <= 5 and len(hybrid_rows) == advisor.call_count
    assert all(r.reason_ru == "Против контроля." for r in hybrid_rows)
    base = {r.type: r for r in rows(store, "baseline")}
    assert all(r.candidate_id != base[r.type].candidate_id or r.type not in base for r in hybrid_rows[:1])


def test_failures_leave_the_rules_alone_and_rest_the_provider(ctx, tmp_path, payloads, keys):
    with respx.mock(assert_all_called=False) as mock:
        jev = mock.post(JEV_URL).mock(return_value=httpx.Response(401, text="bad key"))
        store, hybrid, _ = play(ctx, tmp_path, payloads)
    assert jev.call_count == 1  # a bad key is not retried for the rest of the session
    assert hybrid.status(DEMO_MATCH_ID)["jev"]["error"] == "auth" and not rows(store, "jev")
    assert rows(store, "baseline")
    with respx.mock(assert_all_called=False) as mock:
        mock.post(JEV_URL).mock(side_effect=jev_picks(1))
        advisor = mock.post(ADVISOR_URL).mock(return_value=httpx.Response(429, text="balance below 30"))
        store2, hybrid2, _ = play(ctx, tmp_path / "second", payloads)
    # 429: a minute's rest between tries, and failed tries count against the match's limit of 5.
    assert 1 < advisor.call_count <= 5 and hybrid2.status(DEMO_MATCH_ID)["advisor"]["error"] == "rate"
    assert rows(store2, "jev") and not rows(store2, "hybrid")  # Jev's opinion stays, unexplained


def test_limits_per_match(ctx, tmp_path, payloads, keys):
    ctx.settings.update({"providers": {**ctx.settings.get().providers.model_dump(), "jev_per_match": 2}})
    with respx.mock(assert_all_called=False) as mock:
        jev = mock.post(JEV_URL).mock(side_effect=jev_picks(0))
        play(ctx, tmp_path, payloads)
    assert jev.call_count == 2


def test_rules_only_mode_calls_nobody(ctx, tmp_path, payloads, keys):
    ctx.settings.update({"providers": {**ctx.settings.get().providers.model_dump(), "mode": "baseline"}})
    with respx.mock(assert_all_called=False) as mock:
        jev = mock.post(JEV_URL)
        play(ctx, tmp_path, payloads)
    assert jev.call_count == 0


def test_the_journal_and_the_api_never_hold_a_key(ctx, tmp_path, payloads, keys):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(JEV_URL).mock(side_effect=jev_picks(0))
        store, _, _ = play(ctx, tmp_path, payloads)
    dump = "\n".join(str(tuple(r)) for r in store._db.execute("SELECT * FROM provider_calls"))
    assert dump and JEV_SECRET not in dump and ADVISOR_SECRET not in dump


def test_the_test_button(ctx, tmp_path, monkeypatch, keys):
    monkeypatch.setenv("D2BG_HOME", str(tmp_path / "home"))
    with (
        TestClient(create_app(ctx, static_dir=tmp_path / "no-ui")) as client,
        respx.mock(assert_all_called=False) as mock,
    ):
        mock.route(host="testserver").pass_through()
        mock.post(JEV_URL).mock(return_value=httpx.Response(200, json=jev_reply("yes")))
        mock.post(ADVISOR_URL).mock(return_value=httpx.Response(402, text="no money"))
        body = client.post("/api/copilot/providers/test").json()
        status = client.get("/api/copilot/status")
    assert body["jev"]["ok"] is True and body["advisor"] == {
        "ok": False,
        "error": "payment",
        "message": "HTTP 402: no money",
    }
    assert JEV_SECRET not in status.text and ADVISOR_SECRET not in status.text
    assert status.json()["providers"]["jev"]["configured"] is True


def test_a_weak_disagreement_is_noted_but_not_explained(ctx, tmp_path, payloads, keys):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(JEV_URL).mock(side_effect=jev_picks(1, confidence=0.3))
        advisor = mock.post(ADVISOR_URL)
        store, _, _ = play(ctx, tmp_path, payloads)
    assert advisor.call_count == 0 and rows(store, "jev") and not rows(store, "hybrid")
