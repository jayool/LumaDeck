# Achievements

LumaDeck generates achievement files for SLSsteam-managed games using
[SLScheevo](https://github.com/xamionex/SLScheevo) by xamionex. SLScheevo signs
into Steam, fetches a game's achievement **schema** from accounts that own it,
and writes the stats files into Steam's `appcache/stats` so the game's
achievements are recognised.

## Setup

SLScheevo has to be installed and signed in once:

1. On a game page (or when prompted), use **Download SLScheevo** to fetch it.
2. **Sign in once.** SLScheevo authenticates with a **Steam account** (username,
   password and Steam Guard). LumaDeck can't do this interactive login for you,
   so when a game page shows *"Run SLScheevo in terminal to set up login"*, open
   Konsole (Desktop mode) and run SLScheevo once to log in. It saves an
   encrypted token, and generation then works from the QAM.

The achievement status on each game page reflects this:

| Status | Meaning |
| --- | --- |
| *SLScheevo not installed* | Download it first. |
| *Run SLScheevo in terminal to set up login* | One-time login needed. |
| *Ready to generate* | Good to go. |
| *Generating…* | In progress. |
| *Achievements generated (Restart Steam)* | Done — restart Steam to see them. |

## Per-game

On a game's page, tap **Generate Achievements**. When it finishes, restart
Steam to pick them up.

## All games at once

On the main page, when SLScheevo is ready, a **Sync All Achievements** button
generates for every installed game that has its files in place. A counter shows
progress (done / total).

> **Not every game works.** SLScheevo finds the schema by querying accounts that
> own the game; if none expose one (or the game simply has no achievements),
> generation reports there's nothing to create for it.

> Achievements only appear after a Steam restart, because Steam reads the
> generated files at startup.
