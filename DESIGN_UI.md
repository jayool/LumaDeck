# LumaDeck — UI Design

Single source of truth for the plugin's UI. **Rebuilt from scratch**, verified
element by element against the live code. Nothing here is assumed — every entry
is checked in the source before it is written down.

> **Status: QAM finalized.** The QAM (`GameList`) has been walked top to bottom —
> every element verified against the live code and its rule fixed, including the
> full Add Game state tree (§4–4e), the closing-divider / section-merge model,
> and the bottom nav (§5–6). Other surfaces (Settings, GameDetail, full-screen
> pages) are documented below and refined as they're revisited.

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
block into it. `install_dependencies` runs **headcrab**, which installs and
re-injects **both SLSsteam and CloudRedirect in one pass** and **regenerates
`steam.sh` from scratch** — wiping any *other* component's block.
`install_lumalinux` is the exception: it only *patches* (idempotent), so it
never wipes the others, and it must run **last** so its block survives the
headcrab regeneration.

Consequence — a per-component repair that runs headcrab **silently breaks the
others**:

- SLSsteam `injection_missing` or CloudRedirect `broken` repaired with
  `install_dependencies` alone → re-injects SLSsteam + CloudRedirect (one
  headcrab) but **wipes lumalinux**.

**Rule:** any repair that runs headcrab must **re-inject every *installed*
component, in order `SLSsteam + CloudRedirect → lumalinux`** — not a bare
`install_dependencies`. This is a dedicated routine, `reinject_installed()`
(gated on `check_*_installed()`; never installs a component the user doesn't
have). Wire SLSsteam `injection_missing` and CloudRedirect `broken` to it.
`restart` (no `steam.sh` change) and `install_lumalinux` (patch-only) are safe
standalone and stay as-is.

**What `injection_missing`'s repair does, concretely** — `reinject_installed()`:
re-runs `install_dependencies` (SLSsteam + CloudRedirect, one headcrab) **if
either is installed**, then lumalinux (`install_lumalinux`) **if installed**, in
that order — rebuilding a correct shared `steam.sh`. Each step is gated on
`check_*_installed()`, so it only ever re-injects what the user already had; it
never installs a new component.

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
fix is the same: **run the Steam downgrade in Desktop** ("Fix in Desktop"),
which (via headcrab) downgrades Steam to the blessed stable build `1782257239`
(2026-06-10). Verified
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
| `unsupported` (= `broken` patterns/hash) | "Unsupported Steam version. Run the Steam downgrade in Desktop." | 📄 Field |

**lumalinux** — impact: *"downloads disabled (installed games OK)"*

| State (backend) | description | control |
|---|---|---|
| `not_active` | "Not active." | 🔘 **Restart Steam** |
| `injection_missing` | "Not correctly installed." | 🔘 **Repair** → `install_lumalinux` (patch-only, safe alone) |
| `unsupported` (= `hash_blocked` / `hooks_failed`) | "Unsupported Steam version. Run the Steam downgrade in Desktop." | 📄 Field |

**CloudRedirect** — impact: *"cloud saves off"*

| State (backend) | description | control |
|---|---|---|
| `not_active` | "Not active." | 🔘 **Restart Steam** |
| `unsupported` (= `broken`) | "Unsupported Steam version. Run the Steam downgrade in Desktop." | 📄 Field |
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

### 4b. Add Game — game info card (shared) — ✅ built

- **What:** the card shown once a game is staged — confirms which game you're
  about to add. **Shared by both modes:** By AppID stages it via the field
  (debounced `getGameNotices` on `addAppId`); By name stages it by picking a
  search result. It lives as one `gameCard` const built just before `return`,
  rendered in both branches — no duplicated card JSX.
- **How shown:** a native **`Field`**: `label` = game name, `description` = a
  trimmed fact line *"dev · size · Metacritic NN · ProtonDB Tier"*. The
  description is a `ReactNode`, so Metacritic and ProtonDB keep their **colour as
  inline text**. **`bottomSeparator="none"`** — the card is grouped with the
  Add-game button below it (the closing divider §4d draws the one section line),
  not fenced off by its own separator. The game **notices** (Denuvo / launcher)
  render **inside** this same `description`, one `<div>` per note with an inline
  ⚠ `#ff8c00` icon, so they read as part of the card. The slscheevo achievements
  hint stays as a small gold line below.
- **Native or custom:** 🟢 native `Field`. Replaces the custom `Notice` card +
  hand-made badge pills. Dropped: the card box and grey pills — info preserved
  (colour included); platforms / achievement count / PT-BR move to GameDetail.
- **Rule:** a colored badge/pill has no native equivalent, but most "rich card"
  content reduces to a native `Field` (name = label, facts = a `·`-joined
  `description` ReactNode that can colour the meaningful bits). Reach for a
  custom box only when the colour-coded *badge shape* itself is essential. One
  shared const, not per-mode copies.

### 4c. Add Game — blocked state (why you can't add) — ✅ built

- **What:** a single top-of-section row that says **why** adding is blocked, plus
  a disabled Add-game button. Shown whenever `!canAddGames`
  (`compsBad` = SLSsteam/lumalinux not healthy, or `credBad` = no Hubcap/Ryuu
  key).
- **How shown:** one display-only **`Field`** right under the mode toggle, with
  an inline ⚠ `#ff8c00` icon + `addBlockedReason`. The reason is specific, not a
  generic "fix the issues": `compsBad` → point at the System Status row above
  (`addGameBlockedComponents`); `credBad` → fix in Settings
  (`addGameBlockedCred`). The Add-game / Search buttons are `disabled` while
  blocked, and each search result is `disabled` too.
- **Removed:** the old **per-game credential warning** (an actionable
  `ButtonItem` "Configure API key" that floated a ⚠ icon and duplicated the top
  row). One blocked row at the top + a disabled button is the whole story now —
  no second warning near the button.
- **Native or custom:** 🟢 native `Field`. `components/Notice.tsx` stays deleted.
- **Rule:** state *why* an action is blocked **once**, at the top of the section,
  and point at where it's fixed. Don't repeat the warning next to the disabled
  control; the disabled control + the top reason are enough.

### 4d. Add Game — action button, status & closing divider — ✅ built

