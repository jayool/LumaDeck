# LumaDeck Wiki

User and developer documentation for **LumaDeck** — a Decky Loader plugin that
turns Steam itself into the download engine for manifests, backed by the
[lumalinux](https://github.com/jayool/lumalinux) hooks.

> These pages are **task-oriented guides**. For the project overview, the
> install walkthrough and the under-the-hood "how a game install works"
> narrative, see the root [README](../README.md). For internal architecture
> design decisions and the module map see lumalinux's
> [nosotros.md](https://github.com/jayool/lumalinux/blob/main/docs/nosotros.md) (Spanish); for the UI rules see
> [DESIGN_UI.md](../DESIGN_UI.md).

## For users

| Page | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | First run in three steps: credentials → install components → add your first game. |
| [Credentials](credentials.md) | Hubcap API key, Ryuu cookie (incl. one-tap auto-import), the LuaTools account that fixes need, and the expiry warnings. |
| [Adding & updating games](adding-and-updating-games.md) | AppID auto-detect, search by name, DRM/launcher notices, which drive it installs to, updates. |
| [Managing a game](managing-a-game.md) | The per-game page: auto-update pin, version change, FakeAppId/Token/DLCs, Goldberg, fixes, DRM removal, achievements, uninstall. |
| [Components & health](components-and-health.md) | What SLSsteam / lumalinux / CloudRedirect are, and what each health state means. |
| [Cloud saves](cloud-saves.md) | Signing into a cloud provider for CloudRedirect, which games it covers, and the games that can freeze Steam on exit. |
| [Updating LumaDeck](updating-lumadeck.md) | Updating the plugin (zip to Downloads, then Decky) and the components. |
| [Troubleshooting](troubleshooting.md) | Decoding the banners and fixing common problems. |

## For developers

| Page | What it covers |
| --- | --- |
| [Architecture](dev-architecture.md) | The frontend ⇄ backend bridge and the module layout. |
| [Translations (i18n)](dev-i18n.md) | Adding a string or a new language. |

---

*Educational / research use only. Use LumaDeck with your own Steam account and
content. The plugin hosts and distributes nothing; it only orchestrates the
tools listed in the [credits](../README.md#credits--notes).*
