import { useEffect, useState } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  TextField,
  ToggleField,
  Field,
  Navigation,
  SidebarNavigation,
  ProgressBarWithInfo,
} from "@decky/ui";
import {
  FaInfoCircle,
  FaDownload,
  FaCog,
  FaTrophy,
  FaTools,
  FaTrash,
  FaExclamationTriangle,
} from "react-icons/fa";
import { toaster } from "@decky/api";
import { ProgressBar } from "../components/ProgressBar";
import { ActionButton } from "../components/ActionButton";
import { ROUTE_SETTINGS } from "../routes";
import {
  startDownload,
  getDownloadStatus,
  cancelDownload,
  hasLuatoolsForApp,
  getGameInstallPath,
  addFakeAppId,
  removeFakeAppId,
  checkFakeAppIdStatus,
  addGameToken,
  removeGameToken,
  checkGameTokenStatus,
  addGameDlcs,
  removeGameDlcs,
  checkGameDlcsStatus,
  checkForFixes,
  applyGameFix,
  getApplyFixStatus,
  cancelApplyFix,
  getInstalledFixes,
  unfixGame,
  getUnfixStatus,
  applyLinuxNativeFix,
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
  downloadSlscheevo,
  getSlscheevoDownloadStatus,
  getSteamLibraries,
  checkSteamlessInstalled,
  downloadSteamless,
  getSteamlessDownloadStatus,
  runSteamless,
  getSteamlessStatus,
} from "../api";
import { useT } from "../i18n";
import { showLibraryPicker } from "../components/LibraryPickerModal";

interface GameDetailProps {
  appid: number;
}

