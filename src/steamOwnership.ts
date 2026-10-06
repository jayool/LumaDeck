/**
 * Does the account own this game, according to Steam's own UI?
 *
 * `appStore.GetAppOverviewByAppID(appid)` is the client's library model
 * (the same object the library grid renders from). Measured 2026-10-06 on
 * the SteamOS codespace: an owned game (Darkest Dungeon) and a free one the
 * account has (TF2) return an overview; a game the account does not have
 * returns nothing at all. The answer is only truthful BEFORE LumaDeck adds a
 * game: once SLSsteam lists it, Steam shows it as owned too (Brotato returned
 * an overview right after being added). So this is asked at Add time and the
 * backend records it; it is never re-derived later.
 *
 * Family-shared games also return an overview and count as owned here: Steam
 * downloads and updates them itself, so the DLC-only shape fits them too.
 */
export const isOwnedBySteam = (appid: number): boolean => {
  try {
    const store: any = (window as any).appStore;
    const overview = store?.GetAppOverviewByAppID?.(appid);
    return !!overview;
  } catch {
    return false;
  }
};
