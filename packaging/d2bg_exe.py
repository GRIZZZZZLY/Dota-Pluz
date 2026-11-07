"""Entry point of the single-file Windows build, d2bg.exe.

d2bg.exe                  start the app and open it in the browser (what a double-click does)
d2bg.exe overlay [--app]  the small hint windows over Dota (and the app on the second monitor)
d2bg.exe cv run           the optional draft-screen reader
d2bg.exe <command>        any other d2bg command: serve, data, gsi, ...
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> None:
    multiprocessing.freeze_support()
    for stream in (sys.stdout, sys.stderr):
        # A Russian console is cp1251: a symbol it lacks (the overlay's ⚙) must not stop the program.
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = sys.argv[1:]
    if args[:1] == ["overlay"]:
        sys.argv = [sys.argv[0], *args[1:]]
        from d2bg_overlay.__main__ import main as overlay

        overlay()
        return
    if args[:1] == ["cv"]:
        sys.argv = [sys.argv[0], *args[1:]]
        from d2bg_cv.cli import app as cv

        cv()
        return
    from d2bg.cli import app

    if not args:
        sys.argv.append("serve")
    app()


if __name__ == "__main__":
    main()
