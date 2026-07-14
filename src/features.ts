// Feature flags for UI we may want back later.
//
// ACHIEVEMENTS_ENABLED gates LumaDeck's Steam Web API achievement feature: the
// per-game "Generate" panel (GameDetail), the API-key + "Sync All" tab
// (Settings), the QAM entry and its readiness hint (GameList), the "has
// achievements" marker on the game card (GameCard) and the status lookup that
// feeds it (Library). All of that code is kept intact; only the entry points
// are hidden while SLSsteam handles native achievements on its own. Flip this
// to true to bring the whole achievements UI back if the SLSsteam path turns
// out not to be enough.
//
// Typed as boolean (not the literal `false`) on purpose, so the guarded code
// stays reachable to the type checker and no "unused" errors appear.
export const ACHIEVEMENTS_ENABLED: boolean = false;
