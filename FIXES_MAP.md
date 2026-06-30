# Fixes map

Reference for what LumaDeck's "fixes" actually are, where they come from, how
they are applied, and how they relate to the other tools in the same ecosystem
(luatools-moon, SteaMidra/SFF, ACCELA/ASSella, LuaToolsLinux). Built from a
code-level read of all of them.

> A "fix" is **not only DRM removal**. It is anything that makes a downloaded
> (non-owned) copy behave like an owned one. SLSsteam already fakes ownership at
> the Steam-client layer; a fix patches the game itself for the cases SLSsteam
> can't cover.

## The 3 problems a fix can solve

| Problem | Symptom | Tools that attack it |
|---|---|---|
| **A. Won't launch (ownership / DRM check)** | Crashes on start, "you don't own this" | Generic Fix (crack), Goldberg, Unsteam, Steamless (for SteamStub) |
| **B. Won't launch (.exe wrapped in SteamStub)** | Same, but caused by Steam's own DRM shell | Steamless |
| **C. Online doesn't connect** | Runs solo, multiplayer/co-op won't connect | Online Fix (Unsteam / OnlineFix), perondepot |

Everything else (Tested / Extra Steps / Unstable / voices38 / Ryuu) is a quality
label or a source name, **not** a different kind of fix.

The hard part on the Steam Deck is not downloading the fix — it is making
**Proton load it**. A fix that ships Windows DLLs is ignored under Proton unless
Wine is told to load the native DLL (`WINEDLLOVERRIDES`) or Play is redirected to
a shipped launcher. Only **luatools-moon** does this among the tools surveyed;
LumaDeck now does it too (see "Override" below).

## LumaDeck's fixes (what each does)

The Game Detail → **Fixes** tab, after the v0.3.64 reorg, has two blocks.

### Block: Game Fixes (cracks)

| Button | What it does | Source / origin | File treatment |
|---|---|---|---|
| **Check for Fixes** | Probes whether a fix exists for the appid. Downloads nothing. | `HEAD files.luatools.work/GameBypasses/{appid}.zip` and `/OnlineFix1/{appid}.zip` | none |
| **Apply Crack / Bypass** (Generic Fix) | Crack so the game launches (problem A). | `files.luatools.work/GameBypasses/{appid}.zip` (luatools CDN) | download zip → extract into the game dir, overwriting. Logs a `[FIX]` block in `luatools-fix-log-{appid}.log`. |
| **Apply Online Fix** (Unsteam) | Emulates the network so cracked copies play together (problem C). | `files.luatools.work/OnlineFix1/{appid}.zip` | same extract + patches `unsteam.ini`'s `<appid>` placeholder |
| **Remove Steam DRM** (Steamless) | Unpacks the SteamStub DRM shell from the game's `.exe` (problem B). | `Steamless.CLI` (atom0s), bundled in **ACCELA** (`bin/src/deps/Steamless/`); needs .NET | runs Steamless on each `.exe`, in place, keeps `.exe.bak` |
| **Apply Goldberg** | Steam emulator: fakes ownership + offline achievements (problem A). Overlaps SLSsteam, so use only when SLSsteam isn't enough. | gbe_fork (Detanup01), bundled in **ACCELA** (`bin/src/deps/Goldberg/`) | renames game `steam_api(64).dll` to `.valve`, drops Goldberg's + `steam_settings/` + `steam_appid.txt` |
| **Installed Fixes** | Lists applied CDN fixes (from the log) with per-fix / all remove. | — | un-fix deletes the fix's files and rewrites the log |

### Block: Repairs (plumbing, NOT cracks)

| Button | What it does | Source | Notes |
|---|---|---|---|
| **Fix Linux Permissions** | `chown deck:deck` + `chmod 755` over the game dir. For native Linux games that won't start (Decky downloads as root, Steam runs as deck). | ours | not Proton-related |
| **Reconfigure SLSsteam** | Re-adds the game's token, DLCs and depot decryption keys to the SLSsteam config, read from the installed `.lua`. | ours | rescue when the config drifts from the installed Lua |
| **Repair Appmanifest** | Deletes `appmanifest_{appid}.acf` across all libraries so Steam rebuilds it. | ours | does **not** restart Steam; user restarts afterwards |

## Override (Proton): how DLL fixes are made to load

After applying **or** removing a fix, LumaDeck recomputes the game's launch
options from the fix log and writes them via `SteamClient.Apps.SetAppLaunchOptions`:

