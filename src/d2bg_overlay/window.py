"""The overlay's window settings: where each hint widget sits, how see-through the widgets are, and the
Win32 style bits that let clicks pass through them. Only window styles are touched, and only on the
overlay's own windows."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020  # mouse input goes to the window below
WS_EX_TOOLWINDOW = 0x00000080  # no taskbar button
LWA_ALPHA = 0x2

# Widget sizes; each one shows a single hint and is hidden while it has none.
WIDGETS = {"skill": (320, 76), "draft": (340, 156), "items": (320, 176)}
HANDLE = (40, 176)


def default_spot(name: str, left: int, top: int, width: int, height: int) -> tuple[int, int]:
    """Where a widget starts on Dota's screen before he moves it: the skill hint above the ability bar
    and its talent button, the pick hint in the empty space right of the draft screen's minimap, the
    item hint at the right, the handle at the left edge."""
    w, h = WIDGETS.get(name, HANDLE)
    x, y = {
        "skill": (width // 2 - w // 2, int(height * 0.79) - h),
        "draft": (int(width * 0.245), int(height * 0.825)),
        "items": (width - w - 16, int(height * 0.12)),
    }.get(name, (0, int(height * 0.4)))
    return left + x, top + y


@dataclass
class Layout:
    opacity: float = 0.9  # 0.3 .. 1.0
    # Top-left corner of each widget he moved; the others use default_spot.
    spots: dict[str, list[int]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Layout:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            spots = {k: [int(v[0]), int(v[1])] for k, v in doc.get("spots", {}).items() if k in WIDGETS}
            return cls(opacity=min(max(float(doc.get("opacity", 0.9)), 0.3), 1.0), spots=spots)
        except (OSError, ValueError, TypeError, IndexError, AttributeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")


def ex_style(current: int, click_through: bool) -> int:
    """The extended style for a see-through overlay: layered, no taskbar button, and click-through
    while locked."""
    style = current | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    return style | WS_EX_TRANSPARENT if click_through else style & ~WS_EX_TRANSPARENT


def apply(title: str, click_through: bool, opacity: float) -> bool:  # pragma: no cover - Windows only
    """Set the style and opacity of the overlay's own window, found by its unique title. Opacity 0
    hides a widget without showing or activating any window, so the game keeps the keyboard."""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE, ex_style(user32.GetWindowLongW(hwnd, GWL_EXSTYLE), click_through)
    )
    user32.SetLayeredWindowAttributes(hwnd, 0, round(255 * opacity), LWA_ALPHA)
    return True
