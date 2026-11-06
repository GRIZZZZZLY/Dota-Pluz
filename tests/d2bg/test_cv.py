"""d2bg-cv on synthetic draft screens: calibration, recognition, unknown slots and the observation it
sends. Real screenshots are still needed to measure accuracy (spec acceptance 4); these tests pin the
logic: a slot it cannot read is counted as unknown and never guessed.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from d2bg.copilot.models import DraftObservation
from d2bg_cv import calibrate
from d2bg_cv.cli import Reader, draft_running, waiting_reason
from d2bg_cv.recognize import Recognizer, Votes, fit, read_screen

KEYS = ["juggernaut", "lion", "lina", "axe", "pudge", "riki", "sniper", "viper"]
W, H, SIZE = 1920, 1080, 96


def portrait(seed: int) -> np.ndarray:
    """A landscape 'CDN portrait' (128x72) with a distinct, smooth pattern."""
    rng = np.random.default_rng(seed)
    blocks = rng.integers(0, 256, (3, 5, 3), dtype=np.uint8)
    img = cv2.resize(blocks, (128, 72), interpolation=cv2.INTER_CUBIC)
    cv2.circle(img, (64, 36), 18, tuple(int(c) for c in rng.integers(0, 256, 3)), -1)
    # Like real art, not fully saturated: a flat bright patch would look like a player's bar.
    gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    muted = img.astype(int) // 2 + gray.astype(int) // 2
    return cv2.GaussianBlur(muted.astype(np.uint8), (5, 5), 0)


@pytest.fixture(scope="module")
def templates() -> dict[str, list[np.ndarray]]:
    return {k: [portrait(i)] for i, k in enumerate(KEYS)}


@pytest.fixture(scope="module")
def hero_ids(shared_ctx) -> dict[str, int]:
    return {k: shared_ctx.data.heroes.require(k).id for k in KEYS}


def boxes(side: str) -> list[tuple[int, int, int, int]]:
    x = 60 if side == "left" else W - 60 - SIZE
    return [(x, 160 + i * 140, SIZE, SIZE) for i in range(5)]


def screen(templates, left: list[str | None], right: list[str | None]) -> np.ndarray:
    """A dark draft screen. A key is that hero's portrait, "?" a portrait it has no template for
    (an arcana), None an empty slot."""
    img = np.full((H, W, 3), 25, np.uint8)
    noise = cv2.GaussianBlur(
        np.random.default_rng(99).integers(0, 256, (SIZE, SIZE, 3), dtype=np.uint8), (3, 3), 0
    )
    for side, column in (("left", left), ("right", right)):
        for (x, y, w, h), what in zip(boxes(side), column, strict=True):
            if what is None:
                img[y : y + h, x : x + w] = 90  # an empty slot: a flat tile
            elif what == "?":
                img[y : y + h, x : x + w] = noise
            else:
                img[y : y + h, x : x + w] = fit(templates[what][0], w, h)
    return img


def calibration() -> dict:
    return {
        "resolution": [W, H],
        "radiant_on_right": False,
        "team_left": {"slots": [list(b) for b in boxes("left")]},
        "team_right": {"slots": [list(b) for b in boxes("right")]},
        "bans": [],
    }


def test_fit_crops_the_centre_to_the_slot_shape():
    wide = np.zeros((72, 128, 3), np.uint8)
    wide[:, 28:100] = 200  # the centre square is bright, the sides dark
    out = fit(wide, 50, 50)
    assert out.shape == (50, 50, 3) and out.mean() > 190


def test_recognizer_reads_known_portraits_and_refuses_the_rest(templates):
    rec = Recognizer(templates)
    crop = fit(templates["lion"][0], 80, 80)
    noisy = np.clip(crop.astype(int) + np.random.default_rng(1).integers(-12, 12, crop.shape), 0, 255).astype(
        np.uint8
    )
    name, score, margin = rec.best(noisy)
    assert name == "lion" and score > 0.9 and margin > 0.06
    assert rec.best(np.random.default_rng(2).integers(0, 256, (80, 80, 3), dtype=np.uint8))[0] is None
    # Two heroes with the same picture (arcana variants): no margin, so no answer.
    twins = Recognizer({"lion": templates["lion"], "lina": templates["lion"]})
    assert twins.best(crop)[0] is None
    assert Recognizer({}).best(crop) == (None, 0.0, 0.0)


def test_a_slot_counts_after_two_agreeing_frames():
    v = Votes()
    assert v.vote(("radiant", 0), "lion") is None
    assert v.vote(("radiant", 0), "lion") == "lion"
    assert v.vote(("radiant", 1), "axe") is None
    assert v.vote(("radiant", 1), "lina") is None  # disagreement
    v.reset()
    assert v.vote(("radiant", 0), "lion") is None


def test_read_screen_reports_heroes_unknowns_and_confidence(templates, hero_ids):
    img = screen(
        templates, ["juggernaut", "lion", "lina", "axe", None], ["pudge", "riki", "?", "sniper", None]
    )
    rec, votes = Recognizer(templates), Votes()
    first = read_screen(img, calibration(), rec, votes, hero_ids)
    assert first["radiant"] == [] and first["dire"] == []  # one frame is not enough
    obs = read_screen(img, calibration(), rec, votes, hero_ids)
    assert obs["radiant"] == [hero_ids[k] for k in ("juggernaut", "lion", "lina", "axe")]
    assert obs["dire"] == [hero_ids[k] for k in ("pudge", "riki", "sniper")]
    assert obs["unknown_slots"] == 1  # the "?" slot; empty slots are not unknown
    assert 0.8 * 7 / 8 < obs["confidence"] <= 7 / 8
    assert obs["capture_resolution"] == [W, H]
    DraftObservation.model_validate(obs)  # what the API accepts
    # At another resolution the calibration scales with the screen.
    small = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_AREA)
    votes.reset()
    read_screen(small, calibration(), rec, votes, hero_ids)
    assert read_screen(small, calibration(), rec, votes, hero_ids)["radiant"][:2] == [
        hero_ids["juggernaut"],
        hero_ids["lion"],
    ]


def test_capture_only_during_the_draft_of_a_real_game():
    assert draft_running({"mode": "game", "phase": "hero_selection"})
    assert draft_running({"mode": "game", "phase": "strategy"})
    assert not draft_running({"mode": "game", "phase": "in_game"})
    assert not draft_running({"mode": "demo", "phase": "hero_selection"})
    assert not draft_running({"mode": "replay", "phase": "strategy"})
    assert not draft_running({})


def test_it_says_why_nothing_is_captured():
    server = "http://127.0.0.1:4242"
    assert "не отвечает" in waiting_reason(None, server)
    no_gsi = {"mode": "none", "state": "no_data", "connection": {"packets": 0}}
    assert "не присылает данные" in waiting_reason(no_gsi, server)
    demo_running = {"mode": "demo", "state": "ok", "phase": "hero_selection"}
    assert "демо" in waiting_reason(demo_running, server)
    # A demo that ended long ago is not "a demo is running": the game is simply silent.
    demo_over = {"mode": "demo", "state": "stale", "phase": "in_game"}
    assert "не присылает данные" in waiting_reason(demo_over, server)
    menu = {"mode": "game", "state": "ok", "phase": "menu", "connection": {"packets": 9}}
    assert "menu" in waiting_reason(menu, server)


# ── the real draft screen (1080p, ban stage, 2026-11-07) ───────────

REAL_TOPBAR = Path(__file__).parent / "fixtures" / "draft_topbar_1080p_bans.png"


def real_screen() -> np.ndarray:
    """His real draft screen at the ban stage: the top bar (cards only, no player names) on a dark frame."""
    bar = cv2.imread(str(REAL_TOPBAR))
    img = np.full((H, W, 3), 20, np.uint8)
    img[: bar.shape[0]] = bar
    return img


def test_real_draft_screen_is_calibrated_from_the_player_bars():
    cal = calibrate.topbar(real_screen())
    assert cal is not None and cal["layout"] == "topbar" and cal["match"] == "slide"
    assert cal["bars"] == ["bottom"] * 10  # ban stage: every card stands on its bar
    left = cal["team_left"]["slots"]
    right = cal["team_right"]["slots"]
    # The inside of each card: clear of the slanted sides, above the bar.
    assert [s[0] for s in left] == [234, 358, 482, 606, 730]
    assert all(s[1:] == [6, 79, 54] for s in left)
    # Sophie's pale pink bar is not found; that Dire slot is placed by mirroring the Radiant side.
    expected = [1113, 1237, 1361, 1485, 1609]
    assert all(abs(s[0] - e) <= 8 for s, e in zip(right, expected, strict=True))


def test_empty_cards_are_empty_and_the_flag_is_unknown(templates, hero_ids):
    img = real_screen()
    cal = calibrate.topbar(img)
    votes = Votes()
    read_screen(img, cal, Recognizer(templates), votes, hero_ids)
    obs = read_screen(img, cal, Recognizer(templates), votes, hero_ids)
    assert obs["radiant"] == [] and obs["dire"] == []
    assert obs["unknown_slots"] == 1  # the first card shows a pick-order flag: "?", never a hero


def test_picked_cards_drop_below_their_bar_and_are_read(templates, hero_ids):
    """The pick stage on the real screen: picked Dire cards drop below a bar now on top, the empty
    Radiant cards still stand on theirs. Each card is found where it is and read by sliding."""
    img = real_screen()
    picked = ["lion", "lina", "axe", "pudge", "riki"]
    for (x, _y, _w, _h), key in zip(calibrate.topbar(img)["team_right"]["slots"], picked, strict=True):
        bar_x = x - 15  # the inner box starts 15 px into the card
        img[0:6, bar_x + 9 : bar_x + 9 + 107] = (40, 40, 220)  # the player's bar, now above the card
        img[6:72, bar_x - 2 : bar_x - 2 + 118] = fit(templates[key][0], 118, 66)
    cal = calibrate.topbar(img)
    assert cal["bars"] == ["bottom"] * 5 + ["top"] * 5
    votes, rec = Votes(), Recognizer(templates)
    read_screen(img, cal, rec, votes, hero_ids)
    obs = read_screen(img, cal, rec, votes, hero_ids)
    assert obs["dire"] == [hero_ids[k] for k in picked] and obs["radiant"] == []
    assert obs["unknown_slots"] == 1 and obs["confidence"] > 0.75  # the flag card is still "?"


def test_reader_finds_the_cards_on_every_frame(templates, hero_ids):
    reader = Reader(Recognizer(templates), hero_ids)
    obs = reader.read(real_screen())
    assert obs is not None and obs["unknown_slots"] == 1 and reader.message == ""
    assert reader.read(np.full((H, W, 3), 25, np.uint8)) is None
    assert reader.message == "Карточки пиков на экране не найдены."
