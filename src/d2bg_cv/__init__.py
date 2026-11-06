"""d2bg-cv: reads the heroes on the draft screen and sends them to d2bg.

A separate, optional process (``uv sync --extra cv``, then ``uv run d2bg-cv run``). It captures the
monitor only while d2bg reports a hero selection or strategy phase of a real game, keeps nothing on
disk unless asked (``d2bg-cv snap``), and never sends input to the game. The core app (``d2bg``) never
imports it. See docs/SAFETY.md.
"""
