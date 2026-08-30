# Multi-library support (non-default drives) — findings and plan

Working document for the work behind issue
[#41 "External partition issues"](https://github.com/jayool/LumaDeck/issues/41).

Status: **analysis complete, no code changed.** Five defects identified, each with
its evidence class recorded below. Two are reproduced by automated tests, two by
measurement on real Steam installs, one by reading (dead code).

The scope is not "fix #41". It is: **LumaDeck and lumalinux must behave correctly
whichever library the user installs a game into.** #41 is the first symptom to
surface.

---

## 1. The root cause: two concepts, one variable

Steam's tree holds two things the code conflates:

| | Where | How many |
|---|---|---|
| **Steam install root** | `config/config.vdf`, `config/stplug-in/`, `config/libraryfolders.vdf`, `depotcache/`, `config/depotcache/` | **One** per machine |
| **Library** | `steamapps/appmanifest_<appid>.acf`, `steamapps/common/<installdir>/` | **N** |

The root *is also* the first library. On a single-drive Deck the two coincide, so
conflating them is invisible — which is why none of this surfaced until a user
with a second partition filed #41.

`.manifest` files (`depotcache/`) are a third thing entirely: per-install, never
per-library. They are not involved in any defect here.

### Who decides the destination

**LumaDeck does not download the game — Steam does** (`backend/downloads.py:56-58`).
The user picks the library in Steam's own install dialog, *after* LumaDeck has
finished its setup. LumaDeck therefore cannot know the destination in advance and
must not try to: the correct architecture is **observe and adapt**, not predict.

`target_library_path` is dead plumbing that threads from `src/api.ts:148` →
`main.py:352` → `downloads.py:1461` → `downloads.py:1198` and is read by nobody.
`DESIGN_UI.md:789` documents its removal from the UI, but contains one inaccurate
sentence — *"the manifest flow always installs to the default library"*. It does
not: the user chooses, and we simply never find out.

---

## 2. What the `.acf` is, and why we write one

`appmanifest_<appid>.acf` is Steam's per-library, per-game install record:
installed or not, which build, size on disk, the folder name, and whether the last
attempt errored.

`steamidra_lite.write_or_patch_acf()` has **two jobs**, chosen by whether the file
already exists:

- **Exists → patch.** Zero the stuck error fields so Steam stops reporting
  `NO INTERNET CONNECTION` on the next install attempt. Corroborated by our own
  measurement in `lumalinux/docs/RESEARCH.md` §12.6: after a completed install,
  Steam queues an auto-update that returns `UpdateResult=8` without clearing
  `StateFlags`.
- **Absent → create a stub.** `StateFlags=1`, no `InstalledDepots`, all counters
  zero — Steam sees "exists, not installed" and offers a clean **Install**. Its
  load-bearing part is `installdir`: with a non-canonical value Steam offers
  "Update" instead of "Install", and a later regeneration rewrites `installdir`
  to the official name, orphaning the files and re-downloading the whole game
  (`steamidra_lite.py:776-788`).

The stub is **not** what makes Steam download. Ownership and depot surfacing are
lumalinux's job (package-0 finder, license reconcile, depot keys). The stub is
hygiene.

### Who else writes an `.acf`

| Project | `.acf` | `appinfo.vdf` |
|---|---|---|
| **lumalinux / LumaDeck** | **writes** a stub + patches | no |
| **SteaMidra / SFF** (Linux only) | **writes** — but a *fake-installed* record | no |
| **LumaCore** (the SteaMidra DLL) | no | no |
| **slsteam-moon** | reads only, across all libraries | **splices** |
| **slsdeck** | **deletes** Steam's phantom manifests | no (its engine is moon) |
| **LuaTools** | reads only, per library | edits launch options |
| **BetterSteamTools** | never touches it | no |

We are the only project that writes one on Linux, alongside our ancestor.

**Our stub is not SFF's `write_acf`.** The docstring claiming it "replicates" it is
wrong. SFF writes `StateFlags=4`, real byte counts, `buildid`, `InstalledDepots`
when it has them, then `chmod 0o444` — a *"this is fully installed, do not
download"* record, because DepotDownloader already placed the files. Ours is the
inverse: *"this exists, is not installed, download it"*. Same field list, opposite
meaning. Also: `sff/lua/writer.py:85-87` skips `write_acf` entirely on Windows
(`LumaCore handles ownership`), so `.acf` writing is Linux-only there too.

**SFF does not have our library bug.** `sff/ui/ui.py:579-589` `select_steam_library()`
uses the single library when there is one and **prompts the user** when there are
several; that path feeds the ACF writer's `steam_lib_path`. It also **prompts**
for create-vs-patch (`writer.py:90-97`). We ported the writer and dropped both
questions, hardcoding `steam_root`. **The defect is ours, not inherited.**

---

## 3. The five defects

### D1 — `write_or_patch_acf` decides create-vs-patch from one library

`lumalinux/tools/steamidra_lite.py:743`
```python
acf_path = steam_root / "steamapps" / f"appmanifest_{app_id}.acf"
if acf_path.exists(): ...patch... else: ...create stub...
```

With the game already installed in another library it fails **both** jobs: plants
an orphan stub in the root, and leaves the real `.acf` unpatched.

**Evidence: reproduced.** See §6, Test A.

**Trigger:** any flow reaching `_process_and_install_lua` on an already-installed
game — today the LuaTools version-downgrade slot (`backend/luatools_auth.py:380`),
and re-adding a game. **Not** the path #41 reports (that reporter added before
installing).

