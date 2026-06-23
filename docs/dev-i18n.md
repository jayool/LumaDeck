# Translations / i18n (developer)

All UI strings live in **`src/i18n.ts`**. LumaDeck ships **English (`en`)** and
**Brazilian Portuguese (`pt-BR`)**.

## How it works

```ts
type Lang = "en" | "pt-BR";

const strings: Record<Lang, Record<string, string>> = {
  en:      { addGame: "Add Game", /* ... */ },
  "pt-BR": { addGame: "Adicionar Jogo", /* ... */ },
};
```

- Components read strings via the **`useT()`** hook:
  ```ts
  const t = useT();
  ...
  t("addGame")
  ```
- Placeholders are `{0}`, `{1}`, … filled positionally:
  ```ts
  t("pluginInstalled", version)   // "Installed: {0}"  -> "Installed: 1.2.3"
  ```
- The active language is detected from the Steam/browser locale (anything
  starting with `pt` → `pt-BR`, else `en`) and can be overridden in
  **Settings ▸ System**. `useT` re-renders components on change.

## Adding a string

1. Add the key to **both** locale blocks (`en` and `pt-BR`) in `src/i18n.ts`.
   Keep them next to related keys so the file stays navigable.
2. Use it via `t("yourKey")` (with positional args if it has `{0}`…).

> Add to **every** locale. A missing key falls back to the key name, which ships
> as visible junk text.

## Adding a language

1. Extend the `Lang` type: `type Lang = "en" | "pt-BR" | "es"`.
2. Add a full locale block to `strings` with every key translated.
3. Update `detectLanguage()` so the new locale is auto-selected (and, if you
   want it user-selectable, the toggle in `Settings.tsx`).

## Conventions

- Keys are `camelCase`, grouped by screen with a `// Section` comment.
- Don't bake numbers/names into a string — pass them as `{0}` args so both
  locales share one template.
