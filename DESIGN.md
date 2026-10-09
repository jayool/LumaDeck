# LumaDeck — decision log

Why LumaDeck is built the way it is: each decision with the alternatives that
were weighed and the reason for the choice, plus whether it still holds. Code
comments and other docs cite these by number ("decision 17").

- How the plugin and the stack work **today** is documented from the code in
  lumalinux's [`docs/nosotros.md`](https://github.com/jayool/lumalinux/blob/main/docs/nosotros.md)
  (Spanish).
- How each **UI** element is built, and the rules that keep it consistent, is
  in [DESIGN_UI.md](DESIGN_UI.md).
- User-facing behaviour is in the [wiki](docs/README.md).

LumaDeck is a fork of [DeckTools](https://github.com/lopesleo/DeckTools) by
lopesleo. It keeps DeckTools' Game Mode frontend, SLSsteam operations and
fixes, and replaces the download engine: Steam itself downloads the game,
with [lumalinux](https://github.com/jayool/lumalinux) hooks serving depot keys
and manifest request codes inside `steamclient.so`. This file used to also
carry an architecture overview, a data-flow walkthrough and a paths table
inherited from DeckTools' `DESIGN.md`; they had drifted from the code and were
removed on 2026-10-09 in favour of the documents above.

## Decisions

| # | Decision | Alternatives | Rationale | Status (2026-10-09) |
|---|---|---|---|---|
| 1 | Flow: buy in store → list in plugin → install | Manual AppID; external list | Natural UX, integrates with SLSsteam (inherited from DeckTools) | Superseded in form: a game is picked by store page (auto-detect), by name or by AppID, then **Download Manifest**, then Install in Steam ([Adding & updating games](docs/adding-and-updating-games.md)). |
| 2 | Advanced options (depot, manifest, fixes) | Simple install-only button | Feature parity with LuaToolsLinux (inherited from DeckTools) | Current. |
| 3 | Same API matrix as upstream (Hubcap, Ryuu, Sushi, Spinoza) | Hubcap only; custom API | Already proven, dropping any of them shrinks the catalog | Changed: Hubcap (key) and Ryuu (cookie) are the active sources; Sushi and Spinoza stay in `api.json` but disabled because they lag new games (`backend/api_manifest.py:143-156`). |
| 4 | Auto-install the whole stack via lumalinux `setup.sh` (wrapper model) | Require pre-install; headcrab | One idempotent `setup.sh` run installs SLSsteam + CloudRedirect + netsock + lumalinux + .NET and writes the injection wrapper — no headcrab, no `steam.sh` patch, no per-step ordering | Current. |
| 5 | Hierarchical menu (list → detail) | Single screen; tabs | Best use of QAM space | Current. |
| 6 | **Steam native install via lumalinux hooks** instead of DDL | Keep DDL; offer both as a toggle | Disk layout identical to a normal install; updates handled by Steam; progress shown in Steam library | Current. |
| 7 | Port DeckTools' backend instead of writing the plugin from scratch | Rewrite; shell wrapper | DeckTools' frontend / SLSsteam ops / fixes / achievements are exactly what we want; only the download engine needed changing | Current. |
| 8 | Reuse existing DeckTools / LuaToolsLinux configs (`api.json`, cookies) | Re-prompt the user; isolated config | Avoids rework for existing users | Current. |
| 9 | Game Mode only | Game Mode + Desktop | Clear scope (Desktop has SFF / ASSella) | Current. The one exception is the Desktop hand-off (Quick Install, Steam downgrade), which LumaDeck arms from Game Mode. |
| 10 | DDL legacy pipeline **removed** from `downloads.py` once install + native update were verified on Deck | Keep it parked as dead-code blocks indefinitely | The new flow is proven (routine installs; Mina auto-updated natively), so the ~1250 dead lines were pure cognitive cost. Kept only the 2 helpers `slssteam_ops` still reuses (#6) | Current. |
| 11 | No plugin update-detection badge — updates are Steam-native (unpinned auto-update) + the #21 watchdog for stuck `.acf` | Plugin diffs a saved manifest snapshot vs SteamCMD | The snapshot went stale after Steam's own auto-update (which doesn't run `steamidra_lite`), producing false "update available" badges; Steam already handles the common case | Superseded: the background job in `backend/pins.py` replaced the #21 watchdog. Native updates while a manifest-code provider is up, pins to the installed build otherwise ([Adding & updating games](docs/adding-and-updating-games.md#updating-a-game)). |
| 12 | repair_appmanifest now **deletes** the `.acf` instead of reconstructing it | Keep the legacy reconstruction | The legacy code chmod'd the new .acf to 0444 so Steam couldn't update it; in LumaDeck Steam owns the .acf and we need it writable | Current. |
| 13 | Bearer header for Hubcap API key, never the URL | Keep `?api_key=` in URL | Prevents API key leaks in log files. Backports upstream DeckTools commit d557f2a | Current (`api_manifest.py:508`, `downloads.py:1420-1440`). |
| 14 | Frontend routes moved from `/decktools/*` to `/lumadeck/*` | Keep `/decktools/*` | Avoids router-namespace collision if both forks are installed side by side | Current (`src/routes.ts`). |
| 15 | Identity strings + i18n keys renamed (DeckTools → LumaDeck, Morrenus → Hubcap, addedViaDeckTools → addedViaLumaDeck) | Leave legacy names | Eliminates confusion in QAM, logs, localStorage key, badges; matches the upstream API rename | Current. |
| 16 | `steam -shutdown` runs as the `deck` user (`runuser`), not root | Call `steam -shutdown` directly (the old way) | The plugin runs as root; `steam -shutdown` uses a per-user IPC, so as root it never reached the deck-user Steam and the restart silently no-op'd (v0.3.0 fix) | Current for the restarts LumaDeck still does (Restart Steam, component installs): `-shutdown` as the real user (`main.py:268-290`; `paths.py:571-590` uses `runuser`). Adding a game no longer restarts Steam: SLSsteam hot-reloads and lumalinux refreshes ownership live. |
| 17 | Adding a game writes no `appmanifest` and no ACCELA markers — Steam writes the manifest on Install | Seed a stub `.acf` (and mark for ACCELA off it) | The stub was inherited from the DepotDownloaderMod era, where WE placed the files. With native downloads Steam writes its own manifest in the library the user picks, so ours became an ORPHAN in the root that made Steam show an installed game as NOT INSTALLED (issue #41). Measured both ways on a clean SteamOS: with the stub and without it the button reads "Install" either way, so it bought nothing. The ACCELA markers were derived from that stub's `installdir` and went with it — nothing calls `--accela-mark` any more (v0.7.4) | Current. |
| 18 | Every "is this game installed / where is it" question reads **all** libraries, via one `_library_entries()` | Read `steam_root` only, as three separate parses did | A game's `.acf` lives in the library it was installed into, so a root-only read is wrong for anything on an SD card or a second partition: the grid greyed out installed games (D2) and the error-state patch silently skipped them (D1). The three independent parses of `libraryfolders.vdf` had already drifted apart — one of them `break`ing out of the loop left its own fallback list half-built | Current. |
| 19 | Read **both** copies of `libraryfolders.vdf` (`steamapps/` and `config/`) and union them | Read only the one Steam loads | Steam loads the `steamapps/` copy — its own `content_log.txt` says so — and keeps `config/` identical. A union means neither copy can hide a library from us, and a dead entry surviving in one is harmless because entries with no `steamapps/` under them are dropped (the file outlives the drive it names, and a popped SD card leaves its mount point behind as an empty directory) | Current. |
| 20 | Orphan stubs already on disk are swept **automatically**, once per plugin load | Ship a manual "clean up" button, or leave them | The stub is invisible to the user and its symptom (an installed game re-downloading itself) doesn't point at it, so a button nobody knows to press fixes nobody. Safe because a stub only goes when a REAL manifest for the same appid exists in a DIFFERENT library — redundant by construction — with the shape read from the file at deletion, never from bookkeeping. A lone stub with no real manifest anywhere is deliberately left: it is only cosmetic, and there is no way to prove it is ours. Kill switch: `LUMA_NO_ACF_SWEEP` or `~/.config/lumalinux/no_acf_sweep` | Current. |
| 21 | A rejected LuaTools session is **marked**, not deleted, and only a definite 4xx counts | Delete the session on any failure | A lone 401 can be Cloudflare having a bad minute, and deleting also bins a refresh token that may still work. Marking survives a restart (it lives in the session file) and any call that succeeds clears it. Scoping it to 4xx keeps an offline Deck from nagging for a re-login it could not complete anyway | Current. |
| 22 | Deleting a credential also clears its settings-dir mirror | Delete the credential's own file only | The mirror is read back on every plugin load, so removing just the file left the delete to be undone by the next Steam restart — a LuaTools logout handed the user back the session they had discarded (v0.7.5). `_mirror_cred` merges only non-empty values, so clearing needs its own `_forget_cred` | Current. |
