# Architecture (developer)

A high-level map for contributors. For the rationale behind the native-Steam
download approach and the divergence from DeckTools, read
[DESIGN.md](../DESIGN.md) and [DESIGN_UI.md](../DESIGN_UI.md).

## Two halves

LumaDeck is a Decky plugin: a **TypeScript/React frontend** (runs in Steam's
UI) talking to a **Python backend** (runs as a privileged process).

```
src/ (frontend, React)                     main.py + backend/ (Python)
  pages/  GameList, GameDetail,              Plugin class: one async method
          Settings, Downloads, Help            per frontend call, each a thin
  components/  banners, cards, modals          wrapper that imports a backend
  api.ts   ── call("method", args) ─────►       module and returns _j(result)
  i18n.ts                              ◄──    backend/*.py: the real logic
```

## The bridge

Every backend call goes through one pattern:

- **Frontend** — `src/api.ts` wraps each backend method:
  ```ts
  export const searchHubcap = async (query: string) =>
    parseResult(await call<[string], string>("search_hubcap", query));
  ```
  `call(...)` is Decky's RPC. Backend methods **always return a JSON string**;
  `parseResult()` deserialises it (and yields `{success:false}` on parse error).

- **`main.py`** — the `Plugin` class exposes one `async def` per method. Each is
  a thin wrapper that imports the relevant backend module and serialises the
  result with `_j(...)`:
  ```python
  async def search_hubcap(self, query: str) -> str:
      from api_manifest import search_hubcap
      return _j(await search_hubcap(query))
  ```

- **`backend/`** — the actual implementation. Modules are imported lazily inside
  the wrappers (keeps startup cheap and avoids import cycles).

### Adding a backend method

1. Implement it in the right `backend/` module, returning a dict.
2. Add a thin `async def` wrapper in `main.py` that calls it and returns `_j(...)`.
3. Add an `export const` in `src/api.ts` that `call`s it and `parseResult`s.
4. Use it from a page/component.

## Frontend entry point

`src/index.tsx` (`definePlugin`):

- Registers routes for the sub-pages (`GameDetail`, `Settings`, `Downloads`).
- The QAM panel content is `<GameList />`.
- Patches the Steam **library app page** to inject an "Added via LumaDeck"
  button (`patchLibraryApp`).

## Where state comes from

Pages fetch on mount via `api.ts` and render. Health/update signals
(`get_*_health`, `check_*_update`) drive the banners on `GameList`; the
Dependencies panel in `Settings` polls a few times after mount because an
install can restart Steam mid-flight and tear the UI down (see the comment on
the retry timers in `Settings.tsx`).

## Backend module map

See [Backend reference](dev-backend-reference.md) for a one-line purpose of
every module.
