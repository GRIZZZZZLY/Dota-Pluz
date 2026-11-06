"""Enforces the d2bg-cv part of docs/SAFETY.md: the screen-reading process may capture the screen,
and nothing else. No input, no game memory, no game files; the core app never imports it."""

from __future__ import annotations

import ast
from pathlib import Path

import d2bg
import d2bg_cv
from tests.d2bg.test_safety import FORBIDDEN_CALLS, FORBIDDEN_MODULES

CORE = Path(d2bg.__file__).resolve().parent
CV = Path(d2bg_cv.__file__).resolve().parent
# Capture is the one thing d2bg-cv may do that the core app may not.
ALLOWED_IN_CV = {"mss"}


def _imports(file: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names += [node.module] + [f"{node.module}.{a.name}" for a in node.names]
    return names


def test_the_core_app_never_imports_the_screen_reader():
    for file in sorted(CORE.rglob("*.py")):
        assert not any(n.split(".")[0] == "d2bg_cv" for n in _imports(file)), file.name


def test_the_screen_reader_imports_no_input_memory_or_window_tools():
    forbidden = FORBIDDEN_MODULES - ALLOWED_IN_CV
    for file in sorted(CV.rglob("*.py")):
        for name in _imports(file):
            assert name.split(".")[0] not in forbidden and name not in forbidden, f"{file.name}: {name}"


def test_capture_lives_in_one_file():
    users = sorted(f.name for f in CV.rglob("*.py") if "mss" in {n.split(".")[0] for n in _imports(f)})
    assert users == ["cli.py"]


def test_no_forbidden_calls_and_no_game_folder():
    for file in sorted(CV.rglob("*.py")):
        text = file.read_text(encoding="utf-8")
        assert not FORBIDDEN_CALLS.findall(text), file.name
        assert "dota 2 beta" not in text and "gamestate_integration" not in text, file.name