- **Button:** renamed "Download Manifest" → **"Add game"** (`addGameAction`).
  Native **`ButtonItem`** with **`highlightOnFocus={false}`** (drops the focus
  *glow* — the dark halo that would wrap the whole row band — keeping only the
  native white fill) and **`bottomSeparator="none"`** (the closing divider draws
  the section line, so the button doesn't fence itself off from its status).
  `disabled={!canAddGames}`.
- **Status (`addStatus`):** a plain aligned `<div>` in a `PanelSectionRow`
  (inherits the native content inset — do **not** wrap it in a `Field`, which
  knocks it out of horizontal alignment). `textAlign:"left"`, three-way colour:
  red on error (`error*` / `invalidAppId` / `downloadFailed`), green on
  `doneRestartSteam`, grey otherwise.
- **Progress:** hand-drawn gradient bar → native **`ProgressBarWithInfo`**
  (`nProgress` = percent, `sOperationText` = "read / total GB · speed"), a direct
  `PanelSectionRow` child (nesting it shifted the native bar off the edge).
- **Closing divider:** one native line ends the section (`<Field
  bottomSeparator="standard" padding="none" />`). It's **conditional** — skipped
  when the results list is on screen, because each result / Show-more
  `ButtonItem` already draws its own bottom line and a second divider would
  **double** the line. `padding="none"` keeps it thin with no extra vertical gap.
- **Native or custom:** 🟢 native button + progress; 🔴 the `addStatus` `<div>`
  (Decky has no text primitive — the documented exception).

### 4e. Add Game — "By name" search & results — ✅ built

- **What:** the name-search path: a search field, and then **either** a results
  list (with "Show More") **or**, once a result is picked, the staged game.
- **Pick-a-result stays in place (`nameSelected`):** selecting a search result
  does **not** jump to By AppID. It stays in By name and mirrors it —
  `handleSelectSearchResult` fills the field with the game **name**, stages the
  appid (drives the shared `gameCard` §4b), clears the results, and flips the
  button from **Search** to **Add game**. Editing/clearing the field
  **deselects**: `nameSelected → false`, appid cleared, so the card disappears
  and the button reverts to **Search**.
- **Stale results clear on edit:** typing in the search field clears the
  previously shown results (`setSearchResults([])` + `setShowMoreResults(false)`)
  so a list from the last query doesn't linger until the next search.
- **How shown:**
  - Search field → native `TextField` (no label, per §4). Search / Add-game
    button → native `ButtonItem` (`highlightOnFocus={false}`,
    `bottomSeparator="none"`).
  - **Results count** → a native **`Field`** (`bottomSeparator="standard"
    padding="none"`) whose label is a small grey span — the only row without a
    separator would otherwise sit flush against the first result, so it carries
    the native line like the result rows. Singular/plural via `result`/`results`.
  - **Results** → native `ButtonItem` each (`label` = name, `description` =
    `AppID: …`). **Show More** → native `ButtonItem` (`+N`), capping 5 → 15.
- **Native or custom:** 🟢 native field / buttons / count `Field`. `searchError`
  stays a raw aligned `<div>` (the text-primitive exception, 🔴).

**Add Game is box-free:** native tab toggle, label-less fields, one shared
`Field` game card (notices inline), a single top blocked row, native progress,
a native-`Field` results count, and one conditional closing divider — no boxes,
no doubled lines.

### 5. My Games — QAM entry — ✅ built

- **What:** the entry point to the full-screen library. My Games **lives on its
  own route** (`ROUTE_LIBRARY`, `Library.tsx`) — the QAM only shows a compact
  launcher entry, not the list.
- **How shown:** a single plain native `ButtonItem` → `Navigation.Navigate(
  ROUTE_LIBRARY)`. Same shape as the Downloads entry (§1b).
- **Bottom nav lives in the Add Game `PanelSection`, not its own:** My Games /
  Achievements / Workshop are rows in the **same** `PanelSection` as Add Game.
  A separate section stacked two sections' vertical padding into a big empty gap
  after the closing divider (§4d); as rows here, the divider is followed by My
  Games with the normal single-row rhythm. **Rule:** consecutive QAM groups
  separated by a divider go in **one** `PanelSection` — a new `PanelSection` adds
  a second block of section padding and reads as a big gap.
- **Removed:**
  - The `PanelSection title="My Games"` **and** the button label `"My Games"`
    were the *same word stacked twice* (section header + control). Dropped the
    title; the button label carries the name.
  - The manual `" → "` glyph in the label — an arrow typed into the string is
    not a native affordance. A navigating `ButtonItem` needs no arrow; if a
    "goes to a page" hint is ever wanted it's a native `icon`, not a character.
  - The `(N)` count — the full-screen page owns the list, and a count in the QAM
    costs a **full library load** just to render a number. Label is now just
    `t("myGames")`.
- **Native or custom:** 🟢 native `ButtonItem`, no title, no glyph, no count.
- **Follow-up — ✅ done (v0.3.75):** the panel used to load the whole library on
  mount because the Sync-all-achievements button (§6) consumed `games`. §6 moved
  Sync All to its own page and `loadGames` was dropped from the QAM, so the panel
  is now lazy — it no longer loads the library just to render a launcher.
- **Rule:** a navigation entry is **one** plain `ButtonItem`; the label names the
  destination. Never repeat the destination in a section title above it, never
  type arrows into labels, and never put a value in the QAM that forces a data
  load purely to display it.

### 6. Achievements (SLScheevo) — QAM entry → dedicated page — ✅ built (v0.3.75)

- **What it is:** SLScheevo (third-party, xamionex) generates a game's
  achievement files so Steam recognises them.
- **Split (v0.3.75):** everything **global** — install the binary, the one-time
  interactive Steam login (Desktop/Konsole only — Game Mode has no terminal),
  **Sync All**, and a "X of Y generated" overview — lives on a **dedicated
  full-screen Achievements page** (`Achievements.tsx`, `ROUTE_ACHIEVEMENTS`).
  **Per-game** generation stays on the game page (`GameDetail.tsx` →
  "Achievements" section): status machine
  (`not_installed` → `not_configured` → `ready`/`generating`/`generated`) plus
  the per-game **Generate** button. In the two setup states GameDetail shows the
  reason + a button that navigates to the Achievements page — it no longer
  carries the global download/login buttons.
- **What the QAM button does:** *only* navigate — one plain `ButtonItem`
  (`t("achievements")`) among the bottom-nav rows (in the Add Game
  `PanelSection`, see §5), next to My Games / Workshop, routing to
  `ROUTE_ACHIEVEMENTS`. No achievement logic in the QAM
  anymore (the inline Sync All + its `slscheevoReady`/`syncState` plumbing were
  removed).
- **Why a page, not a sidebar:** the page is a single concern (setup + sync), so
  a plain scroll page (same wrapper as Downloads/Library) reads cleaner than a
  one-item `SidebarNavigation`. Convert to a sidebar only if it grows sections.
- **Sync All (now on the page):** native `ButtonItem`, `disabled` while running,
  a native **`ProgressBarWithInfo`** below it (`nProgress` = `done/total·100`,
  `sOperationText` = `"3 / 12"`), completion/failure via `toaster.toast`.
- **Native or custom:** 🟢 fully native — `ButtonItem` + native progress bar +
  native toast. No `<div>` for actions.
- **Rule:** global one-time setup does not belong on a per-item page. When an
  action is library-wide (install a shared binary, a bulk sync), give it its own
  entry; the per-item page keeps only what is per-item.
- **Follow-up (carried from §5) — ✅ done (v0.3.75):** moving Sync All off the
  QAM removed the last consumer of the panel's `games` list. `loadGames`,
  `games`, `loading`, and the `getInstalledLuaScripts`/`checkAllAchievementsStatus`
  calls are gone from `GameList`, so the QAM panel no longer loads the whole
  library on mount — it only fetches system status. The lazy-load win §5 wanted
  is now realised. The full games list (with achievement badges) is loaded only
  by the Library page, which owns its own `loadGames`.

---

## Full-screen pages — top to bottom

The QAM is a launcher; space-hungry views live on their own routes
(`routerHook.addRoute` in `index.tsx`): **Library** (My Games), **GameDetail**,
**Settings**, **Downloads**. (`Help` is no longer a standalone page — see §7.)

### 7. Library (My Games) — full-screen — ✅ built

- **What:** the full games list, reached from the QAM's My Games button
  (`ROUTE_LIBRARY`). Builds its own list from `getInstalledLuaScripts` (so every
  row is a lua-managed game) and polls `getActiveDownloads` for live phase.
- **Container — was `SidebarNavigation` with ONE page → now a plain page.** A
  single-page sidebar renders a left rail with one item next to the content —
  pure overhead. Library is now a plain scrollable page
  (`<div style={{marginTop:40, height:'calc(100% - 40px)', overflowY:'scroll'}}>`
  + the `PanelSection`). This also removes the **doubled "My Games"** (the
  sidebar page title *and* the `PanelSection` title were the same string) — only
  the section title remains. *(Downloads still uses a 1-page `SidebarNavigation`;
  same treatment pending when we reach it.)*
- **Sort control removed.** A `ButtonItem` that **cycled** A-Z → AppID → Recent
  on each tap was low-discoverability custom interaction. For a personal list,
  type-to-filter (the `TextField`) + a fixed A-Z sort is enough. Dropped the
  button, `sortMode` state and the `sort` i18n key.
- **`GameCard` — colour dot removed, dead progress bar removed:**
  - The hand-built 8px coloured status **dot** (`<div>`+`<span>` flex) is gone.
    State is already named by the row's coloured `description` text, so the dot
    was redundant. Card is now `ButtonItem` `children = {name}`, `description =`
    a single coloured `<span>` (`installed`/`manifest only`/`disabled` +
    `— appid`), colour kept (green `#00cc00` / amber `#ffaa00` / blue `#1a9fff`
    while a phase is active).
  - The custom **`ProgressBar`** branch was **dead code**:
    `downloadProgress`/`downloadTotal` were never assigned anywhere (Library only
    sets the phase string). Steam does the actual download natively — there are
    no bytes for the plugin to show — so the bar never rendered. Removed the
    branch, the two fields and the `ProgressBar` import. The **phase text**
    (`Installing…`, `Configuring…`, `Restarting Steam…`) stays — that's real
    post-download lumalinux work, shown as the coloured `description`.
  - Reachable states here: **Installed** (green, `· ★` if achievements),
    **Manifest only** (amber), **Disabled** (amber), **Downloading/phase**
    (blue). The grey **Pending** (no-lua) branch is **unreachable** in Library
    (every row has lua by construction) — kept in the component only for reuse.
- **`Help` relocated.** `Help.tsx` was a fully-built page wired to **nothing**
  (no route, no import). Its content is general plugin help, so it now lives as
  a **page in the Settings sidebar** (`HelpContent`, no back button — the sidebar
  owns navigation). `Help.tsx` exports `HelpContent`; `Settings.tsx` adds a
  `FaQuestionCircle` "Help" page after About.
- **Native or custom:** 🟢 plain native page — `PanelSection` + `TextField` +
  native `ButtonItem` rows (`GameCard`). Remaining `<div>`s are the
  loading/empty status lines (free-floating text, on-token) and the page's
  scroll wrapper (structural, not decorative).
- **Rule:** a single-list route is a **plain scrollable page**, not a 1-page
  `SidebarNavigation`. Don't ship cycle-through controls where a filter or a
  `Dropdown` fits. Never render UI for data that no longer exists (the native
  Steam download killed per-game byte progress — delete it, don't leave it
  guarded-but-dead). A built page wired to nothing is either routed or deleted —
  Help was rehomed.

### 8. GameDetail — full-screen, 6-page `SidebarNavigation` — ✅ built (8a–8f done)

The per-game page (`ROUTE_GAME_DETAIL/:appid`). **`SidebarNavigation` is
justified here** — it has six genuine sections: Status, Download, Game
Management, Achievements, Fixes, Uninstall. Reviewed page by page.

**`ActionButton` is fine (not custom chrome).** Used across the page, it's just a
native `ButtonItem` with a colour-tinted label (`danger` red `#ff4444`,
`primary` blue `#1a9fff`) — matches the "coloured text in a control slot"
principle. Kept as-is.

**Decided in advance (boxes, when we reach their pages):**
- *Uninstall* red box → **native**: the destructive list becomes a `Field`
  (label + `·` list in the description); severity is already carried by the red
  `danger` button, the two-click confirm, and the page literally titled
  "Uninstall". No hand-bordered box.
- *SLScheevo path* code box → **simplify**: you can't copy it (Game Mode has no
  clipboard to Konsole), so it's reference text, not a copy affordance. Keep a
  legible monospace line, drop the dark bordered "code block" framing.

