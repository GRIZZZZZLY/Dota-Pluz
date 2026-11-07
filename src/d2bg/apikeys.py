"""API keys of the optional cloud models. They come from the environment or from a local ``.env`` file
(the project folder, then the user folder); never from settings.json. Nothing here logs a key or hands
one to the API: callers ask ``configured()``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from d2bg import paths

JEV_KEY = "TYPESAFE_API_KEY"
ADVISOR_KEY = "FORGETAPI_API_KEY"
KEYS = (JEV_KEY, ADVISOR_KEY)


def env_files() -> list[Path]:
    """Next to d2bg.exe (the single-file build), the working folder, the project, the user folder."""
    exe = [Path(sys.executable).parent / ".env"] if getattr(sys, "frozen", False) else []
    return [
        *exe,
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
        paths.user_dir() / ".env",
    ]


def load_env(files: list[Path] | None = None) -> None:
    """Put the keys found in .env files into the environment; a key already set there wins."""
    for path in files if files is not None else env_files():
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            name, sep, value = line.strip().partition("=")
            value = value.strip().strip("\"'")
            if sep and name.strip() in KEYS and value and not os.environ.get(name.strip()):
                os.environ[name.strip()] = value


def key(name: str) -> str | None:
    return os.environ.get(name) or None


def configured(name: str) -> bool:
    return key(name) is not None
