import { useEffect, useState, useCallback, useRef } from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  Navigation,
  Focusable,
  DialogButton,
} from "@decky/ui";
import { GameInfo } from "../components/GameCard";
import {
  getInstalledLuaScripts,
  getDownloadStatus,
  getActiveDownloads,
  startDownload,
  detectStoreAppid,
  searchHubcap,
  checkSlscheevoInstalled,
  checkAllAchievementsStatus,
  generateAllAchievements,
  getSyncAllStatus,
  getSteamLibraries,
  getGameNotices,
  restartSteam,
  getSlssteamHealth,
  getLumalinuxHealth,
  getCloudredirectHealth,
  checkCloudredirectUpdate,
  checkLumalinuxUpdate,
  checkPluginUpdate,
  checkStuckUpdates,
  getCredentialStatus,
  installLumalinux,
  installCloudredirect,
  checkHeadcrabCompat,
  quickInstall,
  getQuickInstallStatus,
} from "../api";
import { showLibraryPicker } from "../components/LibraryPickerModal";
import { Notice } from "../components/Notice";
import { HealthBanner, HealthProblem } from "../components/HealthBanner";
import { UpdatesBanner, UpdateNotice } from "../components/UpdatesBanner";
import { ROUTE_DOWNLOADS, ROUTE_LIBRARY } from "../routes";
import { setRefreshHandler } from "../refresh";
import { useT } from "../i18n";
import { toaster } from "@decky/api";

interface SearchResult {
  appid: number;
  name: string;
}

// ProtonDB compatibility tiers, colored medal-style (see DESIGN_UI.md palette).
const PROTONDB_TIER_COLOR: Record<string, string> = {
  platinum: "#5fd0e0",
  gold: "#c8a84b",
  silver: "#9aa4b2",
  bronze: "#c87a3a",
  borked: "#e06060",
};

