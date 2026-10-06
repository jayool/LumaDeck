/**
 * The tick box of a DLC in a game's properties (Steam's own DLC list), as
 * the client exposes it to its UI: SteamClient.Apps.SetDLCEnabled(app, dlc,
 * enabled). It is the one lever that makes Steam re-plan an INSTALLED game's
 * depots while it runs (measured 2026-10-06, Darkest Dungeon):
 *
 *   false → "user config changed: removed depots": Steam deletes the DLC's
 *           files with its own depotcache manifests, unmounts the depots,
 *           rewrites the .acf (DisabledDLC lists the DLC).
 *   true  → clears DisabledDLC; "added depots" and a download if the account
 *           has (or lumalinux injected) a licence, nothing otherwise.
 *   A call that changes nothing (true on a DLC that was not unticked) does
 *   not make Steam plan at all — hence the false→true cycle on add.
 *
 * A licence appearing while Steam runs never triggers a plan on its own;
 * a Steam restart does. So every helper here is best-effort and returns
 * false when the client did not take the call: the backend's own state is
 * valid either way and a restart is the measured fallback.
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

/** Untick then re-tick every DLC: the user-config change that makes Steam
 *  plan an installed game and fetch DLC a licence just appeared for. Only
 *  for DLC Steam has NOT mounted (the backend filters): unticking a mounted
 *  one deletes its files. */
export const cycleDlcs = (appid: number, dlcs: number[]): boolean => {
  if (!disableDlcs(appid, dlcs)) return false;
  for (const dlc of dlcs) {
    if (!setDlcEnabled(appid, dlc, true)) return false;
  }
  return true;
};

/** After an owned add on an installed game: fetch the DLC to cycle from the
 *  backend (it withholds them until lumalinux has told the client about the
 *  new licence, answering {pending: true} meanwhile) and cycle them. Returns
 *  "none" (nothing to do), "ok" or "failed" (Steam did not take the call:
 *  the user restarts Steam, which plans the same thing at startup). */
export const runOwnedDlcCycle = async (
  appid: number,
  take: (appid: number) => Promise<any>,
): Promise<"none" | "ok" | "failed"> => {
  for (let i = 0; i < 30; i++) {
    let res: any;
    try {
      res = await take(appid);
    } catch {
      return "none";
    }
    if (!res?.success) return "none";
    if (res.pending) {
      await new Promise((r) => setTimeout(r, 1000));
      continue;
    }
    if (!res.dlc?.length) return "none";
    return cycleDlcs(appid, res.dlc) ? "ok" : "failed";
  }
  return "none";
};
