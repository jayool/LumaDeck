# LumaDeck — UI Design

Single source of truth for the plugin's UI. **Rebuilt from scratch**, verified
element by element against the live code. Nothing here is assumed — every entry
is checked in the source before it is written down.

> **Status: IN PROGRESS.** We are walking the QAM (`GameList`) top to bottom.
> Each element is verified and its rule fixed before moving to the next.

## Method

For every element we record four things:

1. **What** — the element and when it appears (always / conditional).
2. **How shown** — the exact component(s) and where in the code.
3. **Native or custom** — 🟢 native Decky · 🟡 native wrapper + custom content ·
   🔴 fully custom — and *why*, if custom.
4. **Rule** — the decision: keep as-is, or how it must be built going forward.

Principles are **derived** from these entries as patterns emerge (see
[§ Principles](#principles-emerging)), not imposed top-down.

---

## QAM — top to bottom

### 0. Plugin header (back · icon · title) — *always* — ✅ verified

- **What:** the panel's top bar: back chevron ‹, the plugin icon, and the title
  **"LumaDeck"**. The very first thing the user sees.
- **How shown:** rendered by **Decky**, not by `GameList`. Comes from
  `definePlugin`'s return in `src/index.tsx`:
  ```tsx
  title: <div className={staticClasses.Title}>LumaDeck</div>,
  icon:  <FaDownload />,
  content: <GameList />,
  ```
- **Native or custom:** 🟢 **Native.** Native QAM header slot + native Steam
  class `staticClasses.Title`. Ours only: the brand text `"LumaDeck"` and the
  icon glyph (`react-icons/fa`).
- **Rule:** Keep. `"LumaDeck"` is the brand string — the one display literal
  allowed without `t()`. Title always uses `staticClasses.Title`; icon always
  from `react-icons/fa`.

### 1. Utility actions (Refresh · Settings) — *always* — ✅ verified

- **What:** the panel's utility actions. Decided home: the **native title bar**,
  not a row inside the content.
- **How shown:** via Decky's **`titleView`** (a custom JSX element in the
  `Plugin` definition that replaces the default header title). In `index.tsx`:
  brand `LumaDeck` (left) + a `Focusable` of two icon `DialogButton`s (right):
  **Refresh** (`FaSync`) and **Settings** (`FaCog`).
  - Refresh and the panel content (`GameList`) are separate React trees, so the
    icon talks to the panel through a tiny bridge (`src/refresh.ts`):
    `GameList` registers `loadGames` via `setRefreshHandler`; the icon calls
    `requestRefresh()`.
  - Settings just navigates: `Navigation.Navigate(ROUTE_SETTINGS)`.
- **Native or custom:** 🟢 **Native slot** (`titleView`) with native
  `DialogButton`s (size-only `headerIconStyle`, native focus kept). The
  previous hand-built header row in `content` is **gone** — and with it the
  glow-clipping fight and the "Game manager" subtitle.
- **Rule:**
  - Header actions go in **`titleView`**, never a custom row at the top of
    `content`. Keep it to **1–2 icons** (the title bar is narrow).
  - Title-bar icons use native `DialogButton` with **size-only** styling
    (`headerIconStyle`); never override background/colour/focus.
  - An action that must reach panel state crosses the tree via the
    `src/refresh.ts` bridge pattern, not by lifting state into `index.tsx`.

### 1b. Downloads entry — *always* — ✅ verified

- **What:** entry point to the Downloads page.
- **How shown:** a plain native `ButtonItem` in a trailing `PanelSection` at the
  **very bottom** of the QAM → `Navigation.Navigate(ROUTE_DOWNLOADS)`.
- **Native or custom:** 🟢 native `ButtonItem`.
- **Rule:** secondary navigation that doesn't fit the 1–2 title-bar icons lives
  as a labelled `ButtonItem`, bottom of the panel.

### 2. Quick Install (onboarding) — *conditional* — ✅ verified

- **What:** the first-run setup entry. Renders **only** when SLSsteam **and**
  CloudRedirect **and** lumalinux are all `not_installed` and headcrab is
  compatible — i.e. a fresh, unconfigured install. It self-hides the moment any
  component is installed (repair/reinstall then lives in Settings).
- **How shown:** `PanelSection title` (i18n) with three rows: an intro text
  `<div>`, a `ButtonItem` (two-click confirm), and a progress text `<div>`
  shown while installing.
- **Native or custom:** 🟢 native skeleton. The two text rows are raw `<div>`s
  (🔴, but unavoidable — Decky has no text primitive) and they already follow
  the tokens: intro `12px #8b929a`, progress `11px #1a9fff`.
- **Rule:**
  - Onboarding only relevant on a fresh install is **gated on health state**
    and self-hides once configured.
  - Install / destructive actions use the **two-click confirm**: a
    `confirm<Action>` state arms the button (relabel + `description` prompt),
    second press executes.
  - Body text is a plain `<div>` in a `PanelSectionRow` using the text tokens.
    **Step-based** progress is a text line; a `ProgressBar` is only for a real
    percentage.

---

## Principles (emerging)

- The brand string `"LumaDeck"` is the only hard-coded display literal; every
  other user-facing string goes through `t()`, added to **both** `en` and
  `pt-BR`.
- Icons come from `react-icons/fa` only.
- **Header actions** live in the native `titleView` (1–2 icons), not a custom
  row in `content`. Native `DialogButton`, size-only styling, native focus.
- **Text tokens observed so far** (inline hex, no CSS framework):
  | Role | Value |
  |---|---|
  | Primary text | `#dcdedf` |
  | Secondary / muted | `#8b929a` |
  | Accent / progress | `#1a9fff` |
  - Sizes: `12px` standard body, `11px` secondary sub-line.
- **Two-click confirm** is the standard for install/destructive actions
  (`confirm<Action>` state + `ButtonItem` `description`).
- Raw `<div>`s for text are expected (no native text component); keep them on
  the tokens above rather than inventing new colours/sizes.

