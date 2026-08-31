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

### D1 — the `.acf` error-state patch only looked in one library — **FIXED**

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

**Fixed** (lumalinux `2c2cc7c`) with `_all_library_paths()` — the separate list
`steam_root` cannot be, since the install root holds `config.vdf`, `stplug-in` and
`depotcache` and there is exactly one of it. It reads **both** copies of
`libraryfolders.vdf` and unions them: Steam loads the `steamapps/` one and keeps
`config/` in sync, and a union means a stale or missing copy cannot hide a library.
A dead entry surviving in one copy is harmless — all we do with a path is look for a
manifest under it. The root is checked first.

The create half of this defect went with P6; only the patch half remained.

### D2 — `hasGameFiles` is computed against the default root only — **FIXED**

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

**Fixed.** `any()` over every library's `steamapps/`, resolved **once** before the
per-`.lua` loop (`get_steam_libraries()` re-parses the vdf and stats each drive, so
doing it per game would multiply that work). Paths deduped by `realpath`; the Steam
root is appended unconditionally so a malformed `libraryfolders.vdf` can only add
libraries, never drop the default one. No frontend change.

Note it does **not** distinguish our own orphan stub from a real manifest — a stub
alone still reads as installed, exactly as it does today in the root. That is D4's
job, not this one.

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

### D4 — the orphan stub after installing to another library (this is #41) — **FIXED AT SOURCE**

The stub is seeded in the root because at that moment the game is installed
nowhere and there is no correct library to choose. Steam then writes its real
manifest wherever the user chose. Two `.acf` exist; after a restart Steam honours
the root one and reports the game as uninstalled; pressing Install sends Steam
down its *move-content* path → **"can't move storage"**.

**Evidence: reproduced end-to-end**, twice, on the SteamOS devcontainer with a
second library. See §6. The cure — deleting only the orphan stub — was validated in
the same run.

Bounded by the reporter's own steps 2–3 (*"Install onto separate btrfs partition
/ Game is fine"*): **the stub does not block or bias the user's choice.** It only
becomes harmful after the restart, once both records exist. Confirmed in the field
run: the install dialog offered the second drive and the download completed normally.

**Correction to the symptom.** Pressing Install on the mis-reported game did NOT
produce "can't move storage" here — Steam simply **re-downloaded the entire game
into the root library**, leaving two copies on disk (273 MB each for Brotato) and,
once the root manifest is cleaned, an orphaned copy Steam will never reclaim. The
reporter's "can't move storage" is presumably specific to his setup; the harm we can
actually reproduce is a wasted full re-download plus dead disk usage. Either way the
cause and the fix are the same.

**Fixed at source** (lumalinux): the seed is gone. `write_or_patch_acf` is now
`patch_acf_error_state` — it clears the error state of a manifest Steam already
wrote and never creates one. With nothing seeded there is no orphan to strip, so
#41 cannot occur on a new install.

What remains is the **migration**: users already carrying a stub from an earlier
version. See §4 — the same five rules, but run once rather than forever.

### D5 — the patch cancels Steam's own scheduled work — **FIXED**

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

**Fixed** (lumalinux `6dc36a0`), three changes:
1. `ScheduledAutoUpdate` and `FullValidateAfterNextUpdate` dropped from the list.
2. An **absent** key is no longer treated as wrong — only keys that are present and
   wrong get corrected. This is what removes the always-rewrite.
3. The `.acf.bak` is taken only when we actually write, not unconditionally.

Real residue is still cleared: `UpdateResult`, the `Bytes*` counters and the
Update-Required bit. `tools/test_acf_error_patch.py` pins all three properties and
was verified sensitive — stashing only `steamidra_lite.py` fails 6 of its 11 checks,
while the 5 covering legitimate residue-clearing pass either way.

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

## 4b. "NO INTERNET CONNECTION" — what it actually is

