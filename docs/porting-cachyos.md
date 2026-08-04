# Porting LumaDeck (+ lumalinux) to other distros — starting with CachyOS

> Status: **Phases 0–2 implemented on `claude/cachyos-support` and VALIDATED
> LIVE on a real CachyOS userland (2026-08-04).** The platform layer, the
> environment generalisation, and the session-layer fixes are done, unit-tested,
> and now confirmed against real CachyOS: lumalinux loaded **3/3 hooks** on a
> genuine CachyOS install, `platform_info` detected `cachyos`, and the real
> `steamos-session-select` / `steam-short-session-tracker` scripts matched what we
> ported. The **one** remaining gate is the **Game-Mode gamescope crash-loop**
> (#31's core), which needs an actual handheld — a GPU-less container has no
> compositor (see §10). The work is additive and **does not regress the tested
> SteamOS path** (65 characterization tests hold the SteamOS golden values).
> Read "Non-regression invariants" before touching any of it.

## 0. Current status & confidence (read this first)

**What is done and how it was verified:**

- **Phase 0 — platform layer** (`backend/platform_info.py`, ~307 lines): distro
  detection (os-release `ID`/`ID_LIKE`, mirroring Headcrab), real-user/home/uid
  resolution, Steam flavor, `session_family()`. **Done, unit-tested.**
- **Phase 1 — environment generalisation**: every hardcoded `deck` /
  `/home/deck` / uid-1000 / cache-dir literal across the backend now routes
  through `platform_info` (see §7 for the full inventory, all struck through).
  **Done.** 65 tests, including golden-value characterization that SteamOS
  resolves bit-for-bit to `deck` / `/home/deck` as before.
- **Phase 2 — session/crash-loop layer**: crash-loop tracker reset generalised
  to `rm -f /tmp/*-short-session-tracker`; `steamos-session-select` desktop arg
  is lineage-correct — **`plasma` for SteamOS AND CachyOS** (both Valve/SteamOS
  forks; source-verified), `desktop` only for the ChimeraOS family (Bazzite); and
  a faithful `do_repair()` reproduction test. (The durable crash-loop protection
  is the Desktop-routing of the downgrade, where the tracker service isn't
  running; CachyOS's own `~/.config/inhibit-short-session-tracker` is documented
  but deliberately NOT set — redundant, and setting it would touch SteamOS.)
  **NOTE:** an earlier revision put
  CachyOS in the ChimeraOS family and sent it `desktop` — a regression (CachyOS
  rejects `desktop`); now fixed. The crash-loop fix is verified against the
  *reproduced* clobber, but is **not** confirmed to be #31's desktop-mode cause.
- **`origin/main` (0.6.0) merged in**: the new CDP login flow
  (`backend/cef_cdp.py`, `luatools_auth.py`) audited clean; `main.py`'s new
  `restart_steam()` carried fresh `deck`/`/home/deck` hardcoding, now routed
  through `real_user()`/`real_home()`.

**Live validation on real CachyOS userland (2026-08-04).** Run in the CachyOS
port-testing devcontainer (real CachyOS repos + session packages, headless
Steam), NOT an Arch stand-in:

- **Core: lumalinux `3/3 hooks active`** on a genuine CachyOS Steam (DepotKey,
  GMRC, ShaderDepot, package-0 finder all installed) — the hooking core works on
  CachyOS, live, not by inference.
- **Env layer:** `platform_info.summary()` returned `distro=cachyos` from the
  backend; user/home/paths resolved correctly.
- **Session scripts source-verified ON the machine:** the real
  `/usr/bin/steamos-session-select` has a `plasma` case and **no `desktop` case**
  (confirming the `plasma` fix and that the earlier `desktop` was a regression);
  `/usr/lib/steamos/steam-short-session-tracker` uses `/tmp/steamos-short-session-
  tracker`, `count_before_reset=3`, and `do_repair()` re-extracts the bootstrap
  over `~/.local/share/Steam` — exactly the mechanism modelled in the tests.
- **Full desktop flow works E2E** (headcrab → SLSsteam → lumalinux → LumaDeck →
  Decky).

**Upstream caveat found live (NOT our code, NOT CachyOS-specific).** On a *fresh*
non-Deck-Linux install (CachyOS-Desktop, or a fresh Arch), SLSsteam can abort
with "Unknown steamclient.so hash" and LumaDeck shows "Steam build not supported".
Root cause: **Headcrab's `LinuxClientManifest` (build 1784669098, 2026-07-21)
lags its own `HeadcrabCompatibleClientVer` (1785187029, 2026-07-27) by ~6 days**,
and SLSsteam's whitelist tracks the newer (compatible) build. So Headcrab
downgrades non-Deck-Linux clients to a build it itself no longer calls compatible
and that SLSsteam doesn't whitelist. **CachyOS-*Handheld* is unaffected** — it
uses Headcrab's Deck manifest (1785187029), which is aligned. An already-pinned
install (the long-lived Arch env) also dodges it (Headcrab's compat check skips
the downgrade). This resolves upstream when Headcrab bumps its Linux manifest.

**Confidence, per target — calibrated, not optimistic:**

| Layer | CachyOS Handheld | Bazzite |
|---|---|---|
| Core hooks (`steamclient.so`) | ✅ **verified LIVE — lumalinux 3/3 hooks on real CachyOS** | ✅ same binary — same verdict |
| Path / user / cache resolution | ✅ verified (tests + live `distro=cachyos` on the machine) | ✅ same code path |
| Install (Headcrab downgrade) | ✅ pacman; Handheld uses the aligned Deck manifest (SLSsteam-whitelisted) | ❌ **blocker: Fedora-atomic, no `pacman`, `/usr` read-only, SELinux — no install route designed yet** |
| Session / crash-loop (#31) | ✅ session scripts source-verified on the machine (`plasma`, `steamos-` tracker, `do_repair`); ⏳ the **Game-Mode gamescope crash-loop** itself is device-gated | ⚠️ same code by construction |

**Bottom line:** **CachyOS Handheld** — the core, the env layer, and the session
scripts are now **verified live on real CachyOS**; the only unverified piece is
the Game-Mode gamescope crash-loop, which is device-gated (no compositor in a
container). One on-device Game-Mode run from callable done. **Bazzite** is *not*:
the hooking core and the env layer carry over unchanged, but its
**package/immutability model breaks the Headcrab install path**, and no
Fedora-atomic install route exists yet. Bazzite is deferred to a future phase
(§6, Phase 3) with that blocker documented, not hand-waved.

## 1. Goal & scope

Make LumaDeck usable on non-SteamOS distros that run Steam in **Game Mode /
Big Picture Mode** with **Decky Loader**. First target: **CachyOS**. The
architecture stays generic (a platform layer) so other distros can slot in
later, but only CachyOS is in scope for now.

**Explicitly out of scope for this pass:** Flatpak/Snap Steam, and any
distro-specific install work beyond CachyOS. **Bazzite** is a stated future
target (§6, Phase 3) but is deferred, not attempted here: it is Fedora-atomic
(`rpm-ostree`, read-only `/usr`, SELinux enforcing, no `pacman`), which breaks
the Headcrab install path. The platform layer already leaves room for it — its
hooking core and env layer carry over unchanged — but the install route is
undesigned. The platform layer must leave room without committing.

The prime directive: **SteamOS on a Steam Deck is the tested, working platform
and must keep behaving exactly as today.**

## 2. What we already know (why this is lower-risk than it looks)

The scary part — the in-process hooking core — is **already portable and does
not need to change**:

- **`steamclient.so` is the same binary on desktop and Deck (current builds).**
  SLSsteam's SafeMode whitelist (`res/updates.yaml` upstream) annotates a
  **single hash** as `#ubuntu12_32 & steamdeck_stable` for every build since
  Jan 2026. Valve ships an identical `steamclient.so` in the generic Linux
  desktop client and the Deck stable client. What differs between channels is
  the *client package/manifest version number*, not the hooked binary.
- **Hooks are signature-scanned, not offset-baked.** Both lumalinux
  (`src/patterns.cpp`, `src/rtti.cpp`) and SLSsteam (`src/patterns.cpp`,
  runtime `libmem` signature search + RTTI vftable analysis) locate targets by
  scanning bytes at runtime. Identical binary ⇒ patterns match; the approach is
  distro-agnostic anyway.
- **SLSsteam is cross-distro by design.** It only acts in the process named
  `steam`, explicitly appends `/usr/lib:/usr/lib32` to `LD_LIBRARY_PATH` "since
  some distros respect it more or less", ships an Arch-packaged variant
  (`libSLSsteam.so`), and has documented Flatpak + Nix support. Its hash
  whitelist already covers the desktop channel.
- **Headcrab is already multi-distro.** `headcrab.sh` has `archcheck`
  (matches `arch`/`cachyos`), `cachyoscheck`, dedicated CachyOS manifest/install
  branches, and installs deps via `pacman` on Arch/CachyOS. It **never touches
  the rootfs** (`/usr`, `/etc`, `steamos-readonly`) — everything is under
  `$HOME`, and it does not assume the `deck` user.

**Conclusion:** lumalinux and SLSsteam do **not** get ported for CachyOS. The
entire change surface is **LumaDeck's Python environment layer** (path/user/
session resolution + a gated CachyOS branch in the installer).

### Field evidence — issue #31 ("Borked install on CachyOS")

A user on **CachyOS Handheld** reported: install ran, **first Steam boot showed
everything injected**, but on the next restart nothing was injected and Steam
hung; returning to Game Mode gave a **black screen**. They switched to SteamOS
and it worked flawlessly.

That the plugin reported **everything injected on first boot** is the one solid
signal: the hooking core *did* load and hook on CachyOS. Everything past that is
**unconfirmed — the reporter explicitly had no logs.**

> ⚠️ **Correction (2026-08, verified against source).** Earlier revisions of this
> doc named the **crash-loop tracker mismatch** as the "strong cause" of #31 and
> assumed CachyOS Handheld is **ChimeraOS lineage**. Both were wrong, and I'm
> leaving the retraction visible rather than silently editing it:
>
> - CachyOS Handheld's `gamescope-session-cachyos` is a **Valve/SteamOS fork**,
>   not ChimeraOS (verified: `CachyOS/gamescope-session@cachyos`,
>   `usr/lib/steamos/…`). It uses the **same** `/tmp/steamos-short-session-tracker`
>   path and the **same** `steam-short-session-tracker` script as SteamOS, and its
>   `steamos-session-select` accepts only `plasma`/`gamescope`/`persistent`/
>   `oneshot` (**no `desktop` case**). So the pre-#31 SteamOS values (`plasma`
>   arg, `steamos-` tracker) were already correct for CachyOS.
> - The tracker's `do_repair()` fires only inside the **gamescope session**
>   (`steam-launcher.service`, `PartOf=graphical-session.target`). But #31's
>   primary symptom is *"steam restarted **in desktop mode**, nothing injected,
>   stuck loading"* — and in Plasma that service isn't running. **do_repair() is
>   therefore NOT the desktop-mode mechanism.** It best fits only the *"black
>   screen returning to Game Mode"* tail.
> - Claims that were unsubstantiated inference (now retracted): "SteamOS barely
>   downgrades / CachyOS downgrades a lot" — never measured.

