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

// Resolved SLSsteam state for the UI. Returns:
//   { state: "not_installed"|"not_active"|"injection_missing"|"broken"|"healthy",
//     cause: null|"patterns"|"hash", action: null|"install"|"restart"|"repair" }
export const getSlssteamHealth = async () =>
  parseResult(await call<[], string>("get_slssteam_health"));

export const checkHeadcrabCompat = async () =>
  parseResult(await call<[], string>("check_headcrab_compat"));

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

export const updateHubcapKey = async (key: string) =>
  parseResult(await call<[string], string>("update_hubcap_key", key));

export const loadHubcapKey = async () =>
  parseResult(await call<[], string>("load_hubcap_key"));

export const searchHubcap = async (query: string) =>
  parseResult(await call<[string], string>("search_hubcap", query));

export const checkGameUpdate = async (appid: number) =>
  parseResult(await call<[number], string>("check_game_update", appid));

// Downloads
export const startDownload = async (appid: number, targetLibraryPath: string = "") =>
  parseResult(await call<[number, string], string>("start_download", appid, targetLibraryPath));

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

export const getSlsPlayStatus = async () =>
  parseResult(await call<[], string>("get_sls_play_status"));

export const setSlsPlayStatus = async (enabled: boolean) =>
  parseResult(await call<[boolean], string>("set_sls_play_status", enabled));

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

// Achievements (SLScheevo)
export const checkSlscheevoInstalled = async () =>
  parseResult(await call<[], string>("check_slscheevo_installed"));

export const checkAchievementsStatus = async (appid: number) =>
  parseResult(await call<[number], string>("check_achievements_status", appid));

export const generateAchievements = async (appid: number) =>
  parseResult(await call<[number], string>("generate_achievements", appid));

export const getGenerateStatus = async (appid: number) =>
  parseResult(await call<[number], string>("get_generate_status", appid));

export const downloadSlscheevo = async () =>
  parseResult(await call<[], string>("download_slscheevo"));

export const getSlscheevoDownloadStatus = async () =>
  parseResult(await call<[], string>("get_slscheevo_download_status"));

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

export const installDependencies = async () =>
  parseResult(await call<[], string>("install_dependencies"));

export const installCloudredirect = async () =>
  parseResult(await call<[], string>("install_cloudredirect"));

export const getCrInstallStatus = async () =>
  parseResult(await call<[], string>("get_cr_install_status"));

export const installLumalinux = async () =>
  parseResult(await call<[], string>("install_lumalinux"));

export const getLlInstallStatus = async () =>
  parseResult(await call<[], string>("get_ll_install_status"));
