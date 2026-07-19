export const ROUTE_GAME_LIST = "/lumadeck";
export const ROUTE_GAME_DETAIL = "/lumadeck/game";
export const ROUTE_SETTINGS = "/lumadeck/settings";
export const ROUTE_LIBRARY = "/lumadeck/library";

// Settings sidebar tab identifiers (each Settings page carries one as its
// `route`/`identifier`). Used to deep-link a specific tab from outside Settings.
export const SETTINGS_TAB_CREDENTIALS = "credentials";
export const SETTINGS_TAB_ACHIEVEMENTS = "achievements";

// Achievements no longer has its own full-screen route — it lives as a tab in
// Settings. Callers that want to land on it stash the tab here, then navigate to
// ROUTE_SETTINGS; Settings reads (and clears) it on mount.
let _pendingSettingsTab: string | null = null;
export const setPendingSettingsTab = (tab: string | null) => {
  _pendingSettingsTab = tab;
};
export const takePendingSettingsTab = (): string | null => {
  const v = _pendingSettingsTab;
  _pendingSettingsTab = null;
  return v;
};
