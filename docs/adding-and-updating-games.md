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
and processes it. When it finishes, the game appears in your library **without a
Steam restart** (restart only if it doesn't show up — some Steam builds don't
support the live refresh). Then press **Install** on it in Steam — it downloads natively,
like any owned title, and **its download progress shows in the Steam library,
not in the plugin.**

The full end-to-end breakdown is in the root
[README → How a game install works](../README.md#how-a-game-install-works).

## Updating a game

Games you install through LumaDeck are **normal owned games to Steam**, so
**Steam updates them natively** — there's no "update" button in the plugin for
the normal case.

### Auto-update (default)

By default a game is **unpinned**: `steamidra_lite` writes `gid=0` for its
content depots in `keys.txt`, so nothing pins them and Steam follows Valve's
current manifest. The game **auto-updates like a legitimate owner**, decrypting
each depot with the keys already in `keys.txt`.

The per-game **auto-update** toggle (on the [game page](managing-a-game.md#auto-update))
controls this:

- **On (unpinned, default)** — follows the latest version.
- **Off (pinned)** — `steamidra_lite --pin-installed` writes the installed GID
  into SLSsteam's `ManifestIds`, and **SLSsteam** freezes that version; updates
  are held back. **LumaDeck won't tell you a newer version exists for a pinned
  game** — unpin it to pick updates back up.

### When an update gets stuck

> ⚠️ This remediation is **expected behaviour, not yet verified end-to-end on a
> Deck** (the auto-update path above is validated).

An auto-update only stalls when a new build pulls in a **new or rotated depot**
whose decryption key isn't in `keys.txt` yet — Steam can't decrypt it, so the
update gets stuck and your **installed version keeps working**. LumaDeck's
watchdog detects this and shows an **Update stuck** notice; tap **Fix Update**
and the plugin re-fetches the manifest (bringing the new key), re-deploys
`keys.txt`, and you restart Steam to finish. (Re-fetching needs a valid Hubcap
key.)
