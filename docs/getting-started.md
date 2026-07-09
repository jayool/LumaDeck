# Getting started

This is the short path from a fresh install to your first downloaded game.
For the full install walkthrough (downloading the zip, sideloading through
Decky), see the root [README → Installation](../README.md#installation).

LumaDeck lives in the **Quick Access Menu (QAM)**: press the **`•••`** button,
scroll to the LumaDeck icon, and open it.

## 1. Set your credentials

LumaDeck fetches game manifests from manifest providers, which need a
credential. Open **Settings ▸ API Credentials** and set at least one:

- **Hubcap API key** — the main provider. See [Credentials](credentials.md#hubcap-api-key).
- **Ryuu cookie** *(optional)* — a second provider, imported in one tap. See [Credentials](credentials.md#ryuu-cookie).

A status line under each field tells you whether the credential is valid and
when it expires.

## 2. Install the components

**First time (nothing installed yet):** the main LumaDeck page in the QAM shows
a **Quick Install** button. It installs and configures every component in the
correct order in a single tap — the recommended path for a fresh setup. (It only
appears while none of the components are installed; once any is present it's
replaced by the individual controls in Settings.)

To install them **individually** (or to reinstall later), open
**Settings ▸ Dependencies** and run them **in this order**:

1. **Install / Reinstall Dependencies** — runs [headcrab.sh](https://github.com/Deadboy666/h3adcr-b)
   in the background: installs **SLSsteam + CloudRedirect** in one pass, plus the
   **.NET 9 runtime** (via Microsoft's official installer script), and patches
   Steam. CloudRedirect ships with the base install but stays inert until you
   sign into a provider — for cloud saves see [Cloud saves](cloud-saves.md).
2. **Install / Reapply lumalinux** — **always do this last.** Runs
   [lumalinux's `install.sh`](https://github.com/jayool/lumalinux/blob/main/install.sh):
   deploys `liblumalinux.so` plus the `tools/` scripts and patches Steam's
   `steam.sh` with the `LD_PRELOAD` block. The earlier steps regenerate
   `steam.sh` and wipe that block, so lumalinux has to go in *after* them, or
   nothing downloads. (Same reason: reapply it whenever you re-run the other
   installers.)

Each step ends with a single, intentional Steam restart. The panel shows a
live green/red state for every component — see [Components & health](components-and-health.md).

> Some actions are blocked in Game Mode and must be run from Desktop (the panel
> tells you when). This usually happens after a SteamOS/Steam client update —
> see [Troubleshooting](troubleshooting.md).

## 3. Add your first game

There are **three ways** to pick a game, all on the main LumaDeck page:

- **From its Steam store page** — open the store page and LumaDeck auto-detects
  the AppID (shown below).
- **Search by name** — type a title under *Search by Name* (uses Hubcap).
- **By AppID** — type the Steam AppID directly into *Add Game*.

All three are covered in [Adding & updating games](adding-and-updating-games.md).
The store-page route, end to end:

1. In Steam, open the **store page** of the game you want.
2. Open LumaDeck in the QAM — it **auto-detects the AppID** and fills it in.
3. Tap **Download Manifest**.
4. When it finishes, **restart Steam** so the game appears in your library.
5. In Steam, press **Install** on the game — it now downloads natively, like any
   owned title. **Progress shows in the Steam library, not in the plugin.**
