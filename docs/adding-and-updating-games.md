# Adding & updating games

## Adding a game

LumaDeck adds a game by fetching its **manifest** and letting Steam download it
natively. There are three ways to pick the game, all on the main QAM page.

### By store page (auto-detect)

1. In Steam, open the **store page** of the game.
2. Open LumaDeck — the **AppID is auto-detected** and filled into the *Add
   Game* field.
3. Tap **Download Manifest**.

### By AppID

Type a Steam **AppID** directly into the *Add Game* field and tap **Download
Manifest**.

### By name (Hubcap search)

Under **Search by Name**, type a game title and tap **Search Hubcap**. Results
list matching games (soundtracks, demos and tools are filtered out); tap one to
fill its AppID into the *Add Game* field. *Requires a valid Hubcap key.*

### Before you confirm

When a valid AppID is staged, LumaDeck shows a preview card with the game's
name, developer, platforms, size, ProtonDB tier, achievement count and more. It
also surfaces:

- **Game notices** — DRM (e.g. Denuvo) or required third-party launchers.
- **Credential warnings** — if your Hubcap key or Ryuu cookie is expired or
  missing (see [Credentials](credentials.md#expiry-warnings)).

### What happens when you tap Download Manifest

The plugin fetches the manifest (a few MB — progress shows **in the plugin**)
and processes it. When it finishes, the game appears in your library **without a
Steam restart** (restart only if it doesn't show up — some Steam builds don't
support the live refresh). Then press **Install** on it in Steam — it downloads natively,
like any owned title, and **its download progress shows in the Steam library,
not in the plugin.**

### Which drive it installs to

**Steam asks you, not LumaDeck.** If you have more than one library, Steam's own
Install dialog offers the drive picker, exactly as it does for a game you own.

LumaDeck writes nothing into any library when you add a game — no manifest, no
placeholder. Steam creates the manifest when you press Install, in whichever
library you picked, with its own name for the folder.

That is deliberate and it is recent. Until v0.7.4 LumaDeck wrote a placeholder
into the default library at *add* time, before you had chosen anything — which
stranded the game if you then installed it elsewhere (issue #41). There was also
a library picker in the add flow at one point; it was removed because the backend
ignored whatever you chose. Choosing the drive has always been Steam's job, and
now nothing pretends otherwise.

The full end-to-end breakdown is in the root
[README → How a game install works](../README.md#how-a-game-install-works).

## Updating a game

Games you install through LumaDeck are **normal owned games to Steam**, so
**Steam applies their updates natively** — there's no "update" button in the
plugin for the normal case.

### Native, with a safety net (0.9)

Steam only downloads a version whose **manifest** (the file list) it can get,
and for a game you don't own Valve only hands out the "manifest request code"
that authorises fetching it to an account that owns the game. Since
2026-09-15 there are again public services that mint those codes from owning
accounts, and lumalinux (0.21.0+) uses them: when Steam needs a manifest it
does not have, lumalinux asks a provider, **checks the code against Valve's
CDN**, and hands it to Steam. So in the normal case a LumaDeck game carries
**no pin**: Steam sees Valve's current build, downloads it, and updates it
later exactly like an owned game. LumaDeck does nothing but keep a copy of
the manifests Steam downloads.

The safety net is for the day no provider answers (they all died once, on
2026-09-09). lumalinux reports it (`gmrc.json`), and within a minute LumaDeck
**pins every game to its installed build** (SLSsteam's `ManifestIds`), whose
manifests it holds, so Steam has nothing to ask for: installed games keep
playing, a pending update is simply dropped. While that lasts, updates go the
0.8 way: every **30 minutes** the job compares each pin with Valve's current
build (`api.steamcmd.net`), fetches the new manifests from the
`manifest.luastools.xyz` archive or Hubcap (once a day per game), and moves
the pin only when it has **every** manifest. The job also probes a provider
every 30 minutes and, when one serves valid codes again, releases the pins
it set. Nothing is shown to the user in either direction.

With an older lumalinux (no `gmrc.json`) LumaDeck stays in the pinned model.

A build that adds a **new depot** (a new DLC, a restructure) needs its
decryption key too, which only a fresh Hubcap zip carries. The job fetches that
zip (same daily limit) and installs it through the normal path; until then a
keyless DLC is simply invisible to Steam — no error.

The per-game **auto-update** toggle (on the [game page](managing-a-game.md#auto-update))
controls the job:

- **On (default)** — no pin while a provider is up (Steam updates the game
  itself); with none, LumaDeck moves the pin whenever it can.
- **Off (frozen)** — the game is pinned to its installed build and nothing
  moves it. Installing a LuaTools version fix freezes the game automatically
  (see [Managing a game → Fixes](managing-a-game.md#fixes)).

Every 60 seconds the job also puts back any pinned manifest that went missing
from `depotcache/` (Steam deletes them on uninstall, and sometimes after an
install commits) from LumaDeck's own copy under `~/.local/share/lumadeck/`, so
a Steam-side uninstall/reinstall works offline.

### When an update gets stuck

The **Update stuck** notice and **Fix Update** button remain as the manual way
out: tap it and the plugin re-fetches the Hubcap zip (bringing any new key),
re-deploys `keys.txt` and the manifests, and re-pins. With the job above this
should be rare — it never moves a pin without every key and manifest in hand —
but it covers an update Steam had already started, or anything unforeseen.
(Re-fetching needs a valid Hubcap key.)