interface InstalledFix {
  date: string;
  fixType: string;
  filesCount: number;
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

export function GameDetail({ appid }: GameDetailProps) {
  const t = useT();
  const [gameName, setGameName] = useState(`Game ${appid}`);
  const [hasLua, setHasLua] = useState(false);
  const [installPath, setInstallPath] = useState("");
  const [gameSize, setGameSize] = useState(0);
  const [downloadState, setDownloadState] = useState<any>(null);
  const [fakeAppId, setFakeAppId] = useState(false);
  const [fakeIdValue, setFakeIdValue] = useState("480");
  const [hasToken, setHasToken] = useState(false);
  const [hasDlcs, setHasDlcs] = useState(false);
  const [dlcCount, setDlcCount] = useState(0);
  const [fixes, setFixes] = useState<any>(null);
  const [fixStatus, setFixStatus] = useState<any>(null);
  const [installedFixes, setInstalledFixes] = useState<InstalledFix[]>([]);
  const [confirmUninstall, setConfirmUninstall] = useState(false);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const [removeCompatdata, setRemoveCompatdata] = useState(false);
  const [isPinned, setIsPinned] = useState(false);
  const [isStuck, setIsStuck] = useState(false);
  const [goldbergApplied, setGoldbergApplied] = useState(false);
  const [achievementStatus, setAchievementStatus] = useState("");
  const [achievementGenState, setAchievementGenState] = useState<any>(null);
  const [slscheevoBinaryPath, setSlscheevoBinaryPath] = useState("");
  const [busy, setBusy] = useState("");
  const [steamlessInstalled, setSteamlessInstalled] = useState(false);
  const [steamlessDotnet, setSteamlessDotnet] = useState(false);
  const [steamlessDownloadState, setSteamlessDownloadState] = useState<any>(null);
  const [steamlessState, setSteamlessState] = useState<any>(null);
  const [steamLibraries, setSteamLibraries] = useState<any[]>([]);

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || gameName, duration });

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

  useEffect(() => {
    const load = async () => {
      // Load libraries immediately so the picker is ready before user clicks
      getSteamLibraries().then((libResult) => {
        if (libResult.success && libResult.libraries) {
          setSteamLibraries(libResult.libraries);
        }
      });

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

        if (pathResult.installPath) {
          const gbResult = await checkGoldbergStatus(pathResult.installPath);
          if (gbResult.success) setGoldbergApplied(gbResult.applied);
        }
      }

      const fakeResult = await checkFakeAppIdStatus(appid);
      if (fakeResult.success) setFakeAppId(fakeResult.exists);

      const tokenResult = await checkGameTokenStatus(appid);
      if (tokenResult.success) setHasToken(tokenResult.exists);

      const dlcResult = await checkGameDlcsStatus(appid);
      if (dlcResult.success) {
        setHasDlcs(dlcResult.exists);
        if (dlcResult.count) setDlcCount(dlcResult.count);
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
        if (achResult.binaryPath) setSlscheevoBinaryPath(achResult.binaryPath);
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
    if (!installPath && steamLibraries.length > 1) {
      showLibraryPicker(steamLibraries, (libraryPath) => {
        doStartDownload(libraryPath);
      });
      return;
    }
    doStartDownload();
  };

  const handleCancel = async () => {
    await cancelDownload(appid);
    setDownloadState((prev: any) => ({ ...prev, status: "cancelled" }));
  };

  const handleToggleFakeAppId = async () => {
    if (fakeAppId) {
      await removeFakeAppId(appid);
      setFakeAppId(false);
      toast(t("toastFakeAppIdRemoved"), gameName);
    } else {
      const id = parseInt(fakeIdValue, 10) || 480;
      const result = await addFakeAppId(appid, id);
      if (result.success) {
        setFakeAppId(true);
        toast(t("toastFakeAppIdAdded", id), gameName);
      } else {
        toast(t("toastError"), result.message || result.error || "", 4000);
      }
    }
  };

  const handleToggleToken = async () => {
    if (hasToken) {
      await removeGameToken(appid);
      setHasToken(false);
      toast(t("toastTokenRemoved"), gameName);
    } else {
      const result = await addGameToken(appid);
      if (result.success) {
        setHasToken(true);
        toast(t("toastTokenAdded"), gameName);
      } else {
        toast(t("toastError"), result.message || result.error || "", 4000);
      }
    }
  };

  const handleToggleDlcs = async () => {
    if (hasDlcs) {
      await removeGameDlcs(appid);
      setHasDlcs(false);
      setDlcCount(0);
      toast(t("toastDlcsRemoved"), gameName);
    } else {
      setBusy("dlcs");
      toast(t("fetchingDlcs"), gameName, 2000);
      const result = await addGameDlcs(appid);
      setBusy("");
      if (result.success) {
        if (result.skipped) {
          setHasDlcs(false);
          toast(t("toastDlcsNoneFound"), gameName, 4000);
        } else {
          setHasDlcs(true);
          if (result.count) setDlcCount(result.count);
          toast(t("toastDlcsAdded", result.count || 0), gameName);
        }
      } else {
        toast(t("toastError"), result.message || result.error || "", 4000);
      }
    }
  };

  const handleCheckFixes = async () => {
    setBusy("fixes");
    const result = await checkForFixes(appid);
    setBusy("");
    if (result.success) {
      setFixes(result);
      const hasAny = result.genericFix?.available || result.onlineFix?.available;
      toast(
        hasAny ? t("toastFixesFound") : t("toastNoFixes"),
        gameName,
      );
    } else {
      toast(t("toastError"), result.error || t("failedToCheck"), 4000);
    }
  };

  const handleApplyFix = async (url: string, fixType: string) => {
    if (!installPath) {
      toast(t("toastError"), t("installPathNotFound"), 4000);
      return;
    }
    const result = await applyGameFix(
      appid,
      url,
      installPath,
      fixType,
      gameName,
    );
    if (result.success) {
      setFixStatus({ status: "queued" });
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

  const handleDownloadSlscheevo = async () => {
    setBusy("slscheevo");
    const result = await downloadSlscheevo();
    if (result.success) {
      const poll = setInterval(async () => {
        const status = await getSlscheevoDownloadStatus();
        if (status.success && status.state) {
          if (status.state.status === "done") {
            clearInterval(poll);
            setBusy("");
            // Refresh status to get binaryPath
            const achResult = await checkAchievementsStatus(appid);
            if (achResult.success) {
              setAchievementStatus(achResult.status);
              if (achResult.binaryPath) setSlscheevoBinaryPath(achResult.binaryPath);
            } else {
              setAchievementStatus("not_configured");
            }
            toast(t("toastSlscheevoInstalled"), gameName);
          } else if (status.state.status === "error") {
            clearInterval(poll);
            setBusy("");
            toast(t("toastSlscheevoDownloadFailed"), status.state.error || "", 5000);
          }
        }
      }, 1000);
      setTimeout(() => { clearInterval(poll); setBusy(""); }, 120000);
    } else {
      setBusy("");
      toast(t("toastError"), result.error || "", 4000);
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
      setFakeAppId(false);
      setHasToken(false);
      setHasDlcs(false);
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

  const dlcLabel = hasDlcs
    ? `${t("removeDlcs")}${dlcCount > 0 ? ` (${dlcCount})` : ""}`
    : `${t("addDlcs")}${dlcCount > 0 ? ` (${dlcCount} ${t("found")})` : ""}`;

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

  const pages = [
    {
      title: t("gameStatus"),
      icon: <FaInfoCircle />,
      hideTitle: true,
      content: (
        <>
      <PanelSection title={gameName}>
        <PanelSectionRow>
          {/* AppID is a technical identifier, used as a literal across the
              codebase (GameCard, search results) — not display prose. */}
          <Field label="AppID">{appid}</Field>
        </PanelSectionRow>
        {/* Status only renders while the game still has a lua config. Every
            game reachable here has one (you arrive from My Games); the only
            time hasLua is false is the ~1.5s flash after Uninstall before the
            page navigates back — so there's no "not installed" state to show. */}
        {hasLua && (
          <PanelSectionRow>
            {/* Status value carries the state colour; the install path (when
                present) rides along as the Field's muted description sub-line. */}
            <Field label={t("gameStatus")} description={installPath || undefined}>
              <span style={{ color: installPath ? "#00cc00" : "#ffaa00" }}>
                {installPath ? t("installed") : t("manifestOnly")}
                {gameSize > 0 && ` — ${formatSize(gameSize)}`}
              </span>
            </Field>
          </PanelSectionRow>
        )}
      </PanelSection>
        </>
      ),
    },
    {
      title: t("download"),
      icon: <FaDownload />,
      hideTitle: true,
      content: (
        <>
      <PanelSection title={t("download")}>
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
              variant="primary"
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
              <span style={{ color: "#00cc00" }}>{t("downloadComplete")}</span>
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
    {
      title: t("gameManagement"),
      icon: <FaCog />,
      hideTitle: true,
      content: (
        <>
      {/* Game Management */}
      <PanelSection title={t("gameManagement")}>
        <PanelSectionRow>
          <ToggleField
            label={t("advancedOptions")}
            checked={showAdvancedOptions}
            onChange={setShowAdvancedOptions}
            description={t("gameManagement")}
          />
        </PanelSectionRow>

        {showAdvancedOptions && (
          <>
            <PanelSectionRow>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <div style={{ flex: 1 }}>
                  <TextField
                    label="FakeAppId"
                    value={fakeIdValue}
                    onChange={(e: any) => setFakeIdValue(e?.target?.value ?? "480")}
                    disabled={fakeAppId}
                  />
                </div>
              </div>
            </PanelSectionRow>
            <ActionButton
              label={
                fakeAppId
                  ? `${t("removeFakeAppId")} (${fakeIdValue})`
                  : `${t("addFakeAppId")} (${fakeIdValue})`
              }
              onClick={handleToggleFakeAppId}
            />
            <ActionButton
              label={hasToken ? t("removeToken") : t("addToken")}
              onClick={handleToggleToken}
            />
            <ActionButton
              label={busy === "dlcs" ? t("fetchingDlcs") : dlcLabel}
              onClick={handleToggleDlcs}
              disabled={busy === "dlcs"}
            />
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
          </>
        )}
      </PanelSection>
        </>
      ),
    },
    {
      title: t("achievements"),
      icon: <FaTrophy />,
      hideTitle: true,
      content: (
        <>
      {/* Achievements */}
      <PanelSection title={t("achievements")}>
        {achievementStatus === "not_installed" ? (
          <>
            <PanelSectionRow>
              <div style={{ fontSize: "12px", color: "#8b929a" }}>
                {t("achievementStatusNotInstalled")}
              </div>
            </PanelSectionRow>
            <ActionButton
              label={busy === "slscheevo" ? t("downloadingSlscheevo") : t("downloadSlscheevo")}
              onClick={handleDownloadSlscheevo}
              disabled={busy === "slscheevo"}
            />
          </>
        ) : achievementStatus === "not_configured" ? (
          <>
            <PanelSectionRow>
              <div style={{ fontSize: "12px", color: "#ffaa00" }}>
                {t("achievementStatusNotConfigured")}
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <div style={{ fontSize: "11px", color: "#8b929a" }}>
                {t("slscheevoRunInTerminal")}
              </div>
            </PanelSectionRow>
            {slscheevoBinaryPath && (
              <PanelSectionRow>
                <div style={{
                  fontSize: "10px",
                  color: "#b8bcbf",
                  fontFamily: "monospace",
                  background: "#1a1d23",
                  padding: "6px 8px",
                  borderRadius: "4px",
                  wordBreak: "break-all",
                }}>
                  {t("slscheevoPath",
                    slscheevoBinaryPath.substring(0, slscheevoBinaryPath.lastIndexOf("/")),
                    slscheevoBinaryPath.substring(slscheevoBinaryPath.lastIndexOf("/") + 1),
                  )}
                </div>
              </PanelSectionRow>
            )}
          </>
        ) : achievementStatus === "generating" ? (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", color: "#1a9fff" }}>
              {achievementGenState?.progress || t("achievementStatusGenerating")}
            </div>
          </PanelSectionRow>
        ) : achievementStatus === "generated" ? (
          <>
            <PanelSectionRow>
              <div style={{ fontSize: "12px", color: "#00cc00" }}>
                {t("achievementStatusGenerated")}
              </div>
            </PanelSectionRow>
            <ActionButton
              label={t("generateAchievements")}
              onClick={handleGenerateAchievements}
              description={t("achievementStatusGenerated")}
            />
          </>
        ) : achievementStatus === "ready" ? (
          <>
            <PanelSectionRow>
              <div style={{ fontSize: "12px", color: "#dcdedf" }}>
                {t("achievementStatusReady")}
              </div>
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
    },
    {
      title: t("fixes"),
      icon: <FaTools />,
      hideTitle: true,
      content: (
        <>
      {/* Fixes */}
      <PanelSection title={t("fixes")}>
        <ActionButton
          label={busy === "fixes" ? t("checkingForFixes") : t("checkForFixes")}
          onClick={handleCheckFixes}
          disabled={busy === "fixes"}
        />
        {fixes && (
          <>
            {fixes.genericFix?.available && (
              <ActionButton
                label={t("applyGenericFix")}
                onClick={() =>
                  handleApplyFix(fixes.genericFix.url, "Generic Fix")
                }
                variant="primary"
                disabled={!!isFixInProgress}
              />
            )}
            {fixes.onlineFix?.available && (
              <ActionButton
                label={t("applyOnlineFix")}
                onClick={() =>
                  handleApplyFix(fixes.onlineFix.url, "Online Fix (Unsteam)")
                }
                variant="primary"
                disabled={!!isFixInProgress}
              />
            )}
            {!fixes.genericFix?.available && !fixes.onlineFix?.available && (
              <PanelSectionRow>
                <div style={{ color: "#8b929a", fontSize: "12px" }}>
                  {t("noFixesAvailable")}
                </div>
              </PanelSectionRow>
            )}
          </>
        )}
        {isFixInProgress && (
          <>
            <PanelSectionRow>
              <ProgressBar
                value={fixStatus.bytesRead || 0}
                max={fixStatus.totalBytes || 1}
                label={fixStatusLabel}
              />
            </PanelSectionRow>
            <ActionButton
              label={t("cancelFix")}
              onClick={handleCancelFix}
              variant="danger"
            />
          </>
        )}
        <ActionButton
          label={t("applyLinuxNativeFix")}
          onClick={handleNativeFix}
        />
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

      {/* Installed Fixes */}
      {installedFixes.length > 0 && (
        <PanelSection title={t("installedFixes")}>
          {installedFixes.map((fix, idx) => (
            <PanelSectionRow key={idx}>
              <div>
                <div style={{ fontSize: "12px", color: "#dcdedf" }}>
                  {fix.fixType} — {t("fixFiles", fix.filesCount)}
                </div>
                <div style={{ fontSize: "11px", color: "#8b929a" }}>
                  {t("fixApplied", fix.date)}
                </div>
              </div>
            </PanelSectionRow>
          ))}
          {installedFixes.length === 1 ? (
            <ActionButton
              label={busy === "unfix" ? t("toastFixRemoving") : t("removeFix")}
              onClick={() => handleRemoveFix(installedFixes[0].date)}
              variant="danger"
              disabled={busy === "unfix"}
            />
          ) : (
            <>
              {installedFixes.map((fix, idx) => (
                <ActionButton
                  key={idx}
                  label={
                    busy === "unfix"
                      ? t("toastFixRemoving")
                      : `${t("removeFix")} — ${fix.fixType}`
                  }
                  onClick={() => handleRemoveFix(fix.date)}
                  variant="danger"
                  disabled={busy === "unfix"}
                />
              ))}
              <ActionButton
                label={busy === "unfix" ? t("toastFixRemoving") : t("removeAllFixes")}
                onClick={() => handleRemoveFix()}
                variant="danger"
                disabled={busy === "unfix"}
              />
            </>
          )}
        </PanelSection>
      )}
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
      <PanelSection title={t("dangerZone")}>
        {/* What will be removed */}
        <div style={{
          background: "rgba(220, 50, 50, 0.07)",
          border: "1px solid rgba(220, 50, 50, 0.25)",
          borderRadius: "6px",
          padding: "10px 14px",
          marginBottom: "4px",
        }}>
          <div style={{ fontSize: "11px", fontWeight: 600, color: "#e07070", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {t("uninstallWillRemove")}
          </div>
          {[
            t("uninstallItemFiles"),
            t("uninstallItemLua"),
            t("uninstallItemManifest"),
            t("uninstallItemDepots"),
            t("uninstallItemSteamConfig"),
            t("uninstallItemKeys"),
          ].map((item, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: "7px", fontSize: "12px", color: "#bbb", lineHeight: "1.9" }}>
              <span style={{ color: "#e07070", fontSize: "10px" }}>✕</span>
              {item}
            </div>
          ))}
        </div>

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
