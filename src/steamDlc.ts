/**
 * The tick box of a DLC in a game's properties (Steam's own DLC list), as
 * the client exposes it to its UI: SteamClient.Apps.SetDLCEnabled(app, dlc,
 * enabled). Measured 2026-10-06 (Darkest Dungeon):
 *
 *   false → Steam deletes the DLC's files with its own depotcache manifests
 *           (it needs the depot key for that), unmounts the depots, rewrites
 *           the .acf; DisabledDLC lists the DLC.
 *   true  → clears DisabledDLC. Steam only downloads the DLC when it next
 *           plans the game, which for a licence lumalinux injected means its
 *           next start; while it runs it does not (an injected licence is
 *           not a licence list from the server). LumaDeck promises exactly
 *           that: "they install the next time Steam starts".
 *
 * Best-effort: every helper returns false when the client did not take the
 * call. The backend's own state is valid either way.
 */

const apps = (): any => (window as any).SteamClient?.Apps;

export const setDlcEnabled = (appid: number, dlc: number, enabled: boolean): boolean => {
  try {
    const fn = apps()?.SetDLCEnabled;
    if (typeof fn !== "function") return false;
    fn.call(apps(), appid, dlc, enabled);
    return true;
  } catch {
    return false;
  }
};

/** Untick every DLC. All or nothing: the first refusal stops the list and
 *  reports failure, so the caller leaves everything else untouched. */
export const disableDlcs = (appid: number, dlcs: number[]): boolean => {
  for (const dlc of dlcs) {
    if (!setDlcEnabled(appid, dlc, false)) return false;
  }
  return true;
};

/** Tick every DLC: clears the DisabledDLC mark a previous uninstall left,
 *  so Steam's next start installs them. Nothing to wait for. */
export const enableDlcs = (appid: number, dlcs: number[]): void => {
  for (const dlc of dlcs) setDlcEnabled(appid, dlc, true);
};
