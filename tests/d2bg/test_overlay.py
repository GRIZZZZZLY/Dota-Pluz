"""The hint widgets over Dota: their layout, the click-through style bits, showing a widget only while
it has a hint, the handle's buttons, and the safety rules for the one package that may set window styles."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import d2bg
import d2bg_overlay
from d2bg_overlay import app as overlay_app
from d2bg_overlay.window import (
    HANDLE,
    WIDGETS,
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    Layout,
    default_spot,
    ex_style,
)
from tests.d2bg.test_safety import FORBIDDEN_CALLS, FORBIDDEN_MODULES

PKG = Path(d2bg_overlay.__file__).resolve().parent


def test_layout_round_trip_and_limits(tmp_path):
    path = tmp_path / "overlay.json"
    assert Layout.load(path) == Layout()  # first run: defaults
    Layout(opacity=0.6, spots={"skill": [10, 20]}).save(path)
    assert Layout.load(path) == Layout(opacity=0.6, spots={"skill": [10, 20]})
    path.write_text('{"opacity": 0.05, "spots": {"skill": [1, 2], "nonsense": [3, 4]}}', encoding="utf-8")
    assert Layout.load(path) == Layout(opacity=0.3, spots={"skill": [1, 2]})  # never invisible
    path.write_text("not json", encoding="utf-8")
    assert Layout.load(path) == Layout()


def test_default_spots_sit_on_dotas_screen():
    for name in [*WIDGETS, "handle"]:
        x, y = default_spot(name, 0, 0, 1920, 1080)
        w, h = WIDGETS.get(name, HANDLE)
        assert x >= 0 and x + w <= 1920 and y >= 0 and y + h <= 1080, name
    sx, sy = default_spot("skill", 0, 0, 1920, 1080)
    assert sy + WIDGETS["skill"][1] <= 1080 * 0.84  # above the ability bar
    assert default_spot("skill", 1920, 0, 1920, 1080)[0] == sx + 1920  # follows the screen's origin


def test_click_through_style_bits():
    base = 0x100
    locked = ex_style(base, click_through=True)
    assert (
        locked & WS_EX_TRANSPARENT and locked & WS_EX_LAYERED and locked & WS_EX_TOOLWINDOW and locked & base
    )
    unlocked = ex_style(locked, click_through=False)
    assert not unlocked & WS_EX_TRANSPARENT and unlocked & WS_EX_LAYERED and unlocked & base


class FakeWindow:
    def __init__(self, x: int, y: int) -> None:
        self.x, self.y = x, y


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("D2BG_HOME", str(tmp_path))
    calls: list[tuple[str, bool, float]] = []
    monkeypatch.setattr(
        overlay_app, "apply", lambda title, through, opacity: calls.append((title, through, opacity)) or True
    )
    o = overlay_app.Overlay("http://127.0.0.1:4242")
    o.windows = {name: FakeWindow(100, 200) for name in WIDGETS}
    return o, calls


def test_widgets_show_only_while_they_have_a_hint(overlay):
    o, calls = overlay
    t = overlay_app.TITLES
    o.sync(None)  # the app is not running: all hidden, all click-through
    assert sorted(calls) == sorted((t[n], True, 0.0) for n in WIDGETS)
    calls.clear()
    o.sync({"skill": {"name": "Echo Slash"}, "draft": None, "items": None})
    assert calls == [(t["skill"], True, 0.9)]  # only the changed window is touched
    calls.clear()
    o.sync({"skill": {"name": "Echo Slash"}, "draft": None, "items": None})
    assert calls == []
    o.sync({"skill": None, "draft": None, "items": None})
    assert calls == [(t["skill"], True, 0.0)]


def test_setup_shows_all_takes_the_mouse_and_remembers_spots(overlay):
    o, calls = overlay
    o.sync(None)
    calls.clear()
    assert o.toggle_setup() is True
    assert sorted(calls) == sorted((overlay_app.TITLES[n], False, 0.9) for n in WIDGETS)
    o.windows["items"].x, o.windows["items"].y = 1500, 300  # he drags it
    calls.clear()
    assert o.toggle_setup() is False
    assert all(through and opacity == 0.0 for _, through, opacity in calls)  # hidden, clicks to the game
    assert Layout.load(o.file).spots["items"] == [1500, 300]


def test_opacity_buttons(overlay):
    o, calls = overlay
    o.sync({"skill": {"name": "x"}})
    for _ in range(10):
        o.fade(-0.1)
    assert o.layout.opacity == 0.3 and (overlay_app.TITLES["skill"], True, 0.3) in calls  # never invisible
    o.fade(0.1)
    assert o.layout.opacity == 0.4 and Layout.load(o.file).opacity == 0.4


def _imports(file: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_overlay_safety():
    core = Path(d2bg.__file__).resolve().parent
    assert not any("d2bg_overlay" in _imports(f) for f in core.rglob("*.py"))
    users = []
    for f in sorted(PKG.rglob("*.py")):
        imported = _imports(f)
        assert not (imported & (FORBIDDEN_MODULES - {"ctypes"})), f.name
        if "ctypes" in imported:
            users.append(f.name)
        text = f.read_text(encoding="utf-8")
        assert not FORBIDDEN_CALLS.findall(text), f.name
    assert users == ["window.py"]  # window styles only, in one file
    calls = set(re.findall(r"user32\.(\w+)", (PKG / "window.py").read_text(encoding="utf-8")))
    assert calls == {"FindWindowW", "GetWindowLongW", "SetWindowLongW", "SetLayeredWindowAttributes"}
