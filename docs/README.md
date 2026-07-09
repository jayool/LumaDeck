# LumaDeck Wiki

User and developer documentation for **LumaDeck** — a Decky Loader plugin that
turns Steam itself into the download engine for manifests, backed by the
[lumalinux](https://github.com/jayool/lumalinux) hooks.

> These pages are **task-oriented guides**. For the project overview, the
> install walkthrough and the under-the-hood "how a game install works"
> narrative, see the root [README](../README.md). For internal architecture
> rationale see [DESIGN.md](../DESIGN.md).

## For users

| Page | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | First run in three steps: credentials → install components → add your first game. |
| [Credentials](credentials.md) | Hubcap API key, Ryuu cookie (incl. one-tap auto-import), and the expiry warnings. |
| [Adding & updating games](adding-and-updating-games.md) | AppID auto-detect, search by name, DRM/launcher notices, library picker, updates. |
| [Managing a game](managing-a-game.md) | The per-game page: auto-update pin, FakeAppId/Token/DLCs, Goldberg, fixes, DRM removal, uninstall. |
| [Achievements](achievements.md) | Generating achievements with SLScheevo. |
| [Components & health](components-and-health.md) | What SLSsteam / lumalinux / CloudRedirect are, and what each health state means. |
| [Cloud saves](cloud-saves.md) | Signing into a cloud provider for CloudRedirect (installed with the base dependencies). |
| [Updating LumaDeck](updating-lumadeck.md) | In-plugin self-update and component update notices. |
| [Troubleshooting](troubleshooting.md) | Decoding the banners and fixing common problems. |

## For developers

| Page | What it covers |
| --- | --- |
| [Architecture](dev-architecture.md) | The frontend ⇄ backend bridge and the module layout. |
| [Backend reference](dev-backend-reference.md) | One-line purpose of every `backend/` module. |
| [Translations (i18n)](dev-i18n.md) | Adding a string or a new language. |

---

*Educational / research use only. Use LumaDeck with your own Steam account and
content. The plugin hosts and distributes nothing; it only orchestrates the
tools listed in the [credits](../README.md#credits--notes).*