The comment our `.acf` code inherited (*"this is what causes 'NO INTERNET
CONNECTION'"*, `sff/lua/writer.py:113`) has been quoted in five places across our
repos and never verified. Two things now bound it.

**SFF has three measures against that popup, and we inherited two.**
`sff/lua/writer.py:272-278` is explicit about the mechanism, and it is not the
game's manifest:

> *"Steam runs a Workshop update after validating the game. If the workshop ACF has
> `NeedsDownload=1` the update will try to fetch workshop manifests the account
> can't access → 'NO INTERNET CONNECTION'. Clear the flag when no workshop content
> is actually installed (SizeOnDisk=0)."*

| Measure | SFF | us |
|---|---|---|
| Clear `appworkshop_<appid>.acf` `NeedsDownload` | yes | **no** |
| Seed manifests into `depotcache` before Steam starts | yes | yes |
| Clear the game manifest's error state | yes | yes |

The one with the clearest causal story is the one we never had — which explains why
the third has never visibly done anything for us.

**It does not apply here, and that is checked, not assumed.** No
`steamapps/workshop/appworkshop_*.acf` exists on the author's rig, and LumaDeck
does not implement Workshop downloads at all. Steam only writes that file for a
game with subscribed Workshop items. Recorded so it is not rediscovered as a
"missing feature": it is a deliberate non-gap.

**`UpdateResult=8` is a decryption failure, on two independent observations.**
Valve publishes no enum for the field (SteamKit's `enums.steamd` has no
`EAppUpdateError`), so this is empirical:

- Ours: Formula Legends, `RESEARCH.md` §12.6 — `Missing decryption key` in
  `content_log.txt`, `UpdateResult=8` left in the manifest, `StateFlags` still 4.
  Our own note calls it benign: *"it doesn't block Play"*.
- A stranger's, different game (2111550), reported on Discord: *"content still
  encrypted"* on launch, fixed by editing `StateFlags 36 → 4` and
  `UpdateResult 8 → 0`. (36 = 4 Fully Installed + 32 Update Paused.)

That second one is the first evidence we have that **clearing the field fixes
something real**, rather than merely tidying it. It is second-hand and changed two
fields at once, so it is a strong lead, not proof. It does raise P4's value: the
field does get stuck, and unsticking it appears to help.

## 5. Open questions

- ~~**Q1 — is the stub still needed?**~~ **ANSWERED: the CREATE branch is not.**
  See §6. With the seed disabled, the button still reads **Install**, the game
  survives a Steam restart un-installed, installs to the second library, and leaves
  exactly one manifest — so #41 cannot occur. The PATCH branch is untouched by this
  and remains justified (RESEARCH.md §12.6).
- ~~**Q2 — does Steam rewrite a deleted `.acf`?**~~ **ANSWERED: no.** Deleted with
  Steam running, restarted, not regenerated — observed twice. Safety rule 4 can
  relax: the cleanup may run on library refresh with Steam up; it takes effect on
  the next Steam start.
- **Q3 — does Steam read `config/depotcache`?** Long-standing. `_write_manifest_both`
  (`steamidra_lite.py:274-286`) writes to both on inherited SteaMidra rationale;
  moon's startup copy implies it does not.

Q1 still needs real Steam with a real login. Two environments:
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
.acf in the secondary library -> hasGameFiles=False  -> CARD GREYED OUT   <- FAILED
.acf in the root (control)    -> hasGameFiles=True   -> normal            OK
```

Now fixed and green, with the fix verified **sensitive**: reverting only
`downloads.py` and re-running turns the second-library case red again, so the test
measures the fix rather than agreeing with it. Two further cases pin the
no-`libraryfolders.vdf` fallback in both directions (the root survives; the second
library is unknowable and reads as not installed — a choice, not a surprise).

Both scripts live in the session scratchpad and are candidates for
`lumalinux/tools/` and `LumaDeck/tests/` respectively. **When D1 and D2 are fixed,
both flip from FAIL to OK with no change to the tests** — they are the acceptance
criteria, written before the fix.

**Field run — D4 reproduced and the cure validated.** SteamOS devcontainer, Steam
with a real login, two libraries (the Steam root plus `/tmp/steamlib`, a real ext4
volume on a separate device).

Getting a second library registered by hand took four attempts; the three failures
are worth recording because they are not obvious:

1. **Steam loads `steamapps/libraryfolders.vdf`, not `config/libraryfolders.vdf`.**
   Its own `content_log.txt` says so (`Loaded Steam library folders configuration:
   .../steamapps/libraryfolders.vdf`). Both files exist, are byte-identical and are
   kept in sync by Steam, so LumaDeck reading `config/` is fine — but a hand edit
   must touch both, or Steam reloads from `steamapps/` and rewrites `config/` from
   memory.
2. **Steam must be genuinely dead**, and `pgrep -x steam` does not detect it in Game
   Mode. Editing under a live Steam is silently discarded on exit.
3. **The devcontainer's supervisor relaunches Steam whenever it dies** (it emulates
   gamescope-session). Stop it with `echo stop > /tmp/lumadev-session` first.

Neither the filesystem type nor the `contentid` mattered; a tmpfs was rejected only
because of the above.

Run 1 (Brotato, 1942280) — reproduced, then contaminated by pressing Install:

```
add                 root: StateFlags 1, SizeOnDisk 0     lib2: -
install to lib2     root: StateFlags 1, SizeOnDisk 0     lib2: StateFlags 4, 286 MB
restart Steam       -> Steam reports NOT INSTALLED
press Install       -> re-downloads the whole game into the ROOT (273 MB duplicate)
```

Run 2 (Vampire Survivors, 1794680) — clean, no Install pressed:

```
add + install to lib2   root: StateFlags 1, SizeOnDisk 0   lib2: StateFlags 4, 1.2 GB
restart Steam           -> NOT INSTALLED                       <- the defect
rm the root stub only   -> restart -> INSTALLED                <- the cure
```

The deleted file matched safety rule 2's fingerprint exactly (`StateFlags 1`, no
`InstalledDepots`, `SizeOnDisk 0`), and in run 1 the file that had been overwritten
by Steam did **not** — so the rule would have acted in exactly one of the two cases,
which is the intended behaviour.

**Field run — is the stub needed? The create branch is not.**
Same rig, with the seed call (`steamidra_lite.py:1577`) replaced by a literal so
`write_or_patch_acf` never runs. Log line confirms it (`appmanifest_1055540.acf:
SKIPPED`). Four observations:

| | with the stub | without it |
|---|---|---|
| button before installing | Install | **Install** |
| survives a Steam restart while un-installed | not measured | **yes, still Install** |
| installing to the second library | **two manifests** | **one manifest** |
| after the next Steam restart | **NOT INSTALLED** | **installed** |

A Short Hike (1055540) installed to the root, Undertale (391540) to the second
library. Both produced a correct Steam-written manifest with the canonical
`installdir` and no orphan anywhere.

This removes the create branch's documented justification. The comment at
`steamidra_lite.py:776-788` warns that a non-canonical `installdir` makes Steam
offer "Update" instead of "Install" and re-download on a later regeneration — but
with no stub there is no `installdir` of ours to be non-canonical: Steam takes its
own from appinfo, and the verb is Install.

**Limits of this result.** It disables the whole call, so it says nothing about the
patch branch, which acts on an `.acf` Steam already wrote and is corroborated
independently (`RESEARCH.md` §12.6, the `UpdateResult=8` residue). It also does not
cover a failed or interrupted install — the "NO INTERNET CONNECTION" case the stub
was inherited to prevent — nor a game whose store name diverges from its official
`installdir`. One Steam build, one environment.

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
| ~~P2~~ | ~~`hasGameFiles` across all libraries — D2~~ | LumaDeck | — | **DONE** — test flips to OK; 112 tests pass |
| ~~P3~~ | ~~Narrow `_ACF_ERROR_FIELDS`; absent ≠ changed — D5~~ | lumalinux | — | **DONE** — `6dc36a0` |
| ~~P4~~ | ~~The patch finds the manifest across libraries — D1~~ | lumalinux | — | **DONE** — `2c2cc7c` |
| **P5** | Reconciliation — D4 | LumaDeck | — (Q2 answered) | a reproduced broken state self-heals on refresh |

P5 is all that is left. It deletes files Steam owns, and is not gated on a
measurement — both the defect and the cure are reproduced above — but it is now a
one-off migration rather than a permanent mechanism, since P6 stopped producing the
orphans in the first place.

**P6 — remove the seed — is done** (lumalinux `8260b12`) and verified on the rig
with the shipped code, not the experiment patch: adding Jump King logs
`none (no .acf yet — Steam writes it on Install)`, writes nothing, and after the
install Steam's own manifest is there with `StateFlags=4` and the real size. The
two-library half of the claim is the Undertale run above — no seed, installed to
the second library, exactly one manifest, still installed after a restart.

It re-scoped the rest:

- **P5** is no longer a permanent mechanism: a one-off migration for users already
  carrying a stub. Same five rules, run once.
- **P4** halved. There is no seed to misplace; what remains is that the patch must
  find the existing `.acf` **across libraries**, for the D1 scenario (a game already
  installed elsewhere getting a LuaTools downgrade or a re-add).
- **P3** was unaffected and is done.

Carried by P6, each verified rather than assumed:

- `--name` stays accepted and **ignored**. LumaDeck probes `--help` for it once per
  session and caches the answer (`downloads.py:78`), so removing the flag would
  break an add if lumalinux is updated without restarting the plugin. Delete it
  once nothing sends it.
- The ACCELA in-game marker is **skipped** when no `.acf` exists instead of falling
  back to `str(app_id)`, which would have created an empty
  `steamapps/common/<appid>/` nobody reads. `--accela-mark` after install still
  places it.
- `_fetch_game_name` and `_sanitize_installdir` lost their only caller and are gone.
- The post-install guard in `downloads.py:1031` checks `keys.txt`, not the `.acf`,
  so it is unaffected.

**UI consequence, and it is a fix rather than a regression.** `GameCard.tsx:32-38`
documents two states: installed → full colour; *"only staged (manifest written but
Steam hasn't downloaded it yet)"* → dimmed with a download-cloud badge. The stub
made `hasGameFiles` true the moment a game was added, so the staged state was
effectively unreachable and a just-added game looked identical to one you had
played. Without the seed the grid does what its own comment says.

`GameDetail` was never fooled: `gameInstalled = !!installPath && gameSize > 0`, and
the stub's size is 0. The LuaTools *manifest* slot needs no install path by design
(`GameDetail.tsx:504`, `canInstallVersion = luatoolsConnected`), so downgrading to a
fix's build before downloading the game keeps working; only *Apply fix*, which drops
DLLs into the game dir, requires an installed game — as it should.
