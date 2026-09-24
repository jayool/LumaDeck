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
  Fixes"), then the **Online** toggle — the crack-free route: 480 + netsock +
  the EOS proxy, each applied by detection (see "Online multiplayer" below).

The split between the two catalogues is a tag filter: an entry tagged `online`
goes to the Online Fixes tab, the rest stay in Fixes & Repairs. Both tabs share
the same loaded listing and the same per-entry rendering; only the filter and the
check-button label differ. (There is no longer a separate Game Management tab —
it was only a FakeAppId control; the 480 online case is now the Online toggle,
and setting an arbitrary FakeAppId lives in Settings.)

### Block: LuaTools Fixes (the catalogue)

Not fixed buttons — a **catalogue**, shown across the two tabs above (non-online
here, online in the Online Fixes tab). "Check for Fixes" loads the public LuaTools
listing for the appid; each entry then renders its own actions.

| Control | What it does | Source / origin | File treatment |
|---|---|---|---|
| **Check for Fixes** | Loads the LuaTools catalogue for the appid (public; no login). Downloads nothing. | `list_luatools_fixes` → `/api/denuvo/fixes?appid=` | none |
| **Apply fix** (per catalogue entry) | Downloads + applies that entry's zip (crack / online / Denuvo — problem A or C). **One LuaTools fix per game** (see below). | `download_luatools_fix` → the entry's signed URL → the same extract pipeline as `apply_game_fix` | extract into the game dir, overwriting; originals copied to `luatools-backup-{appid}/` first (first-time copy only). Logs a `[FIX]` block in `luatools-fix-log-{appid}.log`. **If the zip ships an `OnlineFix.ini` with a `FakeAppId`, it is an online fix → also registers the FakeAppId in SLSsteam and enables netsock (see below).** Freezes the game (see "Anything in the game dir freezes the game"). |
| **Install the game version this fix needs** (per entry, when it has one) | Pins the SLSsteam ManifestId so Steam (re)downloads the build the fix targets. | `download_luatools_fix` slot=`manifest` | no game-dir writes; user restarts Steam + re-downloads |
| **Installed Fixes** | Lists applied fixes (from the log) with per-fix / all remove. | `get_installed_fixes` | un-fix deletes the fix's added files, **copies** the originals back from the backup (the backup tree is only dropped when no fix remains), drops its `[FIX]` block, and removes any FakeAppId / netsock it set (see below) |

#### One LuaTools fix per game

Two fixes on one game overlap (a generic crack and an online fix both ship a
`steam_api`, an `OnlineFix.ini`…) and the result is undefined: whichever wrote
last wins, and nothing can tell which files belong to which. So the rule is
**one LuaTools fix installed per game**, enforced at apply:

- `apply_game_fix` (and `download_luatools_fix` before it spends a signed URL)
  reads the game's `[FIX]` blocks (`installed_fix_types`). With one or more
  present and `replace` false it queues nothing and answers `{"needsReplace":
  true, "installed": ["OnlineFix"]}`.
- The UI turns that entry's "Apply fix" into **"Replace fix"** for 5 s, with
  "This game already has a fix installed: OnlineFix. Press again to replace
  it." (or "…already has 2 fixes installed. Press again to replace them." on a
  legacy install). The second press sends `replace: true`.
- With `replace` the download task first runs the normal un-fix over **all**
  blocks (phase `replacing`, "Removing the installed fix..."): originals back,
  added files gone, FakeAppId / netsock undone; then the new fix lands on a
  clean game. If the un-fix fails nothing is downloaded.
- Goldberg, Steamless and the Online toggle keep no `[FIX]` block and are not
  part of the rule.

**Restores are copies, not moves.** A legacy install may still carry two fixes
over the same file; the backup holds the pristine original from before the
first fix, and each un-fix copies it back, so the second un-fix still finds it
instead of deleting the file. The backup tree is removed with the last fix.

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

## Anything in the game dir freezes the game

