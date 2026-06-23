# LumaDeck

Decky Loader plugin for Steam Deck — game library and configuration manager with a **lumalinux backend**. Fork of [DeckTools](https://github.com/lopesleo/DeckTools) by lopesleo.

> ⚠️ **Educational / research use only.** Use it with your own Steam account and content. The plugin does not host or distribute any third-party content; it only orchestrates installs around SLSsteam, lumalinux, ACCELA and (optionally) CloudRedirect.

## What's different from DeckTools

DeckTools downloads game files via **DepotDownloaderMod** (a .NET CLI) running outside Steam. LumaDeck instead delegates the download to Steam itself, with the [lumalinux](https://github.com/jayool/lumalinux) hooks intercepting depot-key and manifest-request calls inside `steamclient.so`. The trade-off:

|                            | DeckTools (DDL)              | LumaDeck (native + lumalinux) |
| -------------------------- | ---------------------------- | ----------------------------- |
| Download executor          | DepotDownloaderMod (.NET)    | Steam native                  |
| External dependencies      | .NET 9 runtime, ACCELA       | lumalinux artifact, SLSsteam  |
| Sensitive to Steam updates | No (DDL is independent)      | Yes (hooks may need new patterns) |

Everything else (SLSsteam config management, Goldberg, SLScheevo achievements, community fixes, Workshop, auto-detect AppID, search) is **kept from DeckTools** and continues to work the same way.

## Installation

1. **Download the latest LumaDeck zip** from the [releases page](https://github.com/jayool/LumaDeck/releases).

2. **Install it in Decky Loader** as a custom plugin: in the Decky settings on the Deck, point it at the downloaded zip. Decky unpacks the plugin and restarts itself.

3. **Install the components from the QAM.** Open LumaDeck in the QAM. On a fresh setup (nothing installed yet) it shows a **Quick Install** button that installs and configures everything — ACCELA, SLSsteam, the .NET 9 runtime, lumalinux, and optionally CloudRedirect — in the correct order in one tap. This is the recommended path.

   To install or reapply components **individually** (or after a Steam update), use **Settings → Dependencies**. The wiki documents each one and the order they go in: see [Getting started](docs/getting-started.md#2-install-the-components) and [Components & health](docs/components-and-health.md).

4. **(Optional) Sign into your cloud provider.**

   If you enabled CloudRedirect in step 3, the *library* is in place but no provider is signed in. The CloudRedirect Flatpak's sign-in opens a real browser, which gamemode can't drive — switch to desktop mode once, open the **CloudRedirect** app from the application menu, and sign into Google Drive / OneDrive / Dropbox. The Dependencies panel will then show *CloudRedirect provider: Configured* once tokens exist at `~/.config/CloudRedirect/tokens_<provider>.json`.

### After a Headcrab/SLSsteam update

Headcrab regenerates `~/.local/share/Steam/steam.sh` whenever its updater runs. That erases the lumalinux managed block (the deployed `.so` and `keys.txt` survive). Fix it from the plugin: tap **Install / Reapply lumalinux** in Settings → Dependencies.

### Tested platforms

- SteamOS gamemode (Steam Deck, stable channel).

## Usage

Before installing anything, set the API credentials so the plugin can fetch manifests:

- Open LumaDeck → **Settings → API Credentials**.
- Paste your **Hubcap API key** (and, if you use it, your **Ryuu cookie**) and save.

To install a game:

1. From Steam, open the **Store page** of the game you want.
2. Open LumaDeck in the QAM. The plugin detects the AppID of the page you have open and **auto-fills it** in the "Add game" input.
3. Tap **Download Manifest**. The plugin fetches the manifest and processes it. Then **restart Steam manually**.
4. Steam comes back up and the game appears in your library, ready to install. Press **Install** on it in Steam and it downloads natively. **Progress shows in the Steam library**, not in the plugin.

For the full step-by-step of what the plugin does under the hood, see [How a game install works](#how-a-game-install-works) below.

## How a game install works

This is what the plugin does end-to-end when you tap **Download Manifest** in the QAM:

1. **Manifest fetch.** The backend queries the enabled APIs (Hubcap, Ryuu, etc.) listed in `api.json`, picks the first one that responds with a valid zip, and downloads it to a temp directory. Progress for *this* phase (a few MB) is shown in the plugin UI.
2. **Process the zip.** The plugin extracts it, optionally enriches the `.lua` with a Linux depot from PICS (only if the corresponding `.manifest` is already in the extracted tree), and hands the result to `steamidra_lite.py` via subprocess. The script does the heavy lifting: extracts `.manifest` files into `depotcache/`, writes `keys.txt` for lumalinux, injects depot keys into `config.vdf`, adds the AppID to SLSsteam's `AdditionalApps`, drops a clean `.acf` stub, copies the `.lua` to `stplug-in/` for ecosystem interop, and writes the ACCELA `.depot` tracker plus a best-effort in-game `.DepotDownloader` marker.
3. **Steam restart.** You **restart Steam manually**. On the next launch it reads the fresh config and loads the lumalinux hooks.
4. **Native download.** Steam reads the fresh config and the game appears in its library, ready to install. You press **Install** in Steam and it downloads like a normal owned title — the lumalinux hooks intercept depot-key and manifest-request calls so Steam can decrypt and fetch what it needs. **Progress for this phase (the GBs) is shown in the Steam library itself**, not in the plugin.
5. **ACCELA marker self-heal.** The in-game `.DepotDownloader` marker can't be placed authoritatively at step 2 (the game isn't downloaded yet). So on the next library refresh, for any installed game whose folder now has real content but no marker, the plugin re-runs `steamidra_lite --accela-mark <appid>` — this is what lets the standalone **ACCELA** desktop app recognise games you installed through LumaDeck. (Needs lumalinux **v0.13.0+** deployed: the `--accela-mark` mode landed in v0.11.0, but installs only actually complete with the package-0 finder that's default-on from v0.13.0.)

## Update flow

Games installed through LumaDeck are **normal owned games to Steam**, so they
**auto-update natively** — just like any game you actually own. The per-game
**auto-update** toggle can freeze a game at its installed version instead.

Occasionally an update gets stuck (a new depot needs a decryption key the game
doesn't have yet). LumaDeck flags it and a **Fix Update** button re-deploys a
fresh manifest to unblock it; your installed version keeps working meanwhile.

Full mechanism (pinning, the BuildDep passthrough, stuck-update handling):
[Adding & updating games → Updating a game](docs/adding-and-updating-games.md#updating-a-game).

## Why fork instead of contributing to DeckTools

The native-Steam-download approach is a fundamental backend change that wouldn't fit as an option inside DeckTools — too many code paths assume DDL is doing the heavy lifting. A fork keeps both projects clean: DeckTools stays the DDL-based path, LumaDeck stays the native-Steam path. Users can pick the one that fits their setup.

## Related docs

- [**Wiki / docs**](docs/README.md) — task-oriented user & developer guides (credentials, managing games, troubleshooting, architecture, …)
- [lumalinux README](https://github.com/jayool/lumalinux) — the hooks themselves, build flow, manual install steps
- [lumalinux maintenance docs](https://github.com/jayool/lumalinux/blob/main/docs/maintenance.md) — what to do after a SteamOS / Steam client update
- [lumalinux cloudredirect docs](https://github.com/jayool/lumalinux/blob/main/docs/cloudredirect.md) — running side by side with CloudRedirect's flatpak; `LD_PRELOAD` ordering
- [DESIGN.md](DESIGN.md) — internal architecture notes, divergence from DeckTools

## Credits / notes

LumaDeck is a fork of [DeckTools](https://github.com/lopesleo/DeckTools) by **lopesleo**. Most of the architecture, frontend, and backend modules are theirs; LumaDeck replaces only the download engine. The combined credit list:

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
| [enter-the-wired](https://github.com/ciscosweater/enter-the-wired)         | ciscosweater      | Bootstrap script that chains ACCELA + SLSsteam + .NET installs                |
| [Headcrab / h3adcr-b](https://github.com/Deadboy666/h3adcr-b)              | Deadboy666        | SLSsteam launcher wrapper + CloudRedirect installer (`headcrab.pages.dev`)    |
| [CloudRedirect](https://github.com/Selectively11/CloudRedirect)            | Selectively11     | Cloud-save RPC redirector to third-party providers                            |

Research / educational. Use with your own Steam account and content. Do not redistribute Valve binaries.

## License

MIT — inherited from DeckTools.
