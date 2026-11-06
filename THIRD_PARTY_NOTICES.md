# Third-party notices

Every outside project this repository uses or studies, pinned to the commit that was checked.
Checked on 2026-11-06 with the GitHub API. Update the SHA and this table before copying any new code.

## Code in this repository

| Project | Commit | License | What is used | Changed files |
|---|---|---|---|---|
| [Tajaddin/dota2-build-generator](https://github.com/Tajaddin/dota2-build-generator) | `main` at `9d8cdfb184f887d4ed677a0a0c8b9fcc2e45cf0f` (2026-10-19), plus branch `fix-live-draft` at `0cfd08ca7a75cf62dda5cc9aacedad2852ef27c3` (fast-forward, same author) | MIT, Copyright (c) 2026 Tajaddin Gafarov. Kept as `LICENSE` | The whole repository is the base: `src/d2bg/`, `web/`, `data/`, tests, `run.cmd` | `pyproject.toml`, `src/d2bg/api/app.py`, `src/d2bg/api/services.py`, `src/d2bg/paths.py`. New: `src/d2bg/copilot/`, `src/d2bg/api/copilot_routes.py`, `tests/d2bg/test_copilot.py`, the documents listed in `docs/ARCHITECTURE.md` |

The base project's own data notices still apply: hero, item and ability data come from OpenDota's
constants (dotaconstants, MIT), statistics from the public OpenDota API (see `docs/DESIGN.md`).

## Studied, not copied yet

Nothing below is in this repository. Each row says what may be reused and under which condition.

| Project | Commit | License | Files checked (all present at that commit) | Plan |
|---|---|---|---|---|
| [alexisvaleev/dota-assist](https://github.com/alexisvaleev/dota-assist) | `master` at `7c0fc36672dbaf9b58e19137aafbdc60862bc012` (2026-10-20) | MIT | `app/recognizer.py`, `app/draft_watcher.py`, `app/autocalib.py`, `app/wininfo.py` | Stage 3, optional. Template matching (`cv2.matchTemplate`, `TM_CCOEFF_NORMED`, threshold 0.82, top-2 margin) on draft portraits. Its dependencies include `mss`, `keyboard`, `PyQt6`, Flask and its own GSI server, and `wininfo.py` uses `ctypes`. Only the recognizer logic may be ported, outside the `d2bg` package (see `docs/IMPLEMENTATION_PLAN.md`). Hero icons are downloaded at first run, not committed. |
| [forest0xia/dota2bot-OpenHyperAI](https://github.com/forest0xia/dota2bot-OpenHyperAI) | `main` at `cb814c6c8dc51ed08045d6efd9f4a48147992711` (2026-04-03) | MIT | `docs/ARCHITECTURE.md`, `bots/item_purchase_generic.lua`, `bots/BotLib/` (128 entries) | Stage 2+, optional. Per-hero Lua files hold position item lists (`sRoleItemsBuyList['pos_1']`), ability orders and talent trees as plain tables; they can be read as data with tests. No Lua is run, and nothing is loaded into the game. |
| [Maxxoto/Dota-OpenHyperAI-Agent](https://github.com/Maxxoto/Dota-OpenHyperAI-Agent) | `main` at `4f2a7045ccda5b7e5b66dcbc08da97eb61976292` (2026-10-27) | MIT | `scripts/learn.mjs`, `bots/Customize/llm.example.lua`, README "LLM Advisor (Experimental)" | Stage 4, pattern only, rewritten in Python: candidates first, `score = base * (1 - alpha) + model * alpha` with `alpha <= 0.5`, a bounded wait, a small call budget per game, validation and a silent fallback. The README marks it as verified offline only. |
| [odota/core](https://github.com/odota/core) | `master` at `8d774abda8542390fbd215487d961f1b5c3a3ef3` (2026-10-30) | MIT | — | Used through its public API by the base project's client (`src/d2bg/opendota.py`). No code copied. |
| [odota/parser](https://github.com/odota/parser) | `master` at `927adf6bbd1fd321b711f544a5d754bfe75d89a7` (2026-10-24) | MIT | — | Stage 5+, optional local `.dem` parser (Java service), only on request. |
| [Darktex/d2pt-guides](https://github.com/Darktex/d2pt-guides) | `main` at `5012de43ae75198327a59460e4fc08e92b0bd09c` (2026-08-17) | **No license file found** (GitHub API returns 404 for the license) | — | Do not copy anything. Format study only, or point the user to their own install. Dota2ProTracker's terms apply. |

## Assets

No Valve assets are shipped. Hero and item pictures load in the browser from Valve's public CDN, as in
the base project.
