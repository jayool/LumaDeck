import { useEffect, useState, useCallback, useRef } from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  Navigation,
  Focusable,
  DialogButton,
  Field,
  ProgressBarWithInfo,
} from "@decky/ui";
import {
  getDownloadStatus,
  getActiveDownloads,
  startDownload,
  detectStoreAppid,
  searchHubcap,
  getApiKeyStatus,
  getGameNotices,
  restartSteam,
  getComponentsStatus,
  applyComponent,
  downloadUpdateToDownloads,
  checkStuckUpdates,
  getCredentialStatus,
  quickInstall,
  getQuickInstallStatus,
  reinjectInstalled,
  runDesktopHandoffReal,
  runDesktopHandoffQuickInstall,
} from "../api";
import { FaExclamationTriangle } from "react-icons/fa";
import {
  SystemStatus,
  ComponentsStatus,
  SystemStatusActions,
} from "../components/SystemStatus";
import { ROUTE_SETTINGS, ROUTE_DOWNLOADS, ROUTE_LIBRARY, ROUTE_GAME_DETAIL, SETTINGS_TAB_ACHIEVEMENTS, setPendingSettingsTab } from "../routes";
import { setRefreshHandler } from "../refresh";
import { ACHIEVEMENTS_ENABLED } from "../features";
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
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [showMoreResults, setShowMoreResults] = useState(false);
  const [achievementsReady, setAchievementsReady] = useState(false);
  // Unified system status (one fetch). Replaces the 7 health/update states.
  const [compStatus, setCompStatus] = useState<ComponentsStatus | null>(null);
  const [stuckUpdates, setStuckUpdates] = useState<{ appid: number; name: string }[]>([]);
  const [sysBusy, setSysBusy] = useState(false);
  const [quickInstalling, setQuickInstalling] = useState(false);
  const [confirmQuickInstall, setConfirmQuickInstall] = useState(false);
  const [quickProgress, setQuickProgress] = useState("");
  const [pendingNotices, setPendingNotices] = useState<string[]>([]);
  const [pendingGameInfo, setPendingGameInfo] = useState<any>(null);
  const [cred, setCred] = useState<any>(null);
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // One fetch for the whole system-status surface (component health + updates +
  // headcrab gate + plugin) plus the per-game stuck check. Re-run after any
  // system action so the rows reflect the new state.
  // force=true bypasses the 6 h update caches (lumalinux release + CR hash) — used
  // by the manual Refresh icon so a just-cut release shows up immediately. Auto
  // calls (mount, post-action) stay cached to respect GitHub's anon rate limit.
  const refreshStatus = useCallback(async (force = false) => {
    try {
      const [cs, stuck] = await Promise.all([getComponentsStatus(force), checkStuckUpdates()]);
      if (cs?.success) setCompStatus(cs);
      if (stuck?.success && Array.isArray(stuck.stuck)) setStuckUpdates(stuck.stuck);
    } catch { }
  }, []);

  // Run a system action (restart/repair/update/...), keeping a single busy flag
  // so the rows disable while it works, then refresh the status.
  const runSysAction = useCallback(async (fn: () => Promise<void>) => {
    setSysBusy(true);
    try { await fn(); } catch { } finally {
      setSysBusy(false);
      await refreshStatus();
    }
  }, [refreshStatus]);

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
    [formatStatus, t],
  );

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Let the Refresh icon in the native title bar (index.tsx titleView) reload
  // the panel, since it lives in a separate React tree.
  useEffect(() => {
    // The title-bar Refresh force-refreshes the system status (bypassing the 6 h
    // caches), so a just-cut release surfaces at once. The QAM panel no longer
    // renders the games list (that lives on the Library page), so there's no
    // library reload here.
    setRefreshHandler(() => { refreshStatus(true); });
    return () => setRefreshHandler(null);
  }, [refreshStatus]);

  useEffect(() => {
    // Achievements are ready to generate once the Steam Web API key is set.
    // Gate ONLY the achievements probe on the feature flag — the rest of this
    // mount init (system status, credentials, appid detection) must always run.
    // (Regression: a blanket `if (!ACHIEVEMENTS_ENABLED) return` here skipped
    // the whole effect, so the QAM loaded nothing until a manual refresh.)
    if (ACHIEVEMENTS_ENABLED) {
      (async () => {
        try {
          const result = await getApiKeyStatus();
          if (result.success && result.keySet) {
            setAchievementsReady(true);
          }
        } catch { }
      })();
    }

    // Unified system status: one call for all component health + updates +
    // headcrab gate + plugin, plus the per-game stuck check.
    refreshStatus();

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
  }, [formatStatus, startPolling]);

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
    // The backend ignores the install-library path (manifest flow always uses
    // the default library), so there's no disk choice to make.
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

  // Add-Game mode toggle, tab-style: two native DialogButtons. Focusing one
  // selects its mode, so moving L/R swaps the content below — like native
  // tabs, but it fits the narrow QAM where the native Tabs row wouldn't. No
  // background/glow override, so the native focus (white fill) is the only
  // indicator; once focus is in the content, the content itself shows the mode.
  // onFocus/onGamepadFocus aren't in DialogButton's TS props (the element
  // supports them), so spread via an any-typed object.
  const modeFocus = (mode: "appid" | "name"): any => ({
    onFocus: () => setAddMode(mode),
    onGamepadFocus: () => setAddMode(mode),
  });

  // The 5 system actions (DESIGN_UI.md "Component model"). All cascade-safe:
  // repair/reinstall/update go through reinject_installed / apply_component,
  // which own the steam.sh ordering. Each refreshes the status afterwards.
  const sysActions: SystemStatusActions = {
    restart: () => runSysAction(async () => { await restartSteam(); }),
    repair: () => runSysAction(async () => {
      const r = await reinjectInstalled();
      if (r?.success) await restartSteam();
      else toast(t("toastError"), r?.error || "", 4000);
    }),
    reinstallCore: () => runSysAction(async () => {
      const r = await applyComponent("core", "install");
      if (r?.success) await restartSteam();
      else toast(t("toastError"), r?.failedStep || r?.error || "", 4000);
    }),
    downgrade: () => runSysAction(async () => {
      // Arm the one-shot Desktop autostart (headcrab downgrade + lumalinux
      // re-inject) and switch to Desktop. The script runs there and returns to
      // Game Mode on success. If the auto-switch can't fire, tell the user to
      // switch to Desktop manually — the task is already armed.
      const r: any = await runDesktopHandoffReal();
      if (r?.switchLaunched) toast(t("sysSteamTooNew"), t("sysHandoffSwitching"), 8000);
      else if (r?.armed) toast(t("sysSteamTooNew"), t("sysHandoffManual"), 12000);
      else toast(t("toastError"), r?.error || "", 6000);
    }),
    update: () => runSysAction(async () => {
      // SLSsteam/CloudRedirect updates ride headcrab (a full reinject pulls all
      // latest); a lumalinux-only update is the light, patch-only path.
      const comps = compStatus?.components || [];
      // Only CloudRedirect rides headcrab in the update surface (SLSsteam isn't
      // surfaced — choice B); a CR update needs the full reinject.
      const heavy = comps.some((c) =>
        c.installed && c.id === "cloudredirect" && c.update?.available);
      const r = heavy
        ? await reinjectInstalled()
        : await applyComponent("lumalinux", "update");
      if (r?.success) await restartSteam();
      else toast(t("toastError"), r?.error || "", 4000);
    }),
    pluginUpdate: () => runSysAction(async () => {
      const r = await downloadUpdateToDownloads();
      if (r?.success) toast(t("sysPluginUpdate"), t("updateZipSaved", r.path || "Downloads"), 8000);
      else toast(t("toastError"), r?.error || "", 4000);
    }),
    openGame: (appid: number) => Navigation.Navigate(ROUTE_GAME_DETAIL + "/" + appid),
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

    // Off-pin (Steam newer than the headcrab pin): the install includes a Steam
    // downgrade, which can't run in Game Mode (gamescope crash-loop wipe). Hand
    // off to Desktop, where the SAME quick_install runs (gamemode=false) and
    // returns to Game Mode on success. Nothing is re-implemented — it's the real
    // installer code.
    const compatible = compStatus?.headcrab?.compatible === true;
    if (!compatible) {
      const r: any = await runDesktopHandoffQuickInstall();
      if (r?.switchLaunched) toast(t("quickInstallDesktop"), t("quickInstallDesktopSwitching"), 9000);
      else if (r?.armed) toast(t("quickInstallDesktop"), t("quickInstallDesktopManual"), 12000);
      else toast(t("toastError"), r?.error || "", 6000);
      return;
    }

    // At the pin: no downgrade needed, safe to run in Game Mode.
    setQuickInstalling(true);
    setQuickProgress(t("quickInstallStarting"));

    const poll = setInterval(async () => {
      try {
        const s = await getQuickInstallStatus();
        const step = s.step
          ? `[${(s.stepIndex ?? 0) + 1}/${s.totalSteps ?? 2}] ${s.step} — `
          : "";
        if (s.progress) setQuickProgress(`${step}${s.progress}`);
      } catch { }
    }, 1000);

    const result = await quickInstall();
    clearInterval(poll);
    setQuickInstalling(false);
    setQuickProgress("");

    // Refresh status so the onboarding entry hides once components land.
    await refreshStatus();

    if (result.success) {
      toast(t("toastQuickInstallDone"), "", 4000);
      await restartSteam();
    } else {
      toast(t("toastQuickInstallFailed"), result.failedStep || "", 6000);
    }
  };

  // First-run gate: show Quick Install whenever NONE of the three components are
  // installed. NOT gated on headcrab compatibility — a fresh Deck's Steam is
  // almost always newer than the (lagging) headcrab pin, and Quick Install is
  // exactly the action that fixes that: when off-pin it routes through Desktop
  // (where the downgrade is safe) and installs everything there. Gating it on
  // "already compatible" hid the onboarding from precisely the people who need
  // it. As soon as any component is present, this entry disappears (reinstall/
  // repair lives in Settings).
  const showQuickInstall = (() => {
    const cs = compStatus;
    if (!cs?.success) return false;
    // Dev preview override (Settings ▸ Dev) wins over the real check, so the
    // onboarding can be previewed without touching component files on disk.
    if (cs.quickInstall === "show") return true;
    if (cs.quickInstall === "hide") return false;
    return (cs.components || []).every((c) => !c.installed);
  })();

  // Off-pin = Steam newer than the headcrab pin → Quick Install routes to
  // Desktop (see handleQuickInstall). Mirror its exact test so the confirm text
  // matches what will actually happen (Desktop hand-off, not an in-place Steam
  // restart).
  const quickInstallOffPin = compStatus?.headcrab?.compatible !== true;

  // Credential warnings shown ONLY when a game is staged for download (the
  // game-info section is filled). Expired/missing credentials would block the
  // download, so they're worth a heads-up here — but nagging about them on
  // every QAM open is noise, hence the pendingGameInfo gate. "Expiring soon"
  // is deliberately excluded: the current download would still succeed, so it
  // lives only in the Settings status line.
  // Only the Hubcap API key matters for adding a game; Ryuu is intentionally
  // not surfaced here.
  const credWarnings: { key: string; text: string; color: string }[] = [];
  if (pendingGameInfo && cred) {
    const h = cred.hubcap;
    if (h?.state === "expired") credWarnings.push({ key: "h-exp", text: t("dlWarnHubcapExpired"), color: "#ff4444" });
    else if (h?.state === "none") credWarnings.push({ key: "h-none", text: t("dlWarnHubcapNone"), color: "#ffaa00" });
  }

  // Adding a game needs the whole pipeline: SLSsteam (unlocks the download —
  // ownership spoof, without it Steam shows "Buy" and won't download) AND lumalinux
  // (injects the manifests/keys — without it nothing downloads) both healthy, plus
  // at least one manifest provider (Hubcap or Ryuu) usable. If any is missing the
  // add actions are disabled; the QAM rows / credential warnings above say why.
  // Only gate on data we actually have — while status/cred load, don't block.
  const usableCred = (c: any) => c?.state === "ok" || c?.state === "soon" || c?.state === "unknown";
  const hasProvider = usableCred(cred?.hubcap) || usableCred(cred?.ryuu);
  const compHealth = (id: string) => compStatus?.components?.find((c: any) => c.id === id)?.health;
  const compsBad = !!compStatus?.success && (compHealth("slssteam") !== "healthy" || compHealth("lumalinux") !== "healthy");
  const credBad = !!cred && !hasProvider;
  const canAddGames = !compsBad && !credBad;

  return (
    <>
      {/* Top toolbar — light nav/utility actions as icons, right-aligned,
          so they sit at the top of the panel instead of stacking full-width
          buttons at the bottom. */}
      {showQuickInstall && (
        <PanelSection>
          {/* Mirror the SystemStatus row model (the coherent one): section
              title, blurb and action are ONE ButtonItem — title as `label`
              (above), intro as `description` (below), action as children — so
              the focus band wraps all three as a unit, like "Restart needed".
              No PanelSection title: that would sit outside the focus. */}
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              label={<span style={{ fontWeight: "bold", textTransform: "uppercase" }}>{t("quickInstallSectionTitle")}</span>}
              description={t("quickInstallIntro")}
              onClick={handleQuickInstall}
              disabled={quickInstalling}
            >
              {quickInstalling
                ? t("quickInstalling")
                : confirmQuickInstall
                  ? quickInstallOffPin
                    ? t("quickInstallConfirmDesktop")
                    : t("quickInstallConfirm")
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

      <SystemStatus
        status={compStatus}
        stuck={stuckUpdates}
        busy={sysBusy}
        actions={sysActions}
      />

      <PanelSection title={t("addGame")}>
        <PanelSectionRow>
          <Focusable style={{
            display: "flex", gap: "8px", width: "100%",
            // Native-style hairline below the toggle so it reads as a delimited
            // row (like My Games / Workshop) rather than a floating pair that
            // blends into the text field below. The section title bounds it
            // above; this line bounds it below and contains focus without a gap.
            paddingBottom: "8px", marginBottom: "8px",
            borderBottom: "1px solid rgba(255,255,255,0.12)",
          }}>
            {/* minWidth:0 lets the buttons shrink below their content min-width
                — without it DialogButton's native min-width overflows the narrow
                QAM and "By name" runs off the right edge. */}
            <DialogButton
              style={{ flex: 1, minWidth: 0 }}
              onClick={() => setAddMode("appid")}
              {...modeFocus("appid")}
            >
              {t("addByAppId")}
            </DialogButton>
            <DialogButton
              style={{ flex: 1, minWidth: 0 }}
              onClick={() => setAddMode("name")}
              {...modeFocus("name")}
            >
              {t("addByName")}
            </DialogButton>
          </Focusable>
        </PanelSectionRow>

        {!canAddGames && (
          <PanelSectionRow>
            <Field icon={<FaExclamationTriangle color="#ff8c00" />} label={t("addGameBlocked")} />
          </PanelSectionRow>
        )}

        {addMode === "appid" ? (
          <>
        <PanelSectionRow>
          <TextField
            value={addAppId}
            onChange={(e: any) => setAddAppId(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        {pendingGameInfo && (() => {
          // Native Field instead of a custom card (DESIGN_UI.md §4b): name as the
          // label, a trimmed "dev · size · Metacritic · ProtonDB" fact line as
          // the description. The description is a ReactNode, so Metacritic and
          // ProtonDB keep their colour as inline text. Platforms / achievement
          // count / PT-BR move to GameDetail.
          const mc: number | null = pendingGameInfo.metacritic;
          const mcColor = mc == null ? "" : mc >= 75 ? "#7ed36f" : mc >= 50 ? "#c8a84b" : "#e06060";
          const size = pendingGameInfo.sizeBytes > 0
            ? (pendingGameInfo.sizeBytes >= 1073741824
              ? `${(pendingGameInfo.sizeBytes / 1073741824).toFixed(1)} GB`
              : `${Math.round(pendingGameInfo.sizeBytes / 1048576)} MB`)
            : "";
          const facts: any[] = [];
          if (pendingGameInfo.developer) facts.push(pendingGameInfo.developer);
          if (size) facts.push(size);
          if (mc != null) facts.push(<span key="mc" style={{ color: mcColor }}>Metacritic {mc}</span>);
          if (pendingGameInfo.protondb) facts.push(
            <span key="proton" style={{ color: PROTONDB_TIER_COLOR[pendingGameInfo.protondb] || "#9aa4b2" }}>
              ProtonDB {pendingGameInfo.protondb.charAt(0).toUpperCase() + pendingGameInfo.protondb.slice(1)}
            </span>,
          );
          const desc = facts.flatMap((f, i) => (i === 0 ? [f] : [" · ", f]));
          return (
            <>
              <PanelSectionRow>
                <Field
                  label={pendingGameInfo.name || `AppID ${addAppId}`}
                  description={<span>{desc}</span>}
                  bottomSeparator="standard"
                />
              </PanelSectionRow>
              {ACHIEVEMENTS_ENABLED && pendingGameInfo.achievements > 0 && !achievementsReady && (
                <PanelSectionRow>
                  <div style={{ fontSize: "11px", color: "#c8a84b", display: "flex", gap: "6px", alignItems: "flex-start" }}>
                    <span style={{ flexShrink: 0 }}>⚡</span>
                    <span>{t("slscheevoHint")}</span>
                  </div>
                </PanelSectionRow>
              )}
            </>
          );
        })()}
        {/* Game notices → display-only Field rows (one per note), ⚠ gold icon. */}
        {pendingNotices.map((notice, i) => (
          <PanelSectionRow key={`note-${i}`}>
            <Field icon={<FaExclamationTriangle color="#c8a84b" />} label={notice} />
          </PanelSectionRow>
        ))}
        {/* Credential warning → an actionable row: the fix lives in Settings ▸
            Credentials, so navigate there (Health tier-2 pattern). Only Hubcap. */}
        {credWarnings.length > 0 && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              icon={<FaExclamationTriangle color={credWarnings[0].color} />}
              description={credWarnings[0].text}
              onClick={() => Navigation.Navigate(ROUTE_SETTINGS)}
            >
              {t("fixCredentials")}
            </ButtonItem>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleAddGame} disabled={!canAddGames}>
            {t("addGameAction")}
          </ButtonItem>
        </PanelSectionRow>
        {/* Download status + progress live BELOW, outside the appid/name toggle,
            so an in-flight download stays visible regardless of input mode. */}
          </>
        ) : (
          /* By name (Hubcap search) — bottom padding only while the field is
             focused so the on-screen keyboard doesn't hide it */
          <div style={{ paddingBottom: hubcapFocused ? "280px" : "0px" }}>
        <PanelSectionRow>
          <TextField
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
            disabled={searching || !canAddGames}
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
          <PanelSection title={`${searchResults.length} ${t("results")}`}>
            {searchResults.slice(0, showMoreResults ? 15 : 5).map((r: SearchResult) => (
              <PanelSectionRow key={r.appid}>
                <ButtonItem
                  layout="below"
                  onClick={() => handleSelectSearchResult(r)}
                  description={`AppID: ${r.appid}`}
                  disabled={!canAddGames}
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
          </PanelSection>
        )}
          </div>
        )}
        {/* Download status + progress: rendered OUTSIDE the appid/name toggle so
            an in-flight download stays visible when switching input modes. The
            ProgressBarWithInfo is a DIRECT PanelSectionRow child (not nested in a
            flex div) — nesting it shifted the native bar off the right edge. */}
        {addStatus && (
          <PanelSectionRow>
            <div style={{
              width: "100%",
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
          </PanelSectionRow>
        )}
        {(activeDownloadPhase === "depot_download" || activeDownloadPhase === "downloading") && downloadPct > 0 && (
          <PanelSectionRow>
            <ProgressBarWithInfo
              nProgress={downloadPct}
              sOperationText={
                (downloadBytes.total > 0
                  ? `${(downloadBytes.read / 1073741824).toFixed(2)} / ${(downloadBytes.total / 1073741824).toFixed(2)} GB`
                  : "") +
                (downloadSpeed > 0
                  ? `  ·  ${downloadSpeed >= 1048576
                      ? `${(downloadSpeed / 1048576).toFixed(1)} MB/s`
                      : `${Math.round(downloadSpeed / 1024)} KB/s`}`
                  : "")
              }
            />
          </PanelSectionRow>
        )}
      </PanelSection>

      {/* Bottom navigation — My Games, the optional Sync-all shortcut, and
          Downloads share ONE PanelSection. Each entry in its own section stacked
          the sections' vertical padding into big empty gaps; one section with
          rows gives the normal native row rhythm. My Games and Downloads each
          live on their own full-screen route, so the QAM only carries compact
          entries (no title, no count). */}
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => Navigation.Navigate(ROUTE_LIBRARY)}
          >
            {t("myGames")}
          </ButtonItem>
        </PanelSectionRow>

        {ACHIEVEMENTS_ENABLED && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => {
              setPendingSettingsTab(SETTINGS_TAB_ACHIEVEMENTS);
              Navigation.Navigate(ROUTE_SETTINGS);
            }}
          >
            {t("achievements")}
          </ButtonItem>
        </PanelSectionRow>
        )}

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => Navigation.Navigate(ROUTE_DOWNLOADS)}
          >
            {t("workshop")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
