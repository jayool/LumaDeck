# Cloud saves (CloudRedirect)

[CloudRedirect](https://github.com/Selectively11/CloudRedirect) redirects Steam
Cloud save traffic to storage you control (Google Drive, OneDrive, an
S3-compatible bucket, Cloudflare R2 or a local folder), so cloud saves keep
working for games added through LumaDeck. It is installed with the rest of the
stack; until you sign into a provider it does nothing.

## How it's installed

CloudRedirect ships with the **base install**. There's no separate
**Enable CloudRedirect** step anymore. **Install / Reinstall Components** runs
lumalinux's `setup.sh` (the wrapper-model installer), which installs SLSsteam and
CloudRedirect together, flips `DisableCloud: yes` to `no` in SLSsteam's config, and
drops the CloudRedirect Flatpak plus its `cloud_redirect.so` hook. It ends with a
Steam restart.

After this the **library is in place but no provider is signed in**, so the
Components panel shows CloudRedirect as `not_authed`.

## Sign into a provider

The provider sign-in opens a real OAuth browser flow, which Game Mode can't
drive today. So, once:

1. Switch to **Desktop mode**.
2. Open the **CloudRedirect** app from the application menu.
3. Sign into Google Drive or OneDrive, or enter your S3 / R2 credentials or a
   folder.

The tokens land at `~/.config/CloudRedirect/tokens_<provider>.json` (S3 and R2:
`s3_credentials.json`, `r2_credentials.json`). Back in
LumaDeck, the panel then shows **CloudRedirect provider: Configured** and the
health state flips to `healthy`.

## Which games it covers

Every game in SLSsteam's `AdditionalApps`, which is where LumaDeck registers the
games it adds. A game you **own** is not in that list (for an owned game
LumaDeck only adds its DLC), so its saves stay on Valve's Steam Cloud.

## A game with many save files can freeze Steam on exit

When a game writes a lot of new files in one session (replays, photos,
ghosts…), Steam uploads them all when you quit, and CloudRedirect makes Steam
wait until the upload is done. Steam's interface stops responding after about
15 seconds of waiting; with ~100 files to Google Drive the upload takes a minute
and a half, so Steam stays stuck on "Syncing" and has to be restarted. Most
games write a few files and only take a few seconds longer to close.

For a game that does this, turn its cloud sync off: in Steam, the game's
**Properties ▸ General ▸ Keep game saves in the Steam Cloud**, unticked. Steam
then skips the sync for that game and it opens and closes normally. CloudRedirect
has no per-game setting of its own.

To turn CloudRedirect off entirely, create the file
`~/.config/CloudRedirect/disable` and restart Steam. LumaDeck then shows it as
`disabled`.

## Opening the CloudRedirect app

The app checks whether its own copy of `cloud_redirect.so` matches the installed
one and, if not, offers **Update** on its Setup tab. You don't need it: LumaDeck
keeps the `.so` updated from Settings ▸ Components. With LumaDeck's install the
app may also say *"h3adcr-b not installed"*; that check looks for a different
installer and does not mean CloudRedirect isn't loaded. The Components panel is
the place to check.

## Roadmap

Driving that sign-in **entirely from Game Mode** (no Desktop trip) is tracked in
[issue #25](https://github.com/jayool/LumaDeck/issues/25). The key finding: the
32-bit `.so` that consumes the tokens reads the plain
`tokens_<provider>.json` file directly and never touches the OS keyring — so
LumaDeck only needs to write that file. Not implemented yet.

## Related

- [CloudRedirect analysis](https://github.com/jayool/lumalinux/blob/main/docs/cloudredirect.md) (Spanish) — what CloudRedirect does inside Steam and the known risks.