**Honest current read of #31:** root cause **unconfirmed**. The best-supported
suspect for the primary (desktop-mode) symptom is that the client downgrade's own
Steam restarts re-extract the bootstrap over `steam.sh` (wiping the LD_PRELOAD
block) and the re-patch never settles because Steam hangs on CachyOS — but *why*
it hangs on CachyOS and not SteamOS is exactly what needs a device/repro. The
`do_repair()` clobber is a real, reproduced failure mode (see
`tests/test_installer_crashloop.py`) but for the game-mode / return-to-gamemode
path, not the reported desktop-mode one.

## 3. CachyOS: two editions, very different for us

| | Desktop Edition | Handheld Edition |
|---|---|---|
| Boots to | KDE desktop | **Game Mode** (`gamescope-session-cachyos`) |
| Steam UI | window / **Big Picture Mode** | gamescope session |
| Crash-loop detector | none | **yes** (`steam-short-session-tracker`, Valve/SteamOS fork) |
| Session switch | n/a | `steamos-session-select` (Valve/SteamOS fork; args `plasma`/`gamescope`/`persistent`/`oneshot`) |
| Extras | — | HHD (Handheld Daemon) for power/controller |
| Difficulty for us | **low** (env-only) | **high** (session/crash-loop) |
| Real audience? | stepping stone | **yes — this is what handheld users run** |

