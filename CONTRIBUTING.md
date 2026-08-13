# Contributing to LumaDeck

Contributions are welcome! Bug fixes, new features, translations, documentation improvements — all appreciated.

---

## Before you start

Open an **Issue** first to describe what you want to do. This avoids duplicate work and lets us align on approach before you invest time coding.

---

## Development setup

### Requirements

- Node.js + pnpm
- Python 3.11+
- A Steam Deck with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) (or Bazzite on PC)
- SSH access to the Deck

### Install dependencies

```bash
pnpm install
```

### Build

```bash
pnpm run build       # build once
pnpm run watch       # watch mode
```

### Deploy to Deck

Edit `deploy.sh` with your Deck's IP, then:

```bash
bash deploy.sh
```

This copies the plugin to `/home/deck/homebrew/plugins/LumaDeck/` and restarts Decky Loader.

---

## Project structure

```
backend/          Python (async) — all plugin logic
  paths.py        Steam/SLSsteam path & identity detection, wrapper coverage
  downloads.py    Manifest download, depot handling, ACF repair
  slssteam_ops.py SLSsteam configuration (tokens, DLCs, FakeAppId)
  installer.py    Runs lumalinux setup.sh (wrapper model): SLSsteam + CR + lumalinux + .NET
  desktop_handoff.py  Desktop hand-off (Steam downgrade / re-inject)
  components.py   Per-component health + update status (Components panel)
  steam_utils.py  VDF parser, library detection, game path resolution
  fixes.py        Community fix download/apply/remove
  api_manifest.py API manifest management
  utils.py        File I/O helpers
  ...             (full list in docs/dev-backend-reference.md)

src/              TypeScript + React — Decky frontend
  pages/
    GameList.tsx  Main page
    GameDetail.tsx Game detail and actions
    Settings.tsx  Plugin settings
  api.ts          Frontend ↔ backend bridge (call())
  i18n.ts         Translations (EN + PT-BR)

main.py           Plugin entry point — exposes async methods to frontend
```

### Key conventions

- All Python methods in `main.py` must be `async` (Decky requirement)
- Blocking I/O runs in executor via `loop.run_in_executor()`
- Frontend calls backend via `@decky/api` `call()`
- Steam Deck paths use `/home/deck/` explicitly (Decky runs as root)

---

## Submitting a PR

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Test on a real Deck or Bazzite
4. Open a Pull Request referencing the related Issue

Please keep PRs focused — one feature or fix per PR.

---

## Translations

Translations live in `src/i18n.ts`. Currently supported: **English** and **PT-BR**.

To add or fix a translation, find the relevant key in both language blocks and submit a PR.

To add a new language, duplicate one of the existing blocks and translate the values.

---

## Licença / License

By contributing, you agree your code will be released under the [MIT License](LICENSE).

---

*Obrigado / Thank you!*
