import { Fragment, useEffect, useState } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  ToggleField,
  Field,
  Navigation,
  SidebarNavigation,
  ProgressBarWithInfo,
} from "@decky/ui";
import {
  FaInfoCircle,
  FaDownload,
  FaTrophy,
  FaTools,
  FaTrash,
  FaExclamationTriangle,
  FaCheckCircle,
  FaUsers,
} from "react-icons/fa";
import { toaster } from "@decky/api";
import { listLuatoolsFixes, downloadLuatoolsFix, selfHealAcfBuild } from "../api";
import { useLuatoolsConnect } from "../hooks/useLuatoolsConnect";
import { ActionButton } from "../components/ActionButton";
import { ROUTE_SETTINGS, SETTINGS_TAB_ACHIEVEMENTS, setPendingSettingsTab } from "../routes";
import { ACHIEVEMENTS_ENABLED } from "../features";
import {
  startDownload,
  getDownloadStatus,
  cancelDownload,
  hasLuatoolsForApp,
  getGameInstallPath,
  enableNativeOnline,
  disableNativeOnline,
  getNativeOnlineStatus,
  getApplyFixStatus,
  cancelApplyFix,
  getInstalledFixes,
  unfixGame,
  getUnfixStatus,
  applyLinuxNativeFix,
  computeFixLaunchOptions,
  uninstallGameFull,
  fetchAppName,
  repairAppmanifest,
  reconfigureSlssteam,
  checkStuckUpdates,
  pinGame,
  unpinGame,
  getPinStatus,
  checkGoldbergStatus,
  applyGoldberg,
  removeGoldberg,
  checkAchievementsStatus,
  generateAchievements,
  getGenerateStatus,
  checkSteamlessInstalled,
  downloadSteamless,
  getSteamlessDownloadStatus,
  runSteamless,
  getSteamlessStatus,
} from "../api";
import { useT } from "../i18n";

interface GameDetailProps {
  appid: number;
}

interface InstalledFix {
  date: string;
  fixType: string;
  filesCount: number;
  online?: boolean;
}

