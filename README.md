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

Everything else (manifest auto-discovery via Morrenus/Ryuu, SLSsteam config management, Goldberg, SLScheevo achievements, community fixes, Workshop, auto-detect AppID, search, i18n) is **kept from DeckTools** and continues to work the same way.

## Status

**Early development — not usable yet.** No releases available. The download backend rewrite is in progress on the `lumalinux-backend` branch.

Track progress in the [issues](https://github.com/jayool/LumaDeck/issues) or the commit history of that branch.

## Why fork instead of contributing to DeckTools

The native-Steam-download approach is a fundamental backend change that wouldn't fit as an option inside DeckTools — too many code paths assume DDL is doing the heavy lifting. A fork keeps both projects clean: DeckTools stays the DDL-based path, LumaDeck stays the native-Steam path. Users can pick the one that fits their setup.

## Installation

Not packaged yet. To run from source on the Deck:

```bash
git clone https://github.com/jayool/LumaDeck.git
cd LumaDeck
git checkout lumalinux-backend
pnpm install
pnpm run build
```

Copy `plugin.json`, `main.py`, `package.json`, `dist/`, and `backend/` to `/home/deck/homebrew/plugins/LumaDeck/`, then:

```bash
sudo chown -R root:root /home/deck/homebrew/plugins/LumaDeck
sudo chmod -R 755 /home/deck/homebrew/plugins/LumaDeck
sudo systemctl restart plugin_loader
```

You also need:
- **[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)** installed.
- **[SLSsteam](https://github.com/AceSLS/SLSsteam)** patched into Steam (ownership / licensing layer).
- **[lumalinux](https://github.com/jayool/lumalinux)** deployed as `LD_PRELOAD` (Steam-native download hooks).

See the lumalinux README for the `/usr/bin/steam` configuration.

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
| [Morrenus](https://manifest.morrenus.xyz)                                  | Morrenus          | Manifest API                                                                  |

## Disclaimer

This tool is provided for educational and personal use only. Users are responsible for complying with all applicable laws and terms of service. The authors do not condone or encourage any form of software piracy.

## License

MIT — inherited from DeckTools.
