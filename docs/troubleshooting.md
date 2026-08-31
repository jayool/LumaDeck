# Troubleshooting

LumaDeck surfaces problems through **banners** on the main QAM page and
**status lines** in Settings. This page decodes them and lists common fixes.

## Reading the banners

| Banner | Colour | Meaning |
| --- | --- | --- |
| **Health banner** | 🔴 red | A component is broken/inactive and needs action now. Often has a one-tap fix button (e.g. *Restart Steam*, *Reinstall*). |
| **Updates banner** | 🔵 blue | A routine update is available. Not urgent; the action lives in Settings. |
| **Credential warning** (above *Download Manifest*) | 🔴/🟠 | The Hubcap key or Ryuu cookie is expired/missing — fix it before downloading. |

Healthy components stay silent — no banner means nothing to do.

## Common problems

### A game won't download / Steam doesn't start it
- **Did the game appear in your library?** Normally it appears **without a Steam
  restart** (LumaDeck hot-reloads SLSsteam and lumalinux refreshes ownership live).
  If it doesn't show up, your Steam build may not support the live refresh — in
  that case **restart Steam** and it appears, ready to **Install**.
- Check **Components**: lumalinux and SLSsteam must be 🟢 **Active**.
- If a component shows `not_loaded`, **restart Steam**.
- If it shows `not_supported`, Steam updated past the hooks. Use **Fix in
  Desktop** (see below).

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
Discord** — in **Settings ▸ LuaTools fixes**, or on the game's Fixes tab where the
same button appears next to the greyed-out fix buttons.

You shouldn't see this often: the session renews itself in the background. Before
v0.7.4 that renewal never worked at all, so every session died one hour after
logging in (issue #42) — if you're on an older build, updating is the fix.

If it comes back immediately after logging in, check that your Deck has a working
connection: LumaDeck only reports "expired" when the server actually rejects the
session, but it can't renew one with no network either. See
[Credentials](credentials.md#luatools-account).

### "Reapply blocked in Game Mode"
Some installs/repairs need a real desktop session. The panel shows the exact
command — switch to **Desktop mode**, run it, then return to Game Mode.

### After a SteamOS / Steam client update
A Steam self-update can regenerate its launcher `.desktop` (or a DE change drops the
Game Mode `steam-launcher.service` drop-in), so a launch no longer routes through
lumalinux's injection **wrapper** (the deployed `.so` and `keys.txt` survive). This
shows as `not_injected`. Fix: **Settings ▸ Components ▸ Install / Reinstall
Components** — it re-runs `setup.sh`, which rewrites the wrapper and re-affirms
coverage, then restarts. (`steam.sh` is left vanilla; nothing patches it.)

### Components show *Installed* but never *Active* in Game Mode (Desktop works)
The Game Mode systemd drop-in (`steam-launcher.service.d/lumalinux.conf`) that routes
Game Mode through the injection wrapper went missing or wasn't loaded, so Game Mode
launches Steam un-injected — even though Desktop (which uses the `.desktop`/PATH path)
works. LumaDeck **self-heals** this on every plugin load: it rewrites the drop-in and
`daemon-reload`s it (as the `deck` user). So **update/reload LumaDeck, then restart
Steam once** and the components go Active. If it persists, run **Settings ▸ Components
▸ Install / Reinstall Components** (re-runs `setup.sh`).

### Manifest fetch fails
- Check your credentials in **Settings ▸ API Credentials** — an expired/invalid
  key or cookie is the usual cause ([Credentials](credentials.md)).
- Try the other provider if you have both configured.

### Ryuu cookie import says "couldn't decrypt"
Your cookie is keyring-encrypted (`v11`) on this setup. Paste it manually from
the browser's DevTools into the Ryuu Cookie field instead.

### CloudRedirect shows `not_authed`
No cloud provider is signed in. Sign in once from Desktop — see
[Cloud saves](cloud-saves.md).

### A specific game crashes or won't launch
Try, in order: **Repair appmanifest**, **Reconfigure SLSsteam**, **Check for
Fixes**, or (for emulator-expecting titles) **Apply Goldberg** — all on the
[game's page](managing-a-game.md).

### A Denuvo game downloads but won't launch
Denuvo validates the licence **server-side**, so faked ownership isn't enough —
a Denuvo game you don't own **downloads but won't run** on this alone. You need
either an **SLS ticket** from an owner or a **fix that strips Denuvo**. See the
Denuvo note in [Managing a game](managing-a-game.md#fixes).

## Still stuck?

- Component health logic and every state is documented in
  [Components & health](components-and-health.md).
- The hooks themselves and SteamOS-update guidance live in the
  [lumalinux maintenance docs](https://github.com/jayool/lumalinux/blob/main/docs/maintenance.md).
- Open an [issue](https://github.com/jayool/LumaDeck/issues).