export function GameList() {
  const t = useT();
  const [games, setGames] = useState<GameInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [addAppId, setAddAppId] = useState("");
  const [addStatus, setAddStatus] = useState("");
  const [activeDownloadId, setActiveDownloadId] = useState<number | null>(null);
  const [activeDownloadPhase, setActiveDownloadPhase] = useState("");
  const [downloadPct, setDownloadPct] = useState(0);
  const [downloadSpeed, setDownloadSpeed] = useState(0);
  const [downloadBytes, setDownloadBytes] = useState({ read: 0, total: 0 });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Hubcap search state
  const [searchQuery, setSearchQuery] = useState("");
  const [hubcapFocused, setHubcapFocused] = useState(false);
  // Which "add a game" mode the section shows: by AppID (default, autofilled
  // from the open store page) or by name (Hubcap search).
  const [addMode, setAddMode] = useState<"appid" | "name">("appid");
  // Key of the custom button (toggle / toolbar icon) currently focused, so we
  // can draw an explicit focus ring — overriding a DialogButton's background
  // hides its native focus highlight.
  const [focusedBtn, setFocusedBtn] = useState<string>("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [showMoreResults, setShowMoreResults] = useState(false);
  const [slscheevoReady, setSlscheevoReady] = useState(false);
  const [slssteamHealth, setSlssteamHealth] = useState<{
    state: string;
    cause: string | null;
    action: string | null;
  } | null>(null);
  const [lumalinuxHealth, setLumalinuxHealth] = useState<{
    state: string;
    cause: string | null;
    version: string | null;
    action: string | null;
  } | null>(null);
  const [crHealth, setCrHealth] = useState<{
    state: string;
    cause: string | null;
    version: string | null;
    action: string | null;
  } | null>(null);
  const [crUpdate, setCrUpdate] = useState<{
    installed: string | null;
    latest: string | null;
    has_update: boolean;
  } | null>(null);
  const [llUpdate, setLlUpdate] = useState<{
    installed: string | null;
    latest: string | null;
    has_update: boolean;
  } | null>(null);
  const [pluginUpdate, setPluginUpdate] = useState<{
    latest: string | null;
    has_update: boolean;
  } | null>(null);
  const [stuckUpdates, setStuckUpdates] = useState<{ appid: number; name: string }[]>([]);
  const [headcrabCompat, setHeadcrabCompat] = useState<{
    current_build: number | null;
    target: number | null;
    compatible: boolean;
  } | null>(null);
  const [restartingStream, setRestartingStream] = useState(false);
  const [reinstallingLL, setReinstallingLL] = useState(false);
  const [reinstallingCR, setReinstallingCR] = useState(false);
  const [quickInstalling, setQuickInstalling] = useState(false);
  const [confirmQuickInstall, setConfirmQuickInstall] = useState(false);
  const [quickProgress, setQuickProgress] = useState("");
  const [syncState, setSyncState] = useState<any>(null);
  const [steamLibraries, setSteamLibraries] = useState<any[]>([]);
  const [pendingNotices, setPendingNotices] = useState<string[]>([]);
  const [pendingGameInfo, setPendingGameInfo] = useState<any>(null);
  const [cred, setCred] = useState<any>(null);
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadGames = useCallback(async () => {
    try {
      const luaResult = await getInstalledLuaScripts();
      const gameList: GameInfo[] = [];

      if (luaResult.success && luaResult.scripts) {
        for (const s of luaResult.scripts) {
          gameList.push({
            appid: s.appid,
            name: s.gameName || `Unknown (${s.appid})`,
            hasLua: true,
            isDisabled: s.isDisabled,
            hasGameFiles: s.hasGameFiles,
          });
        }
      }

      // Check achievement status for all games
      const appids = gameList.map((g) => g.appid);
      if (appids.length > 0) {
        try {
          const achResult = await checkAllAchievementsStatus(appids);
          if (achResult.success && achResult.map) {
            for (const g of gameList) {
              g.hasAchievements = !!achResult.map[g.appid];
            }
          }
        } catch { }
      }

      gameList.sort((a, b) => a.name.localeCompare(b.name));
      setGames(gameList);
    } catch (err) {
      console.error("GameList: load error", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const formatStatus = useCallback(
    (st: any): string => {
      const phase = st.status || "unknown";
      if (phase === "downloading") {
        const total = st.totalBytes || 0;
        const read = st.bytesRead || 0;
        if (total > 0) {
          const pct = Math.round((read / total) * 100);
          return `${t("statusDownloading")} ${pct}%`;
        }
        const kb = Math.round(read / 1024);
        return `${t("statusDownloading")} ${kb} KB`;
      } else if (phase === "checking") {
        return `${t("statusChecking")} ${st.currentApi || "APIs"}...`;
      } else if (phase === "processing") {
        return t("statusProcessing");
      } else if (phase === "configuring") {
        return t("statusConfiguring");
      } else if (phase === "depot_download") {
        return `${t("statusDownloadingGame")}: ${st.depotProgress || t("statusDownloadingGameFiles")}`;
      } else if (phase === "installing") {
        return t("statusInstalling");
      } else if (phase === "queued") {
        return t("statusQueued");
      }
      return `${phase}...`;
    },
    [t],
  );

  const startPolling = useCallback(
    (id: number) => {
      if (pollRef.current) clearInterval(pollRef.current);
      setActiveDownloadId(id);

      pollRef.current = setInterval(async () => {
        try {
          const status = await getDownloadStatus(id);
          if (!status.success || !status.state) return;
          const st = status.state;
          const phase = st.status || "unknown";

          if (phase === "done") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setAddStatus(t("doneRestartSteam"));
            setActiveDownloadId(null);
            setActiveDownloadPhase("");
            setDownloadPct(0); setDownloadSpeed(0); setDownloadBytes({ read: 0, total: 0 });
            loadGames();
            setTimeout(() => setAddStatus(""), 6000);
          } else if (phase === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setAddStatus(st.error || t("downloadFailed"));
            setActiveDownloadId(null);
            setActiveDownloadPhase("");
            setDownloadPct(0); setDownloadSpeed(0); setDownloadBytes({ read: 0, total: 0 });
          } else if (phase === "cancelled") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setAddStatus(t("downloadCancelled"));
            setActiveDownloadId(null);
            setActiveDownloadPhase("");
            setDownloadPct(0); setDownloadSpeed(0); setDownloadBytes({ read: 0, total: 0 });
          } else {
            setAddStatus(formatStatus(st));
            setActiveDownloadPhase(phase);

            if (phase === "depot_download") {
              // depotPercent is per-depot (0-100). Compute overall % from "Depot X/Y" in depotProgress.
              const depotPct = st.depotPercent || 0;
              const m = (st.depotProgress || "").match(/Depot\s+(\d+)\/(\d+)/);
              let overallPct = depotPct;
              if (m) {
                const cur = parseInt(m[1]);
                const tot = parseInt(m[2]);
                if (tot > 0) overallPct = ((cur - 1) + depotPct / 100) / tot * 100;
              }
              setDownloadPct(Math.min(100, Math.max(0, Math.round(overallPct))));
              // No reliable byte data during depot phase — clear to avoid showing stale values
              setDownloadBytes({ read: 0, total: 0 });
              setDownloadSpeed(0);
            } else if (phase === "downloading") {
              // Backend provides totalBytes, bytesRead and speed directly
              const total = st.totalBytes || 0;
              const read = st.bytesRead || 0;
              if (total > 0) {
                setDownloadPct(Math.min(100, Math.round((read / total) * 100)));
                setDownloadBytes({ read, total });
                setDownloadSpeed(st.speed || 0);
              } else {
                setDownloadPct(0);
                setDownloadBytes({ read: 0, total: 0 });
                setDownloadSpeed(0);
              }
            } else {
              setDownloadPct(0);
              setDownloadSpeed(0);
              setDownloadBytes({ read: 0, total: 0 });
            }
          }
        } catch {
          // ignore poll errors
        }
      }, 500);

      setTimeout(() => {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
      }, 3600000);
    },
    [formatStatus, loadGames, t],
  );

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (syncPollRef.current) clearInterval(syncPollRef.current);
    };
  }, []);

  // Let the Refresh icon in the native title bar (index.tsx titleView) reload
  // the panel, since it lives in a separate React tree.
  useEffect(() => {
    setRefreshHandler(loadGames);
    return () => setRefreshHandler(null);
  }, [loadGames]);

  useEffect(() => {
    loadGames();

    // Load Steam libraries for library picker
    getSteamLibraries().then((libResult) => {
      if (libResult.success && libResult.libraries) {
        setSteamLibraries(libResult.libraries);
      }
    });

    // Check SLScheevo availability
    (async () => {
      try {
        const result = await checkSlscheevoInstalled();
        if (result.success && result.installed) {
          setSlscheevoReady(true);
        }
      } catch { }
    })();

    // Health (HealthBanner, critical) + updates (UpdatesBanner, info). Five
    // signals fetched in parallel — keeps the critical lane uncluttered and
    // surfaces routine updates separately.
    (async () => {
      try {
        const [sls, ll, cr, hc, cru, llu, pu, stuck] = await Promise.all([
          getSlssteamHealth(),
          getLumalinuxHealth(),
          getCloudredirectHealth(),
          checkHeadcrabCompat(),
          checkCloudredirectUpdate(),
          checkLumalinuxUpdate(),
          checkPluginUpdate(),
          checkStuckUpdates(),
        ]);
        if (sls.state) setSlssteamHealth(sls);
        if (ll.state)  setLumalinuxHealth(ll);
        if (cr.state)  setCrHealth(cr);
        if (hc.success) setHeadcrabCompat({
          current_build: hc.current_build,
          target: hc.target,
          compatible: hc.compatible,
        });
        setCrUpdate({
          installed: cru.installed ?? null,
          latest: cru.latest ?? null,
          has_update: !!cru.has_update,
        });
        setLlUpdate({
          installed: llu.installed ?? null,
          latest: llu.latest ?? null,
          has_update: !!llu.has_update,
        });
        if (pu.success) setPluginUpdate({
          latest: pu.latest ?? null,
          has_update: !!pu.has_update,
        });
        if (stuck.success && Array.isArray(stuck.stuck)) setStuckUpdates(stuck.stuck);
      } catch { }
    })();

    // Credential expiry — only surfaced at download time (see credWarnings),
    // so fetch once on mount and let the gated block decide whether to show it.
    (async () => {
      try {
        const cs = await getCredentialStatus();
        if (cs.success) setCred(cs);
      } catch { }
    })();

    const detectAppId = async () => {
      try {
        const result = await detectStoreAppid();
        if (result.success && result.appid) {
          setAddAppId(String(result.appid));
          return;
        }
      } catch { }
      try {
        const path = window.location.pathname || "";
        const match = path.match(/\/library\/app\/(\d+)/);
        if (match) {
          setAddAppId(match[1]);
        }
      } catch { }
    };
    detectAppId();

    const onVisibility = () => {
      if (document.visibilityState === "visible") detectAppId();
    };
    document.addEventListener("visibilitychange", onVisibility);
    const cleanup1 = () => {
      document.removeEventListener("visibilitychange", onVisibility);
    };

    (async () => {
      try {
        const result = await getActiveDownloads();
        if (result.success && result.downloads) {
          const ids = Object.keys(result.downloads);
          if (ids.length > 0) {
            const id = parseInt(ids[0], 10);
            const st = result.downloads[ids[0]];
            setAddStatus(formatStatus(st));
            startPolling(id);
          }
        }
      } catch { }
    })();

    return () => cleanup1();
  }, [loadGames, formatStatus, startPolling]);

  const doStartDownload = async (id: number, libraryPath: string = "") => {
    setAddStatus(t("startingDownload"));
    try {
      const result = await startDownload(id, libraryPath);
      if (!result.success) {
        setAddStatus(result.error || t("downloadFailed"));
        return;
      }
      setAddAppId("");
      startPolling(id);
    } catch (err: any) {
      setAddStatus(`${t("error")}: ${err?.message || String(err)}`);
    }
  };

  // Fetch DRM / launcher notices when a valid AppID is entered (debounced, via backend)
  useEffect(() => {
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    const id = parseInt(addAppId.trim(), 10);
    if (!id || id <= 0) {
      setPendingNotices([]);
      setPendingGameInfo(null);
      return;
    }
    noticeTimerRef.current = setTimeout(async () => {
      try {
        const result = await getGameNotices(id);
        if (!result.success) {
          setPendingNotices([]);
          setPendingGameInfo(null);
          return;
        }
        setPendingGameInfo(result.info || null);
        if (!result.notices?.length) { setPendingNotices([]); return; }
        const labels: string[] = result.notices.map((n: string) => {
          if (n === "denuvo") return t("drmDenuvo");
          if (n.startsWith("drm:")) return t("drmOther");
          if (n.startsWith("launcher:")) return t("launcherRequired").replace("{0}", n.slice(9));
          return n;
        });
        setPendingNotices(labels);
      } catch {
        // Non-critical
      }
    }, 600);
  }, [addAppId]);

  const handleAddGame = () => {
    const id = parseInt(addAppId.trim(), 10);
    if (!id || id <= 0) {
      setAddStatus(t("invalidAppId"));
      return;
    }
    if (steamLibraries.length > 1) {
      showLibraryPicker(steamLibraries, (libraryPath) => {
        doStartDownload(id, libraryPath);
      }, pendingGameInfo?.sizeBytes || 0);
      return;
    }
    doStartDownload(id);
  };

  const handleSearchHubcap = async () => {
    if (searchQuery.trim().length < 2) {
      setSearchError(t("enterAtLeast2Chars"));
      return;
    }
    setSearching(true);
    setSearchError("");
    setSearchResults([]);
    setShowMoreResults(false);
    try {
      const result = await searchHubcap(searchQuery.trim());
      if (result.success) {
        setSearchResults(result.results || []);
        if ((result.results || []).length === 0) {
          setSearchError(t("noGamesFound"));
        }
      } else {
        setSearchError(result.error || t("searchFailed"));
      }
    } catch (err: any) {
      setSearchError(`${t("error")}: ${err?.message || String(err)}`);
    } finally {
      setSearching(false);
    }
  };

  const handleSelectSearchResult = (result: SearchResult) => {
    setAddAppId(String(result.appid));
    setSearchResults([]);
    setSearchQuery("");
    setAddStatus(`${t("selected")}: ${result.name} (${result.appid})`);
    // Jump back to AppID mode so the staged game's info card + Download
    // Manifest button are right there — no scrolling between sections.
    setAddMode("appid");
  };

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || "", duration });

  const handleSyncAllAchievements = async () => {
    const appids = games.filter((g) => g.hasLua && g.hasGameFiles).map((g) => g.appid);
    if (appids.length === 0) return;

    const result = await generateAllAchievements(appids);
    if (!result.success) {
      toast(t("toastSyncFailed"), result.error || "");
      return;
    }

    setSyncState({ status: "running", done: 0, total: appids.length });

    syncPollRef.current = setInterval(async () => {
      try {
        const status = await getSyncAllStatus();
        if (status.success && status.state) {
          setSyncState(status.state);
          if (status.state.status === "done") {
            if (syncPollRef.current) clearInterval(syncPollRef.current);
            syncPollRef.current = null;
            toast(t("toastSyncComplete"));
            loadGames();
            setTimeout(() => setSyncState(null), 3000);
          }
        }
      } catch { }
    }, 2000);
  };

  // Segmented toggle button. Active option in accent; on focus it grows and
  // glows — mirrors Steam's native button focus animation, which an inline
  // background would otherwise suppress.
  const segBtnStyle = (active: boolean, focused: boolean) => ({
    flex: 1,
    minWidth: 0,
    padding: "8px 0",
    fontSize: "13px",
    borderRadius: "6px",
    border: "none",
    background: active ? "#1a9fff" : "rgba(255,255,255,0.08)",
    color: active ? "#ffffff" : "#dcdedf",
    transform: focused ? "scale(1.04)" : "scale(1)",
    boxShadow: focused ? "0 0 10px rgba(26,159,255,0.55)" : "none",
    transition: "transform 0.16s ease, background 0.16s ease, box-shadow 0.16s ease",
  });

  // Focus tracking for the custom buttons. DialogButton's TS props don't
  // declare onFocus/onBlur (the underlying element supports them), so spread
  // them via an any-typed object to keep the ring logic type-safe.
  const focusProps = (key: string): any => ({
    onFocus: () => setFocusedBtn(key),
    onBlur: () => setFocusedBtn(""),
    onGamepadFocus: () => setFocusedBtn(key),
    onGamepadBlur: () => setFocusedBtn(""),
  });

  const handleRestartSteam = async () => {
    setRestartingStream(true);
    await restartSteam();
    setRestartingStream(false);
    try {
      const [sls, ll] = await Promise.all([getSlssteamHealth(), getLumalinuxHealth()]);
      if (sls.state) setSlssteamHealth(sls);
      if (ll.state) setLumalinuxHealth(ll);
    } catch { }
  };

  const handleReinstallLumalinux = async () => {
    setReinstallingLL(true);
    const result = await installLumalinux();
    setReinstallingLL(false);
    if (result.success) {
      toast(t("llInstalled"), t("llInstalledBody"), 6000);
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleReinstallCloudredirect = async () => {
    setReinstallingCR(true);
    const result = await installCloudredirect();
    setReinstallingCR(false);
    if (result.success) {
      toast(t("crInstalled"), t("crInstalledBody"), 6000);
      try {
        const cr = await getCloudredirectHealth();
        if (cr.state) setCrHealth(cr);
      } catch { }
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleQuickInstall = async () => {
    // First-run onboarding action. Two-click confirm like the individual
    // installers in Settings. The backend chains dependencies → CloudRedirect
    // → lumalinux (lumalinux last so headcrab doesn't wipe its steam.sh
    // patch); none of them kill Steam mid-flight, so we fire a single
    // controlled restart at the very end.
    if (!confirmQuickInstall) {
      setConfirmQuickInstall(true);
      setTimeout(() => setConfirmQuickInstall(false), 5000);
      return;
    }
    setConfirmQuickInstall(false);
    setQuickInstalling(true);
    setQuickProgress(t("quickInstallStarting"));

    const poll = setInterval(async () => {
      try {
        const s = await getQuickInstallStatus();
        const step = s.step
          ? `[${(s.stepIndex ?? 0) + 1}/${s.totalSteps ?? 3}] ${s.step} — `
          : "";
        if (s.progress) setQuickProgress(`${step}${s.progress}`);
      } catch { }
    }, 1000);

    const result = await quickInstall();
    clearInterval(poll);
    setQuickInstalling(false);
    setQuickProgress("");

    // Refresh health so the onboarding button hides once components land.
    try {
      const [sls, ll, cr] = await Promise.all([
        getSlssteamHealth(),
        getLumalinuxHealth(),
        getCloudredirectHealth(),
      ]);
      if (sls.state) setSlssteamHealth(sls);
      if (ll.state) setLumalinuxHealth(ll);
      if (cr.state) setCrHealth(cr);
    } catch { }

    if (result.success) {
      toast(t("toastQuickInstallDone"), "", 4000);
      await restartSteam();
    } else {
      toast(t("toastQuickInstallFailed"), result.failedStep || "", 6000);
    }
  };

  // First-run gate: show Quick Install only when NONE of the three components
  // are installed and Steam's build is compatible. As soon as any one is
  // present, this onboarding entry point disappears (reinstall/repair lives in
  // Settings via the individual buttons).
  const showQuickInstall =
    slssteamHealth?.state === "not_installed" &&
    crHealth?.state === "not_installed" &&
    lumalinuxHealth?.state === "not_installed" &&
    headcrabCompat?.compatible === true;

  // Translate each component's health into a HealthProblem row, or null when
  // healthy / not installed (the banner only surfaces actionable failures —
  // "not installed" belongs to the install flow in Settings, not here).
  const slssProblem = ((): HealthProblem | null => {
    if (!slssteamHealth) return null;
    if (slssteamHealth.state === "healthy" || slssteamHealth.state === "not_installed") return null;
    const body = (() => {
      switch (slssteamHealth.state) {
        case "not_active":        return t("slssBannerBodyNotActive");
        case "injection_missing": return t("slssBannerBodyInjectionMissing");
        case "broken":
          return slssteamHealth.cause === "hash"
            ? t("slssBannerBodyBrokenHash")
            : t("slssBannerBodyBrokenPatterns");
        default: return "";
      }
    })();
    const isRestart = slssteamHealth.action === "restart";
    return {
      key: "slssteam",
      title: t("slssBannerTitle"),
      body,
      actionLabel: isRestart
        ? (restartingStream ? t("restarting") : t("slssBannerActionRestart"))
        : undefined,  // repair states route through Settings (Headcrab + gamemode checks live there)
      onAction: isRestart ? handleRestartSteam : undefined,
      actionDisabled: isRestart ? restartingStream : false,
    };
  })();

  const llProblem = ((): HealthProblem | null => {
    if (!lumalinuxHealth) return null;
    if (lumalinuxHealth.state === "healthy" || lumalinuxHealth.state === "not_installed") return null;
    const body = (() => {
      switch (lumalinuxHealth.state) {
        case "not_active":    return t("llBannerBodyNotActive");
        case "injection_missing": return t("llBannerBodyInjectionMissing");
        case "hash_blocked":  return t("llBannerBodyHashBlocked");
        case "hooks_failed":  return t("llBannerBodyHooksFailed", lumalinuxHealth.cause || "?");
        default: return "";
      }
    })();
    const isRestart = lumalinuxHealth.action === "restart";
    return {
      key: "lumalinux",
      title: t("llBannerTitle"),
      body,
      actionLabel: isRestart
        ? (restartingStream ? t("restarting") : t("llBannerActionRestart"))
        : (reinstallingLL ? t("installingLL") : t("llBannerActionReinstall")),
      onAction: isRestart ? handleRestartSteam : handleReinstallLumalinux,
      actionDisabled: isRestart ? restartingStream : reinstallingLL,
    };
  })();

  // CloudRedirect rides in the HealthBanner for broken / not_active /
  // not_authed. broken → Reinstall button (safe in gamemode, no downgrade
  // involved). not_active → Restart Steam. not_authed → no button, the body
  // tells the user to switch to Desktop and sign in. healthy / kill_switched
  // / not_installed → silence at the banner level.
  const crProblem = ((): HealthProblem | null => {
    if (!crHealth) return null;
    if (
      crHealth.state === "healthy" ||
      crHealth.state === "not_installed" ||
      crHealth.state === "kill_switched"
    ) return null;
    const body = (() => {
      switch (crHealth.state) {
        case "broken":     return t("crBannerBodyBroken");
        case "not_active": return t("crBannerBodyNotActive");
        case "not_authed": return t("crBannerBodyNotAuthed");
        default: return "";
      }
    })();
    const isRestart  = crHealth.action === "restart";
    const isReinstall = crHealth.action === "reinstall";
    return {
      key: "cloudredirect",
      title: t("crBannerTitle"),
      body,
      // not_authed has action="configure_desktop" → no button (the body says it all).
      actionLabel: isRestart
        ? (restartingStream ? t("restarting") : t("crBannerActionRestart"))
        : isReinstall
          ? (reinstallingCR ? t("installingCR") : t("crBannerActionReinstall"))
          : undefined,
      onAction: isRestart ? handleRestartSteam : isReinstall ? handleReinstallCloudredirect : undefined,
      actionDisabled: isRestart ? restartingStream : isReinstall ? reinstallingCR : false,
    };
  })();

  const healthProblems = [slssProblem, llProblem, crProblem].filter((p): p is HealthProblem => p !== null);

  // Info-level updates (blue). Only surface for components that are HEALTHY
  // — a broken component already shouts via HealthBanner with its repair button,
  // doubling up would be noise. The text says where to apply the update; the
  // button lives in Settings (intentional — keeps the QAM uncluttered).
  const updates: UpdateNotice[] = [];
  if (
    headcrabCompat && !headcrabCompat.compatible &&
    slssteamHealth?.state === "healthy"
  ) {
    updates.push({ key: "slssteam", text: t("slssUpdateAvailableMain") });
  }
  if (
    crUpdate?.has_update &&
    crHealth?.state === "healthy"
  ) {
    updates.push({ key: "cloudredirect", text: t("crUpdateAvailableMain") });
  }
  if (
    llUpdate?.has_update &&
    lumalinuxHealth?.state === "healthy"
  ) {
    updates.push({ key: "lumalinux", text: t("llUpdateAvailableMain") });
  }
  if (pluginUpdate?.has_update) {
    updates.push({
      key: "lumadeck",
      text: t("pluginUpdateAvailableMain", pluginUpdate.latest ?? ""),
    });
  }
  for (const s of stuckUpdates) {
    updates.push({ key: `stuck-${s.appid}`, text: t("stuckUpdateMain", s.name) });
  }

  // Credential warnings shown ONLY when a game is staged for download (the
  // game-info section is filled). Expired/missing credentials would block the
  // download, so they're worth a heads-up here — but nagging about them on
  // every QAM open is noise, hence the pendingGameInfo gate. "Expiring soon"
  // is deliberately excluded: the current download would still succeed, so it
  // lives only in the Settings status line.
  const credWarnings: { key: string; text: string; color: string }[] = [];
  if (pendingGameInfo && cred) {
    const h = cred.hubcap;
    const r = cred.ryuu;
    if (h?.state === "expired") credWarnings.push({ key: "h-exp", text: t("dlWarnHubcapExpired"), color: "#ff4444" });
    else if (h?.state === "none") credWarnings.push({ key: "h-none", text: t("dlWarnHubcapNone"), color: "#ffaa00" });
    if (r?.state === "expired") credWarnings.push({ key: "r-exp", text: t("dlWarnRyuuExpired"), color: "#ff4444" });
    else if (r?.state === "none") credWarnings.push({ key: "r-none", text: t("dlWarnRyuuNone"), color: "#ffaa00" });
  }

  return (
    <>
      {/* Top toolbar — light nav/utility actions as icons, right-aligned,
          so they sit at the top of the panel instead of stacking full-width
          buttons at the bottom. */}
      {showQuickInstall && (
        <PanelSection title={t("quickInstallSectionTitle")}>
          <PanelSectionRow>
            <div style={{ fontSize: "12px", color: "#8b929a", lineHeight: "1.4" }}>
              {t("quickInstallIntro")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={handleQuickInstall}
              disabled={quickInstalling}
              description={
                confirmQuickInstall ? (
                  <div style={{ textAlign: "center" }}>{t("quickInstallConfirmDesc")}</div>
                ) : (
                  t("quickInstallDesc")
                )
              }
            >
              {quickInstalling
                ? t("quickInstalling")
                : confirmQuickInstall
                  ? t("quickInstallConfirm")
                  : t("quickInstall")}
            </ButtonItem>
          </PanelSectionRow>
          {quickInstalling && quickProgress && (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", color: "#1a9fff", wordBreak: "break-word" }}>
                {quickProgress}
              </div>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      <HealthBanner problems={healthProblems} multiTitle={t("healthBannerTitleMulti")} />
      <UpdatesBanner updates={updates} />

      <PanelSection title={t("addGame")}>
        <PanelSectionRow>
          <Focusable style={{ display: "flex", gap: "8px", width: "100%" }}>
            <DialogButton
              onClick={() => setAddMode("appid")}
              {...focusProps("m-appid")}
              style={segBtnStyle(addMode === "appid", focusedBtn === "m-appid")}
            >
              {t("addByAppId")}
            </DialogButton>
            <DialogButton
              onClick={() => setAddMode("name")}
              {...focusProps("m-name")}
              style={segBtnStyle(addMode === "name", focusedBtn === "m-name")}
            >
              {t("addByName")}
            </DialogButton>
          </Focusable>
        </PanelSectionRow>

        {addMode === "appid" ? (
          <>
        <PanelSectionRow>
          <TextField
            value={addAppId}
            onChange={(e: any) => setAddAppId(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        {pendingGameInfo && (
          <Notice variant="info">
              {pendingGameInfo.name && (
                <div style={{ fontSize: "13px", fontWeight: 600, color: "#fff", lineHeight: "1.3" }}>
                  {pendingGameInfo.name}
                </div>
              )}
              {pendingGameInfo.developer && (
                <div style={{ fontSize: "11px", color: "#8b929a" }}>
                  {pendingGameInfo.developer}
                  {pendingGameInfo.metacritic != null && (
                    <span style={{
                      marginLeft: "8px",
                      background: pendingGameInfo.metacritic >= 75 ? "rgba(100,200,80,0.18)" : pendingGameInfo.metacritic >= 50 ? "rgba(200,168,75,0.18)" : "rgba(220,80,80,0.18)",
                      color: pendingGameInfo.metacritic >= 75 ? "#7ed36f" : pendingGameInfo.metacritic >= 50 ? "#c8a84b" : "#e06060",
                      borderRadius: "3px",
                      padding: "1px 5px",
                      fontSize: "10px",
                      fontWeight: 700,
                    }}>
                      Metacritic: {pendingGameInfo.metacritic}
                    </span>
                  )}
                </div>
              )}
              <div style={{ display: "flex", gap: "6px", marginTop: "2px", flexWrap: "wrap" }}>
                {pendingGameInfo.platforms?.windows && (
                  <span style={{ fontSize: "10px", color: "#8b929a", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>Windows</span>
                )}
                {pendingGameInfo.platforms?.linux && (
                  <span style={{ fontSize: "10px", color: "#8b929a", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>Linux</span>
                )}
                {pendingGameInfo.platforms?.mac && (
                  <span style={{ fontSize: "10px", color: "#8b929a", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>macOS</span>
                )}
                {pendingGameInfo.achievements > 0 && (
                  <span style={{ fontSize: "10px", color: "#8b929a", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>
                    {pendingGameInfo.achievements} {t("achievements")}
                  </span>
                )}
                {pendingGameInfo.hasPtBR && (
                  <span style={{ fontSize: "10px", color: "#8b929a", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>PT-BR</span>
                )}
                {pendingGameInfo.sizeBytes > 0 && (
                  <span style={{ fontSize: "10px", color: "#8b929a", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>
                    {pendingGameInfo.sizeBytes >= 1073741824
                      ? `${(pendingGameInfo.sizeBytes / 1073741824).toFixed(1)} GB`
                      : `${Math.round(pendingGameInfo.sizeBytes / 1048576)} MB`}
                  </span>
                )}
                {pendingGameInfo.protondb && (
                  <span style={{
                    fontSize: "10px",
                    fontWeight: 700,
                    color: PROTONDB_TIER_COLOR[pendingGameInfo.protondb] || "#9aa4b2",
                    background: "rgba(255,255,255,0.07)",
                    borderRadius: "3px",
                    padding: "1px 6px",
                  }}>
                    ProtonDB: {pendingGameInfo.protondb.charAt(0).toUpperCase() + pendingGameInfo.protondb.slice(1)}
                  </span>
                )}
              </div>
              {pendingGameInfo.achievements > 0 && !slscheevoReady && (
                <div style={{ marginTop: "4px", fontSize: "11px", color: "#c8a84b", display: "flex", gap: "6px", alignItems: "flex-start" }}>
                  <span style={{ flexShrink: 0 }}>⚡</span>
                  <span>{t("slscheevoHint")}</span>
                </div>
              )}
          </Notice>
        )}
        {pendingNotices.length > 0 && (
          <Notice variant="warn" title={t("gameNoticesTitle")}>
              {pendingNotices.map((notice, i) => (
                <div key={i} style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "7px",
                  fontSize: "12px",
                  color: "#dcdedf",
                  lineHeight: "1.45",
                }}>
                  <span style={{ color: "#c8a84b", flexShrink: 0, marginTop: "1px" }}>▸</span>
                  <span>{notice}</span>
                </div>
              ))}
          </Notice>
        )}
        {credWarnings.length > 0 && (
          <Notice variant="danger">
              {credWarnings.map((w) => (
                <div key={w.key} style={{ fontSize: "12px", color: w.color, lineHeight: "1.45" }}>
                  {w.text}
                </div>
              ))}
          </Notice>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleAddGame}>
            {t("downloadManifest")}
          </ButtonItem>
        </PanelSectionRow>
        {addStatus && (
          <PanelSectionRow>
            <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{
                textAlign: "center",
                color:
                  addStatus.startsWith(t("error")) ||
                    addStatus === t("invalidAppId") ||
                    addStatus === t("downloadFailed")
                    ? "#ff6b6b"
                    : "#00cc00",
                fontSize: "12px",
              }}>
                {addStatus}
              </div>
              {(activeDownloadPhase === "depot_download" || activeDownloadPhase === "downloading") && downloadPct > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <div style={{ height: "6px", background: "rgba(255,255,255,0.1)", borderRadius: "3px", overflow: "hidden" }}>
                    <div style={{
                      height: "100%",
                      width: `${downloadPct}%`,
                      background: "linear-gradient(90deg, #1a9fff, #00cc00)",
                      borderRadius: "3px",
                      transition: "width 0.4s ease",
                    }} />
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#8b929a" }}>
                    <span>
                      {downloadBytes.total > 0
                        ? `${(downloadBytes.read / 1073741824).toFixed(2)} / ${(downloadBytes.total / 1073741824).toFixed(2)} GB (${downloadPct}%)`
                        : `${downloadPct}%`}
                    </span>
                    {downloadSpeed > 0 && (
                      <span style={{ color: "#00cc00" }}>
                        {downloadSpeed >= 1048576
                          ? `${(downloadSpeed / 1048576).toFixed(1)} MB/s`
                          : `${Math.round(downloadSpeed / 1024)} KB/s`}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </PanelSectionRow>
        )}
          </>
        ) : (
          /* By name (Hubcap search) — bottom padding only while the field is
             focused so the on-screen keyboard doesn't hide it */
          <div style={{ paddingBottom: hubcapFocused ? "280px" : "0px" }}>
        <PanelSectionRow>
          <TextField
            label={t("gameName")}
            value={searchQuery}
            onChange={(e: any) => setSearchQuery(e?.target?.value ?? "")}
            onFocus={() => setHubcapFocused(true)}
            onBlur={() => setHubcapFocused(false)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleSearchHubcap}
            disabled={searching}
          >
            {searching ? t("searching") : t("searchHubcap")}
          </ButtonItem>
        </PanelSectionRow>
        {searchError && (
          <PanelSectionRow>
            <div
              style={{
                textAlign: "center",
                padding: "4px",
                color: "#ff6b6b",
                fontSize: "12px",
              }}
            >
              {searchError}
            </div>
          </PanelSectionRow>
        )}
        {searchResults.length > 0 && (
          <>
            <PanelSectionRow>
              <div
                style={{
                  fontSize: "11px",
                  color: "#8b929a",
                  textAlign: "center",
                }}
              >
                {searchResults.length} {t("results")}
              </div>
            </PanelSectionRow>
            {searchResults.slice(0, showMoreResults ? 15 : 5).map((r: SearchResult) => (
              <PanelSectionRow key={r.appid}>
                <ButtonItem
                  layout="below"
                  onClick={() => handleSelectSearchResult(r)}
                  description={`AppID: ${r.appid}`}
                >
                  {r.name}
                </ButtonItem>
              </PanelSectionRow>
            ))}
            {searchResults.length > 5 && !showMoreResults && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => setShowMoreResults(true)}>
                  {t("showMoreResults") || "Show More Results"} (+{searchResults.length - 5})
                </ButtonItem>
              </PanelSectionRow>
            )}
            {searchResults.length > 15 && showMoreResults && (
              <PanelSectionRow>
                <div
                  style={{
                    fontSize: "11px",
                    color: "#8b929a",
                    textAlign: "center",
                  }}
                >
                  +{searchResults.length - 15} {t("moreResults")}
                </div>
              </PanelSectionRow>
            )}
          </>
        )}
          </div>
        )}
      </PanelSection>

      {/* My Games lives on its own full-screen route now — the QAM only shows
          a compact entry so the panel stays a lean launcher. */}
      <PanelSection title={t("myGames")}>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => Navigation.Navigate(ROUTE_LIBRARY)}
          >
            {loading
              ? t("loadingGames")
              : `${t("myGames")} (${games.length}) →`}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {slscheevoReady && (
        <PanelSection>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={handleSyncAllAchievements}
              disabled={syncState?.status === "running"}
            >
              {syncState?.status === "running"
                ? t("syncingAchievements", syncState.done || 0, syncState.total || 0)
                : t("syncAllAchievements")}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}

      {/* Downloads lives at the very bottom as a plain button (the header only
          carries Refresh + Settings now). */}
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => Navigation.Navigate(ROUTE_DOWNLOADS)}
          >
            {t("downloads")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
