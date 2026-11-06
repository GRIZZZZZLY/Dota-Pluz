"""Hero portraits on the draft screen, by OpenCV template matching.

Ported from alexisvaleev/dota-assist (MIT), ``app/recognizer.py`` and ``app/draft_watcher.py`` at
commit 7c0fc36: normalised cross-correlation against every template, a score threshold, a margin
over the second-best hero (two similar portraits give no answer), and two agreeing frames before a
slot counts. Changes here: a template is cropped to the slot's shape before scaling, slots are read
as Radiant, Dire or ban, and the result has the shape of d2bg's ``DraftObservation``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
import numpy as np

THRESHOLD = 0.82
MIN_MARGIN = 0.06
# An empty slot is a smooth gradient; a portrait has detail. Measured on a real 1080p draft screen
# (2026-11-07): empty cards 3-16, a first-pick flag 678, a hero portrait about 2,000.
EMPTY_TEXTURE = 100.0
# A top-bar card shows the hero's CDN portrait scaled to the card, partly hidden by its slanted frame:
# the inside we read is 0.64-0.68 of the portrait's width (measured on ten real cards, 2026-11-07).
ZOOM = (0.62, 0.66, 0.70)

Image = np.ndarray


def fit(template: Image, w: int, h: int) -> Image:
    """Crop the template's centre to the slot's aspect ratio, then scale it to the slot."""
    th, tw = template.shape[:2]
    if tw / th > w / h:
        nw = max(round(th * w / h), 1)
        x = (tw - nw) // 2
        template = template[:, x : x + nw]
    else:
        nh = max(round(tw * h / w), 1)
        y = (th - nh) // 2
        template = template[y : y + nh, :]
    return cv2.resize(template, (w, h), interpolation=cv2.INTER_AREA)


def filled(crop: Image) -> bool:
    """Whether a slot shows something (a portrait, or anything it cannot read) rather than nothing."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var()) > EMPTY_TEXTURE


def inner(img: Image, inset: tuple[int, int, int, int]) -> Image:
    """The part of a slot inside its frame: (left, top, right, bottom) pixels cut off."""
    left, top, right, bottom = inset
    h, w = img.shape[:2]
    return img[top : h - bottom, left : w - right]


class Recognizer:
    def __init__(
        self,
        templates: Mapping[str, list[Image]],
        threshold: float = THRESHOLD,
        min_margin: float = MIN_MARGIN,
    ) -> None:
        self.templates = dict(templates)
        self.threshold = threshold
        self.min_margin = min_margin
        self._scaled: dict[tuple[str, int, int, int], Image] = {}
        self._gray: dict[str, list[Image]] = {}

    @classmethod
    def from_dir(cls, directory: Path) -> Recognizer:
        """Templates as ``<directory>/<hero key>/*.png``."""
        templates: dict[str, list[Image]] = {}
        for hero_dir in sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []:
            images = [img for f in sorted(hero_dir.glob("*.png")) if (img := cv2.imread(str(f))) is not None]
            if images:
                templates[hero_dir.name] = images
        return cls(templates)

    def best(
        self, crop: Image, inset: tuple[int, int, int, int] = (0, 0, 0, 0)
    ) -> tuple[str | None, float, float]:
        """(hero key or None, best score, margin over the second-best hero).

        The template is fitted to the whole slot, then only the part inside ``inset`` is compared: the
        game draws portraits in slanted cards, and their corners are background.
        """
        if crop.size == 0 or not self.templates:
            return None, 0.0, 0.0
        h, w = crop.shape[:2]
        visible = inner(crop, inset)
        if visible.size == 0:
            return None, 0.0, 0.0
        scores: dict[str, float] = {}
        for key, images in self.templates.items():
            for i, template in enumerate(images):
                size = (key, i, w, h)
                scaled = self._scaled.get(size)
                if scaled is None:
                    scaled = self._scaled[size] = fit(template, w, h)
                score = float(cv2.matchTemplate(visible, inner(scaled, inset), cv2.TM_CCOEFF_NORMED)[0][0])
                scores[key] = max(score, scores.get(key, -1.0))
        return self._decide(scores)

    def slide(self, crop: Image, zoom: tuple[float, ...] = ZOOM) -> tuple[str | None, float, float]:
        """Find the crop anywhere inside each hero's portrait at a few scales (top-bar cards)."""
        if crop.size == 0 or not self.templates:
            return None, 0.0, 0.0
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        ch, cw = gray.shape
        scores: dict[str, float] = {}
        for key, images in self.templates.items():
            grays = self._gray.get(key)
            if grays is None:
                grays = self._gray[key] = [cv2.cvtColor(t, cv2.COLOR_BGR2GRAY) for t in images]
            for i, template in enumerate(grays):
                for share in zoom:
                    tw = round(cw / share)
                    th = round(template.shape[0] * tw / template.shape[1])
                    if th < ch:
                        continue
                    size = (key, i, tw, th)
                    scaled = self._scaled.get(size)
                    if scaled is None:
                        scaled = self._scaled[size] = cv2.resize(
                            template, (tw, th), interpolation=cv2.INTER_AREA
                        )
                    score = float(cv2.matchTemplate(scaled, gray, cv2.TM_CCOEFF_NORMED).max())
                    scores[key] = max(score, scores.get(key, -1.0))
        return self._decide(scores) if scores else (None, 0.0, 0.0)

    def _decide(self, scores: dict[str, float]) -> tuple[str | None, float, float]:
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        name, top = ranked[0]
        margin = top - (ranked[1][1] if len(ranked) > 1 else 0.0)
        if top >= self.threshold and margin >= self.min_margin:
            return name, top, margin
        return None, top, margin


