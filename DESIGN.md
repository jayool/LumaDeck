# LumaDeck — Decky Loader Plugin

## Overview

LumaDeck is a Decky Loader plugin for Steam Deck Game Mode that lets users
install and manage games that have been "purchased" through SLSsteam — i.e.
games whose ownership SLSsteam injects, served via the standard Steam
client. It is a **fork of [DeckTools](https://github.com/lopesleo/DeckTools)
by lopesleo**, sharing most of its frontend and configuration code, but
replaces the download backend so Steam itself fetches the game payload
natively, with [lumalinux](https://github.com/jayool/lumalinux) hooks
intercepting depot-key and manifest-request calls inside `steamclient.so`.

## Understanding Summary

- **What**: A Decky plugin that mirrors what LuaToolsLinux does in Desktop
  Mode, but in Game Mode and with Steam doing the actual download.
- **Why**: LuaToolsLinux only runs in Desktop Mode (via Millennium).
  DeckTools filled the Game Mode gap using DepotDownloaderMod (.NET CLI).
  LumaDeck keeps the Game Mode UX but routes the download through Steam
  itself, so the on-disk layout, progress UI, and updates work the way a
  normal owned title does.
- **For whom**: Steam Deck users running SLSsteam + lumalinux (and
  optionally CloudRedirect / ACCELA for the auxiliary features).
- **Main flow**: User opens the QAM, picks a game (manually by AppID, by
  search, or via the auto-detected Steam Store page), taps Install. The
  plugin fetches the manifest zip from Hubcap/Ryuu/etc., hands it to
  `steamidra_lite.py` from the lumalinux project, and triggers
  `steam -shutdown`. SteamOS Game Mode relaunches Steam, which then
  downloads the game natively while the lumalinux hooks serve depot keys
  and manifest request codes.
- **Scope**: Game Mode plugin. Desktop Mode users have other tools
  (LuaToolsLinux, SFF, ACCELA standalone).

## Architecture

### Stack

- **Backend**: Python (Decky native runtime), invoked async by Decky.
- **Frontend**: TypeScript + React via `@decky/api` / `@decky/ui`.
- **Download executor**: Steam native, hooked by lumalinux. The plugin
  itself does NOT extract a depot downloader binary at install time.

### Project Structure

```
LumaDeck/
├── plugin.json
├── main.py                          # Decky entrypoint — Plugin class exposes
│                                    # ~70 async methods that wrap backend calls
├── backend/
│   ├── api_manifest.py              # Hubcap/Ryuu API client, depot snapshot,
│   │                                # update-check helpers
│   ├── downloads.py                 # _download_zip_for_app + _process_and_
│   │                                # install_lua. DDL pipeline kept as DEAD
│   │                                # CODE blocks A/B for rollback
│   ├── steam_utils.py               # libraryfolders/.acf parsing, install
│   │                                # path resolution, compat tool override
│   ├── slssteam_config.py           # config.yaml read/write (flat keys)
│   ├── slssteam_ops.py              # AdditionalApps / tokens / DLC entries /
│   │                                # uninstall_game_full / Headcrab repair
│   ├── achievements.py              # SLScheevo integration
│   ├── fixes.py                     # Community fixes (online-fix etc.)
│   ├── goldberg.py                  # Goldberg emulator toggle (uses ACCELA's
│   │                                # bundled DLLs)
│   ├── steamless.py                 # Steam DRM remover (uses ACCELA's
│   │                                # bundled .NET binary)
│   ├── workshop.py                  # Workshop downloader via DDM (separate
│   │                                # binary lookup from the dead-code DDL)
│   ├── paths.py                     # Steam/SLSsteam/ACCELA/lumalinux/
│   │                                # CloudRedirect path detection; SLSsteam
│   │                                # auto-injection via /usr/bin/steam
│   ├── installer.py                 # check_dependencies + enter-the-wired
│   │                                # bootstrap
│   ├── http_client.py               # urllib-backed async client (no httpx
│   │                                # runtime dep)
│   ├── utils.py                     # File / JSON helpers
│   └── config.py                    # URL + filename constants
├── src/
│   ├── index.tsx                    # definePlugin + library page patch
│   ├── api.ts                       # call() wrappers (1:1 with main.py
│   │                                # endpoints)
│   ├── routes.ts                    # /lumadeck/* router paths
│   ├── i18n.ts                      # EN + PT-BR strings, useT hook
│   ├── pages/
│   │   ├── GameList.tsx             # Main screen
│   │   ├── GameDetail.tsx           # Per-game actions
│   │   ├── Downloads.tsx            # Active download tracking
│   │   └── Settings.tsx             # API keys, deps, SLSsteam toggles
│   └── components/
│       ├── GameCard.tsx
│       ├── AppPageButton.tsx        # Injected into Steam library page
│       ├── ProgressBar.tsx
│       ├── ActionButton.tsx
│       ├── LibraryPickerModal.tsx
│       └── TextInputButton.tsx
├── package.json
└── tsconfig.json
```

### Communication

Frontend ↔ Backend via Decky's `call<TArgs, TResult>("function_name", args)`.
Every backend method returns a JSON string; `parseResult()` in `src/api.ts`
deserialises it.

## Data Flow

### 1. Game Detection

Backend scans:
- `{steam_root}/steamapps/appmanifest_*.acf` — games Steam already
  recognises (via SLSsteam ownership injection).
- `~/.config/lumalinux/keys.txt` — games this plugin (or
  `steamidra_lite.py` invoked manually) registered with the lumalinux
  hooks.
- `{steam_root}/config/stplug-in/*.lua` — legacy / SteaMidra-style
  detection (kept because the plugin's `has_lua_for_app` semantics now
  cover both paths).
- `loadedappids.txt` — historical record of AppIDs the plugin touched.

Per-game state: `installed`, `manifest available`, `pending`.

### 2. Manifest Auto-Discovery

```
AppID → iterate enabled APIs from api.json
  → Hubcap: GET https://hubcapmanifest.com/api/v1/manifest/<appid>
            Authorization: Bearer <api_key>
            (legacy ?api_key=... in URL is rewritten to header so the key
             doesn't end up in logs)
  → Ryuu: GET with session cookie
  → Sushi / Spinoza / Forced Ryu: GitHub repo archives
  → Response: ZIP containing .manifest files + a .lua
```

API fallback chain. `api.json` is fetched from Star123451's
LuaToolsLinux repo on first run; the URL list there is authoritative
upstream.

### 3. Game Install

This is where LumaDeck diverges from DeckTools.

```
plugin._download_zip_for_app(appid)
  → fetch zip from one of the APIs       (progress shown in plugin)
  → validate ZIP magic + Ryuu login check
  → _process_and_install_lua:
        extract zip to a temp directory
        optionally enrich the .lua with the Linux depot from PICS
        invoke steamidra_lite.py with --manifests-dir
            → writes keys.txt for lumalinux
            → injects DecryptionKey entries into config.vdf (inline VDF
              text editing, no vdf module dependency)
            → adds the AppID to SLSsteam's AdditionalApps
            → writes a clean .acf stub
            → copies the .lua to stplug-in/
            → drops ACCELA-compatible markers (.DepotDownloader dir +
              <accela>/depots/<appid>.depot tracker)
  → optional: add_game_dlcs (Steam Web API)
  → optional: set_compat_tool_for_app (force Proton if no Linux depot)
  → _restart_steam_delayed(delay=5)
        Steam shuts down cleanly; SteamOS Game Mode relaunches it.
        On relaunch the lumalinux hooks read the fresh keys.txt and
        Steam's native download flow takes over.
```

The legacy DDL pipeline (`_run_depot_download`,
`_extract_ddm_from_appimage`, `_create_or_update_appmanifest`, …) is
preserved in DESIGN-marked dead-code blocks in `downloads.py` so the
flow can be rolled back without re-deriving any code; nothing in the
active path imports it.

### 4. Progress Tracking

For the manifest-zip fetch (tens of MB at most): `DOWNLOAD_STATE` dict
with `status`, `bytesRead`, `totalBytes`, `currentApi`, `speed`. Frontend
polls `get_download_status(appid)`.

For the actual game download (the GBs after Steam restart):
**Steam's own library UI shows the progress**. The plugin doesn't poll
for it — duplicating the bar adds no information and would require
parsing `.acf` files on a timer.

Statuses in order: `checking → downloading → processing → installing →
configuring → restarting_steam → done`. The legacy `depot_download`
status is no longer emitted but matching UI branches are kept (clearly
marked) so a rollback is one-line.

### 5. Update Detection

Single source of truth: `~/.local/share/ACCELA/depots/<appid>.depot`,
which `steamidra_lite.py` always writes during install (commit `c0b5da0`
in lumalinux). Any tool in the ecosystem (LumaDeck install/update,
SteaMidra desktop, ASSella in Desktop Mode, the user running the script
from Konsole) writes there, so there's nothing to keep in sync.

`check_game_update(appid)` reads the file's `<main_depot>:<manifest>`,
queries SteamCMD's public API for the current public manifest GID, and
compares.

(Pendiente at the time of writing: the implementation of
`check_game_update` itself in `api_manifest.py` still uses the old
`<plugin_data>/depots/<appid>.json` snapshot path. Documented as TODO for
the downloads-pipeline pass.)

## Features

### Core (install / library)

- List of "purchased" games via SLSsteam (lumalinux keys.txt + AdditionalApps).
- Auto-fetch of manifest zips from the API matrix (Hubcap, Ryuu, Sushi,
  Spinoza, Forced Ryu).
- Native Steam download via lumalinux hooks.
- Auto-detect AppID from the Steam Store page open in Game Mode.
- Search by name backed by Steam's `ISteamApps/GetAppList/v2/` (with
  legacy applist.morrenus.xyz as fallback for backward compat).

### Game management

- FakeAppId management (480 Spacewar etc.).
- Access token management in SLSsteam `config.yaml`.
- DLC management (Steam Web API → DlcData in SLSsteam).
- Community fixes (online-fix etc.) applied directly to the install dir.
- Workshop downloader via DepotDownloaderMod (kept; the user supplies
  the binary path in Settings or copies it into `backend/`).
- SLScheevo achievements generation.
- Steamless DRM remover.
- Goldberg emulator toggle.
- Full game removal (uninstall_game_full): folder, ACF, depot manifests,
  SLSsteam entries, optional compatdata.
- Repair ACF: deletes the existing `.acf` so Steam regenerates it on
  next library refresh (replaces the DDL-era reconstruction code which
  chmod'd 0444 and would lock Steam out of its own bookkeeping).

### Configuration

- Ryuu cookie stored in `backend/data/ryuu_cookie.txt`.
- Hubcap API key in `backend/data/api.json` (URL value), moved to
  Bearer header at request time so it never lands in logs.
- Language switcher (EN / PT-BR) with `lumadeck_lang` localStorage key.
- Auto-detection of SLSsteam, lumalinux, CloudRedirect, ACCELA,
  SLScheevo, .NET runtime, dotnet path. Reported in
  Settings → Dependencies.
- Auto-injection of SLSsteam into `/usr/bin/steam` (Steam Deck
  read-only rootfs handled with `steamos-readonly disable/enable`).
- Headcrab repair flow for when SLSsteam's hash check rejects an
  updated `steamclient.so`.

## Key Paths (Linux / SteamOS)

| Component                | Path                                                                 |
| ------------------------ | -------------------------------------------------------------------- |
| Steam root               | `/home/deck/.local/share/Steam` (preferred) or `~/.steam/steam`      |
| Manifest cache           | `{steam_root}/depotcache/*.manifest`                                 |
| stplug-in luas           | `{steam_root}/config/stplug-in/<appid>.lua`                          |
| Steam `config.vdf`       | `{steam_root}/config/config.vdf`                                     |
| SLSsteam config          | `~/.config/SLSsteam/config.yaml`                                     |
| SLSsteam binary          | `~/.local/share/SLSsteam/SLSsteam.so`                                |
| lumalinux library        | `~/.local/share/lumalinux/liblumalinux.so`                           |
| lumalinux keys           | `~/.config/lumalinux/keys.txt`                                       |
| `steamidra_lite.py`      | `~/.local/share/lumalinux/tools/steamidra_lite.py`                   |
| CloudRedirect library    | `~/.local/share/CloudRedirect/cloud_redirect.so`                     |
| ACCELA root              | `~/.local/share/ACCELA/`                                             |
| ACCELA `.depot` tracker  | `~/.local/share/ACCELA/depots/<appid>.depot`                         |
| SLScheevo binary         | `~/.local/share/SLScheevo/SLScheevo/SLScheevo`                       |
| Ryuu cookie              | `{plugin_dir}/backend/data/ryuu_cookie.txt`                          |
| Free API manifest        | `{plugin_dir}/backend/data/api.json`                                 |
| Plugin's own depot cache | `{plugin_dir}/backend/data/depots/<appid>.json` (TODO: migrate to    |
|                          | reading the ACCELA `.depot` directly)                                |
| Steam launcher target    | `/usr/bin/steam`                                                     |

## UI Design

### Game List (main screen)

- Search bar.
- Manual AppID entry.
- Game cards with status indicator (managed / downloading % / pending).
- Settings + Downloads buttons.

### Game Detail (per game)

- AppID, manifest status, install path.
- Actions: Download / Update, manage DLCs / FakeAppId / token, fixes,
  Goldberg, Steamless, achievements, Workshop, Repair ACF, full
  uninstall.

### Settings

- API credentials (Ryuu cookie + Hubcap API key, masked input).
- SLSsteam toggles (PlayNotOwnedGames + verify injection +
  Headcrab repair when needed) + manual Restart Steam.
- Dependency status: ACCELA, SLSsteam, .NET, lumalinux,
  CloudRedirect (the last two added when the plugin was forked).
- Reinstall dependencies via enter-the-wired (covers
  ACCELA + .NET + SLSsteam only; lumalinux and CloudRedirect are manual).
- Language switcher (EN / PT-BR).

## Assumptions

- The Deck runs SLSsteam + lumalinux (and ideally CloudRedirect).
- `/usr/bin/steam` is the canonical Steam launcher (so SLSsteam +
  lumalinux + CloudRedirect can be added via LD_AUDIT + LD_PRELOAD).
- `steamidra_lite.py` lives under `~/.local/share/lumalinux/tools/`
  alongside `liblumalinux.so`.
- SteamOS' system `python3` is enough — the script does its own VDF
  text editing, no external `vdf` module required.
- The Hubcap / Ryuu / Sushi / Spinoza / Forced Ryu API contracts stay
  stable enough that the upstream `api.json` (in Star123451's repo) is
  kept current.
- ACCELA, when installed, ships the AppImage with the bundled binaries
  the plugin's Steamless / Goldberg / Workshop features need.

## Decision Log

| #   | Decision                                                                  | Alternatives                                       | Rationale                                                              |
| --- | ------------------------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------- |
| 1   | Flow: buy in store → list in plugin → install                             | Manual AppID; external list                        | Natural UX, integrates with SLSsteam (inherited from DeckTools)        |
| 2   | Advanced options (depot, manifest, fixes)                                 | Simple install-only button                         | Feature parity with LuaToolsLinux (inherited from DeckTools)           |
| 3   | Same API matrix as upstream (Hubcap, Ryuu, Sushi, Spinoza)                | Hubcap only; custom API                            | Already proven, dropping any of them shrinks the catalog               |
| 4   | Auto-install ACCELA + SLSsteam + .NET via enter-the-wired                 | Require pre-install                                | Inherited from DeckTools; lumalinux + CloudRedirect remain manual      |
| 5   | Hierarchical menu (list → detail)                                         | Single screen; tabs                                | Best use of QAM space                                                  |
| 6   | **Steam native install via lumalinux hooks** instead of DDL               | Keep DDL; offer both as a toggle                   | Disk layout identical to a normal install; updates handled by Steam; progress shown in Steam library |
| 7   | Port DeckTools' backend instead of writing the plugin from scratch        | Rewrite; shell wrapper                             | DeckTools' frontend / SLSsteam ops / fixes / achievements are exactly what we want; only the download engine needed changing |
| 8   | Reuse existing DeckTools / LuaToolsLinux configs (`api.json`, cookies)    | Re-prompt the user; isolated config                | Avoids rework for existing users                                       |
| 9   | Game Mode only                                                            | Game Mode + Desktop                                | Clear scope (Desktop has SFF / ASSella)                                |
| 10  | DDL legacy pipeline kept as **DEAD CODE blocks** in `downloads.py`        | Delete it; move to a separate file                 | Single-file rollback if the new flow ever hits a blocker; markers make it clear it's parked, not abandoned |
| 11  | Single source of truth for update detection: ACCELA `.depot` file        | Plugin's own `<plugin_data>/depots/*.json` snapshot| Whichever tool in the ecosystem updates a game (LumaDeck, ASSella, the script from Konsole) writes the same `.depot`, so no sync needed |
| 12  | repair_appmanifest now **deletes** the `.acf` instead of reconstructing it | Keep the legacy reconstruction                     | The legacy code chmod'd the new .acf to 0444 so Steam couldn't update it; in LumaDeck Steam owns the .acf and we need it writable |
| 13  | Bearer header for Hubcap API key, never the URL                           | Keep `?api_key=` in URL                            | Prevents API key leaks in log files. Backports upstream DeckTools commit d557f2a |
| 14  | Frontend routes moved from `/decktools/*` to `/lumadeck/*`                | Keep `/decktools/*`                                | Avoids router-namespace collision if both forks are installed side by side |
| 15  | Identity strings + i18n keys renamed (DeckTools → LumaDeck, Morrenus → Hubcap, addedViaDeckTools → addedViaLumaDeck) | Leave legacy names                                 | Eliminates confusion in QAM, logs, localStorage key, badges; matches the upstream API rename |