#### 8a. Status page — ✅ built

- **What:** read-only summary — AppID, install status (+ size), install path.
- **Was:** three raw `<div>`s (`AppID: …`, `Status: …` coloured, the path).
- **Now:** native `Field` rows —
  - `Field label="AppID"` → value on the right (AppID is a technical literal used
    across the codebase, not display prose, so no `t()` — consistent with
    GameCard / search results).
  - `Field label={t("gameStatus")}` → coloured status value as children
    (green installed / amber manifest-only / grey not-installed, `+ size`), with
    the **install path as the Field's `description`** sub-line (one Field does
    both; no separate path `<div>`).
- **"Not installed" state removed.** It required `hasLua === false`, but every
  game reachable here arrives from My Games (which only lists lua-managed games),
  so `hasLua` is always true on entry — the only false instant is the ~1.5s flash
  after Uninstall before `NavigateBack()`. So the status row is gated on `hasLua`
  (hidden in that flash) and collapses to two real states: **Installed** (green,
  has files) / **Manifest only** (amber, config but no files). Dropped the
  `notInstalled` i18n key. (Same "delete the unreachable state" call as
  GameCard's grey *Pending*.)
- **Native or custom:** 🟢 native `Field`s; the only inline style left is the
  status **colour** on the value `<span>` (a control-slot child, allowed).
- **Rule:** read-only "label: value" info is a native `Field` (label + value
  child), not a `Label: value` `<div>`. A secondary detail (a path) rides as the
  Field `description` rather than spawning its own row. Don't render states the
  navigation can't reach.

#### 8b. Download page — ✅ built (v0.3.52)

- **What:** start/cancel a download, auto-update toggle, and the in-flight
  status + result/warning messages.
- **Was:** half-native. The structure (`PanelSection`/`PanelSectionRow`), the
  `ToggleField` (auto-update) and the `ActionButton`s were already native; the
  custom chrome was a raw status `<div>`, the custom `ProgressBar` component, two
  hand-bordered orange warning boxes (stuck update, hubcap-key-expired), and two
  raw coloured `<div>`s for done/failed.
- **Now:**
  - **Status line + bar → one native `ProgressBarWithInfo`.** The phase label,
    `API:`, byte counter and speed all ride in `sOperationText`; `nProgress` is
    the byte ratio. `indeterminate` for phases with no measurable total
    (processing/installing/configuring/…). Same pattern as the QAM download bar.
  - **`depot_download` branch deleted.** Dead DDL path (backend no longer runs
    it); the status-label map and the bar no longer reference it.
  - **Stuck-update box → one native actionable `ButtonItem`** (⚠ amber icon,
    `label` = title, `description` = body + key hint, children = "Fix Update",
    `onClick` = re-download). Collapses the old box + separate Fix-Update button
    into one row. **No "open game" action** — we're already in GameDetail.
  - **Hubcap-key-expired box → one native actionable `ButtonItem`** (⚠ amber,
    `onClick` → Settings, where the Hubcap key lives). Same shape as GameList's
    `credWarnings` row.
  - **done / failed → native `Field`** (green child for "complete"; ⚠ red icon +
    error in `description` for failed).
- **Native or custom:** 🟢 native; only inline style left is the status **colour**
  on the "complete" `<span>` child (allowed control-slot colour).
- **Rule:** in-progress work is a native `ProgressBarWithInfo` (text in
  `sOperationText`, never a sibling `<div>`); a warning that has a fix is an
  actionable `ButtonItem` with a `FaExclamationTriangle` icon, not a
  hand-bordered box. Reuse the established native warning shape; don't re-skin it.

#### 8c. Game Management page — ✅ built (v0.3.53)

- **What:** the FakeAppId / token / DLCs / Goldberg controls. **No "Advanced
  Options" toggle** — the controls are **always visible**; the toggle that used
  to gate them was removed (hiding routine per-game management behind an extra
  tap added nothing).
- **Was:** already almost fully native (`ToggleField`, `TextField`,
  `ActionButton`s), but gated behind an "Advanced Options" toggle whose
  `description` was `t("gameManagement")` — repeating the section title verbatim
  as a meaningless sub-line — and the FakeAppId `TextField` was wrapped in two
  pointless `<div>` flex containers (leftover from an old side-by-side layout).
- **Now:** the gating toggle is gone (controls always shown); the wrapper
  `<div>`s removed (TextField is a direct `PanelSectionRow` child like every
  other row). `"FakeAppId"` stays a hardcoded literal (technical term, like
  AppID).
- **Native or custom:** 🟢 fully native, no inline styles left on this page.
- **Rule:** don't wrap a native control in layout `<div>`s "just in case"; a
  control is a direct row child. Don't hide routine per-game controls behind an
  extra toggle. A `description` must add information — never echo a section
  title.

#### 8d. Achievements page — ✅ built (v0.3.54)

- **What:** a 5-state machine (not_installed / not_configured / generating /
  generated / ready) for the SLScheevo achievement-generation flow.
- **Was:** every state's status line was a raw coloured `<div>` (gray/amber/
  blue/green), and the not_configured state showed the binary path in a dark
  bordered "code block" `<div>`.
