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
│   ├── api_manifest.py              # Hubcap/Ryuu API client, manifest search
│   ├── downloads.py                 # _download_zip_for_app + _process_and_
│   │                                # install_lua (Steam-native install flow)
│   ├── steam_utils.py               # libraryfolders/.acf parsing, install
│   │                                # path resolution, compat tool override
│   ├── slssteam_config.py           # config.yaml read/write (flat keys)
│   ├── slssteam_ops.py              # AdditionalApps / tokens / DLC entries /
│   │                                # uninstall_game_full / Headcrab repair
│   ├── achievements.py              # SLScheevo integration
│   ├── fixes.py                     # Community fixes (online-fix etc.)
│   ├── goldberg.py                  # Goldberg emulator toggle (uses the
│   │                                # bundled backend/deps/Goldberg DLLs)
│   ├── steamless.py                 # Steam DRM remover (runs the bundled
│   │                                # backend/deps/Steamless .NET CLI)
│   ├── workshop.py                  # Workshop downloader via DDM (its own
│   │                                # self-contained binary lookup)
│   ├── paths.py                     # Steam/SLSsteam/ACCELA/lumalinux/
│   │                                # CloudRedirect path detection; SLSsteam
│   │                                # auto-injection via /usr/bin/steam
│   ├── installer.py                 # check_dependencies + headcrab
│   │                                # bootstrap (SLSsteam + CloudRedirect)
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

The library-refresh entry point (`get_installed_lua_scripts`) doubles as the
ACCELA marker self-heal trigger — see §3 (`_ensure_accela_mark`).

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
              <accela>/depots/<appid>.depot tracker) — BEST-EFFORT here:
              at this point Steam has not downloaded the game yet, so the
              in-game .DepotDownloader marker can't take effect (ACCELA only
              lists folders that have real content). The authoritative
              marking happens later, on library refresh (see below).
  → optional: add_game_dlcs (Steam Web API)
  → optional: set_compat_tool_for_app (force Proton if no Linux depot)
  → _restart_steam_delayed(delay=5)
        Steam shuts down cleanly; SteamOS Game Mode relaunches it.
        Runs `steam -shutdown` AS THE deck USER (runuser -u deck, clean env,
        XDG_RUNTIME_DIR=/run/user/1000): the plugin runs as root, and
        `steam -shutdown` talks to the client over a per-user IPC — invoked
        as root it never reaches the deck-user Steam and silently no-ops.
        On relaunch the lumalinux hooks read the fresh keys.txt and
        Steam's native download flow takes over.