Under the native model (v0.9+, a request-code provider up) an unfrozen game
updates by itself, like an owned one, and a Steam update rewrites the depot's
files: the crack's `steam_api`, Goldberg's, the Steamless-unpacked exe, the EOS
proxy all silently revert to Valve's. In the SLSsteam world this never came up
(games are downloaded pinned and never update); in LumaDeck it does. So **every
operation that writes into the game dir freezes the game** to its installed
build, with the same freeze the Auto-update toggle applies (`pins.freeze_for_files`
→ `ensure_pinned` + `set_frozen(reason="files")`):

| Operation | Freezes | Why / why not |
|---|---|---|
| Apply fix (generic, online, LuaTools catalogue) | yes, once files landed | its files replace the game's |
| LuaTools version fix | yes (already did) | pins the build the fix needs |
| Apply Goldberg | yes | replaces `steam_api` |
| Steamless | yes, when at least one exe was swapped | replaces the exe |
| Online toggle | only when eos-proxy was applied | 480 is SLSsteam config, steamnetsock-patch a launch option |
| Remove fix / Goldberg / Online | **no** | unfreezing is the user's Auto-update toggle; another fix may still be there |

A game the user already froze is left as is (its version-fix id survives); a
providers freeze (the one the local pass lifts when a provider answers) is
upgraded to the durable `files` freeze. The UI shows nothing new: the Auto-update
toggle goes off and the version line reads "Frozen", as with a manual freeze.
The frontend re-reads the pin after each of these operations (`refreshPin`).

## Online multiplayer: 480, netsock, the EOS proxy, and the Online toggle

Online play (problem C) rests on faking a networking-authorized appid. **480 =
Spacewar**, the Steam SDK sample everyone is "authorized" for, so every online
route goes through it. Four doors exist; the first three need **no crack** and
the Online toggle applies them together:

| Door | What it does | When it matters |
|---|---|---|
| **FakeAppId 480** (SLSsteam) | the game asks Steam for tickets/lobbies as Spacewar | every route — always applied by the toggle |
| **netsock** (`LD_AUDIT` in the game process) | patches steamclient's GameNetworkingSockets cert check | games on SteamNetworkingSockets (Lethal Company, Enshrouded, Teardown…) |
| **EOS proxy** (`EOSSDK-Win64-Shipping.dll`) | forwards to the game's real SDK, renamed `.yes`, and swaps `EOS_Connect_Login` to device-id | games whose multiplayer runs on Epic Online Services |
| **Online fix** (catalogue zip) | in-process replacement steamclient / wrapper `steam_api` (`WINEDLLOVERRIDES`) + its own `FakeAppId` | when the native doors don't connect, or the game needs more (PlayFab, custom backends) |

We don't try to tell one native door from another: 480 is inert where unneeded,
netsock **fails gracefully with `"pattern not found"`** on a non-SNS game, and
the EOS proxy only exists where the game ships the Epic SDK. So the toggle
applies **480 always, netsock when it is installed, the EOS proxy when the SDK
is found**, and tells the user which of the three it applied.

**netsock** = `yesyes0649/steamnetsock-patch`. `setup.sh` installs it on every run
to `~/.config/SLSsteam/tools/netsock/netsock.so`; we do not bundle it. Launch
option (per its README): `LD_AUDIT="$HOME/.config/SLSsteam/tools/netsock/netsock.so" %command%`.

**EOS proxy** = `yesyes0649/eos-proxy`, release **v1.0.0** (only a 64-bit build
exists; the 32-bit asset is a dead link). `release.yml` fetches it into
`backend/deps/EosProxy/` at build time and checks its SHA-256, so the plugin zip
carries it and the backend can verify a placed copy by hash. Its README caveats
are the toggle's: most games ask Steam for a web-API ticket before calling EOS,
which is why 480 goes with it; games that turned off device-id login in their
Epic product cannot be helped; the proxy writes `epic_proxy.log` beside the exe.

### The Online toggle (Online Fixes tab)

