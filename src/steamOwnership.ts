/**
 * Does the account own this game, according to Steam's own UI? A HINT for
 * the page ("you already own this game"); the backend decides on its own
 * from Steam's package cache (backend/steam_licenses.py), which SLSsteam's
 * `SubscriptionTimestamps` setting cannot fake and whose format is known.
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
 * Family-shared games: whether they carry rt_purchased_time is NOT measured
 * yet. If they do not, they take the normal add path (today's behaviour).
 */
export const isOwnedBySteam = (appid: number): boolean => {
  try {
    const store: any = (window as any).appStore;
    const overview = store?.GetAppOverviewByAppID?.(appid);
    if (!overview) return false;
    // A real licence carries its purchase time (Darkest Dungeon 2018, TF2
    // 2010, measured); an app SLSsteam merely lists has an overview but no
    // rt_purchased_time (Brotato right after being added, measured). This is
    // what keeps a game added by ANOTHER tool (ASSella, SLSDeck, a hand-edited
    // AdditionalApps) from passing as owned. The backend adds its own checks.
    const purchased = Number(overview.rt_purchased_time || 0);
    return purchased > 0;
  } catch {
    return false;
  }
};

/**
 * Does Steam's client know this app at all (it has a library entry, owned or
 * merely listed by SLSsteam)? Any overview counts, unlike isOwnedBySteam. Used
 * to show "Open in Steam library": the library page needs an entry to show,
 * and a game added a moment ago has one only once SLSsteam's hot reload (or a
 * restart) put it there.
 */
export const isInSteamLibrary = (appid: number): boolean => {
  try {
    const store: any = (window as any).appStore;
    return !!store?.GetAppOverviewByAppID?.(appid);
  } catch {
    return false;
  }
};

/** Steam's own library page for an app (the one the library grid opens). */
export const steamLibraryRoute = (appid: number): string => `/library/app/${appid}`;