Implication: Desktop/BPM is a **validation milestone**, not the destination.
The realistic LumaDeck-on-CachyOS user is on Handheld Edition (that's who filed
#31). We use Desktop/BPM to prove the env layer end-to-end without the session
complexity, then add the handheld pieces.

## 4. Non-regression invariants (the contract)

These are hard rules. A change that violates one is wrong even if it "works" on
CachyOS.

1. **SteamOS is the default / fallback.** Platform detection returns `steamos`
   (or an "unknown ⇒ behave as SteamOS") result unless CachyOS is *positively*
   identified via `/etc/os-release`. When the result is SteamOS, every code path
   executes exactly as it does today.
2. **Additive only — never remove or reorder existing SteamOS logic.**
   Candidate lists (e.g. `paths._STEAM_PATHS`, the `/home/deck/...`-first
   ordering) keep their current entries and order. New entries are appended or
   live behind a branch. `find_*` already picks the first existing match, so on
   a Deck the `deck` paths still win, unchanged.
3. **The user/home helper is a superset, not a replacement.** On SteamOS the
   real user *is* `deck`, so the helper resolves to `deck` / `/home/deck` and
   reproduces today's values bit-for-bit. It only diverges when the user isn't
   `deck`.
4. **Feature-gate every divergent behavior.** Anything genuinely different
   (crash-loop handling, downgrade routing, session persistence) sits behind
   `if platform.is_cachyos*()`. The SteamOS branch is the current code, byte for
   byte.
5. **Quarantine the delicate zone.** The Headcrab patch / downgrade / crash-loop
   block is the only code that can harm a working SteamOS install (it kills and
   restarts Steam and can wipe the Steam dir). Do **not** alter its SteamOS
   output. Add a CachyOS branch beside it; route the CachyOS downgrade through
   the existing **Desktop hand-off** (`gamemode=False`), where no crash-loop
   detector is running.
6. **Prove non-regression with characterization tests.** Pin what the
   resolution functions return in a simulated SteamOS environment; assert the
   generalized versions return **identical** values. A changed SteamOS golden
   value is a red alarm. These run with fixtures — no Deck or CachyOS hardware
   needed.
7. **Ship CachyOS as opt-in / experimental first**, on the feature branch.
   SteamOS users on the current release see nothing until a new release is cut.

## 5. Architecture — the platform layer (Phase 0)

Introduce a single module (e.g. `backend/platform.py`, or by extending
`backend/paths.py`'s "platform detection" role) that centralises **all**
environment decisions. Centralisation is itself a safety property: one place to
reason about, with SteamOS as the identity/default.

It must resolve:

- **Distro** — parse `/etc/os-release` (`ID`, `ID_LIKE`), mirroring Headcrab's
  own `archcheck`/`cachyoscheck`. Default → treat as SteamOS.
- **Real user + home** — Decky runs as root, so `~` is `/root`. Resolve the real
  login user via `SUDO_USER` / logind / uid 1000, replacing the hardcoded
  `/home/deck` and `deck:deck` literals. On SteamOS this yields `deck`.
- **Steam root & flavor** — native vs (future) Flatpak; the `~/.steam/steam`
  symlink vs `~/.local/share/Steam`. Note Headcrab uses `$HOME/.steam/steam`
  while lumalinux's `install.sh` writes `~/.local/share/Steam/steam.sh`; confirm
  the symlink holds so both target the same file.
- **Session type** — are we in a gamescope Game Mode session, and of which
  family (SteamOS-lineage — includes CachyOS — vs the ChimeraOS lineage /
  Bazzite)? This gates the crash-loop and session-switch behavior.

Use the existing **`dev` override mechanism** (already used in
`paths.py` health functions via `dev.get(...)`) to add a **platform override**,
so both branches can be exercised without hardware.

## 6. Phased plan

- **Phase 0 — platform layer. ✅ done.** `backend/platform_info.py`, SteamOS as
  default/fallback from line one. Prerequisite for everything.
- **Core cold-check (lumalinux side). ✅ done.** The port validator
  (`.devcontainer/port-testing/validate-port.sh`) fetches the **pinned-build**
  desktop-channel `steamclient.so` and runs `check_patterns.py` + the hash gate
  against it — **CLEAN** on the live desktop client, confirming the "identical
  binary" conclusion for Headcrab's exact pin. lumalinux `res/updates.yaml`
  whitelist confirmed in sync with the pinned build.
- **Phase 1 — environment fixes → Desktop/BPM. ✅ done (env layer).** All
  consumers route through the platform layer: user/home, Steam root,
  cache/config/status paths (§7). Validated at the Codespace ceiling (headless
  Steam via Xvfb + software Vulkan). The **end-to-end Desktop/BPM install** is
  still pending a machine that actually runs the CachyOS desktop client — the
  code is done, the on-device confirmation is not.
- **Phase 2 — Handheld Edition. ◑ code done; #31 root cause UNCONFIRMED.**
  Crash-loop reset generalised to all lineages (`rm -f /tmp/*-short-session-
  tracker`); session-switch arg source-verified (**`plasma` for CachyOS**, a
  Valve/SteamOS fork — an earlier `desktop` value was a regression, now fixed;
  `desktop` reserved for the ChimeraOS family/Bazzite); and a faithful
  `do_repair()` clobber reproduction (`tests/test_installer_crashloop.py`).
  **What is NOT done:** confirming #31's
  *desktop-mode* symptom. The reproduced clobber is the game-mode/return-to-
  gamemode path; the reporter's primary failure was in Plasma, where the tracker
  service isn't running, so its root cause is still open and **device/repro-
  gated** (see the §2 correction box). This is the remaining gate for CachyOS.
- **Phase 3 — Bazzite (future, blocked). ⛔ not started.** Bazzite Game Mode is
  a wanted target, but it is **Fedora-atomic**: `rpm-ostree`, read-only `/usr`,
  SELinux enforcing, **no `pacman`**. The hooking core and the entire env layer
  (Phases 0–1) carry over unchanged, and its ChimeraOS-lineage session bits
  overlap Phase 2 — but Headcrab's **install/downgrade path is pacman-based and
  will not run on Bazzite**. A Fedora-atomic install route (layered package or a
  `~`-local, rootfs-free installer) must be designed before Bazzite is viable.
  Nothing about Phases 0–2 blocks it; it simply is not built.

## 7. Concrete change inventory (LumaDeck env layer)

Hardcoded `deck` / `/home/deck` / uid to route through the platform layer:

- `backend/paths.py` — `_STEAM_PATHS` (deck-first, ~L61-68), SLSsteam config
  deck-first (~L117-121), lumalinux keys path (`/home/deck/.config/lumalinux/…`,
  ~L212), status.json under `/run/user/1000` + `/home/deck/.cache` (~L255-272),
  and the analogous `/home/deck` leads in the SLSsteam/ACCELA/CloudRedirect
  candidate lists.
- `backend/dotnet.py` — `DOTNET_ROOT="/home/deck/.dotnet"`,
  `DECK_USER/DECK_GROUP="deck"` (~L37-40), `chown -R deck:deck` (~L144),
  `HOME=/home/deck` forced.
- `backend/desktop_handoff.py` — `_HOME="/home/deck"` (~L30),
  `steamos-session-select gamescope`/`plasma` (~L72,184,243),
  `pwd.getpwnam("deck")`, KDE autostart / `konsole` assumptions.
- `backend/headcrab_compat.py` — hardcoded `_CACHE_DIR="/home/deck/.cache/lumadeck"`
  (~L37) vs the `expanduser` caches elsewhere (one-line inconsistency).
- `backend/steam_utils.py`, `backend/ryuu_cookie.py` — duplicate `_STEAM_PATHS`
  lists; `ryuu_cookie.py` runs keyring via `sudo -u deck` in the deck D-Bus
  session.
- Session/crash-loop (quarantined, Phase 2): `backend/installer.py`
  `_HEADCRAB_PATCHES` + `_SESSION_TRACKER_RESET` (~L121-212), `gamemode` gating.

lumalinux-side items (tracked in the lumalinux repo, see its
`docs/cachyos-port.md`): desktop-channel option in `tools/fetch_steamclient.py`,
the outdated hash comment, and hash-whitelist sync. `install.sh` hardcodes
`~/.local/share/Steam/steam.sh` (fine as long as the `~/.steam/steam` symlink
resolves there — verify).

## 8. Open questions — resolved vs. still open

Resolved by reading the **actual CachyOS source** (`CachyOS/gamescope-session
@cachyos`, cloned and inspected — not inferred):

- **Crash-loop mechanism** — CachyOS Handheld uses `/tmp/steamos-short-session-
  tracker` (its `steam-short-session-tracker` is a Valve/SteamOS fork), **not**
  a `chimeraos-` variant as an earlier revision claimed. `do_repair()` fires at
  `short_session_count_before_reset=3` and re-extracts
  `/usr/lib/steam/bootstraplinux_ubuntu12_32.tar.xz` over `~/.local/share/Steam`.
  The glob reset covers it (and the desktop-routing avoids it entirely, since the
  tracker service isn't running in Plasma). CachyOS/SteamOS also expose
  `~/.config/inhibit-short-session-tracker` to disable it, but LumaDeck does NOT
  set it — redundant given the routing, and it would touch SteamOS. Reproduced in
  `tests/test_installer_crashloop.py`. ✅ (mechanism) / ⚠️ (that it's #31's cause)
- **`steamos-session-select` args** — verified from source: `gamescope` (Game
  Mode), `plasma` (desktop) on **both SteamOS and CachyOS**, `persistent`/
  `oneshot` for boot behaviour. **No `desktop` case on CachyOS.** `desktop` is
  the ChimeraOS-family value only. ✅
- **Real-user / `~`-is-`/root`** — resolved via the Steam-install owner (not
  "uid 1000"), covering non-1000 users. ✅

Still open — **only answerable on a real device / repro**:

- **#31's actual root cause.** The reproduced `do_repair()` clobber is the
  game-mode path; the reporter's failure was in **desktop mode**, where that
  service isn't running. The desktop-mode mechanism (suspect: the downgrade's own
  Steam restarts re-extract `steam.sh` and the re-patch doesn't settle because
  Steam hangs on CachyOS) is unconfirmed and needs logs/repro.
- `~/.steam/steam` → `~/.local/share/Steam` symlink on a stock CachyOS Steam
  install (assumed, matches SteamOS; unverified on CachyOS).
- Persistence semantics of `~/.config/last-session-mode` on CachyOS vs the
  hand-off (does not block install; affects "sticky desktop" behavior).

## 10. Why the remaining gates need hardware (Codespace ceiling)

The development environment is a Linux Codespace, **not** a handheld. It can and
does validate: the platform layer, the env-layer generalisation (65 tests +
live run with uid≠1000), and the hooking core against the pinned desktop-channel
`steamclient.so` (headless Steam via Xvfb + software Vulkan). It **cannot**
reproduce a **gamescope Game Mode session** or its **short-session crash-loop
detector** — there is no compositor, no seat, no session manager. Issue #31 is
by definition a Game Mode failure, so the Phase-2 fix is verifiable only on a
device that boots CachyOS Handheld Game Mode. Everything writable-blind has been
written; the rest is a hardware-gated test, not missing code.

## 9. Reference

- Field bug: LumaDeck issue #31 — "Borked install on CachyOS".
- SLSsteam `res/updates.yaml` (single-hash `ubuntu12_32 & steamdeck_stable`).
- `headcrab.sh` (Deadboy666/h3adcr-b) — `cachyoscheck`, CachyOS branches, no
  rootfs touch.
- CachyOS Handheld Edition — `gamescope-session-cachyos` (ChimeraOS
  `gamescope-session` lineage), HHD.
