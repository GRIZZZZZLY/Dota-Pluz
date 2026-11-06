"""Where the pick slots are on the draft screen.

The draft screen as it is now (checked on real 1080p Turbo frames, 2026-11-07): each team's five
picks are slanted cards in the top bar, Radiant on the left. The side columns of square tiles that
alexisvaleev/dota-assist calibrates for (``app/autocalib.py``) are not on this screen, so that part
was not kept. The layout is found again on every frame, because each card moves on its own.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import cv2
import numpy as np

from d2bg_cv.recognize import Image

Box = list[int]


def _runs(line: Image, min_len: int) -> list[tuple[int, int]]:
    """(start, length) of every run of True at least ``min_len`` long."""
    padded = np.concatenate(([False], line.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(s), int(e - s)) for s, e in zip(edges[::2], edges[1::2], strict=True) if e - s >= min_len]


def topbar(img: Image) -> dict[str, Any] | None:
    """The top-bar layout, found again on every frame because each card moves on its own.

    Each pick card has a bar in its player's colour (checked on real 1080p Turbo frames, 2026-11-07):
    an empty card stands on its bar; once the hero is picked the card drops and the bar is above it.
    So the slots are found from every coloured bar in the band, and each slot's own topmost bar says
    where its card is (the coloured lines under the player names sit lower than both). The teams
    mirror each other around the centre, so one side with five slots gives the other (a pale colour
    such as pink can be missed). Slots are the insides of the cards, read by sliding them over each
    portrait (``match: slide``).
    """
    height, width = img.shape[:2]
    band = img[: max(int(height * 0.12), 1)]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    colour = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 80)
    rows = [_runs(colour[r], int(width * 0.03)) for r in range(colour.shape[0])]
    widths = [rw for row in rows for _, rw in row]
    if not widths:
        return None
    # Every player bar has the same width to a pixel; the lines under the names and bright patches
    # of portraits have all sorts of widths. So the bar width is the one most runs agree on.
    common = max(set(widths), key=lambda v: sum(abs(u - v) <= 3 for u in widths))
    w = int(np.median([u for u in widths if abs(u - common) <= 3]))
    rows = [[(x, rw) for x, rw in row if abs(rw - w) <= w * 0.1] for row in rows]
    found = sorted((x + rw / 2, rw) for row in rows for x, rw in row)
    centres: list[list[float]] = []
    for c, _ in found:
        if centres and c - centres[-1][-1] < w / 2:
            centres[-1].append(c)
        else:
            centres.append([c])
    # The median: a bright patch of a portrait next to a bar must not pull the slot sideways.
    slots_x = [float(np.median(group)) for group in centres if len(group) >= 2]
    left = [c for c in slots_x if c < width / 2]
    right = [c for c in slots_x if c >= width / 2]
    if len(left) == 5 and len(right) != 5:
        right = [width - c for c in reversed(left)]
    elif len(right) == 5 and len(left) != 5:
        left = [width - c for c in reversed(right)]
    if len(left) != 5 or len(right) != 5:
        return None
    steps = [b - a for side in (left, right) for a, b in pairwise(side)]
    if max(steps) - min(steps) > w * 0.15:
        return None  # not five evenly spaced cards
    card_h, margin = round(w * 0.62), round(w * 0.06)
    inside = (round(w * 0.14), round(w * 0.12))  # clear of the slanted sides on either team
    split = colour.shape[0] * 0.3

    def card(centre: float) -> tuple[Box, str]:
        near = [
            (r, run) for r, row in enumerate(rows) for run in row if abs(run[0] + run[1] / 2 - centre) < w / 2
        ]
        if not near:  # a bar too pale to see: assume the card is where its neighbours' empty cards are
            x0 = round(centre - w / 2)
            return [x0 + inside[0], margin, w - sum(inside), card_h - 2 * margin], "bottom"
        y0, (x0, _) = near[0]
        y1 = max(r for r, _ in near if r - y0 < w * 0.1)
        if y0 < split:  # bar on top: the card hangs below it
            return [x0 + inside[0], y1 + 1 + margin, w - sum(inside), card_h - 2 * margin], "top"
        return [x0 + inside[0], margin, w - sum(inside), y0 - 2 * margin], "bottom"

    cards = [card(c) for c in left + right]
    return {
        "resolution": [width, height],
        "layout": "topbar",
        "match": "slide",
        "bars": [where for _, where in cards],
        "radiant_on_right": False,
        "auto": True,
        "team_left": {"slots": [box for box, _ in cards[:5]]},
        "team_right": {"slots": [box for box, _ in cards[5:]]},
        "bans": [],
    }
