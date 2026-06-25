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

### 3. Health alerts — *conditional* — ✅ built (v0.3.33)

- **What:** surfaces a broken / degraded **core component** (SLSsteam,
  lumalinux, CloudRedirect). One alert per unhealthy component. Only
  *actionable failures* appear here — `healthy` / `not_installed` are silent
  (install lives in Quick Install / Settings).
- **Current (to be replaced):** a custom orange box (`HealthBanner`) with a
  title, body, and a hand-rolled `<button>` — the worst "red" (non-native
  control, broken gamepad focus, and it looks identical whether or not there's
  an action).
- **Direction (decided — colored box → native rows):**
  - **No colored box.** Each problem is its own **native row**:
    - **Fixable from Game Mode** → **`ButtonItem`**: `icon` = ⚠ in the severity
      colour, `children` = the fix action ("Restart Steam" / "Reinstall …"),
      `description` = the problem. Native focus, the whole row is the button.
    - **Not fixable from Game Mode** → **`Field`**: `icon` = ⚠, `label` = the
      problem, `description` = where/how to fix it (Settings, or Desktop).
      Display-only — **no dead button**.
  - **Severity = the ⚠ icon colour** (warn `#ff8c00`), not a box.
  - **Multiple problems = multiple rows** (one per component), not one stacked
    box.
- **Native or custom:** 🟢 native (`ButtonItem` / `Field`). Drops the custom
  box *and* the raw `<button>`.
- **Rule:** **never render a button for something you can't do from here.** An
  unactionable alert is a `Field` (info + instructions), not a fake button. The
  exact actionable/not split per state is the table below.

### 3b. Repair architecture — the shared `steam.sh` cascade — ⚠️ correctness

`steam.sh` is **shared**: SLSsteam, CloudRedirect and lumalinux each inject a
block into it. Both the SLSsteam installer (`install_dependencies`) and the
CloudRedirect installer (`install_cloudredirect`) run **headcrab**, which
**regenerates `steam.sh` from scratch** — wiping the *other* components' blocks.
`install_lumalinux` is the exception: it only *patches* (idempotent), so it
never wipes the others, and it must run **last** so its block survives the
headcrab regenerations.

Consequence — a per-component repair that runs headcrab **silently breaks the
others**:

- SLSsteam `injection_missing` repaired with `install_dependencies` alone →
  re-injects SLSsteam but **wipes CloudRedirect + lumalinux**.
- CloudRedirect `broken` repaired with `install_cloudredirect` alone →
  re-injects SLSsteam (headcrab) + CR but **wipes lumalinux**.

**Rule:** any repair that runs headcrab must **re-inject every *installed*
component, in order `SLSsteam → CloudRedirect → lumalinux`** — not a single
installer. This is a dedicated routine, `reinject_installed()` (= `quick_install`
gated on `check_*_installed()`; never installs a component the user doesn't
have). Wire SLSsteam `injection_missing` and CloudRedirect `broken` to it.
`restart` (no `steam.sh` change) and `install_lumalinux` (patch-only) are safe
standalone and stay as-is.

**What `injection_missing`'s repair does, concretely** — `reinject_installed()`:
re-runs SLSsteam (`install_dependencies`) **if installed**, then CloudRedirect
(`install_cloudredirect`) **if installed** (omitted otherwise), then lumalinux
(`install_lumalinux`) **if installed**, in that order — rebuilding a correct
shared `steam.sh`. Each step is gated on `check_*_installed()`, so it only ever
re-injects what the user already had; it never installs a new component.

**`steam.sh` ordering has two reasons, not one.** lumalinux's `install.sh`
*preserves* CloudRedirect's `LD_PRELOAD` (it appends `cloud_redirect.so` rather
than clobbering it) — but only if CR's block is already in `steam.sh` when
lumalinux runs. It **preserves, it does not resurrect** a wiped CR block. So
lumalinux must run after CloudRedirect both (a) so headcrab's regeneration
doesn't wipe lumalinux, and (b) so lumalinux can chain onto CR's freshly
re-added `LD_PRELOAD` (`sls:cr:lumalinux`). The backend's CR detection and the
lumalinux script's preservation work together via this order.

### 3c. Health text spec (normalized, beginner-friendly) — ✅ final

The backend keeps its **granular** states (for logs/diagnostics). The **UI
collapses** the "Steam too new" family into one `unsupported` message per
component, because they share one cause and one fix.

**Why `unsupported` is one state + one fix:** SLSsteam `patterns`/`hash` and
lumalinux `hash_blocked`/`hooks_failed` and CloudRedirect `broken` all mean the
same thing to the user — *Steam updated past what this component supports*. The
fix is the same: **run enter-the-wired in Desktop**, which (via headcrab)
downgrades Steam to the blessed stable build `1782257239` (2026-06-10). Verified
that build is supported by all three: CloudRedirect lists it explicitly
(`SUPPORTED_STEAM_VERSIONS`), it is SLSsteam's headcrab target by definition,
and lumalinux's current hash set covers that era (shared `steamclient.so` hashes
with SLSsteam). It downgrades to an *older stable* build, so even a slightly
lagging component still supports it.

**Render:** each row is `icon` ⚠ (`#ff8c00`) + `label` = *"[Component] —
[impact]"* + `description` = the text below + the control. The component
(technical name) stays, led by the plain-language impact.

**SLSsteam** — impact: *"games won't launch"*

| State (backend) | description | control |
|---|---|---|
| `not_active` | "Not active." | 🔘 **Restart Steam** |
| `injection_missing` | "Not correctly installed." | 🔘 **Repair** → `reinjectInstalled` |
| `unsupported` (= `broken` patterns/hash) | "Unsupported Steam version. Run enter-the-wired in Desktop." | 📄 Field |

