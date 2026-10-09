# Components & health

LumaDeck orchestrates several independent tools. **Settings ▸ Components** shows
each one's live status with a one-line health detail underneath. This page
explains what each component is, what its states mean, and how the repair
actions map onto them.

## The components

| Component | What it does |
| --- | --- |
| **SLSsteam** | The ownership layer. Makes Steam treat configured apps as owned. |
| **lumalinux** | The native hooks in `steamclient.so` (Linux i386) that let Steam fetch and decrypt depots. This is what makes native downloads work. |
| **CloudRedirect** | Redirects Steam Cloud saves to a third-party provider. See [Cloud saves](cloud-saves.md). Ships with the base install. |
| **.NET 9 runtime** | Runtime for the bundled Steamless CLI used by [DRM removal](managing-a-game.md#remove-drm-steamless). Installed on demand via Microsoft's official installer. |

Under them, a **Steam** row shows whether the current Steam client build is one
the stack supports. LumaDeck doesn't install Steam; the row only reads
**Supported** (green) or **Not supported** (amber), with *Steam build N not
supported (target: M)* underneath when it isn't, or *Steam update available
(N → M)* when a newer supported build is out (see
[Steam build compatibility](#steam-build-compatibility)).

Headcrab is not a component and not the launcher wrapper — LumaDeck only reads its
published **compat pin** (the Steam build it supports) to check whether the current
Steam client is one the stack can hook. The break-recovery downgrade itself is
lumalinux's `downgrade.sh`, not Headcrab. The injection wrapper itself is installed
by lumalinux's `setup.sh`. For who wrote what, see the root
[README → Credits](../README.md#credits--notes).

## The status chip

Each component row shows one of three status words:

| Chip | Colour | Meaning |
| --- | --- | --- |
| **Not installed** | 🔴 red | The component isn't on disk. |
| **Installed** | 🟠 amber | It's on disk but not working right now (the sub-line says why). |
| **Active** | 🟢 green | Working. |

CloudRedirect can also read **Disabled** (grey) when you turned it off on
purpose. That is not an error. The **.NET Runtime** row has no *Active* state:
it only ever reads **Installed** (green) or **Not installed** (red).

When a component is working and a newer version exists, its sub-line shows a
blue **↑ Update available (vX → vY)** (SLSsteam shows build dates instead of
version numbers).

## The Components button

However a component breaks, from your side the fix is either **in place**
(restart or repair Steam's injection right here) or **in Desktop** (a Steam
downgrade that needs a real desktop session). The Components tab has **one
action button** whose label follows the most urgent problem:

- **Fix in Desktop** — a Steam update outpaced the hooks, so they can't attach
  to the current build. This repair needs a real desktop session (it downgrades
  Steam to a build the hooks know), so it can't run in Game Mode. The button
  opens the Desktop hand-off.
- **Finish setup** — only part of the core (SLSsteam / lumalinux) is installed.
  It installs the rest in place, then restarts.
- **Re-enable injection** — Steam is in [Recovery mode](#recovery-mode-crash-guard).
- **Repair** — a component is `not_injected`. Repair re-runs `setup.sh` first —
  rewriting the wrapper and re-affirming `.desktop`/Game-Mode coverage — then
  restarts.
- **Restart Steam** — a component is installed and injection coverage is fine,
  it just isn't live in this session. A restart reloads it.
- **Update in Desktop** — everything works, but Steam is behind a newer build
  the stack now supports. It switches to Desktop, updates Steam, and brings you
  back.
- **Install Components** / **Reinstall Components** — nothing is wrong; manual
  install on a fresh device, or a reinstall of the stack.

Every action needs a second tap: the first one says what is about to happen,
**Confirm (restarts Steam)** or **Confirm (continues in Desktop)**.

CloudRedirect has one extra case: if no cloud provider is signed in, you sign in
from the CloudRedirect app in Desktop Mode. There is no in-plugin button for it.

## Health states

The three components share one state vocabulary, keyed by cause and solution.

| State | What happened | Fix |
| --- | --- | --- |
| `healthy` | Working. | Nothing. |
| `not_installed` | The component isn't on disk. | Install from Components. |
| `not_loaded` | Installed and injected, just not live this session. | Restart Steam. |
| `not_injected` | Installed, but the wrapper's launch coverage was lost (e.g. a Steam update regenerated its `.desktop`, or the Game Mode `steam-launcher.service` drop-in was dropped). | **Repair** (re-runs `setup.sh` to rewrite the wrapper + coverage, then restarts). The QAM shows it as **Restart needed**. |
| `not_supported` | Steam updated past a build the hooks support. Cause `version` = Steam's client isn't one the component recognises; cause `hooks` = a load-bearing hook couldn't attach. (A non-critical lumalinux hook failing does not count.) | Fix in Desktop. |

Exception for `not_supported`: if only lumalinux is affected and it doesn't
support that Steam build yet, there is nothing to fix. The QAM says **Adding
games unavailable** until a lumalinux update arrives.

CloudRedirect adds two of its own:

| State | What happened | Fix |
| --- | --- | --- |
| `not_authed` | Hooks are fine, but no cloud provider is signed in. | Sign in from the CloudRedirect app in Desktop. |
| `disabled` | You turned CloudRedirect off (`~/.config/CloudRedirect/disable`). | Nothing. Re-enable in Desktop if you want it back. |

> After a **Steam client update**, the launcher `.desktop` (or the Game Mode
> `steam-launcher.service` drop-in) can be regenerated, so a launch stops routing
> through the wrapper (the deployed `.so` survives). That surfaces as `not_injected`.
> **Repair** re-runs `setup.sh` to restore coverage and restarts.
>
> LumaDeck also **self-heals** the Game Mode drop-in specifically: on every plugin
> load it rewrites `steam-launcher.service.d/lumalinux.conf` if it went missing or
> inert and `daemon-reload`s it — so a Game-Mode-only loss (components *Installed*,
> never *Active*, while Desktop works) recovers on the next Steam restart without a
> manual reinstall.

## Recovery mode (crash guard)

The launcher has a crash guard: if Steam keeps crashing at startup (three times,
or once right after a Steam update), it stops injecting and starts plain Steam
so you aren't stuck. While it's latched, every component reads *Installed*, the
sub-lines say **Paused by crash guard. Press "Re-enable injection" to resume.**,
and a plain restart doesn't help.

**Re-enable injection** (in Components or on the QAM) clears the guard and
restarts Steam with injection again. If the cause is still there, the guard
latches again after more crashes.

## What the QAM shows

The Quick Access Menu never names a specific component. It collapses component
problems into at most one row with one action:

- If any component is `not_supported`, the QAM shows **Steam build not
  supported** and a **Fix in Desktop** action. (If only lumalinux is affected
  and it doesn't support the current Steam build yet, it shows **Adding games
  unavailable** instead: an info line with no action, which clears itself once
  lumalinux catches up.)
- If setup is only half done (a core piece missing while Steam is on a supported
  build), it shows **Setup incomplete** and a **Finish setup** action.
- If Steam crashed at startup and the launcher fell back to plain Steam, it
  shows **Recovery mode** and a **Re-enable injection** action.
- If something just needs reloading (`not_loaded` / `not_injected`), it shows
  **Restart needed** and a **Restart Steam** action (for `not_injected` it
  re-runs `setup.sh` before restarting).

Below that it may list:

- **Cloud saves need sign-in** — CloudRedirect needs sign-in. A blue info line,
  not an error.
- **<game> can't update** — one row per game whose Steam update is stuck, with
  **Open game** (the fix is on the game's page).
- **Steam update available** → **Update in Desktop** — Steam can move up to a
  newer supported build.
- **Update available** → **Update** — a component update is ready. It re-runs
  `setup.sh` for the whole stack and restarts Steam.
- **LumaDeck update available** → **Download update**.

Actions that restart Steam or leave Game Mode ask for a second tap.

More generally, the Add game controls are greyed out whenever SLSsteam or
lumalinux isn't Active, or no Hubcap/Ryuu key is usable, and a line under them
says why: **Fix the problem above to add games.** or **Set up a Hubcap or Ryuu
key in Settings.**

## Steam build compatibility

The hooks patch specific byte patterns inside the Steam client, so a Steam
update can outpace them. When that happens a component reads `not_supported` and
the fix is **Fix in Desktop**, which downgrades Steam to a build the hooks know.
This is the most common cause of a component breaking after a system update.

## Game Mode vs Desktop

Some repairs need a real desktop session. For **Fix in Desktop** (and the Steam
update **Update in Desktop**) the plugin opens the Desktop hand-off for you and
returns to Game Mode when done. CloudRedirect sign-in you do yourself, from its
app in Desktop Mode. Everything else (install, Restart Steam, Repair) runs in
place. See [Troubleshooting](troubleshooting.md).