**Constraint on the fix:** `--steam-root` cannot be repurposed as "the library" —
`steamidra_lite` also derives `depotcache/`, `config/depotcache/`, `config/config.vdf`
and `config/stplug-in/` from it (`:1393-1394`, `:1551,1558`, `:852`). The `.acf` at
`:743` is the *only* per-library path. The fix needs a separate library concept,
used only there. `sff/gui/bridges/download_bridge.py:977` `_find_app_manifest_acf`
is the reference shape.

### D2 — `hasGameFiles` is computed against the default root only

`backend/downloads.py:1676`
```python
"hasGameFiles": os.path.exists(os.path.join(base_path, "steamapps", f"appmanifest_{appid}.acf"))
```
feeds `src/components/GameCard.tsx:38`
```typescript
const installed = !!game.hasLua && !!game.hasGameFiles && !game.isDisabled;
```

A game installed in a second library reads as not installed → **the card renders
greyed out.** This is the symptom the #41 reporter describes in his comment.

**Evidence: reproduced.** See §6, Test B.

**Fix:** `any()` over `get_steam_libraries()`, resolving the library paths once
outside the per-script loop.

### D3 — the ACCELA marker path is dead code — **FIXED**

- `backend/paths.py:260` `get_accela_run_script()` — **no callers**.
- `check_accela_installed()` / `find_accela_root()` — consumed only by a diagnostics
  dict at `paths.py:1169-1170`; nothing branches on them.
- Nothing reads the `.DepotDownloader` marker functionally. `steamless.py:208` skips
  it while walking; `_ensure_accela_mark` checks its own marker to avoid repeating.
- `README.md:103` already states ACCELA is *"not a dependency"*.

`_ensure_accela_mark` (`downloads.py:1570-1602`) is also root-only twice over (the
`.acf` and the game dir), and spawns a Python subprocess **per game, per library
refresh, without checking whether ACCELA is installed at all**.

**Evidence: read.** No callers, no consumers.

**Fixed** by removing `_ensure_accela_mark`, its refresh loop, `_dir_has_real_content`
(its only caller) and `get_accela_run_script`, plus the DESIGN.md/README sections that
described the self-heal. The library refresh no longer spawns a subprocess per game, and
D2's fix is now simpler: it only needs *whether* a game is installed, not *where*.

Deliberately kept: the uninstall path still removes ACCELA markers and the `.depot`
tracker (`downloads.py:919, 1013, 1334`) — cleaning up markers that exist stays correct
for users who have them. `check_accela_installed()` / `find_accela_root()` stay too;
they only feed a diagnostics dict.

Still open, in lumalinux and decided separately: `steamidra_lite` writes the marker once
at add time (`:1607-1613`). That is a cheap one-shot, not a loop.

### D4 — the orphan stub after installing to another library (this is #41)

The stub is seeded in the root because at that moment the game is installed
nowhere and there is no correct library to choose. Steam then writes its real
manifest wherever the user chose. Two `.acf` exist; after a restart Steam honours
the root one and reports the game as uninstalled; pressing Install sends Steam
down its *move-content* path → **"can't move storage"**.

