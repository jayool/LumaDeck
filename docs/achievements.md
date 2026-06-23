# Achievements

LumaDeck generates achievement files for SLSsteam-managed games using
[SLScheevo](https://github.com/xamionex/SLScheevo) by xamionex.

## Setup

SLScheevo has to be installed and signed in once:

1. On a game page (or when prompted), use **Download SLScheevo** to fetch it.
2. SLScheevo needs a one-time login. If a game page reports *"Run SLScheevo in
   terminal to set up login"*, open Konsole (Desktop mode) and run it once to
   authenticate. After that, generation works from the QAM.

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

> Achievements only appear after a Steam restart, because Steam reads the
> generated files at startup.