- Fix dropped **DLLs** (online fixes, some cracks) → `WINEDLLOVERRIDES="dll=n,b;..." %command%`.
- Fix dropped a **launcher** (basename contains `launcher`, e.g. `FC25 Launcher.exe`) →
  `"<abs launcher>" %command%`, and the DLL override is skipped (launcher takes precedence).
- Fix is **exe-only** (e.g. CoD4's `iw3sp.exe`) → no override; the swapped exe runs directly.
- **Removing** a fix drops its block from the log, so the override is recomputed
  down to the remaining fixes' DLLs (none left → stripped clean). User wrappers
  like `mangohud` are preserved.

Backend: `fixes.compute_fix_launch_options` + `steam_utils.get_app_launch_options`.
Goldberg is intentionally NOT wired into the override (in-place steam_api64
replacement that Proton loads without forcing).

## Two real fix examples (verified by opening the zips)

| Game | Zip contents | Type | Needs override? |
|---|---|---|---|
| **Call of Duty 4** (7940) | a single `iw3sp.exe` | crack = replacement exe (no Steam markers; CoD4 used `cl_cdkey`, not SteamStub) | No — exe swap runs directly |
| **Baldur's Gate 3** (1086940) | `steam_api64.dll` + `OnlineFix.ini` (`RealAppId=1086940`, `FakeAppId=480`, DLC unlock) | online fix = OnlineFix64 emulator | Yes — DLL, needs `WINEDLLOVERRIDES` |

BG3 has no DRM yet still has a fix: the fix is for **online co-op + DLC + achievements**,
not DRM. "Fix" ≠ "DRM removal".

## The ecosystem (where fixes come from)

One library, several taps:

- **Makers:** online-fix.me (online fixes), Unsteam (cs.rin.ru), voices38 (cracks).
- **Ryuu** aggregates makers into `generator.ryuu.lol/fixes` (HTML catalogue,
  ~500 games, badges: bypass / online / tested / extra_steps / unstable).
- **lua.tools/fixes** (web for humans) + **files.luatools.work** (CDN for plugins)
  serve the same library; lua.tools tags some entries "sourced from Ryuu".
- **LumaDeck** fetches fixes only from `files.luatools.work` by appid. It uses
  Ryuu only as a **manifest** source (to add games), never for fixes.

Note: `generator.ryuu.lol` serves two different things — `/fixes` (the crack
catalogue, used by luatools-moon's crackfix) and `/download?...file_type=manifest`
(the manifest generator, used by SFF / LTL / LumaDeck). Don't confuse them.

## Cross-reference: our fixes vs the other tools

| Our fix | luatools-moon | SteaMidra / SFF | ACCELA / ASSella | LuaToolsLinux |
|---|---|---|---|---|
| **Generic Fix** | same CDN + ryuu crackfix (`generator.ryuu.lol/fixes`) | "Fixes & Bypasses" → `KoriaPolis/CrakFiles` | — | same CDN (identical code) |
| **Online Fix** | same CDN + perondepot (`api.perondepot.xyz`) | "Multiplayer Fix" (online-fix.me) + LC Online Fix | — | same CDN |
| **Goldberg** | not a tool (only a DLL heuristic) | gbe_fork + gse_fork | **the source** (`deps/Goldberg`) | via ACCELA |
| **Steamless** | — | `steamstub_unpacker.py` | **the source** (`steamless-aio.sh`) | via ACCELA |
| **Fix Linux Permissions** | partial (unset LD_* only) | — (Windows) | `chmod_resume.py` | identical code |
| **Reconfigure SLSsteam** | `slsteam.lua` | SLSsteam ID mgmt | writes `SLSsteam/config.yaml` | "Missing Keys / No licenses fix" |
| **Repair Appmanifest** | `steam_utils.lua` | "Purchase error fix" | `manifest_check_task.py` | "Purchase error fix" |
| **WINEDLLOVERRIDES override** | **yes** (`fix_overlays.lua`) — the reference | — | — | no |

Tech the others have that we don't: **HyperVisor / Denuvo cracks** (SFF, needs
Windows VBS — not viable on Deck) and **DLC unlockers** SmokeAPI / CreamAPI /
Uplay (SFF; mostly redundant with SLSsteam's DLC handling).

## Upstream origins

- Generic Fix → luatools team (curated cracks on their CDN)
- Online Fix → Unsteam (cs.rin.ru) / OnlineFix (online-fix.me)
- Goldberg → gbe_fork (Detanup01)
- Steamless → atom0s/Steamless
- Fix Linux Permissions / Reconfigure SLSsteam / Repair Appmanifest → LumaDeck (the ACCELA/SLSsteam stack)
