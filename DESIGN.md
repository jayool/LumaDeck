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
│   ├── slssteam_version.py          # which SLSsteam release is installed
│   │                                # (recorded tag, else derived floor)
│   ├── slssteam_ops.py              # AdditionalApps / tokens / DLC entries /
│   │                                # uninstall_game_full / Headcrab repair
│   ├── achievements.py              # Achievement schema via Steam Web API
│   │                                # (UI hidden; SLSsteam does it natively)
│   ├── fixes.py                     # Community fixes (online-fix etc.)
│   ├── goldberg.py                  # Goldberg emulator toggle (uses the
│   │                                # bundled backend/deps/Goldberg DLLs)
│   ├── steamless.py                 # Steam DRM remover (runs the bundled
│   │                                # backend/deps/Steamless .NET CLI)
│   ├── paths.py                     # Steam/SLSsteam/ACCELA/lumalinux/
│   │                                # CloudRedirect path detection; wrapper
│   │                                # coverage + Game Mode drop-in self-heal
│   ├── installer.py                 # runs lumalinux setup.sh (wrapper model):
│   │                                # SLSsteam + CloudRedirect + lumalinux + .NET
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
            → resets the .acf error state (only if Steam already wrote one)
            → copies the .lua to stplug-in/
        It does NOT write an appmanifest. Steam creates that when the user
        presses Install, in whichever library they pick — see decision 17.
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

The legacy DDL pipeline (DepotDownloaderMod extraction/execution, `.acf`
writing, and the Bifrost launcher-path config) has been **removed** from
`downloads.py` — it was unreachable from the Steam-native flow. The two
helpers that `slssteam_ops` still reuses (`_fetch_installdir_from_api`
and `_parse_lua_depots`) were kept as live utilities.

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
- Achievements: schema generation via the Steam Web API (code present but
  UI hidden — SLSsteam handles achievements natively).
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
  .NET runtime, dotnet path. Reported in Settings → Components.
- Injection via lumalinux's launch **wrapper**
  (`~/.local/share/SLSsteam/path/steam`), reached by patched `.desktop`
  (Desktop), a PATH drop-in (terminals) and a systemd drop-in on
  `steam-launcher.service` (Game Mode). `steam.sh` / `/usr/bin/steam`
  stay vanilla.
- Break-recovery downgrade (`downgrade.sh`, Desktop-only) for when a
  Steam update outpaces the hooks; then `setup.sh` re-establishes the
  wrapper.

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
| ACCELA `.depot` tracker  | `~/.local/share/ACCELA/depots/<appid>.depot` — READ-ONLY to us now;  |
|                          | we stopped writing it with the `.acf` stub (decision 17)            |
| Injection wrapper        | `~/.local/share/SLSsteam/path/steam`                                |
| Game Mode launcher       | `~/.local/share/SLSsteam/lumalinux-steam-launcher`                  |
| Game Mode drop-in        | `~/.config/systemd/user/steam-launcher.service.d/lumalinux.conf`    |
| Ryuu cookie              | `{plugin_dir}/backend/data/ryuu_cookie.txt`                          |
| Free API manifest        | `{plugin_dir}/backend/data/api.json`                                 |
| Plugin's own depot cache | `{plugin_dir}/backend/data/depots/<appid>.json`                      |
| Real Steam (left vanilla)| `/usr/bin/steam` · `steam.sh` (not patched)                         |

## UI Design

### Game List (main screen)

- Search bar.
- Manual AppID entry.
- Game cards with status indicator (managed / downloading % / pending).
- Settings + Downloads buttons.

### Game Detail (per game)

- AppID, manifest status, install path.
- Actions: Download / Update, manage DLCs / FakeAppId / token, fixes,
  Goldberg, Steamless, Repair ACF, full uninstall.

### Settings

- API credentials (Ryuu cookie + Hubcap API key, masked input).
- SLSsteam toggles (PlayNotOwnedGames + verify injection) + manual
  Restart Steam.
- Dependency status: SLSsteam, CloudRedirect, .NET, lumalinux
  (CloudRedirect + lumalinux added when the plugin was forked).
- Reinstall components via lumalinux `setup.sh` — one wrapper-model run
  installs SLSsteam + CloudRedirect + netsock + lumalinux + .NET.
- Language switcher (EN / PT-BR).

## Assumptions

- The Deck runs SLSsteam + lumalinux (and ideally CloudRedirect).
- Steam is launched through lumalinux's wrapper
  (`~/.local/share/SLSsteam/path/steam`), which exports LD_AUDIT (SLSsteam)
  + LD_PRELOAD (CloudRedirect + lumalinux) and execs the real Steam;
  `steam.sh` / `/usr/bin/steam` stay vanilla.
