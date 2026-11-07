"""Small always-on-top hint widgets over Dota (skill, picks, items), each shown only while it has a hint,
plus a handle that is never click-through: it unlocks the widgets to move them, changes their opacity
and opens the full app on the second monitor."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Any

from d2bg import paths
from d2bg_overlay.window import HANDLE, WIDGETS, Layout, apply, default_spot

TITLES = {name: f"d2bg hint {name}" for name in WIDGETS}
HANDLE_TITLE = "d2bg overlay handle"

HANDLE_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
html,body{overflow:hidden}
body{margin:0;background:#1c2529;font:16px system-ui;display:flex;flex-direction:column;gap:2px;padding:2px}
button{width:36px;height:40px;border:1px solid #3c4b52;border-radius:4px;background:#243035;color:#e8e2d0;cursor:pointer}
button:hover{background:#2e3b41}
</style></head><body>
<button id="setup" title="Настроить: показать все подсказки, чтобы перетащить их" onclick="pywebview.api.toggle_setup().then(show)">⚙</button>
<button title="Плотнее" onclick="pywebview.api.fade(0.1)">◼</button>
<button title="Прозрачнее" onclick="pywebview.api.fade(-0.1)">◻</button>
<button title="Приложение на втором мониторе" onclick="pywebview.api.toggle_app()">🖥</button>
<script>
function show(on){var b=document.getElementById('setup');b.textContent=on?'✔':'⚙';
b.title=on?'Готово: запомнить места, клики снова идут в игру':'Настроить: показать все подсказки, чтобы перетащить их';}
</script></body></html>"""


def fetch_hud(server: str) -> dict[str, Any] | None:
    try:
        # The app's own server, given on the command line (http://127.0.0.1:4242 by default).
        with urllib.request.urlopen(f"{server}/api/copilot/hud", timeout=2) as r:  # noqa: S310
            doc: dict[str, Any] = json.load(r)
            return doc
    except (OSError, ValueError):
        return None  # the app is not running: hide everything


class Overlay:
    def __init__(self, server: str) -> None:
        self.file = paths.user_dir() / "overlay.json"
        self.layout = Layout.load(self.file)
        self.server = server
        self.setup = False
        self.windows: dict[str, Any] = {}
        self.app_window: Any = None
        self.hud: dict[str, Any] | None = None
        self._shown: dict[str, bool] = {}
        self._lock = threading.Lock()

    def sync(self, hud: dict[str, Any] | None) -> None:
        """Show the widgets that have a hint and hide the rest; windows whose state did not change are
        left alone. While he sets them up, all are shown and take the mouse."""
        with self._lock:
            self.hud = hud
            for name, title in TITLES.items():
                on = self.setup or bool(hud and hud.get(name))
                if self._shown.get(name) != on:
                    apply(title, not self.setup, self.layout.opacity if on else 0.0)
                    self._shown[name] = on

    # Called from the handle's buttons (pywebview js_api).

    def toggle_setup(self) -> bool:
        with self._lock:
            if self.setup:
                for name, w in self.windows.items():
                    self.layout.spots[name] = [int(w.x), int(w.y)]
                self.layout.save(self.file)
            self.setup = not self.setup
            self._shown.clear()  # restyle every widget
        self.sync(self.hud)
        return self.setup

    def fade(self, step: float) -> None:
        with self._lock:
            self.layout.opacity = round(min(max(self.layout.opacity + step, 0.3), 1.0), 2)
            self.layout.save(self.file)
            self._shown.clear()
        self.sync(self.hud)

    def toggle_app(self) -> None:  # pragma: no cover - opens a window
        """The full app, maximized on the second monitor (the first if there is one), instead of a
        browser tab."""
        import webview

        if self.app_window is not None:
            self.app_window.destroy()
            self.app_window = None
            return
        screens = webview.screens
        self.app_window = webview.create_window(
            "d2bg", f"{self.server}/", screen=screens[1 if len(screens) > 1 else 0], maximized=True
        )
        self.app_window.events.closed += lambda *_: setattr(self, "app_window", None)

    def run(self, open_app: bool = False) -> None:  # pragma: no cover - opens windows
        import webview

        screen = webview.screens[0]
        for name, (w, h) in WIDGETS.items():
            x, y = self.layout.spots.get(name) or default_spot(
                name, screen.x, screen.y, screen.width, screen.height
            )
            self.windows[name] = webview.create_window(
                TITLES[name],
                f"{self.server}/hud/{name}",
                x=x,
                y=y,
                width=w,
                height=h,
                min_size=(100, 40),
                on_top=True,
                frameless=True,
                easy_drag=True,
                focus=False,  # never takes the keyboard from the game
                background_color="#1c2529",
            )
        hx, hy = default_spot("handle", screen.x, screen.y, screen.width, screen.height)
        handle = webview.create_window(
            HANDLE_TITLE,
            html=HANDLE_HTML,
            js_api=self,
            x=hx,
            y=hy,
            width=HANDLE[0],
            height=HANDLE[1],
            min_size=HANDLE,
            on_top=True,
            frameless=True,
            easy_drag=False,
            background_color="#1c2529",
        )

        def started() -> None:
            sizes = {**WIDGETS, "handle": HANDLE}
            for name, w in [*self.windows.items(), ("handle", handle)]:
                w.events.shown.wait(15)
                # pywebview opens a frameless window smaller by the frame it does not have (16x39 px
                # here); resizing once it is shown gives the exact size.
                w.resize(*sizes[name])
            apply(HANDLE_TITLE, False, 0.9)
            if open_app:
                self.toggle_app()
            while True:
                self.sync(fetch_hud(self.server))
                time.sleep(1.0)

        webview.start(started)
