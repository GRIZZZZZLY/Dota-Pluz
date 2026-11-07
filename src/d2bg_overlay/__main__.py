"""``python -m d2bg_overlay [server] [--app]``: open the hint widgets over Dota (needs pywebview;
run-overlay.cmd brings it). ``--app`` also opens the full app on the second monitor."""

from __future__ import annotations

import sys

from d2bg_overlay.app import Overlay


def main() -> None:  # pragma: no cover - opens windows
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    server = args[0] if args else "http://127.0.0.1:4242"
    print("Подсказки d2bg поверх Dota. Dota должна быть в режиме «Окно без рамки».")
    print("Каждая подсказка появляется, только когда ей есть что сказать.")
    print("Кнопка ⚙ на ручке слева показывает все подсказки, чтобы их перетащить; ✔ запоминает места.")
    print(
        "Кнопка 🖥 открывает приложение на втором мониторе. Закройте это окно терминала, чтобы убрать подсказки."
    )
    Overlay(server).run(open_app="--app" in sys.argv)


if __name__ == "__main__":
    main()
