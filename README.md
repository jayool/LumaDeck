# LumaDeck

Decky Loader plugin for Steam Deck — game library and configuration manager with a **lumalinux backend**. Fork of [DeckTools](https://github.com/lopesleo/DeckTools) by lopesleo.

## What's different from DeckTools

DeckTools downloads game files via **DepotDownloaderMod** (a .NET CLI) running outside Steam. LumaDeck instead delegates the download to Steam itself, with the [lumalinux](https://github.com/jayool/lumalinux) hooks intercepting depot-key and manifest-request calls inside `steamclient.so`. The trade-off:

|                          | DeckTools (DDL)              | LumaDeck (native + lumalinux) |
| ------------------------ | ---------------------------- | ----------------------------- |
| Download executor        | DepotDownloaderMod (.NET)    | Steam native                  |
| External dependencies    | .NET 9 runtime, ACCELA       | lumalinux artifact, SLSsteam  |
| Sensitive to Steam updates | No (DDL is independent)    | Yes (hooks may need new patterns) |
| Disk layout              | DDL-owned + post-copy        | Steam-owned, identical to a normal install |
| Progress UI              | Plugin polls DDL stdout      | Native Steam progress in the library |

Everything else (manifest auto-discovery via Hubcap/Ryuu, SLSsteam config management, Goldberg, SLScheevo achievements, community fixes, Workshop, auto-detect AppID, search, i18n) is **kept from DeckTools** and continues to work the same way.

## Status

**Early development — not usable yet.** No releases available. The download backend rewrite is in progress on the `lumalinux-backend` branch.

Track progress in the [issues](https://github.com/jayool/LumaDeck/issues) or the commit history of that branch.

## Dependencies — required vs optional

| Dependency | Required? | Used for |
| --- | --- | --- |
| [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) | **Required** | Plugin host on Steam Deck |
| [SLSsteam](https://github.com/AceSLS/SLSsteam) | **Required** | Steam ownership / licensing layer (`LD_AUDIT`) |
| [lumalinux](https://github.com/jayool/lumalinux) | **Required** | Native depot-key / manifest hooks for `steamclient.so` (`LD_PRELOAD`) |
| Python venv with `vdf` module | **Required** | The `steamidra_lite.py` script the plugin invokes uses it to write `DecryptionKey` entries into Steam's `config.vdf` |
| [CloudRedirect](https://github.com/Selectively11/CloudRedirect) | Recommended | Cloud saves for non-owned games (extra `LD_PRELOAD`) |
| [ACCELA](https://github.com/nichelimux/ACCELA) | Optional | Only needed if you want the plugin's fixes / Steamless / Goldberg / Workshop features. The install flow itself doesn't touch ACCELA |
| .NET 9 runtime | Optional | Same scope as ACCELA (Steamless and the Workshop downloader use .NET) |

## Installation

Not packaged yet. To build and run from source on the Deck:

### 1. Build the plugin

```bash
git clone https://github.com/jayool/LumaDeck.git
cd LumaDeck
git checkout lumalinux-backend
pnpm install
pnpm run build
```

### 2. Deploy to the plugins directory

```bash
sudo mkdir -p /home/deck/homebrew/plugins/LumaDeck
sudo cp -r plugin.json main.py package.json dist backend \
    /home/deck/homebrew/plugins/LumaDeck/
sudo chown -R root:root /home/deck/homebrew/plugins/LumaDeck
sudo chmod -R 755 /home/deck/homebrew/plugins/LumaDeck
sudo systemctl restart plugin_loader
```

### 3. Create the Python venv

The `steamidra_lite.py` script that the plugin invokes needs the `vdf` Python module to write `DecryptionKey` entries into Steam's `config.vdf`. SteamOS uses [PEP 668](https://peps.python.org/pep-0668/) which blocks system-wide `pip install`, so a virtualenv is the clean way to provide that module:

```bash
python3 -m venv ~/venvs/lumalinux
~/venvs/lumalinux/bin/pip install vdf
```

The plugin auto-detects this path. If the venv is missing, the script falls back to system `python3` and silently skips the `config.vdf` step — most installs still work because the lumalinux DepotKey hook serves keys at runtime, but Steam's pre-download manifest-signature validation will fail for some games. The venv is the supported path.

### 4. Lumalinux + SLSsteam injection

Make sure `/usr/bin/steam` includes the `LD_AUDIT` line (SLSsteam) and the `LD_PRELOAD` line (lumalinux + optionally CloudRedirect). See the [lumalinux README](https://github.com/jayool/lumalinux) for the exact lines and the `steamos-readonly disable / enable` dance.

## How a game install works

This is what the plugin does end-to-end when you tap **Install** in the QAM:

1. **Manifest fetch.** The backend queries the enabled APIs (Hubcap, Ryuu, etc.) listed in `api.json`, picks the first one that responds with a valid zip, and downloads it to a temp directory. Progress for *this* phase (a few MB) is shown in the plugin UI.
2. **Process the zip.** The plugin extracts it, optionally enriches the `.lua` with a Linux depot from PICS (only if the corresponding `.manifest` is already in the extracted tree), and hands the result to `steamidra_lite.py` via subprocess. The script does the heavy lifting: extracts `.manifest` files into `depotcache/`, writes `keys.txt` for lumalinux, injects depot keys into `config.vdf`, adds the AppID to SLSsteam's `AdditionalApps`, drops a clean `.acf` stub, copies the `.lua` to `stplug-in/` for ecosystem interop, and writes the ACCELA `.depot` tracker file.
3. **Steam restart.** The plugin schedules `steam -shutdown` with a 5-second delay. SteamOS Game Mode relaunches Steam automatically.
4. **Native download.** Steam reads the fresh config, sees the AppID in its library, and starts downloading the game like a normal owned title. The lumalinux hooks intercept depot-key and manifest-request calls so Steam can decrypt and fetch what it needs. **Progress for this phase (the GBs) is shown in the Steam library itself**, not in the plugin — there's no point duplicating the bar.

## Update flow

> **⚠️ Expected behaviour — not yet runtime-verified on a Deck.** The flow follows from how the hooks work; this section will be updated once a real update has been exercised end-to-end.

When Hubcap publishes a new `.lua` for a game you've already installed:

1. The plugin's `check_game_update` notices the manifest GID for the main depot has changed (compared against the ACCELA `.depot` tracker `steamidra_lite.py` wrote during the install).
2. You tap **Update** in the plugin. Same code path as a fresh install: download the new zip → process → `steamidra_lite.py` → `steam -shutdown`.
3. `steamidra_lite.py` overwrites `keys.txt` with the new manifest GID, the stplug-in `.lua`, and the `.depot` tracker. It detects the existing `.acf` (with the *old* `InstalledDepots`) and **patches** the error-state fields instead of overwriting the whole file — so Steam's record of "what's currently on disk" survives the update.
4. Steam comes back up. It sees `InstalledDepots` says depot X is at manifest GID Y_old. It queries PICS, which returns Y_new (the public GID). The BuildDep hook then patches Steam's in-memory depot info with the GID `keys.txt` lists (which is *also* Y_new, because we just wrote it). Steam pulls the new manifest, computes the diff against the local files, and downloads only the changed chunks.

## Troubleshooting

### "No internet connection" on the very first Install of a game

Spurious. Steam shows this transient toast the first time the `.acf` is freshly created, even with the network fully up — it's stale error state from the moment Steam writes the `.acf` before any download has actually run.

Fix: the `steamidra_lite.py` script seeds a clean stub `.acf` *before* you click Install, exactly so this state isn't there. **The stub is gone after a Steam Uninstall.** If you uninstall a game and want to reinstall it without seeing the toast, re-run the install through the plugin (or `steamidra_lite.py` directly) before clicking Install in Steam again.

### Steam updated and now the hooks don't work

Toast says `N/4 hooks — <HOOK> FAILED`; lumalinux's log shows `pattern NOT FOUND`. The hooks pin to byte patterns in `steamclient.so`; Steam updates can shift those.

Fix: re-derive the patterns with lumalinux's `tools/derive_patterns.py` (see the [lumalinux README §8.1](https://github.com/jayool/lumalinux/blob/main/docs/RESEARCH.md)), paste the fresh patterns into `src/patterns.hpp`, rebuild `liblumalinux.so`, redeploy. Most updates only move the anchored hooks, which the script fixes automatically.

### Settings panel shows lumalinux as "not found"

Check the path. The plugin auto-detects `/home/deck/.local/share/lumalinux/liblumalinux.so`. If you installed it somewhere else, either symlink it into that path or open an issue with the path you used and I'll add it to the candidate list in `paths.py`.

### Game shows "Update available" in the plugin but the install on disk is already the latest

The plugin compares the `.depot` tracker that `steamidra_lite.py` wrote against the public PICS GID. If you updated via something *other* than the plugin (running the script from Konsole, ASSella in Desktop Mode, etc.), the plugin's stale check fires a false positive. Tapping Update is harmless — the script writes the same GIDs Steam already has, no download happens.

## Why fork instead of contributing to DeckTools

The native-Steam-download approach is a fundamental backend change that wouldn't fit as an option inside DeckTools — too many code paths assume DDL is doing the heavy lifting. A fork keeps both projects clean: DeckTools stays the DDL-based path, LumaDeck stays the native-Steam path. Users can pick the one that fits their setup.

## Credits

LumaDeck is a fork of [DeckTools](https://github.com/lopesleo/DeckTools) by **lopesleo**. Most of the architecture, frontend, and backend modules are theirs; LumaDeck replaces only the download engine. Their original credit list (kept here for full transparency):

| Project                                                                    | Author            | Role                                                                          |
| -------------------------------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------- |
| [DeckTools](https://github.com/lopesleo/DeckTools)                         | lopesleo          | **Base project — LumaDeck is a fork**                                         |
| [LuaToolsLinux](https://github.com/Star123451/LuaToolsLinux)               | Star123451        | Original project that inspired DeckTools                                      |
| [SLSsteam](https://github.com/AceSLS/SLSsteam)                             | AceSLS            | Steam ownership / licensing layer                                             |
| [lumalinux](https://github.com/jayool/lumalinux)                           | jayool            | Native depot-key / manifest hooks for `steamclient.so` (Linux i386)           |
| [SLScheevo](https://github.com/xamionex/SLScheevo)                         | xamionex          | Achievement file generator for SLSsteam-managed games                         |
| [ACCELA](https://github.com/nichelimux/ACCELA)                             | nichelimux        | Dependency installer (Goldberg, DepotDownloader, .NET) — still used for fixes |
| [Goldberg Steam Emulator](https://gitlab.com/nichelimux/goldberg_emulator) | nichelimux        | Steam API emulator                                                            |
| [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)          | SteamDeckHomebrew | Plugin platform                                                               |
| [Hubcap](https://hubcapmanifest.com)                                       | Hubcap            | Manifest API (formerly Morrenus)                                              |

## Disclaimer

This tool is provided for educational and personal use only. Users are responsible for complying with all applicable laws and terms of service. The authors do not condone or encourage any form of software piracy.

## License

MIT — inherited from DeckTools.