- **Now:**
  - Status lines → native `Field`. Colour signal carried by **icons** (per the
    "icons not coloured text" choice): ⚠ amber `FaExclamationTriangle` on
    not_configured, ✓ green `FaCheckCircle` on generated; the neutral states
    (not_installed / generating / ready) are plain `Field`s.
  - Path "code block" → a plain **monospace** line inside a `Field` description
    (monospace kept, dark frame dropped — the §8 decision).
  - Dropped the redundant `description` on the generated-state button (it echoed
    the status line above it).
- **New capability — "Configure in Desktop":** SLScheevo's login is an
  interactive terminal flow (Desktop only), so the not_configured state now has a
  primary **"Configure in Desktop"** button. It reuses the v0.3.50 hand-off with
  an **interactive payload**: arms an autostart that opens Konsole already
  running `cd <dir> && ./<binary>`, switches to Desktop, and — unlike the
  downgrade — does **NOT** auto-return (the user logs in, then switches back by
  hand; konsole stays open via `--hold`). The backend recomputes the binary path
  via `find_slscheevo_binary()` (no command from the frontend) and `shlex.quote`s
  it. The monospace command line stays as a manual fallback.
- **Native or custom:** 🟢 native `Field`s + icons; only inline style left is
  `fontFamily: monospace` on the path span (a value child, allowed).
