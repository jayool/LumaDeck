# LumaDeck — UI Design

Single source of truth for the plugin's UI. **Rebuilt from scratch**, verified
element by element against the live code. Nothing here is assumed — every entry
is checked in the source before it is written down.

> **Status: re-checked against the code on 2026-10-09.** Every per-element entry
> (QAM, Library, GameDetail, Settings, Component model) was compared with `src/`
> and updated to what the code does now. Removed elements keep their heading
> marked ❌ removed; elements hidden behind a flag in `src/features.ts` are marked
> hidden. The Principles are unchanged; code that breaks them is listed under
> [Drift in code](#drift-in-code-to-fix-in-code-not-in-the-rules).

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
  name:    "LumaDeck",
  titleView: (
    <Focusable style={{ display: "flex", alignItems: "center", gap: "6px", width: "100%" }}>
      <div className={staticClasses.Title} style={{ flex: 1 }}>LumaDeck</div>
      {/* Refresh + Settings icons, see §1 */}
    </Focusable>
  ),
  content: <GameList />,
  icon:    <FaDownload />,
  ```
  There is no `title` key any more: the brand is the first child of `titleView`.
  `flex:1` is layout only (it pushes the icons right); the title's mask and
  drop shadow stay native. See §1 for the icons on the right.
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
    `GameList` registers `refreshStatus(true)` via `setRefreshHandler` (a
    forced status re-check that skips the 6 h update caches; the QAM has no
    library to reload); the icon calls `requestRefresh()`.
  - **Refresh spin:** the same bridge carries a `refreshing` flag
    (`setRefreshing` / `subscribeRefreshing`). `GameList.refreshStatus` sets it
    around every status refresh, including the first load when the QAM opens,
    and `RefreshButton` (`index.tsx`) spins its `FaSync` while it is set, via
    `element.animate()` on a wrapper `<span>` (an injected CSS `@keyframes` did
    not apply in the QAM document).
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

### 1b. Downloads entry — ❌ removed

- **Replaced by:** nothing. The Downloads/Workshop page and its QAM `ButtonItem`
  are gone (no `ROUTE_DOWNLOADS`, see §10); the bottom of the QAM is now My Games
  (§5), plus Achievements when `ACHIEVEMENTS_ENABLED` (§6).
- **Rule (kept):** secondary navigation that doesn't fit the 1–2 title-bar icons
  lives as a labelled `ButtonItem` at the bottom of the panel (today: My Games).

### 2. Quick Install (onboarding) — *conditional* — ✅ verified

- **What:** the first-run setup entry. Renders when every component in
  `get_components_status` is `!installed` — i.e. a fresh, unconfigured install.
  A dev preview override (`quickInstall: "show" | "hide"`, set from
  Settings ▸ Dev, §9g, via `backend/dev.py`) wins over the real check. (Since
  v0.3.61 it **no longer** also requires `headcrab.compatible`; Quick Install is
  the action that *makes* you compatible, so gating it on compatibility was
  backwards — see "Off-pin onboarding" below.) It self-hides the moment any
  component is installed (repair/reinstall then lives in Settings).
- **How shown:** a `PanelSection` with **no title** and one
  `ButtonItem layout="below"` that mirrors the SystemStatus row model:
  `label` = the section title (bold, uppercase span, `quickInstallSectionTitle`
  "Welcome"), `description` = `quickInstallIntro`, children = the action
  (`⚡ Quick Install` → first press **"Confirm (restarts Steam)"** at the pin or
  **"Confirm (continues in Desktop)"** off-pin, auto-reverting after 5 s →
  `Setting up...` while running). The focus band wraps title, blurb and action
  as one unit (a `PanelSection` title would sit outside the focus). While
  installing, a step progress `<div>` follows.
- **Native or custom:** 🟢 native skeleton. The only raw `<div>` is the progress
  line (🔴, but unavoidable — Decky has no text primitive), on the tokens:
  `11px #1a9fff`.
- **Rule:**
  - Onboarding only relevant on a fresh install is **gated on health state**
    and self-hides once configured.
  - Install / destructive actions use the **two-click confirm**: a
    `confirm<Action>` state arms the button, second press executes. Here the
    first press relabels the button with what will happen (see the Component
    model "Confirm rule"); no `description` prompt is used.
  - Body text is a plain `<div>` in a `PanelSectionRow` using the text tokens.
    **Step-based** progress is a text line; a `ProgressBar` is only for a real
    percentage.

### 3. Health alerts (`SystemStatus`) — *conditional* — ✅ built (v0.3.33)

- **What:** surfaces what is wrong with the stack (SLSsteam, lumalinux,
  CloudRedirect) and what is new. Only *actionable* states appear —
  `healthy` / `not_installed` / CR `disabled` are silent (install lives in
  Quick Install / Settings).
- **How shown:** `SystemStatus` (`src/components/SystemStatus.tsx`), one
  `PanelSection` of native rows from `buildRows()`:
  - A row **with an action** is a `ButtonItem layout="below"`: `icon` = coloured
    glyph, `label` = the problem, `description` = the explanation, children =
    the action. Native focus; the whole row is the button.
  - A row **without one** is a `Field` (`icon` + `label` + `description`). Only
    info states with no Game-Mode action use it (Adding games unavailable,
    CloudRedirect sign-in). Display-only — **no dead button**.
  - A Steam-unsupported state is **not** a `Field`: it is an actionable
    `ButtonItem` **"Fix in Desktop"** (the Desktop hand-off *is* the action
    from Game Mode).
  - **At most one system-problem row**, picked by priority (see Component
    model), then CloudRedirect sign-in, stuck games (one row each), and the
    update track. The rows are stack-wide, not one per component (§3c).
  - **Severity = the icon colour**, not a box: problems use ⚠
    `FaExclamationTriangle #ff8c00`; info uses `FaArrowCircleUp #5b9eff`.
  - The old orange `HealthBanner` box (title, body, hand-rolled `<button>`) is
    deleted.
- **Native or custom:** 🟢 native (`ButtonItem` / `Field`). No custom box and
  no raw `<button>`.
- **Rule:** **never render a button for something you can't do from here.** An
  unactionable alert is a `Field` (info + instructions), not a fake button. The
  exact actionable/not split per state is the table below.

### 3b. Repair architecture — one idempotent `setup.sh` run — ✅

There is **no shared `steam.sh` cascade** anymore. `steam.sh` is left **vanilla**;
injection comes from a launch **wrapper** (`~/.local/share/SLSsteam/path/steam`)
that lumalinux's `setup.sh` interposes, reached by patched `.desktop` (Desktop), a
PATH drop-in (terminals) and a systemd drop-in on `steam-launcher.service` (Game
Mode).

Because **one** `setup.sh` run installs and re-establishes the *whole* stack
(SLSsteam + CloudRedirect + netsock + lumalinux + .NET) and rewrites the wrapper +
coverage, there is no per-component ordering to get right and no "repairing one
component wipes another's block" hazard. Every install/repair path collapses to
that single run:

- `install_via_setup()` — the core install/repair, running
  `jayool/lumalinux/main/setup.sh`.
- `reinject_installed()` and `apply_component(id)` — both re-run `setup.sh`; a
  per-component id just maps onto the same idempotent run. setup.sh reconciles the
  full stack, so it re-establishes coverage for everything present without a
  hand-ordered sequence.

**Rule:** a `not_injected` / "coverage lost" repair re-runs `setup.sh` (rewrites
the wrapper and re-affirms `.desktop`/Game-Mode coverage), then restarts Steam. A
`not_loaded` fix is a plain **Restart Steam** — coverage is fine, the stack just
isn't live this session. **Finish setup** (core half-installed) runs
`apply_component("core","install")` then restarts Steam — the same single
`setup.sh` run. The break-recovery **Steam downgrade** (`downgrade.sh`,
Desktop-only) is a separate escape-hatch — see §3c. (The other actions in the
map, `retry` for the crash guard and `alignUp` for moving Steam up to a newer
pin, are covered in the Component model.)

> Startup self-heal (v0.7.2): on every plugin load `paths.heal_gamemode_dropin()`
> re-writes the Game Mode `steam-launcher.service` drop-in if it went missing/inert
> and `daemon-reload`s it (via `runuser`), so a Deck whose Game Mode coverage was
> lost recovers on the next Steam restart without a manual repair.

### 3c. Health text spec (normalized, beginner-friendly) — ✅ final

The backend reports one canonical state per component (`not_installed` /
`not_loaded` / `not_injected` / `not_supported` / `not_authed` / `disabled` /
`healthy`; `not_authed` and `disabled` are CloudRedirect-only), with the detail kept in a
separate `cause` field for logs/diagnostics. The **UI collapses** all components
into **one stack-wide row**: the user is told *what to do*, not *which
component* failed (the per-component breakdown lives in Settings ▸ Components,
§9c).

**Why `not_supported` is one state + one fix:** every "Steam too new" cause
(SLSsteam patterns/hash, lumalinux hooks, CloudRedirect init failure) means the
same thing to the user — *Steam updated past what the stack supports*. The fix
is the same: **run the Steam downgrade in Desktop** ("Fix in Desktop", a
hand-off `ButtonItem`, not a `Field`),
which downgrades Steam via `downgrade.sh` (Desktop-only) to the **headcrab-pinned
stable build** the stack supports. The target build is fetched **dynamically**
(`HeadcrabCompatibleClientVer`, read by `headcrab_compat.py`), not a fixed
constant. It's an *older stable* build supported by all three components
(CloudRedirect lists supported builds explicitly in `SUPPORTED_STEAM_VERSIONS`;
lumalinux shares `steamclient.so` hashes with SLSsteam for that era), so even a
slightly lagging component still supports it.

**Render:** each row is `icon` + `label` = the problem in plain words +
`description` = the text below + the control. No component name and no impact
suffix: the row is stack-wide.

**State → row** (`buildRows()` in `SystemStatus.tsx`; strings in `i18n.ts`):

| State (backend) | label | description | control |
|---|---|---|---|
| any installed component `not_supported` | "Steam build not supported" | "A Steam update broke LumaDeck. Press Fix in Desktop to repair it." | 🔘 **Fix in Desktop** (confirm "continues in Desktop") |
| only lumalinux `not_supported` and `headcrab.lumalinux_ready === false` | "Adding games unavailable" (info ↑) | "This Steam build doesn't support adding games through LumaDeck. Wait for an update." | 📄 Field |
| core half-installed (SLSsteam xor lumalinux) | "Setup incomplete" | "LumaDeck isn't fully set up. Press to finish." | 🔘 **Finish setup** |
| `guard.active` (crash guard latched) | "Recovery mode" | "Steam crashed at startup. Running without injection." | 🔘 **Re-enable injection** |
| any `not_injected` or `not_loaded` | "Restart needed" | "LumaDeck needs a restart to work." | 🔘 **Restart Steam** |
| CR `not_authed` | "Cloud saves need sign-in" (info ↑) | "Open the CloudRedirect app in Desktop Mode to sign in." | 📄 Field |

**Wiring notes:**
- **Restart Steam** → `restart_steam` (clean `steam -shutdown`, GM auto-restarts).
  When the cause is `not_injected` the same button runs `reinjectInstalled`
  first (re-runs `setup.sh`, the wrapper-model installer, then restarts), and
  its busy label is "Working..." instead of "Restarting Steam...". No
  per-component ordering, and `steam.sh` is left vanilla.
- **Fix in Desktop** → the Desktop hand-off (`runDesktopHandoffReal`, see
  Component model action 3).
- **Field** rows exist only for info states with no Game-Mode action; the
  instruction is in the `description`. CR sign-in is Desktop-only and is hidden
  while anything is `not_supported`.
- Text drops jargon (`steam.sh`, hooks, patterns, hash, SafeMode) and the
  component/hook names (kept in logs and in `cause` only).

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
- **Switching mode** (`changeMode`) also clears `addStatus` and `searchError`, so
  a stale "Invalid AppID" or search error doesn't linger across modes.
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
  ⚠ `#ff8c00` icon, so they read as part of the card. Metacritic colours:
  `#7ed36f` ≥ 75 / `#c8a84b` ≥ 50 / `#e06060` below; ProtonDB tiers use a medal
  map (`PROTONDB_TIER_COLOR` in `GameList.tsx`). The achievements hint (11px
  gold `#c8a84b` ⚡ line below the card) only renders when
  `ACHIEVEMENTS_ENABLED` is on (currently off).
- **Owned game:** if Steam already owns the game (`isOwnedBySteam`,
  `src/steamOwnership.ts`), a green `#7ed36f` line *"Owned game: Only its DLC
  will be added."* rides in the same description, above the notices. It is a
  hint from Steam's own library model; the backend decides for itself.
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
  knocks it out of horizontal alignment). `textAlign:"left"`, `12px`, three-way
  colour: red `#ff6b6b` on error (`error*` / `invalidAppId` / `downloadFailed`),
  green `#00cc00` on `doneRestartSteam`, grey `#8b929a` otherwise — including
  `downloadCancelled` and the owned-game result `ownedDlcNextStart` ("DLC added.
  They install the next time Steam starts.", shown when the owned game was
  already installed). `ownedDlcNextStart` is a success message rendered grey
  because the green test matches `doneRestartSteam` only — a code
  inconsistency, see [Drift in code](#drift-in-code-to-fix-in-code-not-in-the-rules).
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
  The count label is `12px #8b929a`. The search is the Steam store search and
  needs no credential.
- **Native or custom:** 🟢 native field / buttons / count `Field`. `searchError`
  stays a raw aligned `<div>` (`12px #ff6b6b`; the text-primitive exception, 🔴).

**Add Game is box-free:** native tab toggle, label-less fields, one shared
`Field` game card (notices inline), a single top blocked row, native progress,
a native-`Field` results count, and one conditional closing divider — no boxes,
no doubled lines.

### 5. My Games — QAM entry — ✅ built

- **What:** the entry point to the full-screen library. My Games **lives on its
  own route** (`ROUTE_LIBRARY`, `Library.tsx`) — the QAM only shows a compact
  launcher entry, not the list.
- **How shown:** a single plain native `ButtonItem` → `Navigation.Navigate(
  ROUTE_LIBRARY)`. Same shape the removed Downloads entry had (§1b).
- **Bottom nav lives in the Add Game `PanelSection`, not its own:** My Games
  (and, when `ACHIEVEMENTS_ENABLED`, Achievements, §6) are rows in the **same**
  `PanelSection` as Add Game.
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

### 6. Achievements — QAM entry → Settings tab — hidden (`ACHIEVEMENTS_ENABLED=false`)

- **What it is:** LumaDeck's own achievement generation (the "Steam Web API
  achievement feature": an API key, per-game **Generate**, **Sync All**). It is
  kept in code, but every entry point (QAM row, Settings tab, GameDetail page,
  the library marker and the Add Game hint) is hidden by
  `ACHIEVEMENTS_ENABLED = false` in `src/features.ts`, because SLSsteam handles
  achievements natively. No dedicated page or route exists any more (no
  `Achievements.tsx`, no `ROUTE_ACHIEVEMENTS`); it is no longer SLScheevo.
- **When the flag is on:**
  - **QAM row:** one plain `ButtonItem` (`t("achievements")`) under My Games in
    the Add Game `PanelSection` (§5). It *only* navigates:
    `setPendingSettingsTab(SETTINGS_TAB_ACHIEVEMENTS)` +
    `Navigation.Navigate(ROUTE_SETTINGS)`. No achievement logic in the QAM.
    (The deep-link does not land on the tab today: `takePendingSettingsTab()`
    is never called, see Drift in code.)
  - **Settings ▸ Achievements tab** (global setup): an intro `<div>`
    (`12px`, opacity 0.8), the API-key status `Field` (value `#00cc00` set /
    `#ffaa00` not set), a key-help `<div>` with a monospace URL, the key
    `TextField` + Save + Get key, a ready `Field`, **Sync All** (`ButtonItem`,
    `disabled` while running, native **`ProgressBarWithInfo`** below it,
    `nProgress` = `done/total·100`, `sOperationText` = `"3 / 12"`), a restart
    hint (⚠ `#c8a84b`) and a two-tap **Restart Steam** ("Confirm (restarts
    Steam)").
  - **GameDetail ▸ Achievements page** (per game): see §8d.
- **Native or custom:** 🟢 native controls — `ButtonItem` + native progress
  bar + native toast; the intro/help text is `<div>`s (off-token opacity, see
  Drift in code).
- **Rule (kept):** global one-time setup does not belong on a per-item page. When an
  action is library-wide (install a shared binary, a bulk sync), give it its own
  entry; the per-item page keeps only what is per-item.
- **Follow-up (carried from §5) — ✅ done (v0.3.75):** moving Sync All off the
  QAM removed the last consumer of the panel's `games` list. `loadGames`,
  `games`, `loading`, and the `getInstalledLuaScripts`/`checkAllAchievementsStatus`
  calls are gone from `GameList`, so the QAM panel no longer loads the whole
  library on mount — it only fetches system status. The lazy-load win §5 wanted
  is now realised. The full games list is loaded only by the Library page,
  which owns its own `loadGames` (it calls `checkAllAchievementsStatus` only
  when `ACHIEVEMENTS_ENABLED`).

---

## Full-screen pages — top to bottom

The QAM is a launcher; space-hungry views live on their own routes
(`routerHook.addRoute` in `index.tsx`): **Library** (My Games), **GameDetail**,
**Settings**. (`Help` and Achievements are Settings tabs — see §7 and §6; the
Downloads/Workshop page is gone — see §10.)

### 7. Library (My Games) — full-screen — ✅ built

- **What:** the full games list, reached from the QAM's My Games button
  (`ROUTE_LIBRARY`). Builds its own list from `getInstalledLuaScripts` (so every
  tile is a lua-managed game), plus `checkAllAchievementsStatus` only when
  `ACHIEVEMENTS_ENABLED`. No polling: there is no live phase on this page.
- **Container — was `SidebarNavigation` with ONE page → now a plain page.** A
  single-page sidebar renders a left rail with one item next to the content —
  pure overhead. Library is now a plain scrollable page
  (`<div style={{marginTop:72px, height:'calc(100% - 72px)', overflowY:'scroll'}}>`)
  holding a `PanelSection` titled My Games with the filter `TextField` (it keeps
  its `filterGames` label), then the cover grid. This also removes the
  **doubled "My Games"** (the sidebar page title *and* the `PanelSection` title
  were the same string) — only the section title remains.
- **Sort control removed.** A `ButtonItem` that **cycled** A-Z → AppID → Recent
  on each tap was low-discoverability custom interaction. For a personal list,
  type-to-filter (the `TextField`) + a fixed A-Z sort is enough. Dropped the
  button, `sortMode` state and the `sort` i18n key.
- **`GameCard` — Steam-style cover tile** (`src/components/GameCard.tsx`):
  - Each game is a portrait capsule (`library_600x900.jpg` from Steam's CDN,
    `header.jpg` fallback, then a plain name tile on `#1a2129`) with the name
    below (`14px #dcdedf`, one line, ellipsis). The tile is a `Focusable`; all
    tiles sit in **one** `Focusable` CSS grid
    (`repeat(auto-fill, minmax(120px, 1fr))`, gap 16px), so Steam's spatial
    gamepad nav moves across tiles by their on-screen position. The small
    120px minimum keeps ~5–6 covers per row on the Deck, like the native
    library.
  - **Two states only:** **Installed** (lua + game files + not disabled → full
    colour) and **not installed yet / disabled** (dimmed, slightly grayscale,
    `FaCloudDownloadAlt` badge top-right — the native "not installed" look).
    The manifest-fetch phase is not shown (the real download is Steam's, shown
    in Steam's own library). No coloured status text and no ★ achievements
    marker in the tile (`hasAchievements` is loaded behind the flag but not
    rendered).
  - Replaces the earlier `ButtonItem` card with a coloured `description`
    (green/amber/blue phase text), whose custom `ProgressBar` branch was dead
    code (`downloadProgress`/`downloadTotal` were never assigned — Steam does
    the download natively).
- **Loading / empty:** centred `#8b929a` `<div>`s (`loadingGames`,
  `noGamesMatch` / `noGamesYet`), no font size set.
- **`Help` relocated.** `Help.tsx` was a fully-built page wired to **nothing**
  (no route, no import). Its content is general plugin help, so it now lives as
  a **page in the Settings sidebar** (`HelpContent`, no back button — the sidebar
  owns navigation). `Help.tsx` exports `HelpContent`; `Settings.tsx` adds a
  `FaQuestionCircle` "Help" page after About.
- **Native or custom:** 🟢 native page shell (`PanelSection` + `TextField`);
  🔴 custom tile (`Focusable` + `<img>`), justified: Decky has no cover-grid
  primitive and the tile mirrors Steam's own library. Other `<div>`s are the
  loading/empty status lines (free-floating text, on-token) and the page's
  scroll wrapper (structural, not decorative).
- **Rule:** a single-list route is a **plain scrollable page**, not a 1-page
  `SidebarNavigation`. Don't ship cycle-through controls where a filter or a
  `Dropdown` fits. Never render UI for data that no longer exists (the native
  Steam download killed per-game byte progress — delete it, don't leave it
  guarded-but-dead). A built page wired to nothing is either routed or deleted —
  Help was rehomed.

### 8. GameDetail — full-screen `SidebarNavigation` (5 pages, 6 with achievements) — ✅ built (8a–8f done)

The per-game page (`ROUTE_GAME_DETAIL/:appid`), a `SidebarNavigation` titled
with the game name; every page is `hideTitle: true`. **`SidebarNavigation` is
justified here** — it has genuine sections: **Status** (`FaInfoCircle`),
**Updates** (`FaDownload`), **Fixes & Repairs** (`FaTools`), **Online Fixes**
(`FaUsers`), **Danger Zone** (`FaTrash`, tab label "Uninstall") — plus
**Achievements** (`FaTrophy`) when `ACHIEVEMENTS_ENABLED` (off). There is no
Game Management page and no separate Download page any more. Reviewed page by
page.

**`ActionButton` is fine (not custom chrome).** Used across the page, it's a
native `ButtonItem layout="below"` in its own `PanelSectionRow`; only
`variant="danger"` tints the label red `#ff4444` — everything else keeps the
native white label (Steam marks the main action with focus, not coloured text).
There is no `primary` blue variant any more. Kept as-is.

**Decided in advance (boxes, when we reach their pages):**
- *Uninstall* red box → **native**: the destructive list becomes a `Field`
  (label + `·` list in the description); severity is already carried by the red
  `danger` button, the two-click confirm, and the page literally titled
  "Uninstall". No hand-bordered box.
- *SLScheevo path* code box → **simplify**: you can't copy it (Game Mode has no
  clipboard to Konsole), so it's reference text, not a copy affordance. Keep a
  legible monospace line, drop the dark bordered "code block" framing. (The
  SLScheevo flow itself is gone since — see §8d.)

#### 8a. Status page — ✅ built

- **What:** read-only summary — AppID, install status (+ size), install path.
- **Was:** three raw `<div>`s (`AppID: …`, `Status: …` coloured, the path).
- **Now:** one `PanelSection` with **no title** (the sidebar title already names
  the game), holding native `Field` rows —
  - **One** `Field`: `label` = `AppID <n>` (AppID is a technical literal used
    across the codebase, not display prose, so no `t()` — consistent with
    search results), the coloured install status as the value child (green
    `#00cc00` Installed / amber `#ffaa00` Manifest only; for an owned game the
    text is `ownedDlcOnly` "DLC added (owned game)", same colours; `+ size`),
    and the **install path as the Field's `description`** sub-line (one Field
    does all three; no separate path `<div>`).
  - **Owned, not added:** when `!hasLua` and Steam owns the game, a `Field`
    "Owned game" / "Only its DLC will be added."
  - **Version** `Field` (installed, non-owned game only): value `Build N ·
    Latest` or `Build N · Frozen` (plain, uncoloured span), `description` =
    pin date · studio label when LumaDeck pinned it; or "Frozen on the
    installed version" when the pin carries no build number.
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