**Evidence: field report** (issue #41, reproduction steps 1–8). Not reproduced
locally — a second library is required and neither the author's Deck nor his
Windows install currently has one (§6).

Bounded by the reporter's own steps 2–3 (*"Install onto separate btrfs partition
/ Game is fine"*): **the stub does not block or bias the user's choice.** It only
becomes harmful after the restart, once both records exist.

**Fix:** reconciliation — see §4.

### D5 — the patch cancels Steam's own scheduled work

`_ACF_ERROR_FIELDS` (`steamidra_lite.py:609-618`) treats eight fields as "error
residue" and zeroes all of them. Two of them are not error residue:

| Field | What it actually is | Measured |
|---|---|---|
| `ScheduledAutoUpdate` | a **future appointment** Steam set itself | `Halo: Campaign Evolved` (2806050), `StateFlags=6`, value `1788144179` |
| `FullValidateAfterNextUpdate` | an **instruction** Steam left itself | `Steamworks Common Redistributables` (228980), value `1` |

Zeroing them cancels a scheduled update and a pending validation respectively.

Separately: across 13 real manifests (9 SteamOS + 4 Windows), 12 lack
`FullValidateAfterNextUpdate`. Since a *missing* key counts as a change
(`app_state.get(k) != clean` → `None != "0"`), the patch branch **effectively never
returns `"clean"`**: every add of an already-installed game round-trips Steam's
`.acf` through our own parser and writer, and leaves an `.acf.bak` (the backup is
taken before the needed-check).

**Evidence: measured.** See §6.

**Fix, two rules:**
1. Drop `ScheduledAutoUpdate` and `FullValidateAfterNextUpdate` from the list.
2. Do not count an **absent** key as a change — only correct keys that are present
   and wrong. This also removes the always-rewrite.

Inherited honestly: in SFF the list applied to a manifest SFF had just written
itself for a game DepotDownloader had just downloaded, where every counter was zero
by construction and there was nothing of Steam's to overwrite.

---

## 4. Reconciliation design (for D4)

Runs in the existing library-refresh loop (`downloads.py:1688-1690` — the slot D3's
removal frees), which is already periodic, idempotent and non-blocking.

**Rule:** if a manifest matching our stub's fingerprint exists in one library, and a
*real* manifest for the same appid exists in **another**, delete ours.

Five safety rules, in force order:

1. **Nothing is deleted unless a real manifest for that appid exists in another
   library.** This is the property that makes the deletion safe by construction —
   what we remove is redundant by definition. Compare **resolved** paths, never
   strings: `libraryfolders.vdf` includes the root, and SD mounts vary
   (`/run/media/mmcblk0p1`, `/run/media/deck/<label>`, symlinks).
2. **Only delete a file that still carries the stub fingerprint**, read at deletion
   time: `StateFlags=1`, no `InstalledDepots`, `SizeOnDisk=0`, `LastUpdated=0`.
   Fingerprint, not bookkeeping — so it also repairs users already broken today,
   and survives a plugin update. ("Real" = `InstalledDepots` non-empty **or**
   `SizeOnDisk > 0`.)
3. **When in doubt, do nothing.** Not installed anywhere → the stub is doing its
   job, leave it. Partial/failed install elsewhere → does not count as real.
   Unreadable libraries or any parse error → no action.
4. **Timing.** Steam holds the `.acf` while downloading (SFF documents this, see
   below). Until Q2 (§5) is answered, do the deletion with Steam closed —
   `paths.py:1006` `_check_process_injected()` serves as the running-Steam probe.
   The natural moment is the shutdown LumaDeck already performs
   (`downloads.py:1335`), on the *next* one after the download completes.
5. **Every deletion is logged** with the path and the real manifest that justified
   it, behind a kill switch in the style of `slssteam_ops.py:38-60`
   `_hot_reload_enabled()`.

### Prior art worth copying

**slsdeck** ships this machinery for a different purpose — removing the phantom
manifests Steam writes when it cannot resolve depots (`py_modules/lt/steam.py:513-582`).
Its shape matches rules 1–3 and 5: iterate all libraries, strict signature checked
at deletion time, *"Only ever deletes the .acf — never game files"*, log every
removal. Its fingerprint is `StateFlags & 4` with zero size and zero depots — bit 4,
not our bit 1, so the two rules could coexist without overlap. It runs the check
**before triggering a download** rather than on a timer — a decision point beats a
poll, though our orphan appears *after* the download, so the specific moment does
not transfer.

**SFF** ships the deferred-write architecture, `sff/game/acf_pending_queue.py`:
a persistent JSON queue with atomic writes (`tmp.write_text` + `replace`), retried
every 30 s until the `.acf` exists **and** `StateFlags & 4` **and** the write sticks,
with a 7-day expiry, resolving the manifest across all libraries. Its docstring is
also our best evidence for rule 4: *"Steam only creates `appmanifest_*.acf` once a
game is being downloaded, and while it downloads Steam may hold the file."*

### What we already do right

Nine sites already iterate libraries, all using the same idiom
(`get_steam_libraries() or [{"path": detect_steam_install_path() or ""}]`):

`downloads.py:266` `self_heal_acf_build` · `downloads.py:524` `_get_installed_size_bytes` ·
`downloads.py:1155` `repair_appmanifest` · `fixes.py:939` `get_installed_fixes` ·
`slssteam_ops.py:683` `_find_game_dir_fallback` · `slssteam_ops.py:906` `uninstall_game_full` ·
`steam_utils.py:171` `get_game_install_path_response` · `steam_utils.py:242` `get_installed_games` ·
`steam_utils.py:332` `get_steam_libraries` (the canonical helper).

`fixes.py` is drive-agnostic by construction — it takes an `install_path` resolved
by `get_game_install_path_response`.

**No migration code is needed.** `repair_appmanifest` is already library-aware and
deletes the `.acf` so Steam regenerates it — which is what the #41 reporter found
himself at his step 8.

---

## 5. Open questions

- **Q1 — is the stub still needed?** Comment out the call at `steamidra_lite.py:1577`,
  add a clean game, and read the button: **Install** or **Update**. If Install, the
  stub is dead weight and D1 and D4 lose their object. GUI-only; no file records the
  verb.
- **Q2 — does Steam rewrite a deleted `.acf`?** Delete it with Steam running, close
  Steam, look again. Decides whether rule 4 can relax.
- **Q3 — does Steam read `config/depotcache`?** Long-standing. `_write_manifest_both`
  (`steamidra_lite.py:274-286`) writes to both on inherited SteaMidra rationale;
  moon's startup copy implies it does not.

Q1 and Q2 need real Steam with a real login. Two environments:
`lumalinux/.devcontainer/steamos` (Steam in gamepadui, noVNC on 6080, Decky and
LumaDeck pre-deployed — needs a second library added by hand), or a Deck.

---

## 6. Evidence log

**Test A — D1, reproduced.** Fake tree, two libraries, `write_or_patch_acf` called
directly. Deterministic, no network, no Steam.

```
game already in the secondary library -> "created (stub …)"
  [root] CREATED   StateFlags=1  SizeOnDisk=0  InstalledDepots=no
  [lib2] UNTOUCHED UpdateResult=8  StateFlags=22            <- FAILS on both counts
game in the root (control)            -> "patched"  UpdateResult 8->0, StateFlags 22->6   OK
game installed nowhere (control)      -> stub created in the root                          OK
```

**Test B — D2, reproduced.** Same fixture against the real `get_installed_lua_scripts()`.

```
.acf in the secondary library -> hasGameFiles=False  -> CARD GREYED OUT   <- FAILS
.acf in the root (control)    -> hasGameFiles=True   -> normal            OK
```

Both scripts live in the session scratchpad and are candidates for
`lumalinux/tools/` and `LumaDeck/tests/` respectively. **When D1 and D2 are fixed,
both flip from FAIL to OK with no change to the tests** — they are the acceptance
criteria, written before the fix.

**Field measurements — D5.** Author's SteamOS Deck (9 manifests, one library) and
Windows install (4 manifests, one library):

| Field | SteamOS | Windows |
|---|---|---|
| `StateFlags` | 9/9 | 4/4 |
| `ScheduledAutoUpdate` | 9/9 | 4/4 |
| `UpdateResult` | 6/9 | 4/4 |
| `BytesToDownload` | 6/9 | 4/4 |
| `FullValidateAfterNextUpdate` | **0/9** | **1/4** |

Non-zero `ScheduledAutoUpdate`: `4628710` (Proton 11.0, a tool) and **`2806050`
(Halo: Campaign Evolved, a real game)**. `FullValidateAfterNextUpdate=1`: `228980`.

Neither machine has a second library, so D4 could not be reproduced there and no
orphan stubs were found — which independently confirms that with a single library
Steam overwrites our stub on install and leaves no trace.

---

## 7. Plan

| | Change | Repo | Blocked by | Acceptance |
|---|---|---|---|---|
| ~~P1~~ | ~~Remove the ACCELA marker path — D3~~ | LumaDeck | — | **DONE** — 110 tests pass, no subprocess per refresh |
| **P2** | `hasGameFiles` across all libraries — D2 | LumaDeck | P1 (simplifies it) | Test B flips to OK |
| **P3** | Narrow `_ACF_ERROR_FIELDS`; absent ≠ changed — D5 | lumalinux | — | patch returns `"clean"` on a healthy manifest; the two fields survive |
| **P4** | Library-aware create-vs-patch — D1 | lumalinux | — | Test A flips to OK |
| **P5** | Reconciliation — D4 | LumaDeck | **Q2** | a reproduced broken state self-heals on refresh |

P2–P4 need no Steam and are independently shippable and revertible. P5 is the one
that deletes files Steam owns and is the only one gated on a measurement.

Ordering note: P4 prevents an *avoidable* orphan; P5 removes the *unavoidable* one.
Both are needed, and **P5 is what closes #41** — P4 fixes a sibling defect with a
different entry point.
