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

### "Reapply blocked in Game Mode"
Some installs/repairs need a real desktop session. The panel shows the exact
command — switch to **Desktop mode**, run it, then return to Game Mode.

### After a SteamOS / Steam client update
Headcrab regenerates `steam.sh` and erases lumalinux's `LD_PRELOAD` block (the
deployed `.so` and `keys.txt` survive). This shows as `not_injected`. Fix:
**Settings ▸ Components ▸ Repair** (re-injects `steam.sh`, then restarts).

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
