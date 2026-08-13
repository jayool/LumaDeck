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

Headcrab is not a component and not the launcher wrapper — LumaDeck only reads its
published **compat pin** (the Steam build it supports) to check whether the current
Steam client is one the stack can hook, and to drive the break-recovery downgrade. The
injection wrapper itself is installed by lumalinux's `setup.sh`. For who wrote what,
see the root [README → Credits](../README.md#credits--notes).

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

- **Restart Steam** (in place). The component is installed and injection coverage is
  fine, it just isn't live in this session. A restart reloads it. The button may read
  **Restart Steam** or **Repair** (Repair re-runs `setup.sh` first — rewriting the
  wrapper and re-affirming `.desktop`/Game-Mode coverage — then restarts).
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
| `not_injected` | Installed, but the wrapper's launch coverage was lost (e.g. a Steam update regenerated its `.desktop`, or the Game Mode `steam-launcher.service` drop-in was dropped). | Reinstall Components (re-runs `setup.sh` to rewrite the wrapper + coverage, then restarts). |
| `not_supported` | Steam updated past a build the hooks support. Cause `version` = the binary hash isn't recognised; cause `hooks` = a specific hook couldn't attach. | Fix in Desktop. |

CloudRedirect adds two of its own:

| State | What happened | Fix |
| --- | --- | --- |
| `not_authed` | Hooks are fine, but no cloud provider is signed in. | Sign in from the CloudRedirect app in Desktop. |
| `disabled` | You turned CloudRedirect off (`~/.config/CloudRedirect/disable`). | Nothing. Re-enable in Desktop if you want it back. |

> After a **Steam client update**, the launcher `.desktop` (or the Game Mode
> `steam-launcher.service` drop-in) can be regenerated, so a launch stops routing
> through the wrapper (the deployed `.so` survives). That surfaces as `not_injected`.
> **Reinstall Components** re-runs `setup.sh` to restore coverage and restarts.
>
> LumaDeck also **self-heals** the Game Mode drop-in specifically: on every plugin
> load it rewrites `steam-launcher.service.d/lumalinux.conf` if it went missing or
> inert and `daemon-reload`s it — so a Game-Mode-only loss (components *Installed*,
> never *Active*, while Desktop works) recovers on the next Steam restart without a
> manual reinstall.

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