#### 8b. Updates page (was "Download") — ✅ built (v0.3.52)

- **What:** version/manifest management (`t("updates")`): re-fetch or cancel
  the manifest download, auto-update toggle, version picker, the stuck-update
  fix, and the in-flight status + result/warning messages. The game files
  themselves download natively in Steam. No section title (the tab names it).
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
  - **Dead credential rows:** one actionable ⚠ `#ff8c00` `ButtonItem` per
    rejected credential — **Hubcap API key expired** and **Ryuu session
    expired** — each `onClick` → Settings (where the key / login lives). Both
    show when both were rejected. (The QAM `credWarnings` row this once copied
    is gone, §4c.)
  - **Version picker (Change version):** an `ActionButton` "Change version"
    reads the game's public builds (SteamDB through Steam's own browser,
    `backend/game_versions.py`; label "Reading SteamDB…" while loading, the error
    as its `description`) and turns into a native `DropdownItem` (`label` =
    Version, options = builds, `description` = the selected build's studio
    label · LuaTools fix tags for that build) + **Install build N**
    (`ActionButton`, disabled on the build already installed). Installing pins
    + freezes the game; the user restarts Steam (toast), never us. If SteamDB
    needs a human check: ⚠ `#ff8c00` `Field` ("SteamDB asks for a browser
    check") + **Open SteamDB** + **Change version** (retry).
  - **Owned games** hide the auto-update toggle, the version picker and the
    stuck-update row (`!isOwned`).
  - **done / failed → native `Field`** (green `#00cc00` child for "complete";
    ⚠ red `#ff4444` icon + error in `description` for failed).
- **Native or custom:** 🟢 native; only inline style left is the status **colour**
  on the "complete" `<span>` child (allowed control-slot colour).
- **Rule:** in-progress work is a native `ProgressBarWithInfo` (text in
  `sOperationText`, never a sibling `<div>`); a warning that has a fix is an
  actionable `ButtonItem` with a `FaExclamationTriangle` icon, not a
  hand-bordered box. Reuse the established native warning shape; don't re-skin it.

#### 8c. Game Management page — ❌ removed

- **Replaced by:** Goldberg moved to Fixes & Repairs ▸ Fixes (§8e); FakeAppId is
  set only indirectly, by the Online toggle (480, §8e-bis). There are no
  FakeAppId / token / DLC controls in GameDetail any more.
- **Rule (kept):** don't wrap a native control in layout `<div>`s "just in case"; a
  control is a direct row child. Don't hide routine per-game controls behind an
  extra toggle. A `description` must add information — never echo a section
  title.

#### 8d. Achievements page — hidden (`ACHIEVEMENTS_ENABLED=false`)

- **What (when the flag is on):** a 4-state machine (not_configured /
  generating / generated / ready) for per-game achievement generation, in a
  `PanelSection` titled Achievements. Global setup (the Steam Web API key) lives
  on Settings ▸ Achievements (§6); there is no not_installed state, no
  SLScheevo binary path / monospace line and no "Configure in Desktop" hand-off
  any more.
- **How shown:** every state is a native `Field`; colour is carried by
  **icons**:
  - **not_configured** → ⚠ `FaExclamationTriangle #ffaa00` `Field` ("Set up
    achievements first") + an `ActionButton` "Set up achievements" that
    deep-links Settings ▸ Achievements (`setPendingSettingsTab` +
    `Navigate(ROUTE_SETTINGS)`).
  - **generating** → plain `Field` with the progress text.
  - **generated** → ✓ `FaCheckCircle #00cc00` `Field` + **Generate**.
  - **ready** → plain `Field` + **Generate**.
- **Native or custom:** 🟢 native `Field`s + icons; no inline styles.
- **Rule (kept):** a Desktop-only interactive setup (like CR sign-in)
  gets a hand-off button with an **interactive, no-auto-return** payload — the
  user drives the console and returns manually. Don't fake a round-trip around an
  interactive flow.

#### 8e. Fixes & Repairs page (was "Fixes") — ✅ built (v0.3.55)

- **What:** the non-online LuaTools catalogue (crack / Denuvo fixes), the fixes
  installed from it, the game cracks (Steamless, Goldberg) and the
  install/account repairs. Four `PanelSection`s, each with its own title:
  - **LuaTools Fixes** (`renderCatalogueSection`): **Check for Fixes**
    `ActionButton`, whose `description` carries "no fixes" (`noOtherFixes`, or
    "Couldn't load fixes" on error) or "install the game (correct build) first".
    - **LuaTools login gate:** when there are entries but LuaTools is not
      connected, an inline-⚠ `#ff8c00` `Field` (`luatoolsLoginGate` "Log in
      with Discord to install versions and apply fixes", or
      `luatoolsExpiredGate` when the session expired) + a **Log in with
      Discord** `ActionButton` (`src/hooks/useLuatoolsConnect.ts`). Said once,
      at the top; the entries' buttons are just disabled (the "say *why* once"
      principle).
    - **Each entry:** a `Field` (`label` = fix name, `description` = its tags
      joined with ` · `), an optional **Install the game version this fix
      needs** (`description` = the build note), and **Apply fix** (becomes
      **Replace fix**, §8e-ter).
    - **While applying:** a `Field` "Applying fix…" with the step (Queued →
      Downloading → Extracting) as `description` — no bar, no Cancel (the
      apply is quick, and cancelling mid-extract would leave a half-applied
      fix).
  - **Installed LuaTools Fixes** (`renderInstalledFixes`, only when there are
    some): one `Field` per fix (`label` = "type · N files", `description` =
    applied date) and a **Remove fix** danger `ActionButton` per fix
    (`Remove fix · type` when there are several).
  - **Fixes:** Steamless (download, then **Remove Steam DRM**, §8e-quater) and
    Goldberg (apply / remove, moved here from the removed Game Management
    page).
  - **Repairs:** Linux-native fix, Reconfigure SLSsteam, Repair ACF.
- **Was:** a gray `<div>` "No fixes available", the custom `ProgressBar` while a
  fix applied, and the Installed-Fixes rows as nested raw `<div>`s.
- **Native or custom:** 🟢 fully native; no inline styles except the inline ⚠
  on the gate row.

#### 8e-quater. Steamless — one row per exe — ✅ built

- **What:** after a Remove Steam DRM run, under the button (which keeps its
  "Done: N/M executables unpacked" line), one native `Field` per processed exe:
  `label` = the exe name, `description` = its outcome — "DRM removed", "No
  Steam DRM", "Unpack failed", "Unpacked, could not replace the exe", "Timed
  out", "Error". Skipped exes (launchers, tiny files) do not appear, as before.
- **Why:** the count alone hid "SteamStub recognised but unpack failed" behind
  "no DRM" (Steamless.CLI exits 1 for both). Backend: FIXES_MAP.md, Steamless
  outcomes.

#### 8e-ter. One fix per game — the "Replace fix" press — ✅ built

- **What:** a catalogue entry's "Apply fix" on a game that already has a
  LuaTools fix. The backend refuses (`needsReplace` + the installed types) and
  the button becomes **"Replace fix"** with the description "This game already
  has a fix installed: X. Press again to replace it." / "…already has N fixes
  installed. Press again to replace them." Same two-press rule as Uninstall:
  5 s without a press and it reverts to "Apply fix".
- **Second press:** the usual apply flow with a first phase "Removing the
  installed fix..." (`replacing`) as the "Applying fix…" row's step, then
  download / extract.
- **Native or custom:** the same `ActionButton`, label and description only.
  Backend: FIXES_MAP.md, "One LuaTools fix per game".

#### 8e-bis. Online Fixes tab and the Online toggle — ✅ built

- **Online Fixes tab:** three sections, top to bottom: the online LuaTools
  catalogue ("LuaTools Online Fixes", same renderer as §8e incl. the login
  gate), **Installed Online Fixes** (same renderer as §8e's installed list),
  then the **Online** toggle below.
- **What:** one `ActionButton` per installed game, "Enable Online" / "Disable
  Online" ("Enabling…" / "Disabling…" while busy), under a `PanelSection` titled
  "Online" at the end of the Online Fixes tab.
- **Description (native `description`), one line:** what it will apply or has
  applied, each door by its real name — `Will apply: FakeAppId (480) ·
  steamnetsock-patch · eos-proxy.` / `Active: …` — then the situational notes
  (steamnetsock-patch not installed; an online fix already installed, "try it
  first"), and always last: "Do not use with anti-cheat games." (steamnetsock-
  patch's own warning, no detection). No separate `Field`: one line, no extra
  row.
- **Disabled** while busy, with no install path, or on a Denuvo-activated game
  (description: "Denuvo-activated game: online is not available.", no warning),
  or for an owned game (description `ownedNoOnline`: "Disabled for owned games.
  Steam's own online services apply.").
- **Toasts:** "Online enabled" / "Online disabled"; failures show the backend
  error. Backend and lifecycle: FIXES_MAP.md, "Online multiplayer".
- **Freeze:** enabling with eos-proxy applied freezes the game (Auto-update
  toggle off, version line "Frozen"), like Apply fix, Goldberg and Steamless —
  FIXES_MAP.md, "Anything in the game dir freezes the game". The page re-reads
  the pin after each of those operations.

#### 8f. Uninstall (Danger Zone) page — ✅ built (v0.3.56)

- **What:** the destructive full-uninstall flow — a "what will be removed" list,
  a "remove Proton prefix" toggle, and the red two-tap uninstall button.
- **Was:** a hand-bordered **red box** (`<div>` with red bg/border/radius), an
  uppercase "WHAT WILL BE REMOVED" header, and 6 items each with a red `✕` mark.
- **Now:** the box → a single native `Field` in an untitled `PanelSection`
  (`label` = `uninstallWillRemove` "Permanently removes:", `description` = the
  items joined with ` · ` — 7 for an added game: files, lua config, ACF, depot
  manifests, Steam config entries, keys, achievement schema), with a ⚠
  `FaExclamationTriangle #e07070` icon for the destructive signal. For an
  **owned game** the list starts with `uninstallItemOwnedKeeps` ("Only the DLC.
  The game itself stays") and covers only the DLC side (6 items, no game files,
  no achievements); the uninstall first unticks the DLC in Steam
  (`disableDlcs`, `src/steamDlc.ts`) and changes nothing if Steam refuses. The
  hand-bordered box, the uppercase header and the per-item `✕` are gone; the
  rest of the severity is carried by the red `danger` button, the two-tap
  confirm (relabel "Confirm uninstall" + `clickToConfirm` `description`, 5 s
  revert), and the tab title. `ToggleField` + uninstall `ActionButton` were
  already native.
- **Native or custom:** 🟢 fully native; no inline styles left on this page.
- **Rule:** a destructive-action summary is a native `Field` (icon + label + ` · `
  list), not a hand-bordered coloured box. Let the danger button + confirm +
  page title carry severity; the icon is the only decorative signal kept.

**GameDetail done.** All pages (Status, Updates, Fixes & Repairs, Online Fixes,
Danger Zone; Achievements when enabled) are native. The page has zero
hand-bordered boxes and only the handful of allowed inline styles (status
colours on value spans, the inline ⚠ on the LuaTools gate row).

---

### 9. Settings — full-screen `SidebarNavigation` (6 visible pages) — ✅ built (9a–9g done)

The config surface (`ROUTE_SETTINGS`), a `SidebarNavigation` titled LumaDeck,
every page `hideTitle: true`. Pages: **API Credentials** (`FaKey`),
**Components** (`dependencies` key, `FaDownload`), **System** (`FaCog`),
**About** (`FaInfoCircle`), **Help** (`FaQuestionCircle`), **Dev** (`FaCog`,
always shown, §9g) — plus **Achievements** (`ACHIEVEMENTS_ENABLED`, §6) and
**SLSsteam** (`SLSSTEAM_TAB_ENABLED`, §9b), both hidden (`src/features.ts`).
**Components is the "advanced 1%" detailed per-component breakdown** (the
QAM's `SystemStatus` is the collapsed view for everyone else). The pages carry
no `identifier`, so a tab cannot be deep-linked today (see Drift in code).
Original audit: ~27 custom-chrome spots, mostly **colored status
`<div>`s** (green installed / red not-found / amber degraded / blue update),
plus 2 monospace command "code-block" alert boxes (SLSsteam, Dependencies) and 1
custom disk-usage bar (System). Same three native patterns as GameDetail:
status → `Field` (icon for the colour signal), command box → `Field` with
monospace `description`, custom bar → `ProgressBarWithInfo`.

#### 9a. API Credentials page — ✅ built

- **Was:** two colored status sub-line `<div>`s — `renderCredLine` (credential
  validity: green ok / amber soon / red expired / gray none) and
  `renderHubcapUsage` (gray daily-usage stat).
- **Now:** three `PanelSection`s, one per provider (section title = provider
  name; no page-level "API Credentials" title):
  - **Hubcap API Key:** label-less password `TextField`, a `12px` spacer
    `<div>`, **Save**, **Get key** (opens hubcapmanifest.com in Steam's browser).
    Saving an empty key removes it (`toastApiKeyRemoved`).
  - **Ryuu Cookie:** label-less password `TextField` (manual paste fallback),
    the same spacer, **Save**, and **Log in with Discord** — opens
    generator.ryuu.lol in Steam's browser, captures the session cookie via CDP
    the moment the user logs in, closes the browser and refreshes the status
    ("Logging in…" while waiting).
  - **LuaTools fixes:** one `ButtonItem` — **Log in with Discord** / **Log out**
    — whose `description` is the state: connected ("Fixes appear on each game
    details page"), session expired (`luatoolsExpiredSettings`), or logged out.
  - Each credential section (Hubcap, Ryuu) ends with **one** status line: a
    `Field focusable highlightOnFocus={false}` (so the gamepad can scroll to
    it) whose colour rides on an **icon** (✓ `FaCheckCircle #00cc00` ok, ⚠
    `#ff8c00` soon, ⚠ `#ff4444` expired, none for none/unknown), text as
    `label`. Hubcap's today-usage is appended to the same line ("… Today: 1/25
    requests"), not a separate row.
- **Native or custom:** 🟢 native; the credential inputs/buttons are
  `TextField`/`ButtonItem`. The two spacer `<div>`s are layout (see Drift in
  code); the LuaTools/Ryuu login strings are hard-coded (same).

#### 9b. SLSsteam page — hidden (`SLSSTEAM_TAB_ENABLED=false`)

- **What (when the flag is on):** the raw SLSsteam config editors, kept in code:
  **AdditionalApps** (force AppIDs as owned) and **FakeAppIds** (remap AppIDs for
  networking), each its own `PanelSection` titled by the block, with a
  helper-text `Field description`, one `ButtonItem` per entry (`id ✕` /
  `real → fake ✕`, press to remove), labelled `TextField`(s) and an **Add**
  button. No Restart button (SLSsteam hot-reloads `config.yaml`). Hidden because
  both duplicate better homes (My Games; the Online toggle's FakeAppId).
- **No repair/update zone and no `gamemodeBlocked` alert any more:** repair and
  update for SLSsteam live in the Components page's morphing button (§9c), which
  uses the same "Fix in Desktop" hand-off as the QAM.
- **Native or custom:** 🟢 native; no inline styles.

#### 9c. Components page (`dependencies` key) — ✅ built

The dense "advanced 1%" per-component breakdown, one untitled `PanelSection`.
- **Rows:** SLSsteam, .NET Runtime, lumalinux, CloudRedirect, Steam — each a
  `Field focusable highlightOnFocus={false}` (8a pattern): `label` = name,
  coloured value child:
  - hook components (SLSsteam / lumalinux / CloudRedirect): **Active** green
    `#00cc00` (healthy) / **Installed** amber `#ff8c00` (there but not working)
    / **Not installed** red `#ff4444`; CloudRedirect off by choice (`disabled`)
    = grey `#888` **Disabled**, no alarm. .NET Runtime: Installed / Not
    installed.
  - **Steam:** **Supported** green / **Not supported** amber (only when
    `current_build_supported_by_latest === false`).
- **Sub-line:** the `description` is a single coloured line, only when there is
  something to say (nothing when healthy and up to date). It is a text glyph in
  a `<span>`, not a `Field` icon: ⚠ `#ff8c00` problem, ↑ `#9cc4ff` update, •
  `#888` benign. For Steam: the build mismatch (⚠) or "update available" when
  Steam is behind a pin lumalinux is ready for (↑). The install path is not
  shown.
- **One morphing action `ButtonItem`** below the rows, driven by
  `primarySystemAction()` (shared with the QAM, same priority): **Fix in
  Desktop** / **Finish setup** / **Re-enable injection** / **Repair**
  (`not_injected`; the only place "Repair" is a visible label) / **Restart
  Steam** / **Update in Desktop** (Steam align-up) / **Install** or
  **Reinstall** (healthy, manual maintenance). Standard two-tap confirm:
  "Confirm (restarts Steam)" or "Confirm (continues in Desktop)", 5 s revert.
  No per-component install/repair/update buttons.
- No Game-Mode-blocked alert box and no monospace command any more. Removed
  earlier: the `<div style height:8px>` spacer (native rows space themselves)
  and the `<div textAlign:center>` wrappers inside button `description`s.
- **Native or custom:** 🟢 native; inline styles left are the status colour on
  the value spans and the coloured sub-line spans (see Drift in code for the
  `#888` grey).

#### 9d. System page — ✅ built

- **Was:** centered gray "current language" `<div>`, a gray "Steam: <root>"
  `<div>`, and per Steam library a nested `<div>` block (path line + free/games
  line + a **custom disk-usage bar** = background `<div>` + colored fill).
- **Now:** language → a toggle `ButtonItem` labelled with the *other* language
  in its own language ("Português (BR)" / "English", allowed literals) + a plain
  `Field` naming the current one; platform → `Field label="Steam"
  description={root}`; each library → a `Field` (path + default tag in the
  `label`, no description) plus a native `ProgressBarWithInfo` (usage %, with
  free/total + game count in `sOperationText`). Used `flatMap` to emit the
  Field + bar as two keyed rows.
- **Note:** the old bar tinted red >90% / amber >75%; `ProgressBarWithInfo` has
  no threshold colour, so that signal is dropped (the % + text remain). Acceptable
  trade for native.
- **Native or custom:** 🟢 native; no inline styles left.

#### 9e. About page — ✅ built

- **Was:** a gray blurb `<div>`, a version `<div>` (installed + a colored
  `<span>` latest), and a blue plugin-message `<div>`.
- **Now:** blurb → `Field description`; version → `Field label={installed}` with
  the latest as a colored value child (`#9cc4ff` when an update exists,
  `#8b929a` otherwise); plugin message
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
  a game, the features, troubleshooting tips). en only — pt-BR falls back to
  en via `t()`. **Content is sourced from `docs/`** (getting-started,
  managing-a-game, troubleshooting) — an earlier from-memory draft had
  inaccuracies (e.g. Token described as an ownership token, and the add-a-game
  steps missed the restart-Steam → press-Install flow); aligned to the docs.
- **Render:** every block — prose and features — is a
  `Field focusable highlightOnFocus={false} bottomSeparator="none"` carrying the
  text in its `label` as a styled `<div>` (`13px #dcdedf`, line-height 1.5;
  `pre-line` for the steps and tips; troubleshooting `12px`). Reason: the
  `SidebarNavigation` pane only scrolls to focusable elements, so read-only text
  needs a focus anchor (a `<div>` in `<Focusable noFocusRing>` did not reliably
  take gamepad focus). `highlightOnFocus` is off so the text doesn't look
  selectable. Text in the `label` slot, not `description`, keeps it unmuted
  and the numbered steps intact.
- **Features:** four (FakeAppId, Goldberg, Fixes, Linux Native), same treatment,
  with the name as a bold (600) first line.
- **`ScrollAnchor`** (`src/components/ScrollAnchor.tsx`): a bare transparent
  `Focusable` (48px, `noFocusRing`, no-op `onActivate`) closes the page, so Game
  Mode's navbar doesn't hide the last block. It is a `Focusable`, not a `Field`,
  because a `Field` draws visible row chrome.

#### 9g. Dev page — *always shown* — ✅ built (not user-facing)

- **What:** developer-only state forcing and the SteamDB reader probe.
- **How shown:** a `PanelSection` "Dev — force UI states": an intro `<div>`
  (`12px #8b929e`); one `DropdownItem` per forced UI state (SLSsteam /
  lumalinux / CloudRedirect health, Quick Install onboarding, crash guard,
  Hubcap key, Ryuu cookie, fake games), backed by `backend/dev.py` — it only
  forges what the UI reads, nothing real is touched; **Reset all to real**;
  then the SteamDB probe: a second intro `<div>`, an `appid` `TextField`, a
  probe button, an "open SteamDB" button (for the Cloudflare check) and a
  result `<div>` (`12px #c7d5e0`, `pre-wrap`).
- **Native or custom:** 🟢 native controls; 🔴 free-text `<div>`s.
- **Rule:** Dev-only UI is exempt from `t()`. It is not behind a flag today and
  should be gated (flag) before release; its strings are partly Spanish (see
  Drift in code).

**Settings done.** All pages native, except the documented exceptions: status
colours on value spans, the coloured sub-line spans of Components, Help's text
inside focusable `Field` labels, two `12px` spacers under the label-less
`TextField`s (drift), the hidden Achievements tab's intro/help `<div>`s, and the
Dev page's free text.

---

### 10. Workshop (was "Downloads") — ❌ removed

- **Replaced by:** nothing. The page (`Downloads.tsx`, `ROUTE_DOWNLOADS`) and its
  QAM entry are gone; games are added from the QAM's Add Game and Steam downloads
  them natively.
- **Rule (kept):** a single-screen route is a plain full-screen page, not a
  1-page `SidebarNavigation` (§7).

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
  through the native `ProgressBarWithInfo` (QAM, GameDetail, Settings), so the
  component was unreferenced. Deleted.
- **`components/TextInputButton.tsx`** — not imported anywhere (QAM text input is
  a plain `TextField` now). Deleted.
- **`components/AppPageButton.tsx`** — kept: it's injected into Steam's **native**
  library app page (`index.tsx`), not a Decky panel, so its `<div>` "Added via
  LumaDeck" badge is correct (no `PanelSection`/`Field` context there). Badge
  text: `13px #8bca68`, centred.
- **What remains in `components/`:** `ActionButton` (§8), `AppPageButton`,
  `GameCard` (§7), `ScrollAnchor` (§9f), `SystemStatus` (§3).

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
  no bash re-implementation, so **no install step is forgotten**. Today that is
  one step: a single `setup.sh` run (`install_via_setup`) for the whole stack
  (no Steam downgrade, no freeze, no `steam.sh` patch inside it). It streams
  progress to Konsole and writes `~/lumadeck-quickinstall.json` for debugging;
  returns to Game Mode on success, stays in Desktop on failure.
- `gamemode` is kept for a uniform step signature; `setup.sh` handles both modes
  itself. (The old headcrab-script patching is gone.)
- ⚠️ Needs on-device validation: the launcher relies on the system `python3`
  importing the backend (Decky doesn't run in Desktop). The diagnostic file makes
  a failure (e.g. a missing import) debuggable.

---

## Component model — system status (errors + updates) — ✅ DONE (steps 1–6)

> Progress: **1** `get_components_status()` ✅ · **2** `apply_component()` ✅ ·
> **3** one fetch + `SystemStatus` renderer (5-action collapse + update track),
> old builders/banners deleted ✅ · **4** Stuck into the renderer ✅ (folded into
> step 3) · **5** Desktop autostart for the downgrade ✅ (v0.3.50 — the "Fix in
> Desktop" row arms a one-shot autostart that runs `downgrade.sh` (Steam client downgrade
> + pin) then `setup.sh` re-inject in Desktop and auto-returns to Game Mode) · **6** i18n cleanup ✅
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
  components: [ { id, name, installed, health, cause, action,
                  update:{installed,latest,available} }, ... ],
  headcrab:   { compatible, target, current,
                lumalinux_ready,                     // lumalinux supports the pinned target?
                current_build_supported_by_latest }, // latest lumalinux still hooks this build?
  plugin:     { installed, latest, available },
  guard:      { active, fails, since, client_changed }, // launcher crash guard (row 6)
  quickInstall: "show" | "hide" | null,                 // dev preview override (backend/dev.py)
}
```
`health` is one of `not_installed` / `not_loaded` / `not_injected` /
`not_supported` / `not_authed` / `disabled` / `healthy` (`not_authed` and
`disabled` are CloudRedirect-only); `cause` carries the detail (e.g. `version` /
`hooks` for `not_supported`), `action` the backend's suggested fix.
New real check: `check_slssteam_update` (vs **AceSLS/SLSsteam** releases) + a CR
semver check (the version compiled into the installed `.so` vs the newest
**Selectively11/CloudRedirect** release that ships a `cloud_redirect.so` asset)
(see Updates).
`headcrabCompat` goes back to being *only* the compat gate — the
fake "SLSsteam update derived from `!compatible`" is deleted.

**2. `apply_component(id, op)` — one cascade-safe action.** `op ∈ {install,
repair, update}`. Does the op, then **always** runs `reinject_installed()`, which
re-runs `setup.sh` to re-establish the whole installed stack in one idempotent pass.
There is no `steam.sh` ordering for the UI to know — setup.sh reconciles everything
and leaves `steam.sh` vanilla.

### Compatibility contract (how updates stay safe)
The compat anchor is still **headcrab's pinned Steam build**
(`HeadcrabCompatibleClientVer`, read by `headcrab_compat.py` from
Deadboy666/h3adcr-b's `headcrab.sh`) — a build chosen to be
mutually compatible at the **weakest-link**, so the break-recovery downgrade never
lands you on a Steam that breaks SLSsteam or CR. The components themselves are
installed by `setup.sh` from their own upstreams (SLSsteam from AceSLS, CloudRedirect
from Selectively11), not from a headcrab bundle. lumalinux self-validates via its
`steamclient.so` hash/RVA check (reported as `not_supported`). Three safety
layers:
1. Updates are offered whenever an installed component has a newer version (an
   update re-runs `setup.sh`, which is Steam-build-agnostic); the **whole update
   track is skipped while any component is `not_supported`**. The Steam
   align-up row additionally needs `headcrab.lumalinux_ready === true`.
2. lumalinux's hash check refuses silently-incompatible builds (`not_supported`).
3. After `apply_component`, re-fetch status to confirm all healthy.

---

### ERRORS → the user can only ever do 6 things

| # | User action | Backend states it covers | Where |
|---|---|---|---|
| 1 | **Restart Steam** | `not_loaded` (any component) | Game Mode |
| 2 | **Repair** (re-run `setup.sh` + restart) | `not_injected` (any component) — not a separate visible row: it shows as **Restart needed / Restart Steam** and runs repair + restart underneath; core half-installed is its own **Setup incomplete / Finish setup** row (`apply_component("core","install")` + restart) | Game Mode |
| 3 | **Downgrade Steam** ("Fix in Desktop") | "Steam too new": `not_supported` (any cause) | Desktop |
| 4 | **Configure cloud provider** | CR `not_authed` — an **info** (blue ↑) `Field`, not a ⚠ problem | Desktop |
| 5 | **Install LumaDeck manually** | plugin needs the zip | manual |
| 6 | **Re-enable injection** (clear the crash guard + restart) | `guard.active` — the launcher's crash guard latched safe mode (3 startup crashes, or 1 right after a Steam update); every hook component reads `not_loaded` and Steam runs with **no** injection until the guard's state files go | Game Mode |

**Row 6 (2026-09-23).** `lumalinux/setup.sh`'s `luma_guard_run` is the stack's
anti-brick fail-safe: a Steam minidump in `/tmp/dumps` within 180 s of a
launch counts as a startup crash; three in a row (or one when
`steamclient.so` changed since the last clean boot) latch `safe_mode` in
`~/.local/state/lumalinux/`, and from then on every launch is plain Steam
(`env -u LD_AUDIT -u LD_PRELOAD`) until the payload fingerprint changes (a
stack update) or the state files are removed. While latched, action 1 is a
lie — the launcher goes vanilla again — so the plugin reads the latch
(`paths.read_crash_guard`, surfaced as `guard` in `get_components_status`)
and shows **Recovery mode** ("Steam crashed at startup. Running without
injection.") with **Re-enable injection** instead of "Restart needed". It
(`retry_injection` → `paths.clear_crash_guard`) removes exactly
`safe_mode`, `safe_mode_fingerprint`, `boot_fail_count`, `last_launch` and
restarts Steam; nothing else (not the payload, not `setup.sh`, not
`guard.log`). It is a retry, not an override: if the cause is still there
the guard latches again after three more crashes. The guard does not
distinguish whose crash it was — on 2026-09-23 it latched on three
CloudRedirect-induced Steam freezes while lumalinux itself had booted
healthy — and that is by design: vanilla strips the whole stack, which is
what let the user fix the cause (untick Steam Cloud for the game). The
plugin's job is to say what happened, not to second-guess the guard.

Silent: `healthy`, CR `disabled` (`~/.config/CloudRedirect/disable`, a
deliberate opt-out the plugin only *detects*, never creates), CR `not_installed`.

Info, no action: **Adding games unavailable** — only lumalinux is
`not_supported` and `headcrab.lumalinux_ready === false` (lumalinux has no
support for the pinned build yet; aligning Steam would not help, it self-heals
once support ships).

**Collapse / cross-reference rules (why the user sees little):**
- **"Steam too new" is ONE row** even when 3 components report it (three
  `not_supported`).
- **Same cause across components = one row** (two `not_loaded` → one "Restart").
- **Core (SLS+luma) is evaluated as one unit**; CR separate, only if installed.
- **Priority:** action 3 (downgrade) **supersedes** 1 and 2 (nothing works until
  Steam is right). Show the single highest-priority row; the next surfaces once
  it's resolved. Action 6 (Re-enable injection) sits between the incomplete-install row and
  1/2: `not_loaded` / `not_injected` are the guard's *symptom*, and their
  restart / repair cannot lift it. Order: waiting-for-support > downgrade >
  finish setup > **re-enable injection** > repair > restart.
  (Repair and restart share the one **Restart needed** row.)
- **lumalinux `not_supported` is conditional:** if lumalinux is the only
  unsupported component and `headcrab.lumalinux_ready === false`, it is not a
  downgrade: the row is the info **Adding games unavailable** ("wait for an
  update", no action — lumalinux self-heals once support ships). Otherwise it
  joins the downgrade group (Fix in Desktop).

**Confirm rule (2026-09-23).** Every button that restarts Steam or leaves
Game Mode asks for a second tap, and the first tap says which: **"Confirm
(restarts Steam)"** for Restart Steam, Repair, Finish setup, Update,
Reinstall, Re-enable injection, Quick Install at the pin and the achievements section's
Restart Steam; **"Confirm (continues in Desktop)"** for Fix in Desktop,
Update in Desktop and Quick Install off-pin. The armed state auto-reverts
after 5 s. Actions that do neither (open a stuck game, download the plugin
zip) fire at once. While running, a button that *only* restarts says
**"Restarting Steam..."**; anything that runs `setup.sh` first says
**"Working..."**; Quick Install keeps **"Setting up..."**. The same
`SystemStatus` row model drives the QAM and the Settings morphing button, so
the rule holds on both surfaces by construction.

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
not as a ⚠ fix: `FaArrowCircleUp #5b9eff` icon (not the accent `#1a9fff`).

Rows on this track, in order: **Steam update available** / **Update in Desktop**
(align-up, below), **Update available** / **Update** (any component), **LumaDeck
update available** / **Download update** (plugin, fires at once).

| Component | Update check | Apply | Weight |
|---|---|---|---|
| **lumalinux** | latest release of its repo vs installed | re-run `setup.sh` | light |
| **SLSsteam** | release tag of the `latest` asset (**via AceSLS/SLSsteam**) vs recorded `.slssteam.version` | re-run `setup.sh` | heavy |
| **CloudRedirect** | version string in the installed `.so` vs the newest **Selectively11/CloudRedirect** release that has a Linux `cloud_redirect.so` | re-run `setup.sh` | heavy |
| **Steam** (align-up) | Steam build behind headcrab's pin and `lumalinux_ready === true` | Desktop Quick Install hand-off (`runDesktopHandoffQuickInstall`), which lifts the pin so Steam self-updates **up** | Desktop |
| **LumaDeck** | latest plugin release | download zip → message "Decky ▸ Developer ▸ Install from ZIP, then restart Steam" | manual |

Rules:
- **CR's `.so` embeds its version** (`CR_GetVersion`); compare semver against
  the releases that actually ship a Linux build (several releases are
  Windows-only, so "latest" is not enough). The earlier hash compare against the
  rolling `linux-test` asset was replaced: it fired on every rebuild of an
  unchanged version.
- **Updates are offered whenever an installed component has a newer version**;
  the whole update track is skipped while any component is `not_supported`. The
  set updates **together** (one `setup.sh` run); re-check health after.
- **Steam align-up is never the downgrade path:** the "Steam update available"
  row moves Steam **up** to a newer supported pin via the Desktop Quick Install
  hand-off (lifts the pin). Routing it to the downgrade would re-pin and freeze
  Steam on the old build.
- SLSsteam/CR "update" = re-running `setup.sh` (the wrapper-model installer), which
  is **safe in Game Mode when Steam is already at the pin** (no downgrade happens).

---

### Two tracks the user sees
- **"Something's wrong" (⚠):** at most one system fix, by priority — Fix in
  Desktop / Finish setup / Re-enable injection / Restart Steam — plus one row
  per stuck game (Open game).
- **"Something's new" (info):** the update track.

Normally the user sees **nothing, or one row**. The full per-component breakdown
(versions, individual install/repair/update) lives in **Settings ▸ Components**
for the advanced 1%.

### What gets deleted
- The 3 near-identical health row builders (`slssProblem`/`llProblem`/`crProblem`)
  → one generic mapper.
- `UpdatesBanner` (absorbed into the single renderer).
- The fake "SLSsteam update" derived from `!headcrabCompat.compatible`.
- The misleading `checkCloudredirectUpdate` semver check → hash compare (itself
  since replaced by a semver compare of the `.so`'s embedded version, see
  Updates).
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

### Conventions in use (added 2026-10-09)

Observed in the code and consistent across it; recorded here so new UI follows
them. They add to the principles above and change none of them.

- **Feature flags for hidden-but-kept UI:** UI we may want back lives behind a
  flag in `src/features.ts` (`ACHIEVEMENTS_ENABLED`, `SLSSTEAM_TAB_ENABLED`),
  typed `boolean` (not the literal `false`) so the guarded code stays
  type-checked. Only entry points are hidden; the code is kept intact.
- **`hideTitle` pages, no repeated title:** every `SidebarNavigation` page sets
  `hideTitle: true`, and no `PanelSection` title repeats the tab name (or the
  game name that titles the sidebar). Sections are titled only when a page has
  several distinct blocks.
- **Coloured value as a `Field` child span:** a status or version value is a
  `<span>` child of a `Field` (`label` = what, child = value, `description` =
  the detail). That span is the one allowed inline colour on a row.
- **Owned-game awareness:** when Steam already owns the game (`isOwned` /
  `isOwnedBySteam`, `src/steamOwnership.ts`), the UI says so and adapts: pin,
  version and online controls are hidden or disabled with the reason, texts
  switch to the DLC-only wording (Add Game card, Status, Uninstall list).
- **Desktop hand-off buttons say so up front:** a button whose action switches
  to Desktop names it in its label ("Fix in Desktop", "Update in Desktop") and
  its confirm says "Confirm (continues in Desktop)".
- **Read-only rows on scrolling pages:** `Field focusable
  highlightOnFocus={false}`, so the gamepad can scroll to them without the row
  looking selectable (credential status lines, Components rows, Help blocks). A
  page whose tail is read-only ends with a `ScrollAnchor`
  (`src/components/ScrollAnchor.tsx`, a bare transparent `Focusable`) so Game
  Mode's navbar doesn't cover the last block.
- **Allowed literals** (shown without `t()`), as the code uses them: the brand
  `"LumaDeck"`; product/technical names ("AppID", "FakeAppId", "SLSsteam",
  "lumalinux", "CloudRedirect", ".NET Runtime", "Steam", "Metacritic",
  "ProtonDB", "Goldberg", "Linux Native"); and language names shown in their own
  language ("Português (BR)", "English"). Dev-only UI (Settings ▸ Dev, §9g) is
  exempt.
- **Status palette observed in use** (inline hex, alongside the text tokens):
  | Role | Value |
  |---|---|
  | Success | `#00cc00` |
  | Warning | `#ff8c00` (icons) / `#ffaa00` (value text) |
  | Danger | `#ff4444` |
  | Error text | `#ff6b6b` |
  | Info / update | `#5b9eff` (icon) / `#9cc4ff` (text) |
  Also present for data, not status: `#7ed36f` (owned line, Metacritic ≥ 75),
  `#c8a84b` (gold: Metacritic mid, ProtonDB gold, hints), `#e06060`
  (Metacritic low, ProtonDB borked), the ProtonDB medal map
  (`PROTONDB_TIER_COLOR`, `GameList.tsx:54-60`), and the library tile background
  `#1a2129`. Sizes seen beyond the 12/11px tokens: `13px` (Help, AppPageButton),
  `14px` (GameCard name), `15px` (title-bar icons).

### Drift in code (to fix in code, not in the rules)

Places where the code breaks a principle above. The principle stands; these are
code fixes. Line numbers as of 2026-10-09.

- **Hard-coded strings not going through `t()`:**
  - `src/pages/GameDetail.tsx`: fix build notes incl. "⚠ This fix needs build
    …" (:990-998), "Install the game version this fix needs" / "Installing
    version…" (:1015), "Apply fix" (:1023), "Couldn't load fixes" and the
    install-first notes (:1045-1049), "Log in with Discord" / "Logging in…"
    (:1066), "Applying fix…" (:1081), section titles "LuaTools Fixes",
    "Installed LuaTools Fixes", "Installed Online Fixes" (:1397, :1401, :1504),
    "Starting..." (:824, :833), "Failed" (:859), "Build N" / "Fix" (:986).
  - `src/pages/Settings.tsx`: Ryuu / LuaTools login strings, "LuaTools fixes",
    "Log out", the connected / logged-out descriptions (:834, :842, :853-867).
  - `src/hooks/useLuatoolsConnect.ts`: toasts marked `TODO i18n` (:65, :68,
    :82).
  - The Dev page (`Settings.tsx:1351-1413`, handler :732-751) is exempt from
    `t()`, but its strings mix English and **Spanish** ("Leyendo SteamDB…",
    "Probar lector SteamDB", "Abrir SteamDB…", "Lector SteamDB: …"); they
    should at least be one language.
- **Keys missing in pt-BR** (help* keys are en-only by design, §9f):
  `showMoreResults`, `sysAlignUpSwitching`, `sysAlignUpManual`.
- **Off-token colours:** muted greys `#888` (`Settings.tsx:585`, :1094),
  `#8b929e` (`Settings.tsx:1358`, :1380 — a near-duplicate of `#8b929a`),
  `#c7d5e0` (`Settings.tsx:1406`); `opacity: 0.8` instead of a muted colour
  (`Settings.tsx:882`, :898); `#e07070` on the Uninstall ⚠ instead of the
  warning/danger value (`GameDetail.tsx:1536`); `#8bca68` on the AppPageButton
  badge (`AppPageButton.tsx:43`). Off-value warning icons also appear as
  `#ffaa00` (`GameDetail.tsx:1344`) and `#c8a84b` (`Settings.tsx:967`). The
  comment at `GameList.tsx:53` points to a "DESIGN_UI.md palette" for the
  ProtonDB medals; only the observed list above exists.
- **Layout spacer `<div>`s:** `<div style={{ height: "12px" }} />` between the
  label-less `TextField` and Save (`Settings.tsx:789`, :817) — contradicts
  "native rows space themselves" (§9c).
- **Two confirm styles:** the two-click confirm is implemented two ways. Most
  buttons relabel themselves ("Confirm (restarts Steam)" / "Confirm (continues
  in Desktop)", no description: `SystemStatus.tsx`, Quick Install
  `GameList.tsx:695-701`, Components `Settings.tsx:1208-1222`, the achievements
  Restart); Uninstall (`GameDetail.tsx:1577`, `clickToConfirm`) and Replace fix
  (`GameDetail.tsx:1024`) put the prompt in the `description`.
- **Severity as text, not icon:** the Components sub-lines carry severity as a
  coloured text glyph (⚠ / ↑ / •) in a `<span>` (`Settings.tsx:583-588`), and
  "⚡" is a text glyph in the Quick Install label (`i18n.ts:370`).
- **Code bugs:**
  - `takePendingSettingsTab()` (`src/routes.ts:17-21`) is never called, and the
    Settings pages carry no `identifier`, so the Achievements deep-link
    (`setPendingSettingsTab`) lands on API Credentials (moot while
    `ACHIEVEMENTS_ENABLED` is off). `SETTINGS_TAB_CREDENTIALS` is unused.
  - `ownedDlcNextStart` (a success message) renders grey in the QAM status line,
    because the green test is `addStatus === t("doneRestartSteam")` only
    (`GameList.tsx:902`).