- `steamidra_lite.py` lives under `~/.local/share/lumalinux/tools/`
  alongside `liblumalinux.so`.
- SteamOS' system `python3` is enough — the script does its own VDF
  text editing, no external `vdf` module required.
- The Hubcap / Ryuu / Sushi / Spinoza / Forced Ryu API contracts stay
  stable enough that the upstream `api.json` (in Star123451's repo) is
  kept current.
- Steamless and Goldberg binaries ship bundled inside the plugin
  (`backend/deps/Steamless`, `backend/deps/Goldberg`); only .NET 9 is
  fetched on demand.

## Decision Log

| #   | Decision                                                                  | Alternatives                                       | Rationale                                                              |
| --- | ------------------------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------- |
| 1   | Flow: buy in store → list in plugin → install                             | Manual AppID; external list                        | Natural UX, integrates with SLSsteam (inherited from DeckTools)        |
| 2   | Advanced options (depot, manifest, fixes)                                 | Simple install-only button                         | Feature parity with LuaToolsLinux (inherited from DeckTools)           |
| 3   | Same API matrix as upstream (Hubcap, Ryuu, Sushi, Spinoza)                | Hubcap only; custom API                            | Already proven, dropping any of them shrinks the catalog               |
| 4   | Auto-install the whole stack via lumalinux `setup.sh` (wrapper model)     | Require pre-install; headcrab               | One idempotent `setup.sh` run installs SLSsteam + CloudRedirect + netsock + lumalinux + .NET and writes the injection wrapper — no headcrab, no `steam.sh` patch, no per-step ordering |
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
| 17  | Adding a game writes no `appmanifest` and no ACCELA markers — Steam writes the manifest on Install | Seed a stub `.acf` (and mark for ACCELA off it) | The stub was inherited from the DepotDownloaderMod era, where WE placed the files. With native downloads Steam writes its own manifest in the library the user picks, so ours became an ORPHAN in the root that made Steam show an installed game as NOT INSTALLED (issue #41). Measured both ways on a clean SteamOS: with the stub and without it the button reads "Install" either way, so it bought nothing. The ACCELA markers were derived from that stub's `installdir` and went with it — nothing calls `--accela-mark` any more (v0.7.4) |
| 18  | Every "is this game installed / where is it" question reads **all** libraries, via one `_library_entries()` | Read `steam_root` only, as three separate parses did | A game's `.acf` lives in the library it was installed into, so a root-only read is wrong for anything on an SD card or a second partition: the grid greyed out installed games (D2) and the error-state patch silently skipped them (D1). The three independent parses of `libraryfolders.vdf` had already drifted apart — one of them `break`ing out of the loop left its own fallback list half-built |
| 19  | Read **both** copies of `libraryfolders.vdf` (`steamapps/` and `config/`) and union them | Read only the one Steam loads | Steam loads the `steamapps/` copy — its own `content_log.txt` says so — and keeps `config/` identical. A union means neither copy can hide a library from us, and a dead entry surviving in one is harmless because entries with no `steamapps/` under them are dropped (the file outlives the drive it names, and a popped SD card leaves its mount point behind as an empty directory) |
| 20  | Orphan stubs already on disk are swept **automatically**, once per plugin load | Ship a manual "clean up" button, or leave them | The stub is invisible to the user and its symptom (an installed game re-downloading itself) doesn't point at it, so a button nobody knows to press fixes nobody. Safe because a stub only goes when a REAL manifest for the same appid exists in a DIFFERENT library — redundant by construction — with the shape read from the file at deletion, never from bookkeeping. A lone stub with no real manifest anywhere is deliberately left: it is only cosmetic, and there is no way to prove it is ours. Kill switch: `LUMA_NO_ACF_SWEEP` or `~/.config/lumalinux/no_acf_sweep` |
| 21  | A rejected LuaTools session is **marked**, not deleted, and only a definite 4xx counts | Delete the session on any failure | A lone 401 can be Cloudflare having a bad minute, and deleting also bins a refresh token that may still work. Marking survives a restart (it lives in the session file) and any call that succeeds clears it. Scoping it to 4xx keeps an offline Deck from nagging for a re-login it could not complete anyway |
| 22  | Deleting a credential also clears its settings-dir mirror                  | Delete the credential's own file only              | The mirror is read back on every plugin load, so removing just the file left the delete to be undone by the next Steam restart — a LuaTools logout handed the user back the session they had discarded (v0.7.5). `_mirror_cred` merges only non-empty values, so clearing needs its own `_forget_cred` |
