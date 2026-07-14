/**
 * Backend API wrapper — calls Python methods via Decky's serverAPI.
 *
 * Every backend method returns a JSON string.
 * parseResult() deserialises it for the caller.
 */
import { call } from "@decky/api";

function parseResult<T = any>(raw: string): T {
  try {
    return JSON.parse(raw);
  } catch {
    return { success: false, error: "Failed to parse response" } as any;
  }
}

// Platform
export const getPlatformSummary = async () =>
  parseResult(await call<[], string>("get_platform_summary"));

export const verifySlssteamInjected = async () =>
  parseResult(await call<[], string>("verify_slssteam_injected"));

export const getInjectionStatus = async () =>
  parseResult(await call<[], string>("get_injection_status"));

export const checkSlssteamHashStatus = async () =>
  parseResult(await call<[], string>("check_slssteam_hash_status"));

// Resolved SLSsteam state for the UI. Canonical state set (shared by all three
// components). Returns:
//   { state: "not_installed"|"not_loaded"|"not_injected"|"not_supported"|"healthy",
//     cause: null|"version"|"hooks", action: null|"install"|"restart"|"downgrade" }
export const getSlssteamHealth = async () =>
  parseResult(await call<[], string>("get_slssteam_health"));

// Resolved lumalinux state for the UI. Returns:
//   { state: "not_installed"|"not_loaded"|"not_injected"|"not_supported"|"healthy",
//     cause: null|"version"|"hooks", version: null|string,
//     action: null|"install"|"restart"|"downgrade" }
export const getLumalinuxHealth = async () =>
  parseResult(await call<[], string>("get_lumalinux_health"));

// Resolved CloudRedirect state for the UI. Adds two CR-only states (not_authed,
// disabled) to the canonical set. Returns:
//   { state: "not_installed"|"disabled"|"not_loaded"|"not_injected"|"not_supported"|"not_authed"|"healthy",
//     cause: null|"version"|"hooks", version: null|string,
//     action: null|"install"|"restart"|"downgrade"|"configure_desktop" }
export const getCloudredirectHealth = async () =>
  parseResult(await call<[], string>("get_cloudredirect_health"));

// { installed, latest, has_update, url } — GitHub Releases, cached 6h.
export const checkCloudredirectUpdate = async () =>
  parseResult(await call<[], string>("check_cloudredirect_update"));

export const checkLumalinuxUpdate = async () =>
  parseResult(await call<[], string>("check_lumalinux_update"));

export const checkHeadcrabCompat = async () =>
  parseResult(await call<[], string>("check_headcrab_compat"));

// Unified component status (DESIGN_UI.md "Component model"): one call returns
// per-component { installed, health, cause, action, update:{installed,latest,
// available} } for slssteam/cloudredirect/lumalinux, plus headcrab {compatible,
// target, current} and plugin {installed,latest,available}.
export const getComponentsStatus = async (force = false) =>
  parseResult(await call<[boolean], string>("get_components_status", force));

export const repairSlssteamHeadcrab = async () =>
  parseResult(await call<[], string>("repair_slssteam_headcrab"));

export const restartSteam = async () =>
  parseResult(await call<[], string>("restart_steam"));

// API Manifest
export const fetchFreeApisNow = async () =>
  parseResult(await call<[], string>("fetch_free_apis_now"));

export const saveRyuCookie = async (cookie: string) =>
  parseResult(await call<[string], string>("save_ryu_cookie", cookie));

export const loadRyuCookie = async () =>
  parseResult(await call<[], string>("load_ryu_cookie"));

// #22: auto-import the Ryuu session cookie from Steam's CEF browser cookie
// store (no DevTools / copy-paste) -> { success, message? , error? }.
export const importRyuuCookieFromBrowser = async () =>
  parseResult(await call<[], string>("import_ryuu_cookie_from_browser"));

export const updateHubcapKey = async (key: string) =>
  parseResult(await call<[string], string>("update_hubcap_key", key));

export const loadHubcapKey = async () =>
  parseResult(await call<[], string>("load_hubcap_key"));

export const searchHubcap = async (query: string) =>
  parseResult(await call<[string], string>("search_hubcap", query));