- **Rule:** a Desktop-only interactive setup (SLScheevo login, like CR sign-in)
  gets a hand-off button with an **interactive, no-auto-return** payload — the
  user drives the console and returns manually. Don't fake a round-trip around an
  interactive flow.

#### 8e. Fixes page — ✅ built (v0.3.55)

- **What:** the long action list (check for fixes, apply generic/online fix,
  Linux-native fix, Steamless DRM removal, reconfigure SLSsteam, repair ACF) plus
  the "Installed Fixes" list.
- **Was:** almost all native already (every action is an `ActionButton`). Three
  bits of custom chrome: a gray `<div>` "No fixes available", the custom
  `ProgressBar` while a fix applies, and the Installed-Fixes rows as nested raw
  `<div>`s (type + file count, applied date).
- **Now:**
  - "No fixes available" → native `Field` (plain, neutral info).
  - Apply-fix progress → native `ProgressBarWithInfo` (`sOperationText` =
    phase label, `indeterminate` when no byte total) — same pattern as 8b/8d.
  - Each Installed Fix → native `Field` (`label` = "type — N files",
    `description` = applied date).
  - Removed the now-unused `ProgressBar` custom-component import from this file
    (the component still lives for Library/Downloads).
- **Native or custom:** 🟢 fully native; no inline styles left on this page.

#### 8f. Uninstall (Danger Zone) page — ✅ built (v0.3.56)

- **What:** the destructive full-uninstall flow — a "what will be removed" list,
  a "remove Proton prefix" toggle, and the red two-tap uninstall button.
- **Was:** a hand-bordered **red box** (`<div>` with red bg/border/radius), an
  uppercase "WHAT WILL BE REMOVED" header, and 6 items each with a red `✕` mark.
- **Now:** the box → a single native `Field` (`label` = "What will be removed",
  `description` = the 6 items joined with ` · `), with a ⚠ red
  `FaExclamationTriangle` icon for the destructive signal. The hand-bordered box,
  the uppercase header and the per-item `✕` are gone; the rest of the severity is
  carried by the red `danger` button, the two-tap confirm, and the "Danger Zone"
  title. `ToggleField` + uninstall `ActionButton` were already native.
- **Native or custom:** 🟢 fully native; no inline styles left on this page.
- **Rule:** a destructive-action summary is a native `Field` (icon + label + ` · `
  list), not a hand-bordered coloured box. Let the danger button + confirm +
  page title carry severity; the icon is the only decorative signal kept.

**GameDetail done.** All six pages (Status, Download, Game Management,
Achievements, Fixes, Uninstall) are native. The page has zero hand-bordered
boxes and only the handful of allowed inline styles (status colours on value
spans, monospace on path spans).

---

### 9. Settings — full-screen, 6-page `SidebarNavigation` — ✅ built (9a–9f done)

The config surface (`ROUTE_SETTINGS`). Six pages: API Credentials, SLSsteam,
Dependencies, System, About, Help. **Dependencies is the "advanced 1%" detailed
per-component breakdown** (the QAM's `SystemStatus` is the collapsed view for
everyone else). Audited: ~27 custom-chrome spots, mostly **colored status
`<div>`s** (green installed / red not-found / amber degraded / blue update),
plus 2 monospace command "code-block" alert boxes (SLSsteam, Dependencies) and 1
custom disk-usage bar (System). Same three native patterns as GameDetail:
status → `Field` (icon for the colour signal), command box → `Field` with
monospace `description`, custom bar → `ProgressBarWithInfo`.

#### 9a. API Credentials page — ✅ built

- **Was:** two colored status sub-line `<div>`s — `renderCredLine` (credential
  validity: green ok / amber soon / red expired / gray none) and
  `renderHubcapUsage` (gray daily-usage stat).
- **Now:** both → native `Field`. The validity line carries its colour via an
  **icon** (✓ green `FaCheckCircle` ok, ⚠ amber soon, ⚠ red expired, plain for
  none/unknown), text as `label`; the usage stat is a plain `Field`.
- **Native or custom:** 🟢 native; the credential inputs/buttons were already
  `TextField`/`ButtonItem`.

#### 9b. SLSsteam page — ✅ built

- **Was:** the repair/update zone had a colored status `<div>` (amber broken /
  blue update) and, when the fix is Game-Mode-blocked, a hand-bordered alert
  block: bold colored title + body + a dark monospace "code block" with the
  Desktop command.
- **Now:** status line → `Field` (⚠ amber icon broken / `FaInfoCircle` blue
  update). Alert block → a `Field` (icon + title `label` + body `description`)
  plus a second `Field` whose `description` is the command in a plain monospace
  span (dark box dropped). Toggle + Restart + Repair buttons were already native.
- **Note:** `gamemodeBlocked` is the same "downgrade in Desktop" case the QAM
  `SystemStatus` now solves with a "Fix in Desktop" hand-off button. Here the
  Repair button is still *disabled* with a manual command shown — a future pass
  could wire the v0.3.50 hand-off here too. Out of scope for the native pass.
- **Native or custom:** 🟢 native; only inline style left is monospace on the
  command span.

#### 9c. Dependencies page — ✅ built

The dense "advanced 1%" per-component breakdown — the biggest custom-chrome
cluster (~16 spots). Converted with the two patterns:
- **Install-status rows** (SLSsteam, .NET Runtime, lumalinux,
  CloudRedirect) → native `Field` (8a pattern): `label` = component name,
  coloured value child (green "Installed" / red "Not found"), install path as
  `description`.
- **Health / update / provider-auth / Steam-build sub-lines** → native `Field`
  with an **icon** signalling state: ✓ green healthy, ⚠ amber degraded/broken,
  `FaInfoCircle` blue update, `FaInfoCircle` gray for CR `kill_switched`.
