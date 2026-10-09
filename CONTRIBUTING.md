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

There is no deploy script in the repo. Build, then pack the same layout the
release workflow does (`.github/workflows/release.yml`, "Create plugin zip"):
`plugin.json`, `main.py`, `package.json`, `dist/` and `backend/` inside a
`LumaDeck/` folder, zipped as `LumaDeck.zip`. Install it from Decky ▸ Settings ▸
Developer ▸ Install Plugin from ZIP, or copy the folder to
`~/homebrew/plugins/LumaDeck/` over SSH and restart Decky Loader.

The release zip also carries binaries that are not in git: Goldberg (gbe_fork)
in `backend/deps/Goldberg` and the EOS proxy in `backend/deps/EosProxy`, both
fetched by the workflow. A local build without them works except for
**Apply Goldberg** and the EOS part of the Online toggle.

---

## Project structure

```
backend/          Python (async) — all plugin logic
  paths.py        Steam/SLSsteam path & identity detection, wrapper coverage
  downloads.py    Manifest download, depot handling, ACF repair
  slssteam_ops.py SLSsteam configuration (tokens, DLCs, FakeAppId)
  installer.py    Runs lumalinux setup.sh (wrapper model): SLSsteam + CR + lumalinux + .NET
  desktop_handoff.py  Desktop hand-off (Steam downgrade / re-inject)
  pins.py         Background job: native updates, pins, depotcache heal
  manifests.py    Where a manifest comes from (archive, luastools, Hubcap)
  components.py   Per-component health + update status (Components panel)
  steam_utils.py  VDF parser, library detection, game path resolution
  fixes.py        Community fix download/apply/remove
  api_manifest.py API manifest management
  utils.py        File I/O helpers
  ...             (full map in lumalinux's docs/nosotros.md §1.3)

src/              TypeScript + React — Decky frontend
  pages/
    GameList.tsx  Main page
    GameDetail.tsx Game detail and actions
    Settings.tsx  Plugin settings
    Library.tsx   Full-screen My Games
    Help.tsx      In-plugin help
  api.ts          Frontend ↔ backend bridge (call())
  i18n.ts         Translations (EN + PT-BR)
  features.ts     Feature flags (ACHIEVEMENTS_ENABLED)

main.py           Plugin entry point — exposes async methods to frontend
```

### Key conventions

- All Python methods in `main.py` must be `async` (Decky requirement)
- Blocking I/O runs in executor via `loop.run_in_executor()`
- Frontend calls backend via `@decky/api` `call()`
- Decky runs the backend as root: resolve the real user, home and uid through
  `backend/platform_info.py`, never a hard-coded `/home/deck` (SteamOS still
  resolves to `deck` / `/home/deck`)

---

## Testing

```bash
python -m unittest discover -s tests     # backend unit tests, no Steam needed (399 on 2026-10-09)
```

Validating a lumalinux change on a real Steam is in lumalinux's
[`docs/maintenance.md`](https://github.com/jayool/lumalinux/blob/main/docs/maintenance.md) §C.
For a release that touches `pins.py` or `downloads.py`, the dated on-device
tests in lumalinux's `docs/nosotros.md` §5.2 (F4 and F5: native install, pins
released and re-applied when providers go down and come back) say what was
checked and what to re-run on a SteamOS box or the codespace.

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

By contributing, you agree your code will be released under the MIT License,
inherited from DeckTools (see the README).

---

*Obrigado / Thank you!*
