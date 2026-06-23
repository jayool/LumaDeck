# Managing a game

Tapping a game in **My Games** opens its detail page. Everything here is
**per-game** and most of it is optional — a normally-installed game needs none
of it. Groups are ordered from everyday to advanced.

## Status & manifest

- **Status** — whether the game's files and `.lua` are present.
- **Re-download Manifest** — fetches the manifest and game files again (use
  after a failed or partial install).
- **Manifest only** — refreshes just the manifest/config without re-pulling
  game files.

If your Hubcap key is expired, this page shows a **Hubcap key expired** notice
with a shortcut to fix it, instead of silently failing a re-download.

## Auto-update

A toggle per game:

- **Auto-update (on)** — the game follows the latest published manifest.
- **Pinned** — frozen at the installed version; updates are held back. Useful
  when a newer build breaks a fix or a mod.

## Game management (SLSsteam)

These tell **SLSsteam** how to present the game to Steam. Add/remove each, with
a live status:

- **FakeAppId** — maps the game onto a fake owned app so Steam treats it as
  owned.
- **Token** — supplies the app token SLSsteam needs for the title.
- **DLCs** — marks the game's DLCs as owned so they appear in Steam.

## Goldberg

**Apply / Remove Goldberg** swaps the game's `steam_api` libraries for the
[Goldberg Steam Emulator](https://gitlab.com/nichelimux/goldberg_emulator) and
back. Use this for titles that expect an emulator rather than SLSsteam's
ownership layer. *Apply* replaces the DLLs; *Remove* restores the originals.

## Fixes

For games that need community fix files to launch:

- **Check for Fixes** — looks up available fixes for the game.
- **Online Fix** / **Generic Fix** — downloads and applies the matching fix.
- **Linux-native Fix** — applies a fix specific to native Linux builds.
- **Installed Fixes** — lists what's applied, with **Remove Fix** / **Remove
  All Fixes**.

## Remove DRM (Steamless)

**Remove DRM (Steamless)** strips SteamStub DRM from the game executable using
[Steamless](https://github.com/atom0s/Steamless) (extracted from ACCELA). It
reports back if the executable has no DRM to remove. The Steamless CLI is
downloaded on first use.

## Achievements

**Generate Achievements** creates achievement files for the game via SLScheevo.
See [Achievements](achievements.md) for setup and the bulk "sync all" option.

## Advanced options

- **Reconfigure SLSsteam** — re-applies this game's SLSsteam config (FakeAppId,
  token, DLCs) in one go.
- **Repair appmanifest** — regenerates the game's `.acf` so Steam re-recognises
  the install after it has lost track of it.

## Danger zone

- **Full Uninstall** — removes the game and all of LumaDeck's config for it
  (two-tap confirm). Optional extras: **delete compatdata** and **remove the
  Proton prefix**.

> Most users never touch the management/advanced/danger groups. Reach for them
> only when a specific game misbehaves — and see [Troubleshooting](troubleshooting.md)
> first.