- **Game-Mode-blocked alert box** → `Field` (icon + title + body) + a `Field`
  with the command in a monospace span (dark box dropped) — same as §9b.
- Removed the `<div style height:8px>` spacer (native rows space themselves) and
  the three `<div textAlign:center>` wrappers inside the Install/CR/lumalinux
  button `description`s (plain strings now).
- **Native or custom:** 🟢 native; inline styles left are the status colour on
  the install-value spans and monospace on the command span (both allowed).

#### 9d. System page — ✅ built

- **Was:** centered gray "current language" `<div>`, a gray "Steam: <root>"
  `<div>`, and per Steam library a nested `<div>` block (path line + free/games
  line + a **custom disk-usage bar** = background `<div>` + colored fill).
- **Now:** language line → plain `Field`; platform → `Field label="Steam"
  description={root}`; each library → a `Field` (path + default tag) plus a
  native `ProgressBarWithInfo` (usage %, with free/total + game count in
  `sOperationText`). Used `flatMap` to emit the Field + bar as two keyed rows.
- **Note:** the old bar tinted red >90% / amber >75%; `ProgressBarWithInfo` has
  no threshold colour, so that signal is dropped (the % + text remain). Acceptable
  trade for native.
- **Native or custom:** 🟢 native; no inline styles left.

#### 9e. About page — ✅ built

- **Was:** a gray blurb `<div>`, a version `<div>` (installed + a colored
  `<span>` latest), and a blue plugin-message `<div>`.
- **Now:** blurb → `Field description`; version → `Field label={installed}` with
  the latest as a colored value child (blue when an update exists); plugin message
  → plain `Field`. Update buttons were already native.
- **Native or custom:** 🟢 native; only the latest-version value span keeps its
  colour (allowed).

#### 9f. Help page — ✅ built (content written)

- **Finding:** the Help tab was **broken since v0.3.9** — `Help.tsx` referenced
  `help*` i18n keys (`helpWhatIsDesc`, `helpHowToAddSteps`, the feature lines,
  `helpTroubleshootingTips`, …) that were **never defined** in LumaDeck's
  `i18n.ts`. With `t()` falling back to the key itself (`i18n.ts`: `… || key`),
  the page rendered raw variable names, not text. Confirmed via git (`-S`: the
  keys only ever appeared in `Help.tsx`, never in `i18n.ts`) and against the
  upstream — **DeckTools' own `i18n.ts` (master) doesn't contain them either**,
  so there was no original text to recover. Nothing was deleted; the strings were
  simply never written.
- **Fix:** wrote English help content for all keys (what LumaDeck is, how to add
  a game, the six features, troubleshooting tips). en only — pt-BR falls back to
  en via `t()`. **Content is sourced from `docs/`** (getting-started,
  managing-a-game, troubleshooting) — an earlier from-memory draft had
  inaccuracies (e.g. Token described as an ownership token, and the add-a-game
  steps missed the restart-Steam → press-Install flow); aligned to the docs.
- **Render:** the **Features** list → native `Field` per feature (name as
  `label`, explanation as `description`). The prose sections (what-is, how-to-add
  steps, troubleshooting) stay readable `<div>` body text with `pre-line` — Decky
  has no paragraph primitive, and `Field` `description` would mute them and break
  the numbered steps. Prose ≠ chrome, so it's left as prose.

**Settings done.** All six pages native (or, for Help's prose, intentionally
plain body text). The only inline styles left across `Settings.tsx` are status
colours on value spans and monospace on command spans (both allowed).

---

### 10. Workshop (was "Downloads") — full-screen — ✅ built (v0.3.58)

- **Rename:** the QAM entry button and the page are now **"Workshop"**, not
  "Downloads". Games are added from the QAM's Add Game (native Steam download),
  so "Downloads" was misleading — the page's real remaining job is Steam
  **Workshop** items. New `workshop` i18n key; the QAM button uses it. (Internal
  route/file kept as `ROUTE_DOWNLOADS` / `Downloads.tsx` to avoid churn.)
- **Structure:** dropped from a 2-tab `SidebarNavigation` (Manual Download +
  Workshop) to a **single Workshop screen**. The "Manual Download" tab and its
  active-downloads list were removed (redundant with QAM Add Game). Now a plain
  full-screen page (same `marginTop:40px / overflowY:scroll` wrapper as Library)
  — no sidebar for one screen.
- **Native conversion:** the workshop status `<div>` → `Field`; the custom
  `ProgressBar` → `ProgressBarWithInfo` (`sOperationText` = phase label). AppID /
  item-ID `TextField`s and the buttons were already native.
- **Native or custom:** 🟢 native; no inline styles left (the page wrapper div is
  layout, like Library's).

#### 10b. LibraryPickerModal — ❌ removed (dead code)

The "which Steam library to install to" modal (shown from the game-download
flow when `steamLibraries.length > 1`) was **vestigial from the ACCELA era**:
`start_download` passes `target_library_path` to `_download_zip_for_app`, which
**never references it** — the manifest flow always installs to the default
library. So the modal let the user pick a disk that the backend then ignored,
and it only appeared with 2+ libraries (most users, including single-drive
setups, never saw it). Removed `LibraryPickerModal.tsx` and the
`showLibraryPicker` calls in GameDetail/GameList; both `handleDownload`/
`handleAddGame` now call `doStartDownload` directly, and the
`steamLibraries`/`getSteamLibraries` plumbing that only fed the picker is gone
(the Settings ▸ System library list uses its own `getSteamLibraries`, untouched).
If per-disk install is ever wanted, it's a backend feature (make
`_download_zip_for_app` honour `target_library_path`), not a modal.

#### 10c. Dead components removed

- **`components/ProgressBar.tsx`** (the custom bar) — every usage now goes
  through the native `ProgressBarWithInfo` (QAM, GameDetail, Downloads/Workshop,
  Settings), so the component was unreferenced. Deleted.
- **`components/TextInputButton.tsx`** — not imported anywhere (QAM text input is
  a plain `TextField` now). Deleted.
- **`components/AppPageButton.tsx`** — kept: it's injected into Steam's **native**
  library app page (`index.tsx`), not a Decky panel, so its `<div>` "Added via
  LumaDeck" badge is correct (no `PanelSection`/`Field` context there).

---

