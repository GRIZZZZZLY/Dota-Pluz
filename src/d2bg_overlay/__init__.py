"""d2bg-overlay: the Copilot panel in a see-through window over Dota.

An ordinary, separate OS window kept on top of a borderless Dota, like any window placed over a game.
Nothing is drawn inside the game and nothing is read from it; the window shows the app's ``/compact``
page. While locked, clicks pass through it to the game; a small handle next to it unlocks it so it can
be moved and resized. The core app (``d2bg``) never imports it. See docs/SAFETY.md.
"""