**lumalinux** — impact: *"downloads disabled (installed games OK)"*

| State (backend) | description | control |
|---|---|---|
| `not_active` | "Not active." | 🔘 **Restart Steam** |
| `injection_missing` | "Not correctly installed." | 🔘 **Repair** → `install_lumalinux` (patch-only, safe alone) |
| `unsupported` (= `hash_blocked` / `hooks_failed`) | "Unsupported Steam version. Run enter-the-wired in Desktop." | 📄 Field |

**CloudRedirect** — impact: *"cloud saves off"*

| State (backend) | description | control |
|---|---|---|
| `not_active` | "Not active." | 🔘 **Restart Steam** |
| `unsupported` (= `broken`) | "Unsupported Steam version. Run enter-the-wired in Desktop." | 📄 Field |
| `not_authed` | "Sign in via the CloudRedirect app in Desktop." | 📄 Field |

**Wiring notes:**
- **Restart Steam** → `restart_steam` (clean `steam -shutdown`, GM auto-restarts).
- **Repair** → SLSsteam: `reinjectInstalled` (its headcrab wipes the others, so
  re-inject the whole installed set in order). lumalinux: `install_lumalinux`
  alone (patch-only — restores its block, preserves the others; no need to touch
  SLSsteam/CR).
- **Field** rows are display-only (no button); the instruction is in the
  `description`. `unsupported` and `not_authed` are Desktop-only.
- Text drops jargon (`steam.sh`, hooks, patterns, hash, SafeMode) and the
  `hooks_failed` `{0}` hook name (kept in logs only).

### 4. Add Game — mode toggle (By AppID / By name) — ✅ built (v0.3.34)

- **What:** switch the Add Game input between AppID entry and name search; the
  content below follows the selection.
- **How shown:** two native `DialogButton`s in a `Focusable` row. **Focusing**
  one selects its mode (`onFocus`/`onGamepadFocus` → `setAddMode`), so moving
  L/R swaps the content below — native-tab behaviour, but it fits the narrow QAM
  where the native `Tabs` row would look oversized (Tabs is built for full-width
  pages).
- **Native or custom:** 🟢 mostly native — no background/glow override, so the
  **native focus** (white fill) is the only indicator while on the toggle; once
  focus is in the content, the content (AppID field vs search) shows the mode.
  Replaces the old custom segmented control (accent fill + hand-made scale+glow
  focus, which existed only because the fill suppressed native focus).
- **Rule:** for a 2-mode switch with per-mode content in the QAM, prefer
  focus-driven native `DialogButton`s over a custom segmented control or the
  page-sized native `Tabs`. Don't override `background` (it kills native focus);
  let focus + the content below indicate state. No persistent active marker
  needed.
- **Verify on device:** returning *up* from the content should re-focus the
  active mode's button (Decky usually restores last focus within a `Focusable`).
- **No field labels in Add Game:** the tab already names the mode ("By AppID" /
  "By name"), so the AppID and search `TextField`s carry **no `label`** — it
  would be redundant. The active tab is the field's context.

### 4b. Add Game — game info preview — ✅ built

- **What:** the preview shown after a valid AppID — confirms which game you're
  about to add.
- **How shown:** a native **`Field`**: `label` = game name, `description` = a
  trimmed fact line *"dev · size · Metacritic NN · ProtonDB Tier"*. The
  description is a `ReactNode`, so Metacritic and ProtonDB keep their **colour as
  inline text**. `bottomSeparator="standard"`. The slscheevo achievements hint
  stays as a small gold line below.
- **Native or custom:** 🟢 native `Field`. Replaces the custom `Notice` card +
  hand-made badge pills. The only thing dropped is the card box and the grey
  pills — info is preserved (colour included), and platforms / achievement count
  / PT-BR move to GameDetail.
- **Rule:** a colored badge/pill has no native equivalent, but most "rich card"
  content reduces to a native `Field` (name = label, facts = a `·`-joined
  `description` ReactNode that can colour the meaningful bits). Reach for a
  custom box only when the colour-coded *badge shape* itself is essential.

### 4c. Add Game — alerts (game notices / credentials) — ✅ built

- **What:** notices about the game being added, and a credential warning shown
  at add-time.
- **How shown (native rows, same as Health §3):**
  - **Game notices** (info, no action) → one display-only **`Field`** per note,
    ⚠ gold (`#c8a84b`) icon, the note as the label.
  - **Credential warning** (fixable in Settings) → an actionable **`ButtonItem`**
    "Configure API key" → `Navigation.Navigate(ROUTE_SETTINGS)`, the warning as
    `description`, ⚠ icon in the warning colour. (Health tier-2 pattern.)
- **Native or custom:** 🟢 native. Removes the last custom `Notice` cards from
  Add Game — `components/Notice.tsx` is deleted (no remaining users).
- **Scope decision:** only the **Hubcap API key** warning is surfaced here; Ryuu
  is intentionally dropped (not relevant to adding a game).

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
- **Alerts map to native controls by nature**, not one colored box: actionable
  → `ButtonItem` (message in `description`, action in the label); pure info →
  `Field` (`icon` + `label`/`description`); only genuinely rich content (a
  badge grid) keeps a custom container. Severity is carried by a **coloured
  icon**, not a box.
- **Never render a control (button) for something that can't act from the
  current context.** Show it as display (`Field`) with instructions instead.
- Native **text lives in control slots**: `label` / `description` of
  `ButtonItem`/`Field`, `title` of `PanelSection`. Only *free-floating* text
  needs a raw `<div>`.