```

**ACCELA marker self-heal (post-download).** Because the install flow runs
before Steam downloads the game, the in-game `.DepotDownloader` marker can't
be placed authoritatively at install time. Instead, `get_installed_lua_scripts`
(library refresh) calls `_ensure_accela_mark` for each installed game: if the
game folder now has real content but no `.DepotDownloader`, it re-runs
`steamidra_lite --accela-mark <appid> --steam-root <path>` (HOME=/home/deck so
the marker + the `<accela>/depots/<appid>.depot` tracker land in the deck
user's tree). Idempotent and non-blocking. Requires lumalinux **v0.13.0+**:
`--accela-mark` itself landed in v0.11.0, but the install flow this self-heal
relies on (Steam actually downloading the game) only works once the package-0
finder is on by default, which happened in v0.13.0. Against an older
`steamidra_lite` the spawn no-ops (argparse error to a discarded stderr).


The legacy DDL pipeline (DepotDownloaderMod extraction/execution, `.acf`
writing, and the Bifrost launcher-path config) has been **removed** from
`downloads.py` — it was unreachable from the Steam-native flow. The two
helpers that `slssteam_ops` still reuses (`_fetch_installdir_from_api`
and `_parse_lua_depots`) were kept as live utilities. The Workshop
downloader (`workshop.py`) is a separate, self-contained use of
DepotDownloaderMod and is unaffected.

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

### 5. Updates

Updates are **Steam-native**. Games deployed unpinned (`--no-pin`) carry
`keys.txt gid=0` + commented `--setManifestid`, so Steam's own client
auto-updates them like an owned game (BuildDep/GMRC supply the manifest
request code; the per-depot key in `keys.txt` decrypts). The per-game
**Auto-Update toggle** in GameDetail is just pin/unpin; "Re-download
manifest" re-runs `steamidra_lite` to force a redeploy by hand.

The plugin's own update-*detection* badge (`check_game_update` + the
`<plugin_data>/depots/<appid>.json` snapshot helpers) was **removed**: it
was redundant with Steam's native auto-update for unpinned games and gave
false "update available" badges (its snapshot baseline went stale after a
native Steam update, which doesn't run `steamidra_lite`). The rare cases
Steam can't auto-apply (an update adds a new depot, or Valve rotates a
depot key — both surface as `Missing decryption key` / `UpdateResult=8`)
are the domain of the planned Hubcap re-deploy **watchdog** (issue #21),
which detects the stuck `.acf` directly rather than diffing manifests.

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
- Dependency status: SLSsteam, CloudRedirect, .NET, lumalinux
  (CloudRedirect + lumalinux added when the plugin was forked).
- Reinstall dependencies via headcrab (covers SLSsteam + CloudRedirect
  + .NET in one run; lumalinux is installed as Quick Install's second step).
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
- Steamless and Goldberg binaries ship bundled inside the plugin
  (`backend/deps/Steamless`, `backend/deps/Goldberg`); only .NET 9 is
  fetched on demand. The Workshop feature still needs a
  DepotDownloaderMod binary the user supplies.

## Decision Log

| #   | Decision                                                                  | Alternatives                                       | Rationale                                                              |
| --- | ------------------------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------- |
| 1   | Flow: buy in store → list in plugin → install                             | Manual AppID; external list                        | Natural UX, integrates with SLSsteam (inherited from DeckTools)        |
| 2   | Advanced options (depot, manifest, fixes)                                 | Simple install-only button                         | Feature parity with LuaToolsLinux (inherited from DeckTools)           |
| 3   | Same API matrix as upstream (Hubcap, Ryuu, Sushi, Spinoza)                | Hubcap only; custom API                            | Already proven, dropping any of them shrinks the catalog               |
| 4   | Auto-install SLSsteam + CloudRedirect + .NET via headcrab                 | Require pre-install                                | One headcrab run installs SLSsteam + CloudRedirect + the Steam downgrade; .NET via dotnet.py; lumalinux runs as Quick Install's second step |
| 5   | Hierarchical menu (list → detail)                                         | Single screen; tabs                                | Best use of QAM space                                                  |
| 6   | **Steam native install via lumalinux hooks** instead of DDL               | Keep DDL; offer both as a toggle                   | Disk layout identical to a normal install; updates handled by Steam; progress shown in Steam library |
| 7   | Port DeckTools' backend instead of writing the plugin from scratch        | Rewrite; shell wrapper                             | DeckTools' frontend / SLSsteam ops / fixes / achievements are exactly what we want; only the download engine needed changing |
| 8   | Reuse existing DeckTools / LuaToolsLinux configs (`api.json`, cookies)    | Re-prompt the user; isolated config                | Avoids rework for existing users                                       |
| 9   | Game Mode only                                                            | Game Mode + Desktop                                | Clear scope (Desktop has SFF / ASSella)                                |
| 10  | DDL legacy pipeline **removed** from `downloads.py` once install + native update were verified on Deck | Keep it parked as dead-code blocks indefinitely    | The new flow is proven (routine installs; Mina auto-updated natively), so the ~1250 dead lines were pure cognitive cost. Kept only the 2 helpers `slssteam_ops` still reuses (#6) |
| 11  | No plugin update-detection badge — updates are Steam-native (unpinned auto-update) + the #21 watchdog for stuck `.acf` | Plugin diffs a saved manifest snapshot vs SteamCMD | The snapshot went stale after Steam's own auto-update (which doesn't run `steamidra_lite`), producing false "update available" badges; Steam already handles the common case |
| 12  | repair_appmanifest now **deletes** the `.acf` instead of reconstructing it | Keep the legacy reconstruction                     | The legacy code chmod'd the new .acf to 0444 so Steam couldn't update it; in LumaDeck Steam owns the .acf and we need it writable |
| 13  | Bearer header for Hubcap API key, never the URL                           | Keep `?api_key=` in URL                            | Prevents API key leaks in log files. Backports upstream DeckTools commit d557f2a |
| 14  | Frontend routes moved from `/decktools/*` to `/lumadeck/*`                | Keep `/decktools/*`                                | Avoids router-namespace collision if both forks are installed side by side |
| 15  | Identity strings + i18n keys renamed (DeckTools → LumaDeck, Morrenus → Hubcap, addedViaDeckTools → addedViaLumaDeck) | Leave legacy names                                 | Eliminates confusion in QAM, logs, localStorage key, badges; matches the upstream API rename |
| 16  | `steam -shutdown` runs as the `deck` user (`runuser`), not root            | Call `steam -shutdown` directly (the old way)      | The plugin runs as root; `steam -shutdown` uses a per-user IPC, so as root it never reached the deck-user Steam and the restart silently no-op'd (v0.3.0 fix) |
| 17  | ACCELA `.DepotDownloader` marker created via self-heal on library refresh, not at install time | Mark at install time only                          | At install time Steam hasn't downloaded the game yet, so an in-game marker can't take effect; refresh runs `steamidra_lite --accela-mark` once content exists (v0.3.0) |
