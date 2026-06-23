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
- **Library picker** — if you have more than one Steam library, you choose
  where it installs.

### What happens when you tap Download Manifest

The plugin fetches the manifest (a few MB — progress shows **in the plugin**)
and processes it. When it finishes, **restart Steam** so the game appears in
your library. Then press **Install** on it in Steam — it downloads natively,
like any owned title, and **its download progress shows in the Steam library,
not in the plugin.**

The full end-to-end breakdown is in the root
[README → How a game install works](../README.md#how-a-game-install-works).

## Updating a game

Installed games can be **pinned** (frozen at the installed version) or left on
**auto-update** — toggled per game on the [game page](managing-a-game.md). When
a provider publishes a newer manifest for an unpinned game, LumaDeck can surface
an **Update available** notice; applying it follows the same path as a fresh
install.

> ⚠️ The update path is **expected behaviour, not yet runtime-verified on a
> Deck** — see the caveat in the root [README → Update flow](../README.md#update-flow).
