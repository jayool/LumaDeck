# Troubleshooting

LumaDeck surfaces problems through a **status list** at the top of the main QAM
page and **status lines** in Settings. This page decodes them and lists common
fixes.

## Reading the status list

| Row | Colour | Meaning |
| --- | --- | --- |
| **Problem rows** | 🟠 orange ⚠ | A component is broken/inactive (or a game's update is stuck) and needs action now. Usually has a fix button (e.g. *Restart Steam*, *Fix in Desktop*); actions that restart Steam or leave Game Mode ask for a second tap. |
| **Info rows** | 🔵 blue ↑ | A component, Steam or LumaDeck update is available, cloud saves need sign-in, or adding games is paused until lumalinux supports this Steam build. Not urgent; update rows have their own button. |
| **No usable key** (orange, under *Add Game*) | 🟠 | No valid Hubcap key or Ryuu session: *Set up a Hubcap or Ryuu key in Settings.* Adding is disabled until you fix it in **Settings ▸ API Credentials**. On a game page, a failed re-download shows **Hubcap API key expired** / **Ryuu session expired** with an *Open Settings* button. |

Every row is explained in [Components & health → What the QAM shows](components-and-health.md#what-the-qam-shows).

Healthy components stay silent — an empty list means nothing to do.

## Common problems

### A game won't download / Steam doesn't start it
- **Did the game appear in your library?** Normally it appears **without a Steam
  restart** (LumaDeck hot-reloads SLSsteam and lumalinux refreshes ownership live).
  If it doesn't show up, your Steam build may not support the live refresh — in
  that case **restart Steam** and it appears, ready to **Install**.
- Check **Components**: lumalinux and SLSsteam must be 🟢 **Active**.
- If a component shows `not_loaded`, **restart Steam**.
- If it shows `not_supported`, Steam updated past the hooks. Use **Fix in
  Desktop** (see [Components & health](components-and-health.md#steam-build-compatibility)).

### A game on a second drive or SD card shows as Not Installed
The game downloaded fine, but after a Steam restart it's back to **Install** —
and pressing it re-downloads everything into the internal drive.

This was issue #41, fixed in v0.7.4. Older versions wrote a placeholder manifest
into the default library when you *added* a game, before you had chosen a drive.
Install anywhere else and Steam finds that placeholder, believes the game isn't
installed, and starts over.

Nothing creates them any more, and LumaDeck **removes the ones already on your
Deck by itself** — see [the leftover-manifest sweep](managing-a-game.md#the-leftover-manifest-sweep-automatic),
which also explains how to turn it off. Update, restart Steam once, and the game
should come back as installed with no re-download.

The same fix covers a related symptom: games on a second library showing **greyed
out** in LumaDeck's own list even though they were installed. LumaDeck used to
look for game files in the default library only.

### LuaTools says "Session expired"
Your lua.tools login has run out and couldn't be renewed. Tap **Log in with
Discord** — in **Settings ▸ API Credentials ▸ LuaTools fixes**, or on the game's
**Fixes & Repairs** / **Online Fixes** tab, where the same button appears above the
greyed-out fix buttons.

You shouldn't see this often: the session renews itself in the background. Before
v0.7.4 that renewal never worked at all, so every session died one hour after
logging in (issue #42) — if you're on an older build, updating is the fix.

If it comes back immediately after logging in, check that your Deck has a working
connection: LumaDeck only reports "expired" when the server actually rejects the
session, but it can't renew one with no network either. See
[Credentials](credentials.md#luatools-account).

### "Switch to Desktop Mode now"
Some repairs (**Fix in Desktop**, **Update in Desktop**) run in Desktop Mode.
LumaDeck switches there for you, runs the task, and returns to Game Mode when it
succeeds. If the switch can't start on its own, the toast asks you to switch to
Desktop Mode yourself; the task is already armed and runs when you get there. If
the task fails, it stays in Desktop so you can read the error.

### QAM shows "Recovery mode"
Steam crashed at startup, so the launcher's crash guard started plain Steam,
without injection. Nothing LumaDeck adds works until it's lifted, and a plain
restart doesn't lift it. Press **Re-enable injection** (on the QAM row, or in
**Settings ▸ Components**). If Steam keeps crashing, the guard latches again;
see [Components & health → Recovery mode](components-and-health.md#recovery-mode-crash-guard).

### QAM shows "Adding games unavailable"
lumalinux doesn't support the current Steam build yet. Nothing is broken and there
is nothing to press: wait for a lumalinux update, and the row clears itself. Until
then adding games is paused.

### "Fix the problem above to add games."
The Add game controls are greyed out because SLSsteam or lumalinux isn't
**Active**. Use the action on the QAM's problem row (or the button in
**Settings ▸ Components**). If the line says **Set up a Hubcap or Ryuu key in
Settings.** instead, no usable key is configured — see [Credentials](credentials.md).

### QAM shows "Steam update available"
After a break, the stack now supports a newer Steam build than the one you're on.
**Update in Desktop** switches to Desktop, updates Steam, and brings you back. Not
urgent.

### After a SteamOS / Steam client update
A Steam self-update can regenerate its launcher `.desktop` (or a DE change drops the
Game Mode `steam-launcher.service` drop-in), so a launch no longer routes through
lumalinux's injection **wrapper** (the deployed `.so` and `keys.txt` survive). This
shows as `not_injected`. Fix: **Settings ▸ Components ▸ Repair** (or **Restart
Steam** on the QAM's *Restart needed* row) — it re-runs `setup.sh`, which rewrites
the wrapper and re-affirms coverage, then restarts. (`steam.sh` is left vanilla; nothing patches it.)

### Components show *Installed* but never *Active* in Game Mode (Desktop works)
The Game Mode systemd drop-in (`steam-launcher.service.d/lumalinux.conf`) that routes
Game Mode through the injection wrapper went missing or wasn't loaded, so Game Mode
launches Steam un-injected — even though Desktop (which uses the `.desktop`/PATH path)
works. LumaDeck **self-heals** this on every plugin load: it rewrites the drop-in and
`daemon-reload`s it (as the `deck` user). So **update/reload LumaDeck, then restart
Steam once** and the components go Active. If it persists, press **Repair** (or
**Reinstall Components**) in **Settings ▸ Components** (re-runs `setup.sh`).

### Manifest fetch fails
- Check your credentials in **Settings ▸ API Credentials** — an expired/invalid
  key or cookie is the usual cause ([Credentials](credentials.md)).
- Try the other provider if you have both configured.

### Ryuu login doesn't complete
Press **Log in with Discord** in **Settings ▸ API Credentials ▸ Ryuu Cookie** and
finish the login in the browser that opens; LumaDeck picks up the session by
itself. If it says *Ryuu login timed out*, paste the cookie manually from the
browser's DevTools into the Ryuu Cookie field and press **Save Cookie**.

### CloudRedirect shows `not_authed`
No cloud provider is signed in. Sign in once from Desktop — see
[Cloud saves](cloud-saves.md).

### A specific game crashes or won't launch
Try, in order: **Repair Appmanifest**, **Reconfigure SLSsteam**, **Check for
Fixes**, or (for emulator-expecting titles) **Apply Goldberg** — all on the
game's [Fixes & Repairs](managing-a-game.md#fixes--repairs) tab.

### A Denuvo game downloads but won't launch
Denuvo validates the licence **server-side**, so faked ownership isn't enough —
a Denuvo game you don't own **downloads but won't run** on this alone. You need
either an **SLS ticket** from an owner or a **fix that strips Denuvo**. See the
Denuvo note in [Managing a game](managing-a-game.md#fixes).

## A game loops on "No internet connection" / stays on Update queued

Steam wants a manifest it cannot get. It happens when Steam needs a manifest
for a game you don't own, no request-code provider answered, and the manifest
Steam plans is not in `depotcache/` — typically a game added before LumaDeck
pinned games by default, or a manifest Steam purged. When no provider is
answering, LumaDeck's background job pins the game to its installed build and
puts missing manifests back within a minute; Steam picks the file up on its next
retry (~30 s) and the loop ends by itself. If it persists, open the game (the QAM
may list it as *<game> can't update*) and press **Fix Update** on the **Updates**
tab (it re-fetches the game's manifest from Hubcap or Ryuu), or **Re-download
Manifest** if Fix Update isn't shown, then restart Steam.

## Still stuck?

- Component health logic and every state is documented in
  [Components & health](components-and-health.md).
- The hooks themselves and SteamOS-update guidance live in the
  [lumalinux maintenance docs](https://github.com/jayool/lumalinux/blob/main/docs/maintenance.md).
- Open an [issue](https://github.com/jayool/LumaDeck/issues).
