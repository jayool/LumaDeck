# Viability report — reproducing CachyOS Handheld (and issue #31) in a VM

> Question asked: can we stand up CachyOS Handheld **Game Mode** in a VM (inside
> a GitHub Codespace, since that's where testing happens) and reproduce issue
> #31, given we have **no physical handheld**? This is an honest feasibility
> assessment, with confidence levels, not a plan that assumes it works.

## TL;DR verdict

- **Full CachyOS Handheld Game Mode in a Codespace VM: LOW feasibility.** The two
  hardest requirements — KVM acceleration and a real GPU for the gamescope
  compositor — are both **likely unavailable** in a Codespace. It's not flatly
  impossible, but it's a fragile, slow, high-effort path with a real chance of
  never getting a working Game Mode session.
- **The important reframe:** issue #31's *primary* symptom happened **in desktop
  mode**, which does **not** need gamescope at all. The cheapest, highest-value
  reproduction isn't a Handheld VM — it's replaying the **desktop-mode client
  downgrade + steam.sh re-patch** on the *existing* headless-Steam Codespace you
  already run. That needs no GPU and no VM.
- **What still genuinely needs real hardware:** the "black screen returning to
  Game Mode" tail, and any end-to-end confirmation of the gamescope session
  behaviour. No amount of Codespace cleverness fully replaces a handheld here.

## The two hard requirements, and where they stand

### 1. KVM acceleration — *uncertain, probably unavailable in Codespaces*

- This Claude dev container has **no `/dev/kvm`** (checked: `ls /dev/kvm` →
  not found; no `vmx`/`svm` CPU flags exposed). So *this* environment cannot
  hardware-accelerate a VM at all.
- **GitHub Codespaces is a different environment** and its KVM status is **not
  clearly documented**. GitHub *Actions* Linux runners gained nested-virt/KVM;
  Codespaces (Docker-in-VM) historically does **not** hand `/dev/kvm` to the
  container, and community reports are mixed.
- **CONFIRMED (2026-08) on the maintainer's own Codespace:** `ls -l /dev/kvm`
  → *"No such file or directory"*. **No KVM in the Codespace.** So any VM here is
  **TCG** (pure software emulation): it still boots, but ~10–50× slower — a full
  CachyOS image boot becomes many minutes and anything interactive is painful.
  Combined with the no-GPU finding below, this takes approaches **C and D from
  "gated on KVM" to "not practical in a Codespace"** — see the recalibration
  note at the end.

### 2. A GPU for gamescope — *unavailable in Codespaces*

- gamescope is a Vulkan compositor; it wants **DRM/KMS** or a nested Wayland/X
  backend, and a working Vulkan device.
- **Venus** (virtio-gpu Vulkan passthrough) is real but **requires a physical GPU
  on the host** to pass through. Codespaces have **no GPU**, so Venus is out.
- Without Venus, the guest has only **software Vulkan (lavapipe)** + virtual KMS
  (`vkms`). gamescope *can* sometimes run headless/nested on lavapipe, but the
  full **`gamescope-session-cachyos`** (seat, logind, autologin, HHD,
  firmware-update units) is built for real handheld hardware and is exactly the
  combination that "gives war" in a GPU-less VM.

**Combined:** the Handheld Game Mode session needs *both* a fast VM *and* a GPU.
In a Codespace you likely have **neither**. That's why the full-session route is
rated LOW.

## Feasibility tiers — what each approach can actually reproduce

| Approach | Needs | Reproduces #31? | Feasibility |
|---|---|---|---|
| **A. Headless Steam downgrade on the existing Codespace** (Xvfb + lavapipe, no gamescope) | what you already run | The **desktop-mode** clobber (the primary symptom) — steam.sh overwritten by the downgrade's restarts + re-patch race | **HIGH** |
| **B. Bash/systemd harness of the tracker** (no VM, no GPU) | a container | The `do_repair()` clobber mechanism (already done in `tests/test_installer_crashloop.py`) | **DONE** |
| **C. CachyOS ISO in QEMU, desktop only** (no gamescope) | KVM *or* patience (TCG) | The downgrade path on the *real* CachyOS userland (pacman, real `steam.sh`, real session-select) — but in Plasma, not Game Mode | **MEDIUM** (gated on KVM) |
| **D. CachyOS Handheld Game Mode in QEMU** (gamescope session) | KVM **and** a GPU | The full loop incl. the return-to-gamemode black screen | **LOW** |

## The reframe that matters (why D is the wrong first target)

Re-read the #31 report: *"when steam would restart (**in desktop mode**), nothing
would be injected... stuck loading. When I tried to go back to gaming mode... black
screen."*

- The **primary failure is in desktop mode** → gamescope is **not** involved →
  approaches **A** and **C** can chase it **without a GPU and without Game Mode**.
- Only the **tail** ("black screen back to Game Mode") needs the gamescope session
  (approach **D**).

So the honest ranking of what to actually do next:

1. **A first (HIGH, cheap).** On the Arch/CachyOS headless Codespace you already
   have: install a Steam client *newer than* Headcrab's pin, run the real
   LumaDeck install so it triggers the **downgrade**, and watch whether `steam.sh`
   loses the injection across the downgrade restarts and whether the re-patch
   settles. This directly targets #31's primary symptom. If it reproduces, we've
   found the bug with zero new infrastructure.
2. **C next (MEDIUM), only if A can't reproduce it** and only if your Codespace
   has `/dev/kvm`. Boot the CachyOS ISO in QEMU to desktop, repeat A on the real
   CachyOS userland (real pacman/session-select/paths). This catches anything
   CachyOS-userland-specific that a generic Arch Codespace wouldn't.
3. **D last (LOW), realistically device-only.** Full Game Mode. If Codespace KVM
   or GPU is missing, this is not worth fighting — it's cheaper to get **logs
   from a real CachyOS Handheld user** (offer an `inhibit-short-session-tracker`
   + verbose-logging build) than to fake a handheld in a GPU-less VM.

## Concrete first experiment (approach A) — no new infra

On the existing headless Codespace:

1. Note the current `steam.sh` injection state (`_lumalinux_injected_in_steam_sh`).
2. Force Steam **off** Headcrab's pin (install/keep a newer client) so the install
   takes the **downgrade / Desktop** path (`gamemode=False`).
3. Run `install_dependencies(gamemode=False)` and capture, across each Steam
   restart: does `~/.local/share/Steam/ubuntu12_32/steam.sh` still contain the
   `# >>> lumalinux launcher patch >>>` block? Does the 60s settle poll
   (`installer.py`) ever see `INJECT_SLS` come back, or does Steam hang first?
4. If the block disappears and never returns → **that is #31**, reproduced with no
   GPU. If it always returns cleanly → the desktop path is fine and the bug is
   something CachyOS-userland-specific (escalate to C or to a real user's logs).

## What a real device / real logs would settle that a VM can't

- Why Steam **hangs** on the downgrade restart on CachyOS specifically ("stuck
  loading") — timing/GPU/driver, unlikely to reproduce GPU-less.
- The gamescope session's actual behaviour on the return-to-Game-Mode path.
- HHD / firmware-update unit interactions unique to handheld hardware.

## Recalibration after the confirmed no-KVM finding

The no-`/dev/kvm` result forces an honest downgrade of the options:

- **C (desktop CachyOS in QEMU) is now TCG-only** — technically possible, but a
  CachyOS ISO under pure software emulation is slow enough that it's poor ROI for
  iterative debugging. Keep it as a last-resort "real CachyOS userland" option,
  not a daily driver.
- **SUPERSEDED — we built a real CachyOS *container* instead.** The earlier
  framing ("the Codespace runs Arch, so approach A only re-confirms the generic
  path; the best we can do headless is vendor CachyOS's session scripts onto
  Arch — A′") is no longer the ceiling. A **container** (unlike a VM) needs
  **neither KVM nor a GPU** — it's just the CachyOS userland on the host kernel.
  So the port-testing devcontainer was rebuilt on a genuine CachyOS userland
  (`.devcontainer/port-testing/` in the lumalinux repo): CachyOS optimized repos
  via `cachyos-repo.sh`, `ID=cachyos`, and the **real** `gamescope-session-cachyos`
  scripts (`steamos-session-select`, `steam-short-session-tracker`). That gives
  approach A on **real CachyOS userland**, not Arch — so it *can* now surface
  CachyOS-userland-specific behaviour, which A′'s hand-vendored scripts only
  approximated.
- **Still out of reach in any container: the gamescope Game Mode compositor**
  (no GPU/seat). And **#31's hang** remains CachyOS-driver/timing-specific, so
  **real-user logs** stay the highest-signal path for the actual "stuck loading"
  — a diagnostic build (verbose install logging + steam.sh state dumped across
  each downgrade restart) handed to a CachyOS Handheld user beats any GPU-less env.

## Bottom line

Don't build a CachyOS Handheld **VM** — confirmed no KVM and no GPU make the full
Game-Mode route impractical here. But a CachyOS **container** needs neither, so
that's what we run. Ranked by signal-per-effort now:

1. **Approach A on the real CachyOS container** (`.devcontainer/port-testing/`) —
   drive the desktop-mode downgrade on genuine CachyOS userland and watch whether
   `steam.sh` loses/regains the injection. Reproduces #31's *primary* (desktop)
   symptom if it's userland-side.
2. **Real-user diagnostic build** — instrument, ship to a CachyOS Handheld user,
   read the logs. Highest signal for the actual gamescope-session hang.
3. **C** — TCG QEMU of CachyOS desktop, only if 1–2 are inconclusive and something
   needs a booted system rather than a container.
4. **D** — full Game Mode compositor: real device only.
