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

---

## Principles (emerging)

- The brand string `"LumaDeck"` is the only hard-coded display literal; every
  other user-facing string goes through `t()`.
- Icons come from `react-icons/fa` only.

*(More principles will be added as we verify each element.)*