### Off-pin onboarding → Desktop Quick Install — ✅ built (v0.3.61)

A fresh Deck's Steam is almost always **newer** than headcrab's (lagging) pin, so
`headcrab.compatible` is false and the QAM **Quick Install was hidden from exactly
the people who need it**. Fixed:

- `showQuickInstall` no longer requires `headcrab.compatible` — it shows whenever
  no component is installed. (Quick Install is the action that *makes* you
  compatible; gating it on "already compatible" was backwards.)
- `handleQuickInstall` branches on `compatible`:
  - **at pin** → the existing Game-Mode `quick_install()` (no downgrade).
  - **off pin** → arms a Desktop hand-off (`runDesktopHandoffQuickInstall`).
- The hand-off runs `backend/quick_install_cli.py`, which calls the REAL
  `installer.quick_install(gamemode=False)` under the system Python in Desktop —
  no bash re-implementation, so **no install step is forgotten** (deps + CR
  config-flip/seed + lumalinux, in order). It streams progress to konsole and
  writes `~/lumadeck-quickinstall.json` for debugging; returns to Game Mode on
  success, stays in Desktop on failure.
- **`gamemode` flag through the installers:** `quick_install` / `install_*` /
  `_patch_headcrab_script` now take `gamemode`. The kill / short-session-relaunch
  headcrab patches are tagged Game-Mode-only and **skipped in Desktop** — there
  the Steam kills are normal and REQUIRED so the downgrade can restart Steam. The
  atomic-`.so` robustness patches still apply in both modes.
- ⚠️ Needs on-device validation: the launcher relies on the system `python3`
  importing the backend (Decky doesn't run in Desktop). The diagnostic file makes
  a failure (e.g. a missing import) debuggable.

---

## Component model — system status (errors + updates) — ✅ DONE (steps 1–6)

> Progress: **1** `get_components_status()` ✅ · **2** `apply_component()` ✅ ·
> **3** one fetch + `SystemStatus` renderer (5-action collapse + update track),
> old builders/banners deleted ✅ · **4** Stuck into the renderer ✅ (folded into
> step 3) · **5** Desktop autostart for the downgrade ✅ (v0.3.50 — the "Fix in
> Desktop" row arms a one-shot autostart that runs headcrab + lumalinux
> re-inject in Desktop and auto-returns to Game Mode) · **6** i18n cleanup ✅
> (v0.4.8 — swept 87 unreferenced keys, incl. the now-dead per-component update
> strings, from both `en` and `pt-BR`; verified none appear anywhere in `src/`
> outside `i18n.ts`, so the `|| key` fallback can never surface).

> Supersedes the split **Health banner (§3)** + **Updates banner**. Both collapse
> into one data model and one renderer. This is the authoritative spec; §3/§3b/§3c
> remain valid for the *text* and *cascade* rules, but the rendering and fetching
> described there are replaced by this.

### Why
Today SLSsteam, lumalinux and CloudRedirect each live in four places (health,
update, row builder, action) with the `steam.sh` cascade knowledge copied into
every button. Three components × four concerns = a tangle. They are the **same
kind of thing** — a *managed component* — so we unify them.

### The components
- **Core** = **SLSsteam + lumalinux**. They go together; one without the other is
  a broken state, fixed by reinstalling the pair.
- **Optional** = **CloudRedirect**. Add-on; its absence is not an error.
- **Plugin** = **LumaDeck** itself. Special: its "fix" and its "update" are the
  same manual action (download zip, install via Decky ▸ Developer ▸ Install from
  ZIP).

### Backend (two new pieces, wrapping what exists)

**1. `get_components_status()` — one fetch, uniform shape.** Composes the existing
`read_*_health` + the update checks. Replaces the 8 fetches / 7 React states:
```
{
  components: [ { id, name, installed, health, update:{installed,latest,available} }, ... ],
  headcrab:   { compatible, target, current },   // compat gate ONLY (see below)
  plugin:     { installed, latest, available },
}
```
New real check: `check_slssteam_update` + a CR check, both **via h3adcr-b**
(see Updates). `headcrabCompat` goes back to being *only* the compat gate — the
fake "SLSsteam update derived from `!compatible`" is deleted.

**2. `apply_component(id, op)` — one cascade-safe action.** `op ∈ {install,
repair, update}`. Does the op, then **always** runs `reinject_installed()` (which
already re-injects every *installed* component in order SLSsteam → CloudRedirect →
lumalinux). The UI never knows the `steam.sh` ordering. `reinject_installed`
already exists and already gates on `check_*_installed()`.

### Compatibility contract (how updates stay safe)
The whole set is anchored to **h3adcr-b's pinned Steam build**
(`HeadcrabCompatibleClientVer`). Deadboy666 curates the bundle (Steam pin +
SLSsteam `latest` + CloudRedirect `linux-test` `.so`) to be mutually compatible
at the **weakest-link** Steam build, so headcrab never lands you on a Steam that
breaks SLSsteam or CR. **lumalinux is outside headcrab** and self-validates via
its `steamclient.so` hash check (`hash_blocked`). Three safety layers:
1. Updates are **gated on `headcrab.compatible === true`** (Steam at the pin).
2. lumalinux's hash check refuses silently-incompatible builds (`hash_blocked`).
3. After `apply_component`, re-fetch status to confirm all healthy.

---

### ERRORS → the user can only ever do 5 things

| # | User action | Backend states it covers | Where |
|---|---|---|---|
| 1 | **Restart Steam** | `not_active` (any component) | Game Mode |
| 2 | **Repair component** (install + restart) | `injection_missing` (SLS/luma), `hooks_failed` (luma), `broken`→reinstall (CR, Steam OK), core half-installed | Game Mode |
| 3 | **Downgrade Steam** | "Steam too new": `broken`/`hash_blocked` (cross-ref headcrab) | Desktop |
| 4 | **Configure cloud provider** | CR `not_authed` | Desktop |
| 5 | **Install LumaDeck manually** | plugin needs the zip | manual |

Silent: `healthy`, CR `kill_switched` (`~/.config/CloudRedirect/disable`, a
deliberate opt-out the plugin only *detects*, never creates), CR `not_installed`.

**Collapse / cross-reference rules (why the user sees little):**
- **"Steam too new" is ONE row** even when 3 components report it
  (`broken`/`broken`/`hash_blocked`). Cross-ref `headcrab.compatible` to confirm
  it's a downgrade and not a plain reinstall.
- **Same cause across components = one row** (two `not_active` → one "Restart").
- **Core (SLS+luma) is evaluated as one unit**; CR separate, only if installed.
- **Priority:** action 3 (downgrade) **supersedes** 1 and 2 (nothing works until
  Steam is right). Show the single highest-priority row; the next surfaces once
  it's resolved.
- **lumalinux `hash_blocked` is conditional:** it joins the downgrade group ONLY
  if SLS/CR also report "Steam too new" (then the headcrab pin is in lumalinux's
  hash set and it recovers too). If lumalinux is blocked **alone**, headcrab
  can't help (it doesn't know about lumalinux) → it's a **lumalinux update**
  problem, not a downgrade.

