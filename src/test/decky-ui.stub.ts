// Stand-in for @decky/ui under vitest. The real package reaches into Steam's
// webpack modules at import time; the tests only exercise the pure row logic
// in SystemStatus.tsx, so every component it imports is a no-op here.
export const PanelSection = () => null;
export const PanelSectionRow = () => null;
export const ButtonItem = () => null;
export const Field = () => null;