class Votes:
    """A slot counts once the last two readings that found a hero agree (dota-assist's ``_stable``)."""

    def __init__(self) -> None:
        self._history: dict[tuple[str, int], list[str | None]] = {}

    def vote(self, slot: tuple[str, int], hero: str | None) -> str | None:
        history = self._history.setdefault(slot, [])
        history.append(hero)
        del history[:-3]
        found = [h for h in history if h]
        return found[-1] if len(found) >= 2 and found[-1] == found[-2] else None

    def reset(self) -> None:
        self._history.clear()


def _same(a: Image, b: Image) -> bool:
    return float(cv2.absdiff(a, b).mean()) < 2.0


def slots(cal: Mapping[str, Any], group: str, width: int, height: int) -> list[tuple[int, int, int, int]]:
    """A calibration group's boxes, scaled from the calibrated resolution to this frame."""
    raw = cal.get(group)
    boxes = raw.get("slots", []) if isinstance(raw, Mapping) else (raw or [])
    rw, rh = cal.get("resolution") or (width, height)
    sx, sy = width / max(rw, 1), height / max(rh, 1)
    return [(round(x * sx), round(y * sy), round(w * sx), round(h * sy)) for x, y, w, h in boxes]


def read_screen(
    img: Image,
    cal: Mapping[str, Any],
    recognizer: Recognizer,
    votes: Votes,
    hero_ids: Mapping[str, int],
    memo: dict[tuple[str, int], tuple[Image, tuple[str | None, float, float]]] | None = None,
) -> dict[str, Any]:
    """One frame as a ``DraftObservation`` payload. A filled slot it cannot read counts as unknown.

    ``memo`` keeps each slot's last picture and reading, so a slot that did not change is not matched
    again (a pick stays put for the rest of the draft).
    """
    height, width = img.shape[:2]
    radiant_group = "team_right" if cal.get("radiant_on_right") else "team_left"
    dire_group = "team_left" if radiant_group == "team_right" else "team_right"
    out: dict[str, Any] = {"radiant": [], "dire": [], "bans": [], "slots": []}
    unknown, recognised, worst = 0, 0, 1.0
    rw, rh = cal.get("resolution") or (width, height)
    il, it, ir, ib = cal.get("inset") or (0, 0, 0, 0)
    sx, sy = width / max(rw, 1), height / max(rh, 1)
    inset = (round(il * sx), round(it * sy), round(ir * sx), round(ib * sy))
    for side, group in (("radiant", radiant_group), ("dire", dire_group), ("bans", "bans")):
        for i, (x, y, w, h) in enumerate(slots(cal, group, width, height)):
            crop = img[y : y + h, x : x + w]
            if w <= 0 or h <= 0 or crop.size == 0:
                continue
            previous = memo.get((side, i)) if memo is not None else None
            if previous is not None and previous[0].shape == crop.shape and _same(previous[0], crop):
                name, score, margin = previous[1]
            elif cal.get("match") == "slide":
                name, score, margin = recognizer.slide(crop)
            else:
                name, score, margin = recognizer.best(crop, inset)
            if memo is not None:
                memo[(side, i)] = (crop.copy(), (name, score, margin))
            hero = votes.vote((side, i), name)
            hero_id = hero_ids.get(hero) if hero else None
            out["slots"].append(
                {
                    "side": side,
                    "index": i,
                    "hero_id": hero_id,
                    "score": round(score, 3),
                    "margin": round(margin, 3),
                }
            )
            if hero_id is not None:
                if hero_id not in out[side]:
                    out[side].append(hero_id)
                if side != "bans":
                    recognised += 1
                    worst = min(worst, score)
            elif side != "bans" and filled(inner(crop, inset)):
                unknown += 1
    occupied = recognised + unknown
    # dota-assist's honest confidence: the weakest match, scaled down by the share of unread slots.
    out["confidence"] = round(worst * recognised / occupied, 3) if recognised else 0.0
    out["unknown_slots"] = unknown
    out["capture_resolution"] = [width, height]
    return out