// Hubcap key + Ryuu cookie expiry for the UI. Returns
//   { success, hubcap: {state, days_left, expires_at, daily_usage, daily_limit},
//              ryuu:   {state, days_left, expires_at} }
// where state ∈ "none"|"unknown"|"ok"|"soon"|"expired". Hubcap expiry comes from
// the free /user/stats endpoint (no quota); Ryuu from the import-time sidecar.
export const getCredentialStatus = async () =>
  parseResult(await call<[], string>("get_credential_status"));

// Dev-only state overrides (preview harness — see backend/dev.py).
export const getDevState = async () =>
  parseResult(await call<[], string>("dev_get_state"));
export const setDevState = async (key: string, value: string) =>
  parseResult(await call<[string, string], string>("dev_set_state", key, value));
export const clearDevState = async () =>
  parseResult(await call<[], string>("dev_clear_state"));

// In-plugin self-update (#23). checkPluginUpdate → { has_update, installed,
// latest, download_url }; updatePlugin downloads + applies the latest release.
export const checkPluginUpdate = async () =>
  parseResult(await call<[], string>("check_plugin_update"));

export const updatePlugin = async () =>
  parseResult(await call<[], string>("update_plugin"));

// Downloads the latest LumaDeck.zip into ~/Downloads (deck-writable) so the
// user installs it via Decky ▸ Developer ▸ Install from Zip. The in-place
// updatePlugin can't write the root-owned plugin dir on most setups; this is
// the reliable path. Returns { downloaded, path, latest }.
export const downloadUpdateToDownloads = async () =>
  parseResult(await call<[], string>("download_update_to_downloads"));

// Per-game pin (auto-update toggle). pinGame freezes the game at its installed
// version; unpinGame returns it to auto-update; getPinStatus → { pinned, depots }.
export const pinGame = async (appid: number) =>
  parseResult(await call<[number], string>("pin_game", appid));

export const unpinGame = async (appid: number) =>
  parseResult(await call<[number], string>("unpin_game", appid));

export const getPinStatus = async (appid: number) =>
  parseResult(await call<[number], string>("get_pin_status", appid));

// Downloads
export const startDownload = async (appid: number, targetLibraryPath: string = "") =>
  parseResult(await call<[number, string], string>("start_download", appid, targetLibraryPath));

// #21 watchdog: installed lua games whose native Steam update is stuck on a
// missing decryption key (new/rotated depot) → { stuck: [{appid, name}] }.
export const checkStuckUpdates = async () =>
  parseResult(await call<[], string>("check_stuck_updates"));

export const getDownloadStatus = async (appid: number) =>
  parseResult(await call<[number], string>("get_download_status", appid));

export const getActiveDownloads = async () =>
  parseResult(await call<[], string>("get_active_downloads"));

export const cancelDownload = async (appid: number) =>
  parseResult(await call<[number], string>("cancel_download", appid));

export const hasLuatoolsForApp = async (appid: number) =>
  parseResult(await call<[number], string>("has_luatools_for_app", appid));

export const deleteLuatoolsForApp = async (appid: number) =>
  parseResult(await call<[number], string>("delete_luatools_for_app", appid));

export const getInstalledLuaScripts = async () =>
  parseResult(await call<[], string>("get_installed_lua_scripts"));

export const fetchAppName = async (appid: number) =>
  parseResult(await call<[number], string>("fetch_app_name", appid));

export const getGameNotices = async (appid: number) =>
  parseResult(await call<[number], string>("get_game_notices", appid));

// Steam Utils
export const getGameInstallPath = async (appid: number) =>
  parseResult(await call<[number], string>("get_game_install_path", appid));

export const getSteamLibraries = async () =>
  parseResult(await call<[], string>("get_steam_libraries"));

// SLSsteam Operations
export const addFakeAppId = async (appid: number, fakeId: number = 480) =>
  parseResult(
    await call<[number, number], string>("add_fake_app_id", appid, fakeId),
  );

export const removeFakeAppId = async (appid: number) =>
  parseResult(await call<[number], string>("remove_fake_app_id", appid));

export const checkFakeAppIdStatus = async (appid: number) =>
  parseResult(await call<[number], string>("check_fake_app_id_status", appid));

