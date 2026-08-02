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
| **C. Online doesn't connect** | Runs solo, multiplayer/co-op won't connect | **netsock** (native, no crack), Online Fix (Unsteam / OnlineFix), perondepot |

Everything else (Tested / Extra Steps / Unstable / voices38 / Ryuu) is a quality
label or a source name, **not** a different kind of fix.

The hard part on the Steam Deck is not downloading the fix — it is making
**Proton load it**. A fix that ships Windows DLLs is ignored under Proton unless
Wine is told to load the native DLL (`WINEDLLOVERRIDES`) or Play is redirected to
a shipped launcher. Only **luatools-moon** does this among the tools surveyed;
LumaDeck now does it too (see "Override" below).

## LumaDeck's fixes (what each does)

Two Game Detail tabs carry fixes:

- **Fixes & Repairs**: the **non-online** LuaTools catalogue (crack / Denuvo),
  **Fixes** (Steamless / Goldberg), and **Repairs** (install/account plumbing).
- **Online Fixes**: the **online** LuaTools catalogue (its own "Check for Online
  Fixes"), then a **Native Online** control — the crack-free 480 + netsock route
  (see "Online multiplayer" below).

The split between the two catalogues is a tag filter: an entry tagged `online`
goes to the Online Fixes tab, the rest stay in Fixes & Repairs. Both tabs share
the same loaded listing and the same per-entry rendering; only the filter and the
check-button label differ. (There is no longer a separate Game Management tab —
it was only a FakeAppId control; the 480 online case is now the Native Online
control, and setting an arbitrary FakeAppId lives in Settings.)

### Block: LuaTools Fixes (the catalogue)

Not fixed buttons — a **catalogue**, shown across the two tabs above (non-online
here, online in the Online Fixes tab). "Check for Fixes" loads the public LuaTools
listing for the appid; each entry then renders its own actions.

| Control | What it does | Source / origin | File treatment |
|---|---|---|---|
| **Check for Fixes** | Loads the LuaTools catalogue for the appid (public; no login). Downloads nothing. | `list_luatools_fixes` → `/api/denuvo/fixes?appid=` | none |
| **Apply fix** (per catalogue entry) | Downloads + applies that entry's zip (crack / online / Denuvo — problem A or C). | `download_luatools_fix` → the entry's signed URL → the same extract pipeline as `apply_game_fix` | extract into the game dir, overwriting. Logs a `[FIX]` block in `luatools-fix-log-{appid}.log`. **If the zip ships an `OnlineFix.ini` with a `FakeAppId`, it is an online fix → also registers the FakeAppId in SLSsteam and enables netsock (see below).** |
| **Install the game version this fix needs** (per entry, when it has one) | Pins the SLSsteam ManifestId so Steam (re)downloads the build the fix targets. | `download_luatools_fix` slot=`manifest` | no game-dir writes; user restarts Steam + re-downloads |
| **Installed Fixes** | Lists applied fixes (from the log) with per-fix / all remove. | `get_installed_fixes` | un-fix deletes the fix's files, drops its `[FIX]` block, and removes any FakeAppId / netsock it set (see below) |

### Block: Fixes (Steamless / Goldberg — local cracks, not the catalogue)

| Button | What it does | Source / origin | File treatment |
|---|---|---|---|
| **Remove Steam DRM** (Steamless) | Unpacks the SteamStub DRM shell from the game's `.exe` (problem B). | `Steamless.CLI` (atom0s), bundled in the plugin (`backend/deps/Steamless/`); needs .NET | runs Steamless on each `.exe`, keeps `.original.exe`, swaps the unpacked exe in |
| **Apply Goldberg** | Steam emulator: fakes ownership + offline achievements (problem A). Overlaps SLSsteam, so use only when SLSsteam isn't enough. | gbe_fork (Detanup01), bundled in the plugin (`backend/deps/Goldberg/`) | renames game `steam_api(64).dll` to `.valve`, drops Goldberg's + `steam_settings/` + `steam_appid.txt` |

### Block: Repairs (plumbing, NOT cracks)

| Button | What it does | Source | Notes |
|---|---|---|---|
| **Fix Linux Permissions** | `chown deck:deck` + `chmod 755` over the game dir. For native Linux games that won't start (Decky downloads as root, Steam runs as deck). | ours | not Proton-related |
| **Reconfigure SLSsteam** | Re-adds the game's token, DLCs and depot decryption keys to the SLSsteam config, read from the installed `.lua`. | ours | rescue when the config drifts from the installed Lua |
| **Repair Appmanifest** | Deletes `appmanifest_{appid}.acf` across all libraries so Steam rebuilds it. | ours | does **not** restart Steam; user restarts afterwards |

## Override (Proton): how DLL fixes are made to load

After applying **or** removing a fix, LumaDeck recomputes the game's launch
options from the fix log and writes them via `SteamClient.Apps.SetAppLaunchOptions`:

`_merge_launch_options` composes up to **two independent managed pieces** on the
one launch-options line, so an online fix and netsock coexist:

- **netsock** (native online, when enabled for the game) → an `LD_AUDIT="…netsock.so"`
  prefix. Emitted as a **single** colon-separated `LD_AUDIT` (a second assignment
  would just override the first at runtime); a user's own unrelated `LD_AUDIT`
  entries are kept and merged after netsock, ours is de-duped.
- **the fix's DLLs / launcher**:
  - Fix dropped **DLLs** (online fixes, some cracks) → `WINEDLLOVERRIDES="dll=n,b;..."`.
  - Fix dropped a **launcher** (basename contains `launcher`, e.g. `FC25 Launcher.exe`) →
    `"<abs launcher>"`, and the DLL override is skipped (launcher takes precedence).
  - Fix is **exe-only** (e.g. CoD4's `iw3sp.exe`) → no override; the swapped exe runs directly.

Both present → `LD_AUDIT="…netsock.so" WINEDLLOVERRIDES="OnlineFix64=n,b" %command%`.
`LD_AUDIT` is a **native** linker var (acts before Proton's container); `WINEDLLOVERRIDES`
is read by Proton/Wine inside it — different layers, same launch line.

- **Removing** a fix drops its block from the log, so the override is recomputed
  down to the remaining fixes' DLLs (none left → stripped clean). The netsock
  `LD_AUDIT` is re-derived from its per-game marker so it survives the recompute.
  User wrappers like `mangohud` are preserved.

Backend: `fixes.compute_fix_launch_options` + `steam_utils.get_app_launch_options`.
Goldberg is intentionally NOT wired into the override (in-place steam_api64
replacement that Proton loads without forcing).

## Online multiplayer: 480, netsock, and the anti-cheat gate

Online play (problem C) rests on faking a networking-authorized appid. **480 =
Spacewar**, the Steam SDK sample everyone is "authorized" for, so all online
routes route through it. There are three, and the first two need **no crack**:

| Route | What it needs | When |
|---|---|---|
| **Native P2P** | SLSsteam `FakeAppId 480` only | classic Steamworks P2P lobbies |
| **Native SNS** | `FakeAppId 480` + **netsock** (`LD_AUDIT`) | games using SteamNetworkingSockets (Lethal Company, Enshrouded, Teardown…) |
| **OnlineFix crack** | the online-fix zip's DLLs (`WINEDLLOVERRIDES`) + `FakeAppId 480` | fallback when native doesn't connect |

We don't try to tell native-P2P from native-SNS: netsock is **non-destructive and
inert where unneeded** (it patches a steamclient cert function SNS games hit and
fails gracefully with `"pattern not found"` otherwise), so **480 + netsock are
applied together** as the native route.

**netsock** = `yesyes0649/steamnetsock-patch`. headcrab already downloads it on
every dependency install to `~/.config/SLSsteam/tools/netsock/netsock.so`; we do
not bundle it. Launch option (per its README): `LD_AUDIT="$HOME/.config/SLSsteam/tools/netsock/netsock.so" %command%`.

### How each is applied, and the gate that decides

- **From an online fix (catalogue "Apply fix"):** the definitive "this is an
  online fix" signal is that the zip ships an **`OnlineFix.ini` with a `FakeAppId`**
  in its `[Main]` section. On extract, `_apply_onlinefix_fakeappid` reads it and
  registers that id in SLSsteam (logged as a `FakeAppId:` line in the `[FIX]`
  block). Denuvo / single-player / generic cracks have **no such `.ini`** → they
  get **neither 480 nor netsock**; only their files are copied.
- **Native route with no catalogue fix:** the **Native Online** control in the
  Online Fixes tab. Enabling it (game installed) sets FakeAppId 480 and netsock;
  disabling drops netsock (480 is left, it's inert). This is how an SNS game that
  has no LuaTools online-fix still gets the crack-free route. Backend:
  `enable_native_online` / `disable_native_online`.
- **netsock rides the 480**, with two extra gates: it is only set when the
  **`netsock.so` is on disk** and the game has **no anti-cheat**.

### The anti-cheat gate

netsock **scans and modifies game memory**, which any anti-cheat (EasyAntiCheat,
BattlEye) flags → ban. So a bounded scan of the install dir for their markers is
a hard stop: **netsock is never applied to an anti-cheat game.** (The crack and
the bare 480 are config/file-level, not memory scans, so they aren't gated on
this — only netsock is.)

### Lifecycle

Set together, removed together. Un-fixing an online fix (or removing the 480
toggle) drops the FakeAppId **and** the netsock marker, and the launch-options
recompute strips the `LD_AUDIT` with it — only when no surviving fix still needs
the FakeAppId, and never touching a manually-set entry.

Backend: `fixes._apply_onlinefix_fakeappid`, `_parse_onlinefix_ini`,
`enable_native_online` / `disable_native_online`, `_has_anticheat`,
`_netsock_so_installed`, the netsock marker `luatools-netsock-{appid}.on`.

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
