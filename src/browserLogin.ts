import { Navigation } from "@decky/ui";

/**
 * Close the Game-Mode login browser opened via Navigation.NavigateToExternalWeb.
 *
 * The external browser is the `/externalweb` route on the MAIN window's backstack
 * (GamepadUIMainWindowInstance), sitting on top of the route the login was
 * launched from. A single NavigateBack() on that instance pops it and lands back
 * exactly where the user was, with no history pollution (verified on-device). We
 * reach the instance through the SteamUIStore global because the decky
 * Router.WindowStore path didn't resolve reliably; fall back to the decky global.
 *
 * Shared by the LuaTools and Ryuu login flows so their close behaviour can't drift.
 */
export function closeLoginBrowser(): void {
  const inst = (window as any)?.SteamUIStore?.WindowStore
    ?.GamepadUIMainWindowInstance;
  if (inst?.NavigateBack) inst.NavigateBack();
  else Navigation.NavigateBack();
}
