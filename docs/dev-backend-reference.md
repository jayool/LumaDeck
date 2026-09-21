# Backend reference (developer)

One-line purpose of every module under `backend/`. The frontend reaches these
through thin wrappers in `main.py` — see [Architecture](dev-architecture.md).

| Module | Purpose |
| --- | --- |
| `api_manifest.py` | Manages the free-API manifest (`api.json`), the Hubcap key, the Ryuu cookie, Hubcap search, and credential-expiry status. |
| `ryuu_cookie.py` | Imports the Ryuu `session` cookie from Steam's CEF (Chromium) cookie store — finds the SQLite DB, decrypts the `v10`/`v11` value, captures its expiry. |
| `cef_cdp.py` | Chrome DevTools Protocol client for Steam's CEF. Reads open store/library pages for AppID auto-detect, reads the LIVE cookie store (how the LuaTools login is captured the moment it lands, before CEF flushes it to disk), and deletes cookies on logout. |
| `downloads.py` | Game-manifest download flows and related utilities (async): the Hubcap zip install (always `steamidra_lite --pin`), the freeze toggle wrappers, and the orphan-`.acf` sweep that runs on plugin load (`sweep_orphan_stubs`, decision 20). |
| `manifests.py` | Sourcing one `<depot>_<gid>.manifest`: `depotcache/` → LumaDeck's archive (`~/.local/share/lumadeck/manifests/`) → GitHub `P-ToyStore/SteamManifestCache_Pro` (branch, then tag) → `manifest.luastools.xyz/m/<depot>/<gid>` (BetterSteamTools' donated-code archive, keyless) → Hubcap (current build only, once a day per app). Inflates the repo's "Pro" wrapper and validates depot/gid inside before writing. Also `steamcmd_app_info` (Valve's current gids per depot). |
| `pins.py` | The background job started by `main.py`. Reads lumalinux's `gmrc.json` (0.21.0+): `up` → managed games carry no pin and Steam updates them natively (the pass only archives what Steam downloads, and drops any leftover pin); `down` → every unfrozen game is pinned to its `.acf` `InstalledDepots` and marked `reason: "providers"`; absent → the 0.8 model (pin everything, move pins every 30 min from the archive / luastools / Hubcap). Every 60 s heals `depotcache/` from the archive; every 30 min checks for new keyless depots (Hubcap zip) and, while it holds games frozen, probes a provider (code + CDN check) to release them. Frozen state lives in `~/.config/lumadeck/pins.json`, with an optional `version` (build id, date, label, gids) written by whoever pins a build — the `.acf` `buildid` is never used for that label (Steam stamps Valve's current build even on a pinned older one). `mark_update_required(appid)` sets `StateFlags |= 2` in the `.acf` so Steam re-plans the game's depots at its next start: a pin change alone is invisible to Steam (measured 2026-09-21, Balatro: pin + restart → nothing; pin + verify → nothing; pin + StateFlags 6 + restart → SLSsteam substitutes the gid, GMRC gets the code, Steam downloads the Dec-2024 build). Used by the LuaTools version install on an already-installed game and by Auto-update back on. |
| `installer.py` | Runs lumalinux's `setup.sh` (the wrapper-model installer) to install/repair the whole stack — SLSsteam + CloudRedirect + netsock + lumalinux + .NET — plus dependency checks. No headcrab. |
| `components.py` | Unified per-component health + update + plugin status — the model behind the Components panel and the QAM banner. |
| `desktop_handoff.py` | Arms a one-shot Desktop autostart (Steam downgrade via `downgrade.sh` + re-inject via `setup.sh`, or a full Quick Install) and switches to Desktop, returning to Game Mode on success. |
| `steam_freeze.py` | Reads the Steam auto-update freeze/pin (`steam.cfg`) and lifts it during break-recovery catch-up (origin-based, `# lumalinux`-signed). |
| `slssteam_ops.py` | SLSsteam config operations: FakeAppId, GameToken, DLCs, PlayStatus, Uninstall. |
| `slssteam_version.py` | Which SLSsteam release is installed: the tag setup.sh recorded, else a lower bound scanned out of the binary. |
| `slssteam_schema.py` | SLSsteam config-schema reference (best-effort refresh) used for config completion. |
| `headcrab_compat.py` | Reads Headcrab's compat pin (the Steam build it supports) to gate Steam-update offers and the break-recovery downgrade. |
| `fixes.py` | Community game-fix lookup, application and removal (async). |
| `luatools_auth.py` | LuaTools account auth + the authenticated fix catalogue. Owns the session's whole life: harvest from the CEF cookie, the hourly token refresh, the rejected-session mark, restore from the settings mirror, and logout. |
| `goldberg.py` | Goldberg Steam Emulator management (apply/remove). |
| `steamless.py` | Steamless DRM removal — runs the bundled `Steamless.CLI` (.NET 9) from `backend/deps/Steamless/`. |
| `achievements.py` | Achievement-schema generation via the Steam Web API (`GetSchemaForGame`). UI hidden by default (`ACHIEVEMENTS_ENABLED=false`) — SLSsteam handles achievements natively. |
| `self_update.py` | In-plugin self-update from GitHub releases (#23). |
| `update_checks.py` | GitHub Releases API client for component update checks. |
| `dotnet.py` | Auto-installs the .NET 9 runtime when missing. |
| `steam_utils.py` | Steam-related utilities (install paths, AppID detection) shared across modules. `_library_entries()` is the one place that answers "where are the Steam libraries" — both copies of `libraryfolders.vdf`, unioned, dead entries dropped, root first (decisions 18-19). |
| `platform_info.py` | Platform/identity detection — real user / home / uid (SteamOS defaults), distro/session facts. |
| `quick_install_cli.py` | CLI entry point that runs the Quick Install as the `deck` user (used by the Desktop hand-off). |
| `http_client.py` | Shared async HTTP client built on the Python stdlib (no external deps). `get`/`head`/`post`/`stream`, httpx-compatible signatures — it replaced an httpx client and every caller kept its call sites. |
| `subprocess_env.py` | Subprocess environment helper (running tools as the `deck` user, etc.). |
| `dev.py` | Dev-only state overrides for the UI preview harness. |
| `config.py` | Central configuration constants for the backend. |
| `paths.py` | Path/identity resolution (plugin data dir, Steam roots, real-user home) and the wrapper-coverage / Game Mode drop-in self-heal. |
| `utils.py` | Generic file/data helpers. |

> Backend methods return a **dict**; the `main.py` wrapper serialises it to a
> JSON string with `_j(...)`. Keep that contract when adding methods.
