# LumaDeck — UI / Style Conventions

Practical guidelines for the plugin's **visual layer** (layout, color, type,
spacing, recurring component patterns). The goal is consistency: new UI should
look like the UI already there.

This doc is **descriptive and prescriptive** — it records the conventions the
codebase already follows and the canonical tokens to reach for going forward.
Where the current code is inconsistent (e.g. several near-duplicate greens),
the "Use" column is the value to standardise on; the others are legacy and may
be migrated opportunistically.

The plugin renders inside Steam Game Mode via Decky, using `@decky/ui`
components. There is no CSS framework — styles are inline `style={{…}}` on
plain elements wrapped in Decky primitives.

---

## 1. Layout architecture

### 1a. Full-screen routes → **always `SidebarNavigation`**

Pages registered with `routerHook.addRoute` render full-screen **over** Steam's
Game Mode chrome (the top status bar and the bottom controls bar). A bare
`<>…</>` of `PanelSection`s has **no scroll container**, so the whole document
scrolls together and drags the chrome with it: the top bar overlaps the first
header and the bottom bar rides up while scrolling.

**Rule:** every full-screen route returns a native
[`SidebarNavigation`](https://github.com/SteamDeckHomebrew/decky-frontend-lib)
(the same component Steam's own Settings screen uses). It provides a fixed
sidebar/header and a content pane that scrolls correctly and respects the
top/bottom safe areas for free.

```tsx
const pages = [
  {
    title: t("sectionKey"),     // sidebar label (i18n)
    icon: <FaSomething />,       // react-icons/fa
    hideTitle: true,             // keep the inner PanelSection titles as headings
    content: (
      <>
        <PanelSection title={t("sectionKey")}>…</PanelSection>
      </>
    ),
  },
  // …more pages
];
return <SidebarNavigation title="LumaDeck" pages={pages} />;
```

Conventions:
- **`hideTitle: true`** on every page, so the existing `PanelSection` titles
  act as the in-page headings (no duplicate "page title" + "section title").
- **`title`** prop of `SidebarNavigation`: `"LumaDeck"` for static pages;
  the dynamic subject (e.g. the game name) where one exists (GameDetail).
- Wrap each page's `content` in a `<>…</>` fragment when it contains JSX
  comments or more than one section (a `{/* comment */}` directly inside
  `content: ( … )` without a fragment is a syntax error).
- **No in-content "Back" button** — gamepad **B** / the sidebar handle
  navigation natively. (An automatic `Navigation.NavigateBack()` after an
  action, e.g. post-uninstall, is fine.)
- Icons come from **`react-icons/fa`** (matches the rest of the project).

The three full-screen routes and their page split:

| Route | `SidebarNavigation title` | Pages |
|---|---|---|
| Settings | `"LumaDeck"` | Credentials · SLSsteam · Dependencies · System |
| GameDetail | `{gameName}` | Status · Download · Management · Achievements · Fixes · Uninstall |
| Downloads | `"LumaDeck"` | Manual · Workshop |

> **Do not** add a full-screen route that returns a bare `<>` of
> `PanelSection`s. If a page is a single flow with no natural sections,
> `ScrollPanel` (`@decky/ui`) is the lighter native alternative — but prefer
> `SidebarNavigation` for consistency.

### 1b. QAM root (`GameList`) → `PanelSection` / `PanelSectionRow`

The Quick Access Menu panel is **not** a full-screen route; it uses
`PanelSection` + `PanelSectionRow` directly. Conditional onboarding (the Quick
Install block) renders first, only when applicable. Bottom action buttons
(Settings, Refresh, Restart Steam…) live in a trailing `PanelSection`.

---

## 2. Color palette

All colors are inline hex. Canonical tokens below; pick the **Use** value for
new code.

### Text
| Role | Use | Legacy variants seen |
|---|---|---|
| Primary text | `#dcdedf` | `#e5e5e5` |
| Secondary / muted | `#8b929a` | `#9aa4b2`, `#b8bcbf`, `#aaa`, `#ccc` |
| Disabled | `#666` | `#888`, `#555`, `#bbb` |

### Status (the core semantic colors)
| Meaning | Use | Legacy variants |
|---|---|---|
| OK / installed / healthy | `#00cc00` | `#7ed36f`, `#8bca68` |
| Missing / not found / failure | `#ff4444` | — |
| Degraded / warning | `#ff8c00` | — |
| Not configured / caution | `#ffaa00` | `#ffaa33` |
| Inline error text | `#ff6b6b` | — |
| Danger / destructive header | `#e07070` | `#e06060` |

### Accent / info
| Meaning | Use | Legacy variants |
|---|---|---|
| Accent / progress fill | `#1a9fff` | `#4a9eff`, `#5b9eff` |
| "Update available" sub-line | `#9cc4ff` | — |
| Gold accent (notice markers, ▸ bullets) | `#c8a84b` | — |

### Surfaces
| Role | Use |
|---|---|
| Progress-bar track | `#2a2d35` |
| Dark surface / inset (code block bg) | `rgba(0,0,0,0.3)` |
| Borders / dividers | `#3d4450` |

> **Consolidation note:** the greens (`#00cc00` / `#7ed36f` / `#8bca68`) and
> blues (`#1a9fff` / `#4a9eff` / `#5b9eff`) are near-duplicates that drifted in.
> Prefer the **Use** value; migrate stragglers when you touch a file.

---

## 3. Typography

No font-family overrides (inherit Steam's). Scale, by role:

| Size | Role |
|---|---|
| `13px` | Primary detail text (GameDetail info rows) |
| `12px` | Standard status / dependency line — the default body size |
| `11px` | Secondary sub-line: health lines, hints, captions |
| `10px` | Monospace blocks (shell commands), e.g. `fontFamily: "monospace"` |

Weight: default. Use `fontWeight: 600` only for small emphasis headers
(e.g. a ⚠ warning title). Uppercase section eyebrows use
`textTransform: "uppercase"` + `letterSpacing: "0.05em"`.

---

## 4. Spacing

| Token | Value | Use |
|---|---|---|
| Section spacer | `height: "8px"` in a `PanelSectionRow` | separate a status block from an action cluster |
| Sub-line indent | `paddingLeft: "8px"` | indent a health/detail line under its status line |
| Stacked-text gap | `marginBottom: "4px"` (or `6px`) | between stacked text lines in one row |
| Keyboard clearance | `paddingBottom: "280px"` **focus-conditional** | QAM text fields (see §5d) |

Keep ad-hoc margins on the 1–8px scale; don't invent new large constants.

---

## 5. Recurring component patterns

### 5a. Dependency / status line
A 12px line, colored green when present and red when absent, with an optional
indented 11px health sub-line below:

```tsx
<PanelSectionRow>
  <div style={{ fontSize: "12px", color: dep ? "#00cc00" : "#ff4444" }}>
    Name: {dep ? `${t("installed")} (${path})` : t("notFound")}
  </div>
</PanelSectionRow>
{health && (
  <PanelSectionRow>
    <div style={{ fontSize: "11px", color: stateColor, paddingLeft: "8px" }}>
      {healthLine}
    </div>
  </PanelSectionRow>
)}
```

### 5b. Two-click confirm (destructive / install actions)
Install and uninstall actions use a confirm-state toggle: first click arms
(button relabels + shows a `description` prompt), second click executes.
State vars follow `confirm<Action>` naming (`confirmInstallDeps`,
`confirmUninstall`, `confirmQuickInstall`, …).

```tsx
<ButtonItem
  onClick={handleX}
  description={confirmX ? <div style={{ textAlign: "center" }}>{t("xConfirmDesc")}</div> : undefined}
>
  {busy ? t("xing") : confirmX ? t("xConfirm") : t("xLabel")}
</ButtonItem>
```

### 5c. Status-block → action-buttons separation
Insert an 8px spacer between an informational status block and the action
buttons below it so they don't read as one cluster:

```tsx
<PanelSectionRow><div style={{ height: "8px" }} /></PanelSectionRow>
```

### 5d. Keyboard-aware text fields (QAM)
A text field low in the QAM list can be hidden by the on-screen keyboard. Give
it scroll room **only while focused**, so there's no permanent gap:

```tsx
const [focused, setFocused] = useState(false);
…
<div style={{ paddingBottom: focused ? "280px" : "0px" }}>
  <TextField
    value={…}
    onChange={…}
    onFocus={() => setFocused(true)}
    onBlur={() => setFocused(false)}
  />
</div>
```

### 5e. Icons
`react-icons/fa` only. Used for `SidebarNavigation` page icons and inline
markers. Keep one icon family for visual consistency.

### 5f. Custom focusable buttons (DialogButton)
**Default: don't override a DialogButton's `background`/`color`.** Steam's
native focus (button fills white, glyph/text goes dark) is the look to keep —
it matches every other button. For icon buttons, constrain only the *size*
(`width`/`height`/`padding`) and leave the rest to Steam.

**Anchor a utility-icon row in a labelled `Field`** — never let an icon cluster
float at the top of `content`. A `Field` (label on the left, the icons in a
right-aligned `Focusable` on the right, `bottomSeparator="standard"`) drops the
cluster into the panel's native row rhythm so it reads as placed, not lonely.
Don't use a rounded "pill" container or a bare floating `Focusable`:

```tsx
<Field label={t("headerSubtitle")} bottomSeparator="standard">
  <Focusable style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
    <DialogButton style={iconBtnStyle}><FaDownload /></DialogButton>
    …
  </Focusable>
</Field>
```

Re-create focus **only** when an inline `background` is unavoidable — e.g. a
segmented toggle whose selected option must show an accent fill. Native focus is
then suppressed, so animate it like a native button (grow + glow), never a
static ring:

```tsx
transform: focused ? "scale(1.04)" : "scale(1)",
boxShadow: focused ? "0 0 10px rgba(26,159,255,0.55)" : "none",
transition: "transform 0.16s ease, background 0.16s ease, box-shadow 0.16s ease",
```

Track that focus with **both** `onFocus`/`onBlur` (DOM) and `onGamepadFocus`/
`onGamepadBlur` (Decky), spread via an `any`-typed object since
`DialogButtonProps` doesn't declare them.

### 5g. Vertical clearance standard
**8px** is the canonical gap between a block and the next focusable control, so
a control's focus glow never collides with the block above it:
- every `Notice` carries `marginBottom: 8px`;
- insert `<PanelSectionRow><div style={{ height: "8px" }} /></PanelSectionRow>`
  between a mode toggle and the field under it.

Don't rely on `PanelSectionRow`'s own margin alone — it's too tight once a
neighbour shows a focus glow.

---

## 6. Internationalisation

All user-facing strings go through `t("key")` (`src/i18n.ts`), which has `en`
and `pt-BR` dictionaries. **Add every new key to both** dictionaries. Never
hard-code display text in a component (the only inline literal in the UI is the
brand string `"LumaDeck"`).

---

## 7. Don'ts

- ❌ Bare `<>` of `PanelSection`s in a full-screen route (chrome overlap). Use
  `SidebarNavigation`.
- ❌ Permanent large bottom padding to dodge the keyboard. Make it
  focus-conditional.
- ❌ New near-duplicate greens/blues/grays. Reuse the §2 **Use** tokens.
- ❌ In-content "Back" buttons on `SidebarNavigation` pages.
- ❌ Hard-coded display strings — route everything through `t()`.
- ❌ Inventing large spacing constants — stay on the 1–8px scale (plus the
  documented 280px keyboard clearance).
