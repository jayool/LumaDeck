# Porting LumaDeck (+ lumalinux) to other distros — starting with CachyOS

> Status: **design / not started**. This is the planning contract for adding
> non-SteamOS support. It exists so the work stays additive and **cannot regress
> the tested SteamOS path**. Read the "Non-regression invariants" section before
> writing any code.

## 1. Goal & scope

Make LumaDeck usable on non-SteamOS distros that run Steam in **Game Mode /
Big Picture Mode** with **Decky Loader**. First target: **CachyOS**. The
architecture stays generic (a platform layer) so other distros can slot in
later, but only CachyOS is in scope for now.

**Explicitly out of scope for this pass:** Flatpak/Snap Steam, Bazzite
(Fedora-atomic, no `pacman`), and any distro-specific work beyond CachyOS. The
platform layer must leave room for them without committing to them.

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

That the plugin reported **everything injected on first boot** is the key
signal: the hooking core *did* load and hook on CachyOS. The failure is entirely
**downstream, in the session/crash-loop layer** — exactly the environment layer
this document scopes. Most likely root cause (symptom↔code, not log-confirmed):

- CachyOS ships a newer Steam than Headcrab's pin, so the install triggers the
  **client downgrade** (multiple Steam restarts).
- LumaDeck neutralises SteamOS's crash-loop detector by removing
  `/tmp/steamos-short-session-tracker` (`installer.py` `_SESSION_TRACKER_RESET`,
  ~L166-170). That path is **SteamOS/HoloISO-specific**. CachyOS Handheld runs
  `gamescope-session-cachyos` (ChimeraOS `gamescope-session` lineage) with its
  **own** short-session mechanism → the reset is a no-op → the downgrade's
  restarts trip CachyOS's detector → it wipes `~/.local/share/Steam` → "nothing
  injected on restart" + black screen.

(Correction from earlier analysis: CachyOS Handheld **does** provide a
`steamos-session-select` wrapper via the ChimeraOS base, so the session-switch
call in `desktop_handoff.py` is likely *not* the primary culprit — persistence
semantics differ, but the binary exists. The crash-loop tracker mismatch is the
strong cause.)

## 3. CachyOS: two editions, very different for us

| | Desktop Edition | Handheld Edition |
|---|---|---|
| Boots to | KDE desktop | **Game Mode** (`gamescope-session-cachyos`) |
| Steam UI | window / **Big Picture Mode** | gamescope session |
| Crash-loop detector | none | **yes** (ChimeraOS lineage) |
| Session switch | n/a | `steamos-session-select` (ChimeraOS-provided), persistence via `~/.config/last-session-mode` |
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
  family (SteamOS vs ChimeraOS/CachyOS)? This gates the crash-loop and
  session-switch behavior.

Use the existing **`dev` override mechanism** (already used in
`paths.py` health functions via `dev.get(...)`) to add a **platform override**,
so both branches can be exercised without hardware.

## 6. Phased plan

- **Phase 0 — platform layer.** Build the detection/abstraction module above,
  SteamOS-as-default from line one. Prerequisite for everything; cheap; shared
  across editions. *This is where we start.*
- **Core cold-check (lumalinux side).** Fetch the **desktop-channel**
  `steamclient.so` for Headcrab's pinned build and run lumalinux's
  `check_patterns.py` + hash gate against it, to confirm the "identical binary"
  conclusion for the exact pinned build. Fix the now-outdated comment in
  `tools/fetch_steamclient.py` ("DIFFERENT builds with different hashes") and
  ensure lumalinux's own `res/updates.yaml` whitelist stays in sync with the
  build Headcrab pins. (#31 already gives strong empirical support that the core
  works on CachyOS.)
- **Phase 1 — environment fixes → Desktop/BPM works E2E.** Route all consumers
  through the platform layer: user/home, Steam root, cache/config/status paths.
  Milestone: a clean, testable end-to-end install on **CachyOS Desktop + Big
  Picture Mode**, with no session/crash-loop code involved.
- **Phase 2 — Handheld Edition.** Route the initial downgrade through the
  Desktop hand-off (safe, no crash-loop detector), then adapt: the crash-loop
  reset to CachyOS's mechanism (not `/tmp/steamos-short-session-tracker`), and
  the session-switch/persistence to CachyOS's `steamos-session-select` +
  `~/.config/last-session-mode`. This is what actually closes issue #31.

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

## 8. Open questions / to verify

- Exact short-session/crash-loop mechanism of `gamescope-session-cachyos` (file
  path / service) so the Phase-2 reset targets the right thing.
- `steamos-session-select` argument names on CachyOS (`gamescope` / `plasma` /
  `desktop`?) and whether the persistence rewrite interferes with the hand-off.
- Confirm `~/.steam/steam` → `~/.local/share/Steam` symlink on a stock CachyOS
  Steam install.
- Whether Decky runs as root on CachyOS Handheld the same way it does on SteamOS
  (affects the `~`-is-`/root` assumption).

## 9. Reference

- Field bug: LumaDeck issue #31 — "Borked install on CachyOS".
- SLSsteam `res/updates.yaml` (single-hash `ubuntu12_32 & steamdeck_stable`).
- `headcrab.sh` (Deadboy666/h3adcr-b) — `cachyoscheck`, CachyOS branches, no
  rootfs touch.
- CachyOS Handheld Edition — `gamescope-session-cachyos` (ChimeraOS
  `gamescope-session` lineage), HHD.
