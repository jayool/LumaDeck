// Steam's client-side library model, as the page reads it through
// window.appStore. isOwnedBySteam needs a purchase time (a real licence);
// isInSteamLibrary takes any entry (an app SLSsteam merely lists too), which is
// what gates "Open in Steam library" on the game page.
import { afterEach, describe, expect, it } from "vitest";
import { isInSteamLibrary, isOwnedBySteam, steamLibraryRoute } from "./steamOwnership";

const withStore = (overviews: Record<number, any>) => {
  (globalThis as any).window = (globalThis as any).window || {};
  (window as any).appStore = { GetAppOverviewByAppID: (id: number) => overviews[id] };
};

afterEach(() => { delete (window as any).appStore; });

describe("steam library model", () => {
  it("an app with an entry is in the library, owned only with a purchase time", () => {
    withStore({ 1942280: { rt_purchased_time: 0 }, 262060: { rt_purchased_time: 1514764800 } });
    expect(isInSteamLibrary(1942280)).toBe(true);
    expect(isOwnedBySteam(1942280)).toBe(false);
    expect(isInSteamLibrary(262060)).toBe(true);
    expect(isOwnedBySteam(262060)).toBe(true);
  });
  it("an app Steam does not list is neither", () => {
    withStore({});
    expect(isInSteamLibrary(480)).toBe(false);
    expect(isOwnedBySteam(480)).toBe(false);
  });
  it("no appStore at all (outside Steam) answers false, never throws", () => {
    expect(isInSteamLibrary(480)).toBe(false);
  });
  it("the library route is Steam's own app page", () => {
    expect(steamLibraryRoute(1942280)).toBe("/library/app/1942280");
  });
});
