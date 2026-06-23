# Achievements

LumaDeck generates achievement files for SLSsteam-managed games using
[SLScheevo](https://github.com/xamionex/SLScheevo) by xamionex. SLScheevo signs
into Steam, fetches a game's achievement **schema** from accounts that own it,
and writes the stats files into Steam's `appcache/stats` so the game's
achievements are recognised.

## The flow at a glance

| Step | Where it runs | How |
| --- | --- | --- |
| 1. Download SLScheevo | **Game Mode** (LumaDeck) | One button — no terminal. |
| 2. Sign in *(one time)* | **Desktop mode** (terminal) | SLScheevo's Steam login is interactive, and Game Mode has no terminal. |
| 3. Generate achievements | **Game Mode** (LumaDeck) | Per-game or "Sync All" — runs headless using the saved login. |
| 4. Restart Steam | — | Steam reads the files at startup. |

**Only step 2 needs Desktop mode**, and only once. Everything else happens in
Game Mode from the plugin.

## 1. Download (Game Mode)

On a game page, tap **Download SLScheevo**. It fetches the latest Linux build
into the plugin's data folder (`~/homebrew/plugins/LumaDeck/backend/data/SLScheevo/`).
No terminal needed.

## 2. Sign in, once (Desktop mode)

SLScheevo authenticates with a **Steam account** (username, password and Steam
Guard). That login is interactive and Game Mode has no terminal, so LumaDeck
can't do it for you. Once:

1. Switch to **Desktop mode** and open **Konsole**.
2. Run the binary LumaDeck downloaded:
   ```sh
   cd ~/homebrew/plugins/LumaDeck/backend/data/SLScheevo
   ./SLScheevo          # or ./SLScheevo-Linux
   ```
3. Enter your Steam login when prompted. It saves an encrypted token next to the
   binary (`data/saved_logins.encrypted`).

Because Desktop mode runs as the `deck` user, the token is saved as `deck` —
which is the same user LumaDeck drops to when generating, so it can decrypt it.
Back in Game Mode the status flips from *Run SLScheevo in terminal to set up
login* to *Ready to generate*.

The achievement status on each game page reflects all of this:

| Status | Meaning |
| --- | --- |
| *SLScheevo not installed* | Do step 1 (download). |
| *Run SLScheevo in terminal to set up login* | Do step 2 (sign in). |
| *Ready to generate* | Good to go. |
| *Generating…* | In progress. |
| *Achievements generated (Restart Steam)* | Done — restart Steam to see them. |

## 3. Generate (Game Mode)

- **One game** — on its page, tap **Generate Achievements**.
- **All games** — on the main page (when SLScheevo is ready), tap **Sync All
  Achievements**; a counter shows progress (done / total).

Both run headless through the plugin using the saved login — no terminal.

## 4. Restart Steam

> **Not every game works.** SLScheevo finds the schema by querying accounts that
> own the game; if none expose one (or the game simply has no achievements),
> generation reports there's nothing to create for it.

Achievements only appear after a **Steam restart**, because Steam reads the
generated files at startup.