**Two Desktop actions (3 and 4) — why they can't run in Game Mode:**
- **Downgrade (3):** the Steam roll-back is a multi-restart op; even with our
  Game-Mode-safe headcrab patches the failure mode is a wiped Steam, so it stays
  Desktop. Delivered via a **one-shot autostart** in `~/.config/autostart/`: from
  Game Mode we write the script + `.desktop`, switch to Desktop, it runs on login
  (in a visible Konsole), then self-removes. The "order" persists on disk.
- **CR login (4):** the provider sign-in is a GUI flow inside the CloudRedirect
  Flatpak; Game Mode can't drive arbitrary Flatpak windows. Genuinely
  Desktop-only unless CR adds a headless/token login.

---

### UPDATES → a separate track (not folded into "repair")

Mechanically an update is "(re)install + restart" like a repair, but for the user
it's **optional/info**, not a problem — so it renders as a distinct (blue) track,
not as a ⚠ fix.

| Component | Update check | Apply | Weight |
|---|---|---|---|
| **lumalinux** | latest release of its repo vs installed | `install_lumalinux` + reinject | light |
| **SLSsteam** | hash of the `latest` asset (**via h3adcr-b**) vs installed `.so` | re-run headcrab + reinject | heavy |
| **CloudRedirect** | hash/ETag of `linux-test/cloud_redirect.so` (**via h3adcr-b**) vs installed `.so` | re-run headcrab + reinject | heavy |
| **LumaDeck** | latest plugin release | download zip → message "Decky ▸ Developer ▸ Install from ZIP, then restart Steam" | manual |

Rules:
- **CR has no semver of its own** — its "version" *is* which `linux-test` `.so`
  you have, so the check is a **hash/ETag compare against the exact asset headcrab
  installs** (the current `checkCloudredirectUpdate` semver check is wrong and is
  removed).
- **All updates gated on `headcrab.compatible`**; the set updates **together**
  (one reinject at the end); re-check health after.
- SLSsteam/CR "update" = re-running the headcrab install, which is **safe in Game
  Mode when Steam is already at the pin** (no downgrade happens).

---

### Two tracks the user sees
- **"Something's wrong" (⚠):** at most one of the 5 fixes, by priority.
- **"Something's new" (info):** the update track.

Normally the user sees **nothing, or one row**. The full per-component breakdown
(versions, individual install/repair/update) lives in **Settings ▸ Dependencies**
for the advanced 1%.

### What gets deleted
- The 3 near-identical health row builders (`slssProblem`/`llProblem`/`crProblem`)
  → one generic mapper.
- `UpdatesBanner` (absorbed into the single renderer).
- The fake "SLSsteam update" derived from `!headcrabCompat.compatible`.
- The misleading `checkCloudredirectUpdate` semver check → hash compare.
- Per-button cascade wiring → owned by `apply_component`.

### Implementation order (incremental, each step builds + ships)
1. Backend `get_components_status()` wrapping existing health/update fns + real
   `check_slssteam_update` + CR hash check. (Adds only; nothing visible changes.)
2. Backend `apply_component()` over `reinject_installed`.
3. Frontend: one fetch, one renderer (the 5-fix collapse + update track); delete
   the 3 builders + `UpdatesBanner`.
4. Move **Stuck** (per-game `UpdateResult=8`) into the same problem renderer,
   action "Open game".
5. The Desktop autostart for the downgrade (action 3).
6. i18n cleanup + normalized strings.

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
  the tokens above rather than inventing new colours/sizes. **But "on-token" is
  not "native":** a styled `<div>` is still 🔴 custom. Before accepting one, ask
  whether the text is really a *label* — counts, captions and section headers
  belong in a native control slot (`PanelSection title`, `Field` label, button
  `description`). Only genuinely free-floating status text (`searchError`,
  `addStatus`, install progress) has no native home and stays a `<div>`.
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
- **Warning colour is one value:** ⚠ icons use orange **`#ff8c00`** across the
  QAM (blocked row, game notices). Keep it inline on the icon and **inline
  inside the description** (`display:inline-flex`) — a `Field` `icon` prop floats
  the glyph onto its own line when the row has only a description.
- **Focus glow off on grouped actions:** `highlightOnFocus={false}` drops the
  dark focus *halo* that wraps a `ButtonItem`'s whole row band, leaving only the
  native white fill. Use it where a button is grouped with the row above/below
  (Add game, Search) so focus doesn't paint a box around the group. `DialogButton`
  already shows only the white fill (no halo).
- **One closing line per section, and never doubled:** end a section with a
  single native separator. If the last real row already draws its own bottom
  line (a results list of `ButtonItem`s), do **not** add a closing `Field` too —
  that doubles the line; make the closing divider conditional. `padding="none"`
  keeps it thin with no extra vertical gap.
- **Divider-separated groups share one `PanelSection`.** A second `PanelSection`
  adds another block of section padding that reads as a large empty gap. Put the
  groups' rows in the same section; the divider gives the single-row break.
- **Say *why* an action is blocked once**, at the top of the section, pointing at
  where it's fixed — not repeated next to the disabled control. The disabled
  control + the top reason are the whole message.
- **Don't wrap free-floating status in a `Field` to "space" it:** a `Field`
  changes the horizontal inset and the text jumps out of alignment. Keep status
  a plain `<div>` in a `PanelSectionRow` (inherits the content inset); put any
  needed breathing room on the neighbouring divider, not the text.

