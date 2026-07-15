# Components & health

LumaDeck orchestrates several independent tools. **Settings ▸ Components** shows
each one's live status with a one-line health detail underneath. This page
explains what each component is, what its states mean, and how the two repair
actions map onto them.

## The components

| Component | What it does |
| --- | --- |
| **SLSsteam** | The ownership layer. Makes Steam treat configured apps as owned. |
| **lumalinux** | The native hooks in `steamclient.so` (Linux i386) that let Steam fetch and decrypt depots. This is what makes native downloads work. |
| **CloudRedirect** | Redirects Steam Cloud saves to a third-party provider. See [Cloud saves](cloud-saves.md). Ships with the base install. |
| **.NET 9 runtime** | Runtime for the bundled Steamless CLI used by [DRM removal](managing-a-game.md#remove-drm-steamless). Installed on demand via Microsoft's official installer. |

Headcrab is the SLSsteam launcher wrapper. It is not a row in the panel, but the
panel checks that its build ID matches the current Steam client. For who wrote
what, see the root [README → Credits](../README.md#credits--notes).

## The status chip

Each component row shows one of three status words:

| Chip | Colour | Meaning |
| --- | --- | --- |
| **Not installed** | 🔴 red | The component isn't on disk. |
| **Installed** | 🟠 amber | It's on disk but not working right now (the sub-line says why). |
| **Active** | 🟢 green | Working. |

CloudRedirect can also read **Disabled** (grey) when you turned it off on
purpose. That is not an error.

## Two ways to fix things

However a component breaks, from your side there are only ever two fixes:

- **Restart Steam** (in place). The component is installed and its `steam.sh`
  injection is fine, it just isn't live in this session. A restart reloads it.
  The button may read **Restart Steam** or **Repair** (Repair also re-patches
  `steam.sh` first, then restarts).
- **Fix in Desktop**. A Steam update outpaced the hooks, so they can't attach to
  the current build. This repair needs a real desktop session (it downgrades
  Steam to a build the hooks know), so it can't run in Game Mode. The button
  opens the Desktop hand-off and asks you to confirm once.

CloudRedirect has one extra case: if no cloud provider is signed in, you sign in
from the CloudRedirect app in Desktop Mode. There is no in-plugin button for it.

## Health states

The three components share one state vocabulary, keyed by cause and solution.

| State | What happened | Fix |
| --- | --- | --- |
| `healthy` | Working. | Nothing. |
| `not_installed` | The component isn't on disk. | Install from Components. |
| `not_loaded` | Installed and injected, just not live this session. | Restart Steam. |
| `not_injected` | Installed, but `steam.sh` lost its injection line (usually after a Headcrab/SLSsteam update regenerates `steam.sh`). | Repair (re-injects `steam.sh`, then restarts). |
| `not_supported` | Steam updated past a build the hooks support. Cause `version` = the binary hash isn't recognised; cause `hooks` = a specific hook couldn't attach. | Fix in Desktop. |

CloudRedirect adds two of its own:

| State | What happened | Fix |
| --- | --- | --- |
| `not_authed` | Hooks are fine, but no cloud provider is signed in. | Sign in from the CloudRedirect app in Desktop. |
| `disabled` | You turned CloudRedirect off (`~/.config/CloudRedirect/disable`). | Nothing. Re-enable in Desktop if you want it back. |

> After a **Headcrab/SLSsteam update**, Headcrab regenerates `steam.sh` and
> drops lumalinux's injection block (the deployed `.so` survives). That surfaces
> as `not_injected`. **Repair** puts the line back and restarts.

## What the QAM shows

The Quick Access Menu never names a specific component. It collapses everything
into at most one action:

- If any component is `not_supported`, the QAM shows **Steam build not
  supported** and a **Fix in Desktop** action.
- If setup is only half done (a core piece missing while Steam is on a supported
  build), it shows **Setup incomplete** and a **Finish setup** action.
- If something just needs reloading (`not_loaded` / `not_injected`), it shows
  **Restart needed** and a **Restart Steam** action.
- CloudRedirect needing sign-in shows as a blue info line, not an error.

If lumalinux specifically can't add games on the current Steam build, the QAM
also shows **Adding games unavailable**, and the Add game button is greyed out
until it's resolved.

## Steam build compatibility

The hooks patch specific byte patterns inside the Steam client, so a Steam
update can outpace them. When that happens a component reads `not_supported` and
the fix is **Fix in Desktop**, which downgrades Steam to a build the hooks know.
This is the most common cause of a component breaking after a system update.

## Game Mode vs Desktop

Some repairs can't run in Game Mode because they need a real desktop session
(the Steam downgrade behind **Fix in Desktop**, and CloudRedirect sign-in). The
plugin says so and opens the Desktop hand-off for you. Everything else (install,
Restart Steam, Repair) runs in place. See [Troubleshooting](troubleshooting.md).