function formatSpeed(bytesPerSec: number): string {
  if (bytesPerSec < 1024) return `${bytesPerSec} B/s`;
  if (bytesPerSec < 1024 * 1024)
    return `${(bytesPerSec / 1024).toFixed(1)} KB/s`;
  return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

// LuaTools DenuvoFix shape (confirmed from the LuaTools .NET client's models):
//   { id, title, description, tags: [{ id, name, slug, color }],
//     hasFix, hasManifest, manifestFilename, fixFilename, createdAt }
// `tags` is a list of OBJECTS, so read their `name` — using the array directly
// renders "[object Object]".
function luaFixTagList(f: any): string[] {
  const tags = Array.isArray(f?.tags) ? f.tags : [];
  return tags
    .map((t: any) => (t && typeof t === "object" ? t.name : t))
    .filter((s: any) => typeof s === "string" && s.trim());
}

// A Denuvo fix's title is "Build <n>" — <n> being the target Steam build
// (e.g. "Build 23314029"). Anchor the match on the "Build " label so we never
// mistake another long number in the title/tags (a YYYYMMDD date, an appid —
// both also ~8 digits) for the build. The digit count stays open (\d{6,}) so a
// future 9-digit build still matches; the label, not the length, is the guard.
function luaFixBuildTag(f: any): string {
  const candidates = [f?.title, ...luaFixTagList(f)];
  for (const c of candidates) {
    const m = String(c ?? "").match(/\bBuild\s+(\d{6,})\b/i);
    if (m) return m[1];
  }
  return "";
}

export function GameDetail({ appid }: GameDetailProps) {
  const t = useT();
  const [gameName, setGameName] = useState(`Game ${appid}`);
  const [hasLua, setHasLua] = useState(false);
  const [installPath, setInstallPath] = useState("");
  const [gameSize, setGameSize] = useState(0);
  // Steam build id of what's on disk (0 = unknown). Compared against a fix's
  // required build tag to warn about a Denuvo build mismatch.
  const [installedBuild, setInstalledBuild] = useState(0);
  const [downloadState, setDownloadState] = useState<any>(null);
  // Native online (netsock): { enabled, netsockInstalled, hasAntiCheat }. null = not loaded.
  const [nativeOnline, setNativeOnline] = useState<any>(null);
  const [fixStatus, setFixStatus] = useState<any>(null);
  const [installedFixes, setInstalledFixes] = useState<InstalledFix[]>([]);
  // LuaTools catalogue fixes for this game (null = not loaded). The listing is
  // public; only applying a fix needs a connected account.
  const [luatoolsFixes, setLuatoolsFixes] = useState<any[] | null>(null);
  const [luatoolsError, setLuatoolsError] = useState<string>("");
  const [confirmUninstall, setConfirmUninstall] = useState(false);
  const [removeCompatdata, setRemoveCompatdata] = useState(false);
  const [isPinned, setIsPinned] = useState(false);
  const [isStuck, setIsStuck] = useState(false);
  const [goldbergApplied, setGoldbergApplied] = useState(false);
  const [achievementStatus, setAchievementStatus] = useState("");
  const [achievementGenState, setAchievementGenState] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [steamlessInstalled, setSteamlessInstalled] = useState(false);
  const [steamlessDotnet, setSteamlessDotnet] = useState(false);
  const [steamlessDownloadState, setSteamlessDownloadState] = useState<any>(null);
  const [steamlessState, setSteamlessState] = useState<any>(null);

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || gameName, duration });

  // Contextual LuaTools connect (shared with Settings). The catalogue listing is
  // public, but applying a fix needs a session — so we surface a connect prompt
  // here and grey out the fix buttons until connected.
  const {
    connected: luatoolsConnected,
    connecting: luatoolsConnecting,
    connect: handleConnectLuatools,
    refresh: refreshLuatoolsStatus,
  } = useLuatoolsConnect(toast, t);

  // "Actually downloaded" — a game can be ADDED (path reserved in the .acf)
  // without content on disk; the fix extracts INTO the game folder, so gate on
  // real bytes present, not just a resolved path. gameSize is the same
  // sizeOnDisk we already show in the header, so it's a reliable signal.
  const gameInstalled = !!installPath && gameSize > 0;

  const loadInstalledFixes = async () => {
    const result = await getInstalledFixes();
    if (result.success && result.fixes) {
      const gameFixes = result.fixes
        .filter((f: any) => f.appid === appid)
        .map((f: any) => ({
          date: f.date,
          fixType: f.fixType,
          filesCount: f.filesCount || 0,
        }));
      setInstalledFixes(gameFixes);
    }
  };

  // After a fix is applied OR removed, force Proton to load (or stop loading)
  // the fix's Windows DLLs by writing WINEDLLOVERRIDES into the game's launch
  // options. The backend derives the DLL list from the fix log and merges it
  // with any existing options; we write the result via SteamClient — the
  // reliable path the running Steam persists without a restart. Best-effort:
  // a failure here never blocks the fix flow (an exe-only fix needs nothing).
  const syncFixLaunchOptions = async () => {
    if (!installPath) return;
    try {
      const r: any = await computeFixLaunchOptions(appid, installPath);
      if (!r?.success) return;
      const sc: any = (window as any).SteamClient;
      if (sc?.Apps?.SetAppLaunchOptions) {
        sc.Apps.SetAppLaunchOptions(appid, r.launchOptions || "");
      }
    } catch {
      /* never block the fix flow on the override write */
    }
  };

  useEffect(() => {
    const load = async () => {

      // #21: flag if this game's last native Steam update is stuck on a
      // missing decryption key (new/rotated depot) so we can offer Fix Update.
      checkStuckUpdates().then((r) => {
        if (r.success && Array.isArray(r.stuck)) {
          setIsStuck(r.stuck.some((s: any) => s.appid === appid));
        }
      });

      const nameResult = await fetchAppName(appid);
      if (nameResult.success && nameResult.name) {
        setGameName(nameResult.name);
      }

      const luaResult = await hasLuatoolsForApp(appid);
      if (luaResult.success) setHasLua(luaResult.exists);

      const pathResult = await getGameInstallPath(appid);
      if (pathResult.success) {
        setInstallPath(pathResult.installPath || "");
        if (pathResult.sizeOnDisk) setGameSize(pathResult.sizeOnDisk);
        if (pathResult.buildid) setInstalledBuild(pathResult.buildid);

        if (pathResult.installPath) {
          const gbResult = await checkGoldbergStatus(pathResult.installPath);
          if (gbResult.success) setGoldbergApplied(gbResult.applied);
          getNativeOnlineStatus(appid, pathResult.installPath).then((r: any) => {
            if (r?.success) setNativeOnline(r);
          });
        }
      }

      const dlStatus = await getDownloadStatus(appid);
      if (
        dlStatus.success &&
        dlStatus.state &&
        Object.keys(dlStatus.state).length > 0
      ) {
        setDownloadState(dlStatus.state);
      }

      await loadInstalledFixes();

      const achResult = await checkAchievementsStatus(appid);
      if (achResult.success) {
        setAchievementStatus(achResult.status);
      }

      const slResult = await checkSteamlessInstalled();
      if (slResult.success) {
        setSteamlessInstalled(slResult.installed);
        setSteamlessDotnet(slResult.dotnetAvailable);
      }

      const pinResult = await getPinStatus(appid);
      if (pinResult.success) setIsPinned(pinResult.pinned);
};
    load();
  }, [appid]);

  // Poll download status
  useEffect(() => {
    if (
      !downloadState ||
      ["done", "failed", "cancelled"].includes(downloadState.status)
    ) {
      return;
    }
    const interval = setInterval(async () => {
      const status = await getDownloadStatus(appid);
      if (status.success && status.state) {
        setDownloadState(status.state);
        if (status.state.status === "done") {
          setHasLua(true);
          toast(t("toastDownloadComplete"), gameName);
        } else if (status.state.status === "failed") {
          toast(t("toastDownloadFailed"), status.state.error || gameName, 5000);
        }
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [downloadState, appid, t]);

  // Poll fix status
  useEffect(() => {
    if (
      !fixStatus ||
      ["done", "failed", "cancelled"].includes(fixStatus.status)
    ) {
      return;
    }
    const interval = setInterval(async () => {
      const status = await getApplyFixStatus(appid);
      if (status.success && status.state) {
        setFixStatus(status.state);
        if (status.state.status === "done") {
          toast(t("toastSuccess"), gameName);
          loadInstalledFixes();
          syncFixLaunchOptions();
        } else if (status.state.status === "failed") {
          toast(t("toastError"), status.state.error || gameName, 5000);
        }
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [fixStatus, appid]);

  // Poll achievement generation status
  useEffect(() => {
    if (achievementStatus !== "generating") return;
    const interval = setInterval(async () => {
      const status = await getGenerateStatus(appid);
      if (status.success && status.state) {
        setAchievementGenState(status.state);
        if (status.state.status === "done") {
          setAchievementStatus("generated");
          toast(t("toastAchievementsGenerated"), gameName);
        } else if (status.state.status === "error") {
          setAchievementStatus("ready");
          toast(t("toastAchievementsFailed"), status.state.error || gameName, 5000);
        }
      }
    }, 1500);
    return () => clearInterval(interval);
  }, [achievementStatus, appid]);

  // Poll Steamless download
  useEffect(() => {
    if (!steamlessDownloadState || steamlessDownloadState.status !== "downloading") return;
    const interval = setInterval(async () => {
      const status = await getSteamlessDownloadStatus();
      if (status.success && status.state) {
        setSteamlessDownloadState(status.state);
        if (status.state.status === "done") {
          setSteamlessInstalled(true);
          toast(t("steamlessDownloaded"), gameName);
        } else if (status.state.status === "error") {
          toast(t("toastError"), status.state.error || "", 5000);
        }
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [steamlessDownloadState]);

  // Poll Steamless status
  useEffect(() => {
    if (!steamlessState || steamlessState.status !== "running") return;
    const interval = setInterval(async () => {
      const status = await getSteamlessStatus();
      if (status.success && status.state) {
        setSteamlessState(status.state);
        if (status.state.status === "done") {
          const count = status.state.successCount || 0;
          const total = status.state.total || 0;
          if (count > 0) {
            toast(t("removeDrmDone", count, total), gameName);
          } else {
            toast(t("removeDrmNoDrm"), gameName, 4000);
          }
        }
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [steamlessState]);

  const doStartDownload = async (libraryPath: string = "") => {
    const result = await startDownload(appid, libraryPath);
    if (result.success) {
      setDownloadState({ status: "queued", bytesRead: 0, totalBytes: 0 });
      toast(t("toastDownloadStarted"), gameName, 2000);
    } else {
      toast(t("toastError"), result.error || t("failedToStartDownload"), 4000);
    }
  };

  const handleDownload = () => {
    // The backend ignores the install-library path (the manifest flow always
    // uses the default library), so there's no disk choice to make here.
    doStartDownload();
  };

  const handleCancel = async () => {
    await cancelDownload(appid);
    setDownloadState((prev: any) => ({ ...prev, status: "cancelled" }));
  };

  const handleToggleNativeOnline = async () => {
    if (!installPath) {
      toast(t("toastError"), t("installPathNotFound"), 4000);
      return;
    }
    const on = !!nativeOnline?.enabled;
    setBusy("nativeonline");
    // Enable = FakeAppId 480 + netsock marker (backend no-ops on anti-cheat /
    // missing netsock.so). Disable = drop the marker. Either way recompute the
    // launch options so the LD_AUDIT is added or stripped.
    const result = on
      ? await disableNativeOnline(appid, installPath)
      : await enableNativeOnline(appid, installPath);
    setBusy("");
    if (result.success) {
      setNativeOnline((p: any) => ({ ...(p || {}), enabled: !on }));
      await syncFixLaunchOptions();
      toast(on ? t("nativeOnlineOffToast") : t("nativeOnlineOnToast"), gameName);
    } else {
      toast(t("toastError"), result.error || "", 5000);
    }
  };

  const handleCheckFixes = async () => {
    setBusy("fixes");
    setLuatoolsError("");
    refreshLuatoolsStatus(); // in case the account was connected from Settings meanwhile
    // The LuaTools catalogue is the only fix source now. Its listing is public
    // (no login needed) — the same data the lua.tools/fixes/<appid> web page shows;
    // a connected account is only needed to actually apply/download a fix.
    try {
      // Guard against the backend HTTP call hanging (or the bridge rejecting):
      // race a hard 20s timeout so the button never stays stuck on "checking".
      const r: any = await Promise.race([
        listLuatoolsFixes(appid),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error("timeout")), 20000)),
      ]);
      if (r?.success) {
        const list = r.fixes || [];
        setLuatoolsFixes(list);
        // Self-heal: after a manifest-fix downgrade Steam re-stamps the .acf
        // buildid to the LATEST build even though the content is the older fix
        // build (the manifest is the true signal, the buildid lies). If the game
        // is pinned to an UNAMBIGUOUS single manifest build, ask the backend to
        // fix the buildid — it only writes when the installed depot manifest
        // matches the pin, so it never labels the game a build it isn't on.
        try {
          const mBuilds = new Set(
            list
              .filter((f: any) => f?.hasManifest)
              .map((f: any) => luaFixBuildTag(f))
              .filter(Boolean),
          );
          if (mBuilds.size === 1) {
            const y = Number([...mBuilds][0]);
            const heal: any = await selfHealAcfBuild(appid, y);
            if (heal?.success && heal?.healed) setInstalledBuild(y);
          }
        } catch {
          /* best-effort; never block the fix listing */
        }
        toast(list.length ? t("toastFixesFound") : t("toastNoFixes"), gameName);
      } else {
        setLuatoolsFixes([]);
        setLuatoolsError(r?.error || "unknown_error");
        toast(t("toastError"), r?.error || t("failedToCheck"), 4000);
      }
    } catch {
      setLuatoolsFixes([]);
      setLuatoolsError("request_failed");
      toast(t("toastError"), t("failedToCheck"), 4000);
    } finally {
      setBusy("");
    }
  };

  const handleApplyLuatoolsFix = async (fixId: string) => {
    if (!installPath) {
      toast(t("toastError"), t("installPathNotFound"), 4000);
      return;
    }
    // slot="fix" downloads the crack zip (vs "manifest"); download_luatools_fix
    // resolves the signed URL server-side and hands it to the same apply pipeline
    // as applyGameFix, so the existing fixStatus polling and progress UI cover it.
    const result = await downloadLuatoolsFix(appid, fixId, installPath, "fix");
    if (result.success) {
      setFixStatus({ status: "queued" });
      // netsock + 480 are applied by the backend during extraction — but ONLY when
      // the fix is a real online fix (its zip ships an OnlineFix.ini with a
      // FakeAppId). Denuvo / single-player cracks have no such .ini, so they get
      // neither. Nothing to do here; the existing syncFixLaunchOptions on "done"
      // emits the LD_AUDIT if the backend set the marker.
    } else {
      toast(t("toastError"), result.error || "", 5000);
    }
  };

  const handleInstallManifest = async (fixId: string) => {
    // slot="manifest" needs no install path — it pins the build via SLSsteam
    // ManifestIds and Steam (re)downloads it, so it works whether the game is
    // already installed (a downgrade) or not (a fresh install at that build).
    // The user must restart Steam MANUALLY; we never auto-restart.
    setBusy("manifest");
    const r: any = await downloadLuatoolsFix(appid, fixId, installPath, "manifest");
    setBusy("");
    if (r?.success) {
      toast("Compatible version set", "Restart Steam, re-download the game, then apply the fix.", 6000);
    } else {
      toast(t("toastError"), r?.error || "", 5000);
    }
  };

  const handleCancelFix = async () => {
    await cancelApplyFix(appid);
    setFixStatus((prev: any) => ({ ...prev, status: "cancelled" }));
  };

  const handleRemoveFix = async (fixDate?: string) => {
    setBusy("unfix");
    toast(t("toastFixRemoving"), gameName, 2000);
    const result = await unfixGame(appid, installPath, fixDate || "");
    if (result.success) {
      // Poll unfix status
      const poll = setInterval(async () => {
        const status = await getUnfixStatus(appid);
        if (status.success && status.state) {
          if (status.state.status === "done") {
            clearInterval(poll);
            setBusy("");
            toast(t("toastFixRemoved", status.state.filesRemoved || 0), gameName);
            loadInstalledFixes();
            syncFixLaunchOptions();
          } else if (status.state.status === "failed") {
            clearInterval(poll);
            setBusy("");
            toast(t("toastError"), status.state.error || "", 4000);
          }
        }
      }, 500);
      // Safety timeout
      setTimeout(() => { clearInterval(poll); setBusy(""); }, 30000);
    } else {
      setBusy("");
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleNativeFix = async () => {
    if (!installPath) {
      toast(t("toastError"), t("installPathNotFound"), 4000);
      return;
    }
    const result = await applyLinuxNativeFix(installPath);
    if (result.success) {
      toast(t("toastNativeFixApplied", result.count || 0), gameName);
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleTogglePin = async () => {
    const result = isPinned ? await unpinGame(appid) : await pinGame(appid);
    if (result.success) {
      setIsPinned(!isPinned);
      toast(isPinned ? t("toastUnpinned") : t("toastPinned"), gameName);
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleToggleGoldberg = async () => {
    if (!installPath) {
      toast(t("toastError"), t("installPathNotFound"), 4000);
      return;
    }
    if (goldbergApplied) {
      setBusy("goldberg");
      const result = await removeGoldberg(installPath, appid);
      setBusy("");
      if (result.success) {
        setGoldbergApplied(false);
        toast(t("toastGoldbergRemoved"), gameName);
      } else {
        toast(t("toastError"), result.message || result.error || "", 4000);
      }
    } else {
      setBusy("goldberg");
      const result = await applyGoldberg(installPath, appid);
      setBusy("");
      if (result.success) {
        setGoldbergApplied(true);
        toast(t("toastGoldbergApplied"), gameName);
      } else {
        toast(t("toastError"), result.message || result.error || "", 4000);
      }
    }
  };

  const handleGenerateAchievements = async () => {
    const result = await generateAchievements(appid);
    if (result.success) {
      setAchievementStatus("generating");
      setAchievementGenState({ status: "running", progress: "Starting..." });
    } else {
      toast(t("toastError"), result.error || t("toastAchievementsFailed"), 4000);
    }
  };

  const handleDownloadSteamless = async () => {
    const result = await downloadSteamless();
    if (result.success) {
      setSteamlessDownloadState({ status: "downloading", progress: "Starting..." });
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleRunSteamless = async () => {
    if (!installPath) {
      toast(t("toastError"), t("installPathNotFound"), 4000);
      return;
    }
    const result = await runSteamless(installPath);
    if (result.success) {
      setSteamlessState({ status: "running", total: result.total, processed: 0, current: "" });
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleReconfigureSls = async () => {
    setBusy("sls_reconfig");
    const result = await reconfigureSlssteam(appid);
    setBusy("");
    if (result.success) {
      toast(t("toastSlsReconfigured"), gameName);
    } else {
      toast(t("toastError"), result.error || "Failed", 4000);
    }
  };

  const handleRepairAcf = async () => {
    setBusy("acf");
    const result = await repairAppmanifest(appid);
    setBusy("");
    if (result.success) {
      toast(t("toastAcfRepaired"), gameName);
    } else {
      toast(t("toastError"), result.error || t("repairFailed"), 4000);
    }
  };

  const handleUninstall = async () => {
    if (!confirmUninstall) {
      setConfirmUninstall(true);
      setTimeout(() => setConfirmUninstall(false), 5000);
      return;
    }
    setConfirmUninstall(false);
    setBusy("uninstall");
    const result = await uninstallGameFull(appid, removeCompatdata);
    setBusy("");
    if (result.success) {
      setHasLua(false);
      const removed = result.removed || [];
      const hasFiles = removed.includes("game_files");
      const errors = result.errors || [];
      if (errors.length > 0) {
        toast(t("toastUninstalled"), t("uninstallWarnings", errors.join(", ")), 5000);
      } else if (!hasFiles) {
        toast(t("toastUninstalled"), t("configRemoved"));
      } else {
        toast(t("toastUninstalled"), t("gameFullyUninstalled"));
      }
      setTimeout(() => Navigation.NavigateBack(), 1500);
    } else {
      toast(t("toastError"), result.error || t("failedToCheck"), 5000);
    }
  };

  const isDownloading =
    downloadState &&
    !["done", "failed", "cancelled", undefined].includes(downloadState.status);

  const isFixInProgress =
    fixStatus &&
    !["done", "failed", "cancelled"].includes(fixStatus.status);

  const fixStatusLabel = (() => {
    if (!fixStatus) return "";
    if (fixStatus.status === "downloading") return t("statusDownloading");
    if (fixStatus.status === "extracting") return t("extracting");
    if (fixStatus.status === "queued") return t("statusQueued");
    return fixStatus.status;
  })();

  // Download phase → human label. depot_download removed (dead DDL path).
  const dlStatusLabel = (() => {
    switch (downloadState?.status) {
      case "downloading": return t("statusDownloading");
      case "processing": return t("statusProcessing");
      case "configuring": return t("statusConfiguring");
      case "installing": return t("statusInstalling");
      case "queued": return t("statusQueued");
      case "restarting_steam": return t("statusRestartingSteam");
      case "checking": return `${t("statusChecking")} ${downloadState?.currentApi || ""}`.trim();
      default: return downloadState?.status || "";
    }
  })();

  // One native ProgressBarWithInfo replaces the old status <div> + custom
  // ProgressBar: API, phase label, byte counter and speed all ride in
  // sOperationText. Determinate only while a byte total exists (the downloading
  // phase); other phases (processing/installing/...) show an indeterminate bar.
  const dlDeterminate =
    downloadState?.status === "downloading" && downloadState?.totalBytes > 0;
  const dlOperationText = (() => {
    if (!downloadState) return "";
    const parts: string[] = [];
    if (downloadState.currentApi) parts.push(`API: ${downloadState.currentApi}`);
    if (dlStatusLabel) parts.push(dlStatusLabel);
    if (dlDeterminate)
      parts.push(`${formatSize(downloadState.bytesRead || 0)} / ${formatSize(downloadState.totalBytes)}`);
    if (downloadState.speed > 0) parts.push(formatSpeed(downloadState.speed));
    return parts.join(" · ");
  })();

  // A fix is "online" when the catalogue tags it so. Splits the catalogue: online
  // entries go to the Online Fixes tab, the rest stay in Fixes & Repairs.
  const isOnlineFix = (f: any) => luaFixTagList(f).some((tg: string) => /online/i.test(tg));
  const otherFixes = luatoolsFixes ? luatoolsFixes.filter((f: any) => !isOnlineFix(f)) : null;
  const onlineFixes = luatoolsFixes ? luatoolsFixes.filter((f: any) => isOnlineFix(f)) : null;

  // One catalogue entry (name + tags, version button, apply-fix button). Shared by
  // both catalogue tabs.
  const renderFixEntry = (f: any) => {
    const canApply = gameInstalled && luatoolsConnected;
    const canInstallVersion = luatoolsConnected;
    const busyManifest = busy === "manifest";
    const buildTag = luaFixBuildTag(f);
    const onRequiredBuild = !!buildTag && String(installedBuild) === buildTag;
    const rawTitle = String(f?.title ?? "").trim();
    const fTags = luaFixTagList(f);
    const fixName = /^\d{6,}$/.test(rawTitle) ? `Build ${rawTitle}` : (rawTitle || fTags[0] || "Fix");
    const tagsSub = (rawTitle ? fTags : fTags.slice(1)).join(" · ");
    const buildNote = buildTag
      ? (installedBuild
          ? (onRequiredBuild
              ? `You're already on the build this fix needs (${buildTag})`
              : `⚠ This fix needs build ${buildTag}, you have ${installedBuild}. Install the compatible version first`)
          : `Needs build ${buildTag}`)
      : "";
    const manifestDesc = onRequiredBuild
      ? buildNote
      : [buildNote, "Sets the game to the build this fix needs. Restart Steam, (re)download the game, then apply the fix."]
          .filter(Boolean).join(". ");
    const applyDesc = (!f?.hasManifest ? buildNote : "") || undefined;
    return (
      <Fragment key={String(f.id)}>
        {(fixName || tagsSub) && (
          <PanelSectionRow>
            <Field label={fixName || undefined} description={tagsSub || undefined} />
          </PanelSectionRow>
        )}
        {f?.hasManifest && (
          <ActionButton
            label={busyManifest ? "Installing version…" : "Install the game version this fix needs"}
            description={manifestDesc}
            onClick={() => handleInstallManifest(String(f.id))}
            disabled={!canInstallVersion || busyManifest || !!isFixInProgress || onRequiredBuild}
          />
        )}
        {f?.hasFix !== false && (
          <ActionButton
            label="Apply fix"
            description={applyDesc}
            onClick={() => handleApplyLuatoolsFix(String(f.id))}
            disabled={!canApply || !!isFixInProgress || busyManifest}
          />
        )}
      </Fragment>
    );
  };

  // A LuaTools catalogue section: check button + login gate + the filtered entries.
  const renderCatalogueSection = (
    title: string, checkLabel: string, emptyText: string, filtered: any[] | null,
  ) => (
    <PanelSection title={title}>
      <ActionButton
        label={busy === "fixes" ? t("checkingForFixes") : checkLabel}
        onClick={handleCheckFixes}
        disabled={busy === "fixes"}
        description={
          !filtered ? undefined
            : filtered.length === 0
              ? (luatoolsError ? "Couldn't load fixes" : emptyText)
              : (luatoolsConnected && !gameInstalled)
                ? (filtered.some((f: any) => f?.hasManifest)
                    ? "Install the correct build first to apply a fix"
                    : "Install the game first to apply a fix")
                : undefined
        }
      />
      {filtered && (
        <>
          {filtered.length > 0 && !luatoolsConnected && (
            <>
              <PanelSectionRow>
                <Field description={
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                    <FaExclamationTriangle color="#ff8c00" style={{ flexShrink: 0 }} />
                    Log in with Discord to install versions and apply fixes
                  </span>
                } />
              </PanelSectionRow>
              <ActionButton
                label={luatoolsConnecting ? "Logging in…" : "Log in with Discord"}
                onClick={handleConnectLuatools}
                disabled={luatoolsConnecting}
              />
            </>
          )}
          {filtered.map(renderFixEntry)}
        </>
      )}
      {isFixInProgress && (
        <>
          <PanelSectionRow>
            <ProgressBarWithInfo
              indeterminate={!(fixStatus.totalBytes > 0)}
              nProgress={
                fixStatus.totalBytes > 0
                  ? Math.min(100, ((fixStatus.bytesRead || 0) / fixStatus.totalBytes) * 100)
                  : 0
              }
              sOperationText={fixStatusLabel}
            />
          </PanelSectionRow>
          <ActionButton label={t("cancelFix")} onClick={handleCancelFix} variant="danger" />
        </>
      )}
    </PanelSection>
  );

  // Installed fixes already applied to THIS game, filtered per tab (online vs not).
  // Per-fix removal only (a global "remove all" would cross the two tabs).
  const renderInstalledFixes = (list: InstalledFix[], title: string) => {
    if (list.length === 0) return null;
    return (
      <PanelSection title={title}>
        {list.map((fix, idx) => (
          <PanelSectionRow key={`i-${idx}`}>
            <Field
              label={`${fix.fixType} · ${t("fixFiles", fix.filesCount)}`}
              description={t("fixApplied", fix.date)}
            />
          </PanelSectionRow>
        ))}
        {list.length === 1 ? (
          <ActionButton
            label={busy === "unfix" ? t("toastFixRemoving") : t("removeFix")}
            onClick={() => handleRemoveFix(list[0].date)}
            variant="danger"
            disabled={busy === "unfix"}
          />
        ) : (
          list.map((fix, idx) => (
            <ActionButton
              key={`r-${idx}`}
              label={busy === "unfix" ? t("toastFixRemoving") : `${t("removeFix")} · ${fix.fixType}`}
              onClick={() => handleRemoveFix(fix.date)}
              variant="danger"
              disabled={busy === "unfix"}
            />
          ))
        )}
      </PanelSection>
    );
  };

  const pages = [
    {
      title: t("gameStatus"),
      icon: <FaInfoCircle />,
      hideTitle: true,
      content: (
        <>
      {/* No section title — the game name is already the page title
          (SidebarNavigation title={gameName}), so a gameName section header
          duplicated it. AppID + status now share one row: the AppID (a technical
          literal, used as-is across the codebase) labels the row, the install
          status is the row's coloured value, and the install path rides along as
          the muted description sub-line. Status only shows while the game has a
          lua config — the only time hasLua is false is the ~1.5s flash after
          Uninstall before the page navigates back. */}
      <PanelSection>
        <PanelSectionRow>
          <Field label={`AppID ${appid}`} description={installPath || undefined}>
            {hasLua && (
              <span style={{ color: installPath ? "#00cc00" : "#ffaa00" }}>
                {installPath ? t("installed") : t("manifestOnly")}
                {gameSize > 0 && ` · ${formatSize(gameSize)}`}
              </span>
            )}
          </Field>
        </PanelSectionRow>
      </PanelSection>
        </>
      ),
    },
    {
      title: t("updates"),
      icon: <FaDownload />,
      hideTitle: true,
      content: (
        <>
      {/* No section title — the sidebar tab ("Updates") already names it. This
          tab is version/manifest management (pin, re-fetch, stuck-update fix);
          the actual game files download natively in Steam. */}
      <PanelSection>
        {isDownloading ? (
          <>
            {/* Native progress bar: phase/API/bytes/speed in sOperationText.
                Indeterminate for phases without a measurable byte total. */}
            <PanelSectionRow>
              <ProgressBarWithInfo
                indeterminate={!dlDeterminate}
                nProgress={
                  dlDeterminate
                    ? Math.min(100, ((downloadState.bytesRead || 0) / downloadState.totalBytes) * 100)
                    : 0
                }
                sOperationText={dlOperationText}
              />
            </PanelSectionRow>
            <ActionButton
              label={t("cancelDownload")}
              onClick={handleCancel}
              variant="danger"
            />
          </>
        ) : (
          <>
            <ActionButton
              label={hasLua ? t("redownloadManifest") : t("downloadManifest")}
              onClick={handleDownload}
            />
            {hasLua && installPath ? (
              <PanelSectionRow>
                <ToggleField
                  label={t("autoUpdate")}
                  checked={!isPinned}
                  onChange={() => handleTogglePin()}
                  description={
                    isPinned ? t("pinnedToCurrentDesc") : t("autoUpdateDesc")
                  }
                />
              </PanelSectionRow>
            ) : null}
            {/* Stuck update → one native actionable row (warning icon + Fix
                Update). No "open game" button: we're already in GameDetail. */}
            {isStuck && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  icon={<FaExclamationTriangle color="#ff8c00" />}
                  label={t("stuckUpdateTitle")}
                  description={`${t("stuckUpdateBody")} ${t("stuckUpdateKeyHint")}`}
                  onClick={handleDownload}
                >
                  {t("fixUpdate")}
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        )}
        {downloadState?.status === "done" && (
          <PanelSectionRow>
            <Field label={t("download")}>
              <span style={{ color: "#00cc00" }}>{t("doneRestartSteam")}</span>
            </Field>
          </PanelSectionRow>
        )}
        {/* Hubcap key expired → native actionable row that navigates to the
            Hubcap key in Settings. */}
        {downloadState?.status === "failed" &&
          downloadState.errorCode === "hubcap_key_expired" && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                icon={<FaExclamationTriangle color="#ff8c00" />}
                label={t("hubcapKeyExpiredTitle")}
                description={t("hubcapKeyExpiredBody")}
                onClick={() => Navigation.Navigate(ROUTE_SETTINGS)}
              >
                {t("hubcapKeyExpiredButton")}
              </ButtonItem>
            </PanelSectionRow>
          )}
        {downloadState?.status === "failed" &&
          downloadState.errorCode !== "hubcap_key_expired" && (
            <PanelSectionRow>
              <Field
                icon={<FaExclamationTriangle color="#ff4444" />}
                label={t("downloadFailed")}
                description={downloadState.error || undefined}
              />
            </PanelSectionRow>
          )}
      </PanelSection>
        </>
      ),
    },
    ...(ACHIEVEMENTS_ENABLED ? [{
      title: t("achievements"),
      icon: <FaTrophy />,
      hideTitle: true,
      content: (
        <>
      {/* Achievements */}
      <PanelSection title={t("achievements")}>
        {achievementStatus === "not_configured" ? (
          <>
            {/* Global setup (the Steam Web API key) lives on the Achievements
                tab in Settings. Show why it's not ready and send the user there. */}
            <PanelSectionRow>
              <Field
                icon={<FaExclamationTriangle color="#ffaa00" />}
                label={t("achievementStatusNotConfigured")}
              />
            </PanelSectionRow>
            <ActionButton
              label={t("openAchievements")}
              onClick={() => {
                setPendingSettingsTab(SETTINGS_TAB_ACHIEVEMENTS);
                Navigation.Navigate(ROUTE_SETTINGS);
              }}
            />
          </>
        ) : achievementStatus === "generating" ? (
          <PanelSectionRow>
            <Field label={achievementGenState?.progress || t("achievementStatusGenerating")} />
          </PanelSectionRow>
        ) : achievementStatus === "generated" ? (
          <>
            <PanelSectionRow>
              <Field
                icon={<FaCheckCircle color="#00cc00" />}
                label={t("achievementStatusGenerated")}
              />
            </PanelSectionRow>
            <ActionButton
              label={t("generateAchievements")}
              onClick={handleGenerateAchievements}
            />
          </>
        ) : achievementStatus === "ready" ? (
          <>
            <PanelSectionRow>
              <Field label={t("achievementStatusReady")} />
            </PanelSectionRow>
            <ActionButton
              label={t("generateAchievements")}
              onClick={handleGenerateAchievements}
            />
          </>
        ) : null}
      </PanelSection>
        </>
      ),
    }] : []),
    {
      title: t("fixesAndRepairs"),
      icon: <FaTools />,
      hideTitle: true,
      content: (
        <>
      {/* Fixes & Repairs: the NON-online LuaTools catalogue (crack / Denuvo — the
          online ones live in the Online Fixes tab), then Steamless / Goldberg, then
          Repairs. Each keeps its own title. */}
      {renderCatalogueSection("LuaTools Fixes", t("checkForFixes"), t("noOtherFixes"), otherFixes)}

      {/* Installed non-online fixes applied to THIS game (online ones show in the
          Online Fixes tab). Shown directly under the catalogue they came from. */}
      {renderInstalledFixes(installedFixes.filter((f) => !f.online), "Installed LuaTools Fixes")}

      {/* Fixes — Steamless (DRM strip) and Goldberg (Steam-API emulator). These
          are cracks applied to the installed game, distinct from the LuaTools
          catalogue above and the install/account Repairs below. */}
      <PanelSection title={t("fixes")}>
        {!steamlessInstalled ? (
          <ActionButton
            label={
              steamlessDownloadState?.status === "downloading"
                ? t("downloadingSteamless")
                : t("downloadSteamless")
            }
            onClick={handleDownloadSteamless}
            disabled={steamlessDownloadState?.status === "downloading" || !steamlessDotnet}
            description={
              !steamlessDotnet
                ? t("steamlessDotnetRequired")
                : (steamlessDownloadState?.progress || t("removeDrmSteamlessDesc"))
            }
          />
        ) : installPath ? (
          <ActionButton
            label={
              steamlessState?.status === "running"
                ? t("removeDrmRunning", steamlessState.processed || 0, steamlessState.total || 0)
                : t("removeDrmSteamless")
            }
            onClick={handleRunSteamless}
            disabled={steamlessState?.status === "running"}
            description={
              steamlessState?.status === "done"
                ? t("removeDrmDone", steamlessState.successCount || 0, steamlessState.total || 0)
                : t("removeDrmSteamlessDesc")
            }
          />
        ) : null}
        {/* Goldberg — moved here from Game Management (it's a crack: replaces
            steam_api with the emulator). Intentionally NOT wired to the
            WINEDLLOVERRIDES override: it's an in-place steam_api64 replacement
            that Proton loads without forcing. */}
        {installPath && (
          <ActionButton
            label={
              busy === "goldberg"
                ? (goldbergApplied ? t("removingGoldberg") : t("applyingGoldberg"))
                : (goldbergApplied ? t("removeGoldberg") : t("applyGoldberg"))
            }
            onClick={handleToggleGoldberg}
            disabled={busy === "goldberg"}
            description={
              goldbergApplied
                ? t("restoreOriginalDlls")
                : t("replaceWithGoldberg")
            }
          />
        )}
      </PanelSection>

      {/* Repairs — install/account plumbing, NOT game cracks. Kept in a
          separate block so the symptom is clear (these don't make a game
          launch; they fix permissions / SLSsteam config / Steam bookkeeping). */}
      <PanelSection title={t("repairs")}>
        <ActionButton
          label={t("applyLinuxNativeFix")}
          description={t("applyLinuxNativeFixDesc")}
          onClick={handleNativeFix}
        />
        <ActionButton
          label={busy === "sls_reconfig" ? t("reconfiguringSls") : t("reconfigureSls")}
          onClick={handleReconfigureSls}
          disabled={busy === "sls_reconfig"}
          description={t("reconfigureSlsDesc")}
        />
        <ActionButton
          label={busy === "acf" ? t("repairingAcf") : t("repairAppmanifest")}
          onClick={handleRepairAcf}
          disabled={busy === "acf"}
          description={t("regeneratesAcf")}
        />
      </PanelSection>
        </>
      ),
    },
    {
      title: t("onlineFixesTab"),
      icon: <FaUsers />,
      hideTitle: true,
      content: (
        <>
      {/* Online fixes: the online LuaTools catalogue, then the online fixes already
          installed on THIS game, then the crack-free native route (480 + netsock). */}
      {renderCatalogueSection(t("luatoolsOnlineFixes"), t("checkForOnlineFixes"), t("noOnlineFixes"), onlineFixes)}

      {renderInstalledFixes(installedFixes.filter((f) => f.online), "Installed Online Fixes")}

      <PanelSection title={t("nativeOnline")}>
        <ActionButton
          label={
            busy === "nativeonline"
              ? (nativeOnline?.enabled ? t("nativeOnlineDisabling") : t("nativeOnlineEnabling"))
              : (nativeOnline?.enabled ? t("nativeOnlineDisable") : t("nativeOnlineEnable"))
          }
          onClick={handleToggleNativeOnline}
          disabled={
            busy === "nativeonline"
            || !installPath
            || !!nativeOnline?.hasAntiCheat
            || (nativeOnline && !nativeOnline.netsockInstalled)
          }
          description={
            nativeOnline?.hasAntiCheat
              ? t("nativeOnlineAntiCheat")
              : (nativeOnline && !nativeOnline.netsockInstalled)
                ? t("nativeOnlineNoLib")
                : t("nativeOnlineDesc")
          }
        />
      </PanelSection>
        </>
      ),
    },
    {
      title: t("dangerZone"),
      icon: <FaTrash />,
      hideTitle: true,
      content: (
        <>
      {/* Uninstall */}
      <PanelSection>
        {/* What will be removed — native Field (label + "·" list), ⚠ red icon
            for the destructive signal. The hand-bordered red box is gone, and
            the section title too (it just restated the sidebar tab); the danger
            button + two-tap confirm + the ⚠ "Permanently removes:" field carry
            the severity. (DESIGN_UI.md §8f.) */}
        <PanelSectionRow>
          <Field
            icon={<FaExclamationTriangle color="#e07070" />}
            label={t("uninstallWillRemove")}
            description={[
              t("uninstallItemFiles"),
              t("uninstallItemLua"),
              t("uninstallItemManifest"),
              t("uninstallItemDepots"),
              t("uninstallItemSteamConfig"),
              t("uninstallItemKeys"),
              t("uninstallItemAchievements"),
            ].join(" · ")}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label={t("removeProtonPrefix")}
            description={t("deleteCompatdata")}
            checked={removeCompatdata}
            onChange={setRemoveCompatdata}
          />
        </PanelSectionRow>

        <ActionButton
          label={
            busy === "uninstall"
              ? t("uninstalling")
              : confirmUninstall
                ? t("confirmFullUninstall")
                : t("fullUninstall")
          }
          onClick={handleUninstall}
          variant="danger"
          disabled={busy === "uninstall"}
          description={confirmUninstall ? t("clickToConfirm") : undefined}
        />
      </PanelSection>
        </>
      ),
    },
  ];

  return <SidebarNavigation title={gameName} pages={pages} />;
}
