# Backend reference (developer)

One-line purpose of every module under `backend/`. The frontend reaches these
through thin wrappers in `main.py` — see [Architecture](dev-architecture.md).

| Module | Purpose |
| --- | --- |
| `api_manifest.py` | Manages the free-API manifest (`api.json`), the Hubcap key, the Ryuu cookie, Hubcap search, and credential-expiry status. |
| `ryuu_cookie.py` | Imports the Ryuu `session` cookie from Steam's CEF (Chromium) cookie store — finds the SQLite DB, decrypts the `v10` value, captures its expiry. |
| `downloads.py` | Game-manifest download flows and related utilities (async). Also per-game pin/unpin (auto-update freeze). |
| `installer.py` | Dependency installer — checks and installs SLSsteam, CloudRedirect and the .NET runtime (via headcrab + dotnet.py). |
| `slssteam_ops.py` | SLSsteam config operations: FakeAppId, GameToken, DLCs, PlayStatus, Uninstall. |
| `slssteam_config.py` | Read/write helpers for SLSsteam's config file. |
| `headcrab_compat.py` | Headcrab build-ID compatibility check against the current Steam client. |
| `fixes.py` | Community game-fix lookup, application and removal (async). |
| `goldberg.py` | Goldberg Steam Emulator management (apply/remove). |
| `steamless.py` | Steamless DRM removal — runs the bundled `Steamless.CLI` (.NET 9) from `backend/deps/Steamless/`. |
| `achievements.py` | SLScheevo achievement generation. |
| `workshop.py` | Workshop item downloads via DepotDownloaderMod (async). |
| `self_update.py` | In-plugin self-update from GitHub releases (#23). |
| `update_checks.py` | GitHub Releases API client for component update checks. |
| `dotnet.py` | Auto-installs the .NET 9 runtime when missing. |
| `steam_utils.py` | Steam-related utilities (libraries, install paths, AppID detection) shared across modules. |
| `http_client.py` | Shared async HTTP client built on the Python stdlib (no external deps). |
| `config.py` | Central configuration constants for the backend. |
| `paths.py` | Path resolution (plugin data dir, Steam roots, etc.). |
| `subprocess_env.py` | Subprocess environment helper (running tools as the `deck` user, etc.). |
| `utils.py` | Generic file/data helpers. |

> Backend methods return a **dict**; the `main.py` wrapper serialises it to a
> JSON string with `_j(...)`. Keep that contract when adding methods.
