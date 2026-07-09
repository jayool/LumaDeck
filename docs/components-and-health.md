# Components & health

LumaDeck orchestrates several independent tools. **Settings ▸ Dependencies**
shows each one's live state (🟢 installed, 🔴 missing) with a one-line health
detail underneath. This page explains what each component is and what its
states mean.

## The components

| Component | What it does |
| --- | --- |
| **SLSsteam** | The ownership / licensing layer — makes Steam treat configured apps as owned. |
| **.NET 9 runtime** | Runtime needed by the bundled Steamless CLI used by [DRM removal](managing-a-game.md#remove-drm-steamless). Installed on demand via Microsoft's official installer. |
| **lumalinux** | The native hooks in `steamclient.so` (Linux i386) that let Steam fetch and decrypt depots. This is what makes native downloads work. |
| **CloudRedirect** *(optional)* | Redirects Steam Cloud saves to a third-party provider. See [Cloud saves](cloud-saves.md). |
| **Headcrab** | The SLSsteam launcher wrapper. Its build-ID must match the current Steam client (the panel checks this). |

For who wrote what, see the root [README → Credits](../README.md#credits--notes).

## Steam build compatibility

The hooks patch specific byte patterns inside the Steam client, so a Steam
update can outpace them. The panel shows **Steam build OK** or a **build
mismatch** with the target build. A mismatch usually means: reapply the
component, and if it's blocked in Game Mode, do it from Desktop.

## Health states

### SLSsteam

| State | Meaning / fix |
| --- | --- |
| `healthy` | Working. |
| `not_installed` | Install it from Dependencies. |
| `not_active` | Installed but not injected — restart Steam. |
| `injection_missing` | The injection isn't in place — reapply / restart. |
| `broken` (`patterns`) | Steam updated past the hook's byte patterns — reapply (often from Desktop). |
| `broken` (`hash`) | The binary hash no longer matches — reapply. |

### lumalinux

| State | Meaning / fix |
| --- | --- |
| `healthy` | Working. |
| `not_installed` | Install / Reapply lumalinux. |
| `not_active` | Deployed but not loaded — restart Steam. |
| `hash_blocked` | A guard blocked loading against an unexpected binary — reapply. |
| `hooks_failed` | One or more hooks failed to apply (the detail names which). |

> After a **Headcrab/SLSsteam update**, Headcrab regenerates `steam.sh` and
> erases lumalinux's `LD_PRELOAD` block (the deployed `.so` survives). Fix it
> with **Install / Reapply lumalinux**.

### CloudRedirect

| State | Meaning / fix |
| --- | --- |
| `healthy` | Working and signed in. |
| `not_installed` | Install / Reinstall Dependencies — CloudRedirect ships with the base install. |
| `not_active` | Installed but not loaded — restart Steam. |
| `broken` | The hook failed — reinstall. |
| `not_authed` | No cloud provider signed in — sign in from Desktop ([Cloud saves](cloud-saves.md)). |
| `kill_switched` | Intentionally disabled. |

## Game Mode vs Desktop

Some repair/install actions can't run in Game Mode (they need a real desktop
session) and the panel will say so, with the exact command to run. This is most
common when reapplying hooks after a client update. See
[Troubleshooting](troubleshooting.md).
