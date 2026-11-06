@echo off
rem Reads the hero picks on the Dota 2 draft screen and sends them to d2bg (run.cmd must be running).
rem Captures the screen only during the draft of a real game. Close this window to stop. See docs\SAFETY.md.
cd /d "%~dp0"
uv run --no-sync d2bg-cv run %*
pause
