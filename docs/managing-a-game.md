# Managing a game

Tapping a game in **My Games** opens its detail page. Everything here is
**per-game** and most of it is optional — a normally-installed game needs none
of it. Groups are ordered from everyday to advanced.

## Status & manifest

The **Status** line reflects what's on disk:

- **Installed** — the `.lua`/config *and* the game files are present.
- **Manifest only** — the config is in place but the game files aren't
  downloaded yet (**Install** the game in Steam to pull them; no restart needed
  in the normal case — restart only if the game isn't showing in your library).
- **Not installed** — no `.lua` yet.

**Download Manifest** (shown as **Re-download Manifest** once the game has a
`.lua`) re-runs the manifest fetch and processing — it rewrites the config
(`keys.txt`, `config.vdf`, the SLSsteam entry, …). The game files themselves are
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

- **FakeAppId** — makes the game present itself as Spacewar (AppID `480`) so its
  Steam networking (lobbies, matchmaking, P2P) works, for playing **online** on
  titles that use Steam's servers. It does **not** grant ownership — that's
  AdditionalApps. SLSsteam tracks the real AppID per launch, so don't run two
  FakeAppId-enabled games at once.
- **Token** — writes the game's **app access token** into SLSsteam's
  `AppTokens:`. SLSsteam uses it to query the app's product information from
  Steam; in practice it mainly fixes the *"invalid configuration"* error on some
  games. The token comes from a bundled list, or is read from the installed
  `.lua`. (This is **not** a Denuvo unlock — see the note below.)
- **DLCs** — looks up the game's DLCs from Steam's store API and marks them as
  owned so they show up in Steam.

## Goldberg

**Apply / Remove Goldberg** swaps the game's `steam_api` libraries for the
[Goldberg emulator (gbe_fork)](https://github.com/Detanup01/gbe_fork) and
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
> local ownership, but Denuvo validates the licence **server-side**, which needs
> a real **app ticket** from an account that owns the game — something SLSsteam
> can't fabricate. So a Denuvo game you don't own generally **downloads but
> won't launch** on this alone. Two ways to actually play one:
>
> - **An SLS ticket** — a small text file an owner generates for the game. Drop
>   it into `~/.config/SLSsteam/cache` and SLSsteam activates the title (these
>   also work on many other DRM types). This route needs **clean Steam files**:
>   the original `steam_api`, so **don't apply Goldberg** on that game. You get
>   the ticket from an owner (e.g. the SLSsteam community), and **LumaDeck
>   doesn't manage tickets** — you place the file in that folder yourself.
> - **A fix/crack that strips Denuvo** (the Fixes section above).
>
> SLSsteam's `DenuvoGames` setting is **not** a bypass — it only stops an appId
> from unlocking unless the SteamId matches, which keeps external activations
> from breaking across accounts.

## Remove DRM (Steamless)

**Remove DRM (Steamless)** strips SteamStub DRM from the game executable using
[Steamless](https://github.com/atom0s/Steamless), which ships **bundled with the
plugin**. It reports back if the executable has no DRM to remove. The only
prerequisite is the .NET 9 runtime, installed on demand on first use.

## Achievements

Achievements work **natively** for games LumaDeck adds — SLSsteam handles them, so
there's no per-game step here. (The old **Generate Achievements** generator is hidden
behind a flag; see [Achievements](achievements.md).)

## Advanced options

- **Reconfigure SLSsteam** — re-runs this game's full SLSsteam setup at once:
  AdditionalApps, the app token, the depot **decryption keys** (read from the
  installed `.lua`) into `config.vdf`, and the DLCs. Use it when the config has
  drifted out of sync.
- **Repair appmanifest** — **deletes** the game's `.acf` across every library so
  Steam **regenerates** it on its next refresh. Use it when Steam has lost track
  of an installed game. (It doesn't rebuild the `.acf` by hand or restart Steam
  — pair it with **Restart Steam** when you're ready.)

## The leftover-manifest sweep (automatic)

There is one thing LumaDeck does to your `.acf` files **without being asked**, so
it's documented here rather than hidden: on every plugin load it looks for
leftover manifests from a bug it used to have, and removes them.

**Where they came from.** Older versions wrote a placeholder `.acf` into the
default library the moment you *added* a game — before you had chosen where to
install it. Pick any other drive and that placeholder is stranded: Steam reads it,
concludes the game isn't installed, and re-downloads the whole thing into the
default library (issue #41). Nothing creates these any more, but a Deck that added
games under an older version may still be carrying some.

**What it will and won't remove.** A leftover only goes if a **real** manifest for
the same game exists in a **different** library — that is, if it is provably
redundant. Everything else is left alone, deliberately:

- fewer than two libraries (nothing to compare, and the placeholder was
  overwritten in place anyway)
- a manifest LumaDeck can't parse, or a library it can't read (an unmounted SD
  card, say)
- a download in flight for that game
- anything that isn't exactly placeholder-shaped — a queued install, a
  half-finished one, anything unfamiliar
- a lone placeholder with no real manifest anywhere: it only makes the grid say
  "installed" when it isn't, and there's no way to prove it's ours rather than
  something Steam has queued

The shape is read from the file at the moment of deletion, never from a saved
record, so it can't act on stale bookkeeping.

**Seeing it.** Every removal is written to the Decky log with the manifest that
justified it. It takes effect on the next Steam start.

**Turning it off.** Create the file `~/.config/lumalinux/no_acf_sweep`, or set
`LUMA_NO_ACF_SWEEP` in the environment. It's on by default and has its own switch,
unrelated to any other.

## Danger zone

- **Full Uninstall** — removes the game and all of LumaDeck's config for it
  (two-tap confirm). Optional extras: **delete compatdata** and **remove the
  Proton prefix**.

> Most users never touch the management/advanced/danger groups. Reach for them
> only when a specific game misbehaves — and see [Troubleshooting](troubleshooting.md)
> first.
