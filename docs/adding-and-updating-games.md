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
plugin for the normal case. What changed on 2026-09-09 is *where the update
comes from*.

### Why every game is pinned

Steam only downloads a version whose **manifest** (the file list) it can get.
For a game you don't own, Valve refuses the "manifest request code" that
authorises fetching it, and the third-party services that used to mint those
codes are gone. So the only manifests Steam can ever use are the ones LumaDeck
puts into `depotcache/` — and a game that "followed Valve" would ask for the
newest manifest, be refused, and loop on *No internet connection*.

That is why every game LumaDeck adds is **pinned** to the build it has
manifests for (SLSsteam's `ManifestIds`, written by `steamidra_lite --pin`).
The pin is not a restriction, it is what makes install and update possible.

### Auto-update (default)

LumaDeck moves the pin for you. A background job:

- every **30 minutes** compares each game's pin with Valve's current build
  (`api.steamcmd.net`);
- when a build is newer, fetches its manifests from the hubs — the GitHub
  manifest repo (`P-ToyStore/SteamManifestCache_Pro`, updated by a bot minutes
  after Valve) first, then the `manifest.luastools.xyz` archive (filled by
  BetterSteamTools users who own the game; no key, no quota), and Hubcap only if
  neither has it (at most once a day per game, the API key has a daily quota);
- only when it has **every** manifest, seeds them into `depotcache/` and moves
  the pin. Steam sees the new build the next time you **launch the game or
  restart Steam** and updates it like any owned game.

If no hub has the build yet, nothing changes: the game keeps working on its
current build and the job tries again on its next pass.

A build that adds a **new depot** (a new DLC, a restructure) needs its
decryption key too, which only a fresh Hubcap zip carries. The job fetches that
zip (same daily limit) and installs it through the normal path; until then a
keyless DLC is simply invisible to Steam — no error.

The per-game **auto-update** toggle (on the [game page](managing-a-game.md#auto-update))
controls the job:

- **On (default)** — LumaDeck moves the pin whenever it can.
- **Off (frozen)** — the pin stays where it is. Installing a LuaTools version
  fix freezes the game automatically (see [Managing a game → Fixes](managing-a-game.md#fixes)).

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
