"""The overlay widgets' hints (/api/copilot/hud): Turbo told by the early gold rate, the base check, and
what a real lobby game shows in each phase."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from d2bg.api.app import create_app
from d2bg.copilot import hud
from d2bg.gsi import recorder

FIXTURES = Path(__file__).parent / "fixtures"


def _probe(points):
    probe, out = hud.ModeProbe(), None
    for clock, gold, kills in points:
        out = probe.feed(clock, gold, kills) or out
    return out


def test_turbo_is_told_by_passive_gold_after_the_horn():
    # Passive gold as GSI showed it: +1 a tick in a normal game, +2 in Turbo, about every 0.67 s.
    normal = [(t, 3 + t * 3 // 2, 0) for t in range(20)]
    turbo = [(t, 4 + t * 3, 0) for t in range(20)]
    assert _probe(normal) == "normal" and _probe(turbo) == "turbo"
    assert _probe(normal[:10]) is None  # not enough seconds yet
    rune = [(t, g + (40 if t >= 2 else 0), k) for t, g, k in normal]  # a bounty rune at 0:02
    assert _probe(rune) == "normal"
    kill = [(t, g + (150 if t >= 5 else 0), 1 if t >= 5 else 0) for t, g, _ in normal[:16]]
    assert _probe(kill) is None  # the kill restarted the window: 11 s is too short


@pytest.mark.parametrize(
    ("fixture", "mode"),
    [("player_lobby_largo.jsonl.gz", "turbo"), ("player_pre_game.jsonl.gz", "normal")],
)
def test_real_games_are_told_apart(fixture, mode):
    probe, found = hud.ModeProbe(), None
    for _, p in recorder.read(FIXTURES / fixture):
        m, pl = p.get("map") or {}, p.get("player") or {}
        if str(m.get("game_state", "")).endswith("IN_PROGRESS") and pl.get("gold_reliable") is not None:
            found = found or probe.feed(m["clock_time"], pl["gold_reliable"], pl["kills"] + pl["assists"])
    assert found == mode


def test_in_base_is_near_the_own_fountain():
    assert hud.in_base("radiant", -6700, -6700) and hud.in_base("radiant", -6449, -4192)
    assert not hud.in_base("radiant", -6032, 5220)  # top lane
    assert not hud.in_base("dire", -6700, -6700)  # the enemy fountain is not his base
    assert hud.in_base("dire", 6500, 6300)
    assert not hud.in_base(None, 0, 0) and not hud.in_base("radiant", None, -6700)


@pytest.fixture
def client(ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("D2BG_HOME", str(tmp_path / "home"))
    with TestClient(create_app(ctx, static_dir=tmp_path / "no-ui")) as c:
        yield c


def test_nothing_to_show_without_a_game(client):
    body = client.get("/api/copilot/hud").json()
    assert (body["skill"], body["draft"], body["items"]) == (None, None, None)
    assert (body["mode"], body["mode_source"]) == (None, "unknown")


def test_a_real_lobby_game_shows_each_hint_in_its_phase(client, ctx):
    svc = client.app.state.services
    seen: dict[tuple[str, str], dict] = {}
    items_in_game = []
    for i, (_, payload) in enumerate(recorder.read(FIXTURES / "player_lobby_largo.jsonl.gz")):
        svc.engine.ingest(payload, source="game")
        if i % 3:
            continue
        body = client.get("/api/copilot/hud").json()
        s = svc.engine.state
        for k in ("skill", "draft", "items"):
            if body[k]:
                seen.setdefault((k, s.phase), body[k])
        if body["items"] and s.phase == "in_game":
            items_in_game.append(s.hero.alive is False or hud.in_base(s.team, s.hero.xpos, s.hero.ypos))
    draft = seen[("draft", "hero_selection")]
    assert len(draft["picks"]) == 3 and all(p["why"] for p in draft["picks"])
    assert len(draft["bans"]) == 3 and not {b["hero"] for b in draft["bans"]} & {
        p["hero"] for p in draft["picks"]
    }
    start = seen.get(("items", "strategy")) or seen[("items", "pre_game")]
    assert start["items"] and "не определён" in start["note"]  # the first game: no mode yet
    assert seen[("skill", "in_game")]["kind"] in ("skill", "talent")
    assert items_in_game and all(items_in_game)  # in game only when dead or in base
    body = client.get("/api/copilot/hud").json()
    assert (body["mode"], body["mode_source"]) == ("turbo", "gold_rate")
    # The next game starts with the mode of this one; his setting always wins.
    assert svc.mode_file.read_text(encoding="utf-8") == "turbo"
    ctx.settings.update({"game_mode": "normal"})
    assert svc.game_mode() == ("normal", "setting")


def test_hidden_hint_groups_stay_hidden(client, ctx):
    svc = client.app.state.services
    ctx.settings.update({"hidden_hints": ["draft", "items", "skills"]})
    shown = set()
    for i, (_, payload) in enumerate(recorder.read(FIXTURES / "player_lobby_largo.jsonl.gz")):
        svc.engine.ingest(payload, source="game")
        if i % 5 == 0:
            body = client.get("/api/copilot/hud").json()
            shown |= {k for k in ("skill", "draft", "items") if body[k]}
    assert shown == set()
