@echo off
rem Build dist\d2bg.exe (one file: the app, the overlay, the draft reader). Needs uv and Node.js.
cd /d "%~dp0"
pushd web
call npm run build || exit /b 1
popd
uv run --no-sync --with pyinstaller --with "pywebview>=5.3" python packaging\build_exe.py