One button per installed game, **Enable Online / Disable Online**, and one
description line under it, naming each door by its real name: `Will apply:
FakeAppId (480) · steamnetsock-patch · eos-proxy.` / `Active: FakeAppId (480) ·
steamnetsock-patch.` Situational notes on the same line: steamnetsock-patch not
installed (points to Install Dependencies), an online fix already installed
("try it first"). The line always ends with steamnetsock-patch's own README
warning, the only anti-cheat handling: **"Do not use with anti-cheat games."**
— no detection, nobody else gates this either. Applying eos-proxy **freezes the
game** (see "Anything in the game dir freezes the game" above); 480 and
steamnetsock-patch live outside the game dir and do not.

- **Enable** (`enable_online`): registers FakeAppId 480 (remembering whether the
  entry was already there); sets the netsock leg when `netsock.so` is on disk
  (the launch-options recompute emits the `LD_AUDIT`); applies the EOS proxy
  when the game ships the SDK (`eos_proxy.apply_eos_proxy`: rename the SDK to
  `.yes`, copy the proxy, verify by hash; a `stale` location keeps the game's
  *new* SDK as the `.yes`). The result is one marker per game,
  `lumadeck-online-<appid>.json` = `{netsock, eos, fakeAppId}`, where
  `fakeAppId` is true only if the toggle was the one adding the 480.
- **Disable** (`disable_online`): removes the EOS proxy if the marker says we put
  it (`.yes` renamed back); removes the 480 only if the toggle added it **and**
  no installed `[FIX]` block declares a FakeAppId; deletes the marker, so the
  next launch-options recompute strips the `LD_AUDIT`. A fix's or a manual
  FakeAppId is never touched.
- **Status** (`get_online_status`): `enabled`, `applied`, `netsockInstalled`,
  `eosStatus` (none / inactive / active / stale), `eosBundled`, `blockedBy`,
  `hasOnlineFix`. `stale` (a `.yes` exists but the dll is not our proxy: the
  game was updated after all, e.g. the user unfroze it) is backend-only; the UI
  shows nothing for it, a new Enable re-applies the proxy over the new SDK.
- **Refused on Denuvo-activated games**: an appid listed in SLSsteam's
  `DenuvoGames:` block is activated with another account's identity; a FakeAppId
  would break that activation and online cannot work on a ticket-activated Denuvo
  game anyway. The button is disabled with "Denuvo-activated game: online is not
  available." (`slssteam_ops.is_in_denuvo_games`).

### How the online-fix automatism relates

- **From an online fix (catalogue "Apply fix"):** the definitive "this is an
  online fix" signal is that the zip ships an **`OnlineFix.ini` with a `FakeAppId`**
  in its `[Main]` section. On extract, `_apply_onlinefix_fakeappid` reads it and
  registers that id in SLSsteam (logged as a `FakeAppId:` line in the `[FIX]`
  block), and sets the legacy netsock marker `luatools-netsock-{appid}.on` when
  `netsock.so` is on disk and the install dir shows no anti-cheat markers
  (`_has_anticheat`). Denuvo / single-player / generic cracks have **no such
  `.ini`** → only their files are copied.
- Both markers feed the same launch-options recompute: netsock is on when either
  the toggle's marker or the legacy marker says so. Un-fixing an online fix drops
  its FakeAppId and its legacy marker; the toggle's marker is the toggle's own.
- Whether the ini automatism keeps setting netsock by itself is pending a real
  test (Valheim on PC); the toggle does not depend on it.

Backend: `fixes.enable_online` / `disable_online` / `get_online_status`,
`_read_online_marker`, `_netsock_enabled`, `_has_online_fix`,
`_fix_declares_fakeappid`, `eos_proxy.py` (`get_eos_proxy_status`,
`apply_eos_proxy`, `remove_eos_proxy`, `find_eos_dirs`),
`slssteam_ops.is_in_denuvo_games`; the online-fix path keeps
`_apply_onlinefix_fakeappid`, `_parse_onlinefix_ini`, `_has_anticheat`.

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