export const listFakeAppIds = async () =>
  parseResult(await call<[], string>("list_fake_app_ids"));

export const listAdditionalApps = async () =>
  parseResult(await call<[], string>("list_additional_apps"));

export const addToAdditionalApps = async (appid: number) =>
  parseResult(await call<[number], string>("add_to_additional_apps", appid));

export const removeFromAdditionalApps = async (appid: number) =>
  parseResult(await call<[number], string>("remove_from_additional_apps", appid));

export const addGameToken = async (appid: number) =>
  parseResult(await call<[number], string>("add_game_token", appid));

export const removeGameToken = async (appid: number) =>
  parseResult(await call<[number], string>("remove_game_token", appid));

export const checkGameTokenStatus = async (appid: number) =>
  parseResult(await call<[number], string>("check_game_token_status", appid));

export const addGameDlcs = async (appid: number) =>
  parseResult(await call<[number], string>("add_game_dlcs", appid));

export const removeGameDlcs = async (appid: number) =>
  parseResult(await call<[number], string>("remove_game_dlcs", appid));

export const checkGameDlcsStatus = async (appid: number) =>
  parseResult(await call<[number], string>("check_game_dlcs_status", appid));

export const uninstallGameFull = async (
  appid: number,
  removeCompatdata: boolean = false,
) =>
  parseResult(
    await call<[number, boolean], string>(
      "uninstall_game_full",
      appid,
      removeCompatdata,
    ),
  );

// Goldberg Steam Emulator
export const checkGoldbergStatus = async (installPath: string) =>
  parseResult(
    await call<[string], string>("check_goldberg_status", installPath),
  );

export const applyGoldberg = async (installPath: string, appid: number) =>
  parseResult(
    await call<[string, number], string>("apply_goldberg", installPath, appid),
  );

export const removeGoldberg = async (installPath: string, appid: number) =>
  parseResult(
    await call<[string, number], string>("remove_goldberg", installPath, appid),
  );

// Achievements (Steam Web API)
export const getApiKeyStatus = async () =>
  parseResult(await call<[], string>("get_api_key_status"));

export const setSteamApiKey = async (key: string) =>
  parseResult(await call<[string], string>("set_steam_api_key", key));

export const checkAchievementsStatus = async (appid: number) =>
  parseResult(await call<[number], string>("check_achievements_status", appid));

export const generateAchievements = async (appid: number) =>
  parseResult(await call<[number], string>("generate_achievements", appid));

export const getGenerateStatus = async (appid: number) =>
  parseResult(await call<[number], string>("get_generate_status", appid));

export const checkAllAchievementsStatus = async (appids: number[]) =>
  parseResult(await call<[number[]], string>("check_all_achievements_status", appids));

export const generateAllAchievements = async (appids: number[]) =>
  parseResult(await call<[number[]], string>("generate_all_achievements", appids));

export const getSyncAllStatus = async () =>
  parseResult(await call<[], string>("get_sync_all_status"));

// Fixes
export const checkForFixes = async (appid: number) =>
  parseResult(await call<[number], string>("check_for_fixes", appid));

export const applyGameFix = async (
  appid: number,
  downloadUrl: string,
  installPath: string,
  fixType: string,
  gameName: string,
) =>
  parseResult(
    await call<[number, string, string, string, string], string>(
      "apply_game_fix",
      appid,
      downloadUrl,
      installPath,
      fixType,
      gameName,
    ),
  );

export const getApplyFixStatus = async (appid: number) =>
  parseResult(await call<[number], string>("get_apply_fix_status", appid));

export const cancelApplyFix = async (appid: number) =>
  parseResult(await call<[number], string>("cancel_apply_fix", appid));

export const getInstalledFixes = async () =>
  parseResult(await call<[], string>("get_installed_fixes"));

export const unfixGame = async (
  appid: number,
  installPath: string = "",
  fixDate: string = "",
) =>
  parseResult(
    await call<[number, string, string], string>(
      "unfix_game",
      appid,
      installPath,
      fixDate,
    ),
  );

export const getUnfixStatus = async (appid: number) =>
  parseResult(await call<[number], string>("get_unfix_status", appid));

