@echo off
rem Small hint windows over Dota: skill, picks, items (run.cmd must be running). Dota needs the
rem borderless window display mode. Separate windows: nothing is drawn inside the game. See docs\SAFETY.md.
rem "run-overlay.cmd --app" also opens the full app on the second monitor.
cd /d "%~dp0"
uv run --no-sync --with "pywebview>=5.3" python -m d2bg_overlay %*
