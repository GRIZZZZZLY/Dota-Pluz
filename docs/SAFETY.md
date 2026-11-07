# Safety: what this app touches, and why it stays within Valve's rules

Short version: the app only listens to what Dota 2 itself sends through **Game State Integration**
(GSI), calls **public web APIs**, and reads **static data**. It never touches the game process, never
sends input, and the only file it writes into the Dota folder is the GSI config.

## Everything the app touches

| What | How | Why |
|---|---|---|
| `<Dota 2>\game\dota\cfg\gamestate_integration\gamestate_integration_d2bg.cfg` | Written when you click **Install** on the Setup page; deleted when you click **Remove** | This file is how Valve's GSI is switched on. The game reads it and starts sending JSON to the address inside it. |
| `<Steam>\steamapps\libraryfolders.vdf` and the registry value `HKCU\Software\Valve\Steam\SteamPath` | Read only | To find which drive Dota is installed on. |
| `http://127.0.0.1:4242` | A local web server: Dota POSTs GSI JSON to `/gsi`; your browser loads the UI | Loopback only by default. LAN mode (for a phone) is opt-in and needs a token. |
| `https://api.opendota.com` | HTTPS requests, about 1 per second at most, cached on disk | Hero, item, meta, matchup and benchmark data, your public profile and matches, replay-parse requests. |
| `https://cdn.cloudflare.steamstatic.com` | Image downloads by your browser; and, once, by `d2bg-cv templates` | Hero and item pictures from Valve's public CDN. The optional screen reader uses the hero pictures as recognition templates. |
| `%LOCALAPPDATA%\d2bg\` | Read and write | Settings, API cache, refreshed data, GSI recordings, the Copilot journal (`copilot.sqlite3`), and for the optional screen reader its templates and calibration (`cv\`). |
| Your main monitor (optional `d2bg-cv` only) | Screen capture, about twice a second | Only while d2bg reports the hero selection or strategy time of a real game (never a demo or a replay), to read the heroes on the draft screen. Frames stay in memory; nothing is saved unless you run `d2bg-cv snap`, which saves one frame. |

## Things the app never does

- Read or write the memory of `dota2.exe`, inject code, or load anything into the game.
- Draw inside the game. The optional compact window is an ordinary separate window.
- Send keystrokes or mouse clicks, or automate anything in the game or Steam.
- Capture network packets or the game's console log. The core app (`d2bg`) never captures the
  screen either; only the optional, separate `d2bg-cv` process does, and only during a real draft
  (see the table above). It is off unless you start it.
- Write any game file other than the GSI config above, or change Steam settings or launch options.
- Use DotaPlus, Overwolf or any other private backend.

`tests/d2bg/test_safety.py` enforces this in CI. It fails the build if the package imports
process, input, capture or Windows-API libraries (`ctypes`, `pymem`, `pynput`, `pyautogui`,
`keyboard`, `mouse`, `scapy`, `win32api`, `mss`, ...), mentions calls such as `ReadProcessMemory`,
`OpenProcess` or `SendInput`, or writes into the Dota folder anywhere but the GSI installer.
`tests/d2bg/test_cv_safety.py` holds `d2bg-cv` to the same list with one exception, `mss` for the
capture, which may live in one file only, and checks that the core app never imports it.

### The overlay is a window over the game, not inside it

`run-overlay.cmd` opens three small hint windows (what to skill, whom to pick, what to buy) that stay on
top of Dota in borderless window mode, the way any window can sit over a borderless game. It is not an
in-game overlay like Discord's or Steam's, which hook into the game's rendering; this app never does
that. Each window asks the app's own local server once a second what to show
(`/api/copilot/hud`, built from GSI data only) and is fully transparent while it has nothing to show.
Windows passes clicks through the hint windows to the game (a window style, `WS_EX_TRANSPARENT`, set on
the overlay's own windows only), and they never take keyboard focus from the game. A small handle at the
screen edge unlocks them to move them, changes their opacity, and opens the full app maximized on the
second monitor. The overlay reads nothing from the game and sends it nothing. `tests/d2bg/test_overlay.py`
keeps the window-style calls in one file and to four functions (`FindWindowW`, `GetWindowLongW`,
`SetWindowLongW`, `SetLayeredWindowAttributes`), and checks that the core app never imports it.

### Why reading the draft screen is a separate, optional process

During a ranked draft the game does not send a player the enemy picks, but it shows them on screen.
Reading what is already visible to you is a different thing from reading hidden client data, the
target of Valve's 2023 bans. Still, it is a step beyond GSI, so it stays out of the core app: you
install it on purpose (`uv sync --extra cv`), start it on purpose (`uv run d2bg-cv run`), and a slot
it cannot read stays unknown for you to fill in, never guessed.

## Why this is within the rules

1. **GSI is Valve's own interface.** Dota 2 ships with it. You enable it by placing a config file in
   the `gamestate_integration` folder, and the game decides what to send. While you play, it sends
   your own hero, items and abilities, the match clock, the chat's announcements (bans, kills,
   purchases) as `events`, and what your minimap shows as `minimap`: allies after loading, and enemies
   only while you can see them. Its `draft` block stays empty for a player (checked in his recorded
   ranked games), so the app never knows the enemy picks during the draft. Data about all ten players,
   including their items, is sent only when you spectate or cast; the app shows enemy items only then.
2. **Valve's 2023 ban wave targeted reading hidden client data.** In February 2023 Valve banned over
   40,000 accounts for third-party software that read information from the game client that players
   cannot see ("Cheaters Will Never Be Welcome in Dota",
   <https://www.dota2.com/newsentry/3677788723152833273>). This app reads nothing from the client; it
   receives only what GSI sends.
3. **Public APIs.** OpenDota is a public, documented API built on public match data. The client stays
   under its published limits (read from its response headers).
4. **No automation.** Every action in the game is yours. Timers and suggestions are information.

## If no GSI data arrives

Some Dota builds only enable GSI when the game is started with the `-gamestateintegration` launch
option. The app will not edit your launch options. If the Setup page never sees a packet, add it
yourself: Steam → Library → Dota 2 → Properties → General → Launch options.

## The v1 desktop app

The older desktop app in this repo (`python main.py`) uses `pynput` to listen for one global hotkey
that toggles its overlay. It listens only; it never sends input. The new app (`d2bg`) has no global
keyboard hook at all; its shortcuts work only inside the browser tab.

## Limits of this statement

This is a reading of Valve's public statements and the GSI design, not a guarantee from Valve. Valve
can change its rules. Don't run this alongside software that does any of the things listed under
"never", because a ban would apply to the account, not to one program.