export const applyLinuxNativeFix = async (installPath: string) =>
  parseResult(
    await call<[string], string>("apply_linux_native_fix", installPath),
  );

// Compute the launch-options string to write after applying/removing a fix:
// the game's current options merged with the WINEDLLOVERRIDES for the DLLs the
// installed fixes dropped (empty list -> override stripped). The frontend writes
// the returned string via SteamClient.Apps.SetAppLaunchOptions.
export const computeFixLaunchOptions = async (appid: number, installPath: string) =>
  parseResult(
    await call<[number, string], string>("compute_fix_launch_options", appid, installPath),
  );

// Workshop
export const startWorkshopDownload = async (appid: number, pubfileId: number, targetLibraryPath: string = "") =>
  parseResult(
    await call<[number, number, string], string>(
      "start_workshop_download",
      appid,
      pubfileId,
      targetLibraryPath,
    ),
  );

export const getWorkshopDownloadStatus = async () =>
  parseResult(await call<[], string>("get_workshop_download_status"));

export const cancelWorkshopDownload = async () =>
  parseResult(await call<[], string>("cancel_workshop_download"));

// Repair / Maintenance
export const repairAppmanifest = async (appid: number) =>
  parseResult(await call<[number], string>("repair_appmanifest", appid));
export const reconfigureSlssteam = async (appid: number) =>
  parseResult(await call<[number], string>("reconfigure_slssteam", appid));

// Steamless DRM Removal
export const checkSteamlessInstalled = async () =>
  parseResult(await call<[], string>("check_steamless_installed"));

export const downloadSteamless = async () =>
  parseResult(await call<[], string>("download_steamless"));

export const getSteamlessDownloadStatus = async () =>
  parseResult(await call<[], string>("get_steamless_download_status"));

export const runSteamless = async (installPath: string) =>
  parseResult(await call<[string], string>("run_steamless", installPath));

export const getSteamlessStatus = async () =>
  parseResult(await call<[], string>("get_steamless_status"));

// Store AppID Detection
export const detectStoreAppid = async () =>
  parseResult(await call<[], string>("detect_store_appid"));

// Dependencies
export const checkDependencies = async () =>
  parseResult(await call<[], string>("check_dependencies"));

export const installLumalinux = async () =>
  parseResult(await call<[], string>("install_lumalinux"));

export const getLlInstallStatus = async () =>
  parseResult(await call<[], string>("get_ll_install_status"));

// Quick Install — chains dependencies → CloudRedirect → lumalinux in order.
export const quickInstall = async () =>
  parseResult(await call<[], string>("quick_install"));

export const getQuickInstallStatus = async () =>
  parseResult(await call<[], string>("get_quick_install_status"));

// Re-inject every INSTALLED component into steam.sh in dependency order
// (SLSsteam → CloudRedirect → lumalinux). Used to repair injection without the
// shared-steam.sh cascade wiping the other components. Poll
// getQuickInstallStatus() for progress (it shares the same state).
export const reinjectInstalled = async () =>
  parseResult(await call<[], string>("reinject_installed"));

// Cascade-safe install/repair/update for one component (or "core"). op is
// install|repair|update (same mechanics, differs only in trigger/label). Poll
// getQuickInstallStatus for progress. See DESIGN_UI.md "Component model".
export const applyComponent = async (
  componentId: "slssteam" | "cloudredirect" | "lumalinux" | "core",
  op: "install" | "repair" | "update" = "repair",
) => parseResult(await call<[string, string], string>("apply_component", componentId, op));

// REAL Desktop hand-off: headcrab Steam downgrade + lumalinux re-inject.
// Arms a one-shot autostart + switches to Desktop; returns to Game Mode on success.
export const runDesktopHandoffReal = async () =>
  parseResult(await call<[], string>("run_desktop_handoff_real"));

// Desktop hand-off that runs the FULL Quick Install (deps + CR + lumalinux,
// incl. the Steam downgrade) in Desktop, then returns to Game Mode on success.
// For a fresh Deck whose Steam is newer than the headcrab pin.
export const runDesktopHandoffQuickInstall = async () =>
  parseResult(await call<[], string>("run_desktop_handoff_quick_install"));
