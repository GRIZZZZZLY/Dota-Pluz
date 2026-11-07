"""Build dist/d2bg.exe: the app, the overlay and the draft-screen reader in one file (PyInstaller).

Run from the project folder after `npm run build` in web/ (build-exe.cmd does both):

    uv run --no-sync --with pyinstaller --with "pywebview>=5.3" python packaging/build_exe.py

PyInstaller and pywebview live only in that temporary environment; the project's stays as it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    static = ROOT / "src" / "d2bg" / "static"
    if not (static / "index.html").exists():
        sys.exit("Нет собранного интерфейса: сначала выполните npm run build в папке web.")
    sep = ";"  # Windows
    PyInstaller.__main__.run(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--name",
            "d2bg",
            "--paths",
            str(ROOT / "src"),
            "--add-data",
            f"{ROOT / 'data' / 'snapshot'}{sep}d2bg/_snapshot",
            "--add-data",
            f"{ROOT / 'data' / 'knowledge'}{sep}d2bg/knowledge",
            "--add-data",
            f"{static}{sep}d2bg/static",
            "--collect-submodules",
            "uvicorn",
            "--collect-submodules",
            "d2bg",
            "--collect-submodules",
            "d2bg_cv",
            "--collect-submodules",
            "d2bg_overlay",
            "--collect-all",
            "webview",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build" / "pyinstaller"),
            "--specpath",
            str(ROOT / "build"),
            str(ROOT / "packaging" / "d2bg_exe.py"),
        ]
    )


if __name__ == "__main__":
    main()
