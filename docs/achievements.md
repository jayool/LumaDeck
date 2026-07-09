# Achievements

LumaDeck generates achievement files for SLSsteam-managed games using
[SLScheevo](https://github.com/xamionex/SLScheevo) by xamionex. SLScheevo signs
into Steam, fetches a game's achievement **schema** from accounts that own it,
and writes the stats files into Steam's `appcache/stats` so the game's
achievements are recognised.

Everything **global** (installing SLScheevo, the one-time login, "Sync All")
lives on a dedicated **Achievements page** — open it from the **Achievements**
button in the LumaDeck panel. **Per-game** generation lives on each game's page.

## The flow at a glance

| Step | Where it runs | How |
| --- | --- | --- |
| 1. Download SLScheevo | **Achievements page** (Game Mode) | One button — no terminal. |
| 2. Sign in *(one time)* | **Desktop mode** (terminal) | SLScheevo's Steam login is interactive, and Game Mode has no terminal. |
| 3. Generate achievements | **Game Mode** | Per-game from the game's page, or "Sync All" from the Achievements page — both headless using the saved login. |
| 4. Restart Steam | — | Steam reads the files at startup. |

**Only step 2 needs Desktop mode**, and only once. Everything else happens in
Game Mode from the plugin.

## 1. Download (Achievements page)

Open the **Achievements** page from the LumaDeck panel and tap **Download
SLScheevo**. It fetches the latest Linux build into the plugin's data folder
(`~/homebrew/plugins/LumaDeck/backend/data/SLScheevo/`). No terminal needed.

## 2. Sign in, once (Desktop mode)

SLScheevo authenticates with a **Steam account** (username, password and Steam
Guard). That login is interactive and Game Mode has no terminal, so LumaDeck
can't do it for you. On the Achievements page, tap **Configure in Desktop** —
it arms a hand-off that opens Konsole already running SLScheevo and switches to
Desktop. Then:

1. Enter your Steam login when prompted. It saves an encrypted token next to the
   binary (`data/saved_logins.encrypted`).
2. When it finishes, close the window and switch back to Game Mode by hand.

You can also do it manually — the Achievements page shows the exact command:

```sh
cd ~/homebrew/plugins/LumaDeck/backend/data/SLScheevo
./SLScheevo          # or ./SLScheevo-Linux
```

Because Desktop mode runs as the `deck` user, the token is saved as `deck` —
which is the same user LumaDeck drops to when generating, so it can decrypt it.
Back in Game Mode the login status on the Achievements page flips from *Login
required* to *Ready*.

The achievement status on each game page reflects all of this:

| Status | Meaning |
| --- | --- |
| *SLScheevo not installed* | Do step 1 — a button on the game page opens the Achievements page to set it up. |
| *Run SLScheevo in terminal to set up login* | Do step 2 — same button opens the Achievements page. |
| *Ready to generate* | Good to go. |
| *Generating…* | In progress. |
| *Achievements generated (Restart Steam)* | Done — restart Steam to see them. |

## 3. Generate (Game Mode)

- **One game** — on its page, tap **Generate Achievements**.
- **All games** — on the **Achievements** page (once SLScheevo is set up), tap
  **Sync All**; a counter shows progress (done / total), and an overview shows
  how many of your games already have achievements generated.

Both run headless through the plugin using the saved login — no terminal.

## 4. Restart Steam

> **Not every game works.** SLScheevo finds the schema by querying accounts that
> own the game; if none expose one (or the game simply has no achievements),
> generation reports there's nothing to create for it.

Achievements only appear after a **Steam restart**, because Steam reads the
generated files at startup. The Achievements page has a **Restart Steam** button
for this.
