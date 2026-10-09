# Managing a game

Tapping a game in **My Games** opens its detail page. Everything here is
**per-game** and most of it is optional — a normally-installed game needs none
of it. The page has a sidebar with tabs, ordered from everyday to advanced:
**Status**, **Updates**, **Fixes & Repairs**, **Online Fixes** and **Uninstall**.

For a game your Steam account **owns** (LumaDeck only added its DLC), several
controls are hidden or disabled: Auto-update, Change version, Fix Update and
Online don't apply to it.

## Status

The **Status** tab has one row labelled `AppID <id>`. Its coloured value is the
game's state, and the install path sits underneath:

- **Installed** — the `.lua`/config *and* the game files are present (the
  game's size is shown next to it).
- **Ready to download** — the config is in place but the game files aren't
  downloaded yet (**Install** the game in Steam to pull them; no restart needed
  in the normal case — restart only if the game isn't showing in your library).
- **DLC added (owned game)** — you own the game; LumaDeck added only its DLC.

With no `.lua` yet the row shows only the AppID (for a game your account owns,
an **Owned game** note appears instead: *Only its DLC will be added.*).

For an installed game a **Version** row shows its build: `Build N · Latest`
while Auto-update is on, `Build N · Frozen` after a version change (see
[Change version](#change-version)).

## Updates

On the **Updates** tab, **Download Manifest** (shown as **Re-download Manifest**
once the game has a `.lua`) re-runs the manifest fetch and processing — it
rewrites the config (`keys.txt`, `config.vdf`, the SLSsteam entry, …). The game
files themselves are always downloaded by Steam natively afterwards, never by
the plugin. Use it after a failed or partial install. While it runs, a progress
bar replaces the button, with a **Cancel Download** button under it.

If a re-download fails because a credential was rejected, this tab shows a
**Hubcap API key expired** or **Ryuu session expired** notice (both, when both
were rejected) with an **Open Settings** shortcut, instead of a generic failure.

If LumaDeck sees that Steam couldn't apply an update to this game, the tab also
shows **Update stuck** with a **Fix Update** button. It re-fetches the game's
manifest the same way as **Re-download Manifest**, so it needs a valid Hubcap
key or Ryuu session. The QAM lists such a game as *<game> can't update*, with
an **Open game** button that brings you here.

### Auto-update

A per-game toggle on the Updates tab, **on by default**. It appears only for
installed games LumaDeck added (not for a game your account owns).

See [Adding & updating games → Updating a game](adding-and-updating-games.md#updating-a-game)
for how updates reach a LumaDeck game.

- **Auto-update (on)** — the game follows Valve: natively while a code
  provider is up, through LumaDeck's pin otherwise.
- **Off ("Stays on the installed version.")** — frozen to the installed build;
  nothing moves it.
  Useful when a newer build breaks a fix or a mod. Anything LumaDeck writes
  into the game's folder switches this off for you: installing the version a
  LuaTools fix needs, applying a fix, Goldberg, Steam DRM removal, or the
  Online toggle's EOS proxy. Turning it back on lets the job take the game to
  the current build again (which can undo that fix).

### Change version

Under the Auto-update toggle, for installed games. **Change version** reads
the game's build list from SteamDB (the last 10 public builds, ~1 s) and
shows a dropdown: date, build id, `installed` on the current one, and
`1 fix` / `2 fixes` when a LuaTools fix targets that build. The line under
the dropdown shows the build's name from the studio, if it set one, and
the fix tags. **Install build N** pins every depot the build changed to
its exact manifest (from that build's page on SteamDB), freezes the game
(Auto-update goes off) and marks it so Steam re-plans it at its next
start. Then **restart Steam**: it downloads that build like any update.
A depot the build did not change gets the last manifest it had before that
build; only a depot SteamDB has no record for keeps the manifest it has.

The **Status** tab shows the result: `Build N · Latest` while Auto-update
is on, `Build N · Frozen` with the build's date and name after a change.
If you froze the game with the toggle instead, it reads
`Frozen on the installed version`. Turning Auto-update back on takes the
game to the current build at the next Steam restart.

If SteamDB answers with a Cloudflare browser check the tab says so, with an
**Open SteamDB** button: open it, wait for the page, go back and press
Change version again. If it keeps failing, wait a few minutes; SteamDB
rate-limits by address.

## Fixes & Repairs

The **Fixes & Repairs** tab holds, from top to bottom: the LuaTools fixes
catalogue, the **Fixes** block (Steamless and Goldberg) and the **Repairs**
block.

### Fixes

A *fix* is a community patch zip from the LuaTools catalogue, downloaded and
extracted over the game's install folder, for titles that don't launch cleanly
under SLSsteam. The catalogue is split over two tabs:

- **Check for Fixes** (under **LuaTools Fixes**, on this tab) lists the crack /
  Denuvo fixes.
- **Check for Online Fixes** (under **LuaTools Online Fixes**, on the
  [Online Fixes](#online-fixes) tab) lists the online / co-op ones.

Listing is public, but applying needs a LuaTools login: if you aren't logged
in, a **Log in with Discord** button appears in the list (see
[Credentials → LuaTools account](credentials.md#luatools-account)). Each entry
shows its name and tags, and:

- **Apply fix** — downloads the zip and extracts it into the install folder. A
  game holds one fix at a time: if one is already installed, the button turns
  into **Replace fix**; press it again to swap.
- **Install the game version this fix needs** — shown when the fix targets a
  specific build. It sets the game to that build; then restart Steam, let Steam
  (re)download the game, and apply the fix.

Applied fixes are listed under **Installed LuaTools Fixes** (or **Installed
Online Fixes** on the Online Fixes tab), each with **Remove Fix** to revert it.

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

### Remove DRM (Steamless)

**Remove Steam DRM** (in the **Fixes** block) strips SteamStub DRM from the
game's executables using [Steamless](https://github.com/atom0s/Steamless), which
ships **bundled with the plugin**. The first time, press **Setup Steamless** to
unpack the bundled copy. Each executable gets its own result line (including
when it has no DRM to remove), and the original is kept next to it as `<name>.original.exe`.
The only prerequisite is the .NET 9 runtime; if it's missing the button says
so, and you install it from **Settings ▸ Components**.

### Goldberg

**Apply / Remove Goldberg** (in the **Fixes** block) swaps the game's
`steam_api` libraries for the
[Goldberg emulator (gbe_fork)](https://github.com/Detanup01/gbe_fork) and
back. Use this for titles that expect an emulator rather than SLSsteam's
ownership layer. *Apply* replaces the DLLs (and turns Auto-update off);
*Remove* restores the originals.

### Repairs

- **Fix Linux Permissions** — fixes file ownership and permissions on a
  native-Linux game that won't start because of a permissions error (nothing
  is downloaded).
- **Reconfigure SLSsteam** — re-runs this game's full SLSsteam setup at once:
  AdditionalApps, the app access token (it mainly fixes the *"invalid
  configuration"* error on some games; this is **not** a Denuvo unlock), the
  depot **decryption keys** (read from the installed `.lua`) into `config.vdf`,
  and the DLCs (looked up from Steam's store API and marked as owned so they
  show up in Steam). A normal install does all of this automatically; use it
  when the config has drifted out of sync.
- **Repair Appmanifest** — **deletes** the game's `.acf` across every library so
  Steam **regenerates** it on its next refresh. Use it when Steam has lost track
  of an installed game. (It doesn't rebuild the `.acf` by hand or restart Steam
  — pair it with **Restart Steam** when you're ready. It is refused for a game
  your account owns.)

## Online Fixes

The **Online Fixes** tab has the online part of the LuaTools catalogue
(**Check for Online Fixes**, then **Installed Online Fixes**; they work like
the [Fixes](#fixes) above), and the **Online** toggle.

### Online

**Enable Online** makes the game present itself as Spacewar (AppID `480`) so
its Steam networking (lobbies, matchmaking, P2P) works, for playing **online**
on titles that use Steam's servers. When they apply, it also adds the
steamnetsock patch and the EOS proxy (for games using Epic's online services).
The line under the button lists what it will apply, or what is active; press
**Disable Online** to undo it. It does **not** grant ownership — that's
AdditionalApps. SLSsteam tracks the real AppID per launch, so don't run two
online-enabled games at once.

- It needs the game to be installed, and isn't available for a
  Denuvo-activated game or a game your account owns.
- **Don't use it with anti-cheat games.**
- If you already have an online fix installed, try that first.

## Uninstall

The **Uninstall** tab first lists exactly what will be removed
(**Permanently removes:**).

- **Uninstall Game** — removes the game and all of LumaDeck's config for it.
  Press it, then press **Confirm uninstall** to go ahead (it can't be undone).
  Optional: **Also remove Proton prefix** (deletes the game's compatdata:
  saves and per-game config). For a game the account **owns** (LumaDeck only
  added its DLC) it removes the DLC and nothing else: Steam deletes their files
  once LumaDeck unticks them in the game's DLC list; the game, its `.acf` and
  prefix stay. For an owned game it is refused while the game is running.

## Achievements

**There is nothing to do for achievements.** They unlock and persist on their own
for the games LumaDeck adds, the same as for a game you own:

- **SLSsteam fetches each game's achievement list** (the schema) from Steam the
  first time the game asks for it. lumalinux makes sure SLSsteam does this for
  added games too.
- **Across devices, CloudRedirect syncs them** when its stats sync is on
  (`"stats_sync_enabled": true` in `~/.config/CloudRedirect/config.json`). An
  achievement unlocked on the Deck shows on your other machine after you
  **restart Steam there**: CloudRedirect downloads the synced copy once, when
  Steam starts.

A game with no achievements on Steam simply has none to show.

**The old generator.** LumaDeck used to build the schema itself from the Steam
Web API (`backend/achievements.py`, `GetSchemaForGame` → a
`UserGameStatsSchema_<appid>.bin` in `appcache/stats`). The code is still
there but its UI is hidden, because SLSsteam's own path made it redundant:

```ts
// src/features.ts
export const ACHIEVEMENTS_ENABLED: boolean = false;
```

Setting it to `true` brings back the per-game **Achievements** tab (with
**Generate Achievements**), the **Steam Web API key** and **Sync Achievements**
in Settings, the QAM entry and the game-card marker. It needs a free, read-only
Web API key (<https://steamcommunity.com/dev/apikey>), and achievements appear
after a Steam restart.

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

> Most users never touch the Fixes & Repairs, Online Fixes or Uninstall tabs.
> Reach for them only when a specific game misbehaves — and see
> [Troubleshooting](troubleshooting.md) first.
