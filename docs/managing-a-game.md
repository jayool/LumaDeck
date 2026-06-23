# Managing a game

Tapping a game in **My Games** opens its detail page. Everything here is
**per-game** and most of it is optional — a normally-installed game needs none
of it. Groups are ordered from everyday to advanced.

## Status & manifest

The **Status** line reflects what's on disk:

- **Installed** — the `.lua`/config *and* the game files are present.
- **Manifest only** — the config is in place but the game files aren't
  downloaded yet (restart Steam and **Install** the game to pull them).
- **Not installed** — no `.lua` yet.

**Download Manifest** (shown as **Re-download Manifest** once the game has a
`.lua`) re-runs the manifest fetch and processing — it rewrites the config
(`keys.txt`, `config.vdf`, the `.acf` stub, …). The game files themselves are
always downloaded by Steam natively afterwards, never by the plugin. Use it
after a failed or partial install.

If your Hubcap key is expired, this page shows a **Hubcap key expired** notice
with a shortcut to fix it, instead of silently failing a re-download.

## Auto-update

A per-game toggle, **on by default** (a game stays unpinned until you pin it).
It appears only for installed games.

- **Auto-update (on)** — the game follows the latest published manifest.
- **Pinned** — frozen at the installed version; updates are held back. Useful
  when a newer build breaks a fix or a mod.

## Game management (SLSsteam)

These tell **SLSsteam** how to present the game to Steam. Each can be added or
removed, with a live status. A normal install configures them automatically —
reach for them to fix a game whose config drifted.

- **FakeAppId** — maps the game onto a fake owned app (Spacewar, AppID `480`,
  which every account owns) so Steam treats it as owned.
- **Token** — writes the game's **app access token** into SLSsteam's
  `AppTokens:`. SLSsteam uses it to query the app's product information from
  Steam; in practice it mainly fixes the *"invalid configuration"* error on some
  games. The token comes from a bundled list, or is read from the installed
  `.lua`. (This is **not** a Denuvo unlock — see the note below.)
- **DLCs** — looks up the game's DLCs from Steam's store API and marks them as
  owned so they show up in Steam.

## Goldberg

**Apply / Remove Goldberg** swaps the game's `steam_api` libraries for the
[Goldberg Steam Emulator](https://gitlab.com/nichelimux/goldberg_emulator) and
back. Use this for titles that expect an emulator rather than SLSsteam's
ownership layer. *Apply* replaces the DLLs; *Remove* restores the originals.

## Fixes

A *fix* is a community bypass/patch zip, downloaded and extracted over the
game's install folder, for titles that don't launch cleanly under SLSsteam.

- **Check for Fixes** — checks which fixes exist for this game and shows what's
  available:
  - **Generic Fix** — a general bypass.
  - **Online Fix** — a fix for online / multiplayer play.
- **Apply Online Fix** / **Apply Generic Fix** — downloads the matching zip and
  extracts it into the install folder.
- **Linux-native Fix** — a local fix for native-Linux installs (nothing is
  downloaded).
- **Installed Fixes** — lists what's applied, with **Remove Fix** / **Remove
  All Fixes** to revert.

> **Denuvo games:** lumalinux can download a Denuvo title and SLSsteam can fake
> local ownership, but Denuvo validates the licence **server-side** against an
> account that genuinely owns the game — which SLSsteam can't fabricate. So a
> Denuvo game you don't own generally **downloads but won't launch** on this
> alone. The practical way to actually play one is a **fix that strips Denuvo**
> (above), or owning it legitimately. SLSsteam's `DenuvoGames` / `FakeOffline`
> options only help narrow cases (binding an existing external activation to the
> right account, or forcing offline reauth) — they don't generate a licence.

## Remove DRM (Steamless)

**Remove DRM (Steamless)** strips SteamStub DRM from the game executable using
[Steamless](https://github.com/atom0s/Steamless) (extracted from ACCELA). It
reports back if the executable has no DRM to remove. The Steamless CLI is
downloaded on first use.

## Achievements

**Generate Achievements** creates achievement files for the game via SLScheevo.
See [Achievements](achievements.md) for setup and the bulk "sync all" option.

## Advanced options

- **Reconfigure SLSsteam** — re-runs this game's full SLSsteam setup at once:
  AdditionalApps, the app token, the depot **decryption keys** (read from the
  installed `.lua`) into `config.vdf`, and the DLCs. Use it when the config has
  drifted out of sync.
- **Repair appmanifest** — **deletes** the game's `.acf` across every library so
  Steam **regenerates** it on its next refresh. Use it when Steam has lost track
  of an installed game. (It doesn't rebuild the `.acf` by hand or restart Steam
  — pair it with **Restart Steam** when you're ready.)

## Danger zone

- **Full Uninstall** — removes the game and all of LumaDeck's config for it
  (two-tap confirm). Optional extras: **delete compatdata** and **remove the
  Proton prefix**.

> Most users never touch the management/advanced/danger groups. Reach for them
> only when a specific game misbehaves — and see [Troubleshooting](troubleshooting.md)
> first.
