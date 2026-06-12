import { useEffect, useState, useCallback, useRef } from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  Navigation,
} from "@decky/ui";
import { GameCard, GameInfo } from "../components/GameCard";
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
  getInjectionStatus,
  restartSteam,
  checkSlssteamHashStatus,
} from "../api";
import { showLibraryPicker } from "../components/LibraryPickerModal";
import { ROUTE_GAME_DETAIL, ROUTE_SETTINGS, ROUTE_DOWNLOADS } from "../routes";
import { useT } from "../i18n";
import { toaster } from "@decky/api";

interface SearchResult {
  appid: number;
  name: string;
}

export function GameList() {
  const t = useT();
  const [games, setGames] = useState<GameInfo[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [addAppId, setAddAppId] = useState("");
  const [addStatus, setAddStatus] = useState("");
  const [activeDownloadId, setActiveDownloadId] = useState<number | null>(null);
  const [activeDownloadPhase, setActiveDownloadPhase] = useState("");
  const [downloadPct, setDownloadPct] = useState(0);
  const [downloadSpeed, setDownloadSpeed] = useState(0);
  const [downloadBytes, setDownloadBytes] = useState({ read: 0, total: 0 });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [sortMode, setSortMode] = useState<"name" | "appid" | "recent">("name");

  // Hubcap search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [showMoreResults, setShowMoreResults] = useState(false);
  const [slscheevoReady, setSlscheevoReady] = useState(false);
  const [injectionWarning, setInjectionWarning] = useState(false);
  const [unknownHash, setUnknownHash] = useState(false);
  const [restartingStream, setRestartingStream] = useState(false);
  const [syncState, setSyncState] = useState<any>(null);
  const [steamLibraries, setSteamLibraries] = useState<any[]>([]);
  const [pendingNotices, setPendingNotices] = useState<string[]>([]);
  const [pendingGameInfo, setPendingGameInfo] = useState<any>(null);
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

    // Check SLSsteam injection — auto-repairs steam.sh if missing
    (async () => {
      try {
        const [injResult, hashResult] = await Promise.all([
          getInjectionStatus(),
          checkSlssteamHashStatus(),
        ]);
        const hasUnknownHash = hashResult.success && hashResult.unknown_hash;
        setUnknownHash(hasUnknownHash);
        if (injResult.patched || injResult.was_repaired_on_startup || hasUnknownHash) {
          setInjectionWarning(true);
        }
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

  const sortLabels: Record<string, string> = {
    name: "A-Z",
    appid: "AppID",
    recent: "Recent",
  };

  const cycleSortMode = () => {
    setSortMode((prev) => {
      if (prev === "name") return "appid";
      if (prev === "appid") return "recent";
      return "name";
    });
  };

  const filtered = (
    search
      ? games.filter(
        (g: GameInfo) =>
          g.name.toLowerCase().includes(search.toLowerCase()) ||
          String(g.appid).includes(search),
      )
      : games
  )
    .slice()
    .sort((a, b) => {
      if (sortMode === "appid") return a.appid - b.appid;
      if (sortMode === "recent") return b.appid - a.appid;
      return a.name.localeCompare(b.name);
    });

  const navigateToDetail = (appid: number) => {
    Navigation.Navigate(ROUTE_GAME_DETAIL + "/" + appid);
  };

  const handleRestartSteam = async () => {
    setRestartingStream(true);
    await restartSteam();
    setInjectionWarning(false);
    setRestartingStream(false);
  };

  return (
    <>
      {injectionWarning && (
        <PanelSection>
          <div style={{
            background: "rgba(255, 140, 0, 0.1)",
            border: "1px solid rgba(255, 140, 0, 0.4)",
            borderLeft: "3px solid #ff8c00",
            borderRadius: "6px",
            padding: "10px 12px",
          }}>
            <div style={{ fontWeight: 600, color: "#ffaa33", fontSize: "13px", marginBottom: "4px" }}>
              {unknownHash ? t("slssteamUnknownHash") : t("slssteamInjectionMissing")}
            </div>
            <div style={{
              fontSize: "12px",
              color: "#aaa",
              marginBottom: unknownHash ? "0" : "10px",
            }}>
              {unknownHash ? t("slssteamUnknownHashBody") : t("slssteamInjectionRepairedBody")}
            </div>
            {!unknownHash && (
              <button
                onClick={handleRestartSteam}
                disabled={restartingStream}
                style={{
                  background: restartingStream ? "#555" : "#ff8c00",
                  color: "#fff",
                  border: "none",
                  borderRadius: "4px",
                  padding: "6px 14px",
                  fontSize: "12px",
                  fontWeight: 600,
                  cursor: restartingStream ? "default" : "pointer",
                  width: "100%",
                }}
              >
                {restartingStream ? t("restarting") : t("restartSteam")}
              </button>
            )}
          </div>
        </PanelSection>
      )}

      <PanelSection title={t("addGame")}>
        <PanelSectionRow>
          <TextField
            label={t("steamAppId")}
            value={addAppId}
            onChange={(e: any) => setAddAppId(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        {pendingGameInfo && (
          <PanelSectionRow>
            <div style={{
              width: "100%",
              background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.10)",
              borderLeft: "3px solid #4a9eff",
              borderRadius: "4px",
              padding: "8px 12px",
              display: "flex",
              flexDirection: "column",
              gap: "4px",
            }}>
              {pendingGameInfo.name && (
                <div style={{ fontSize: "13px", fontWeight: 600, color: "#fff", lineHeight: "1.3" }}>
                  {pendingGameInfo.name}
                </div>
              )}
              {pendingGameInfo.developer && (
                <div style={{ fontSize: "11px", color: "#9aa4b2" }}>
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
                  <span style={{ fontSize: "10px", color: "#9aa4b2", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>Windows</span>
                )}
                {pendingGameInfo.platforms?.linux && (
                  <span style={{ fontSize: "10px", color: "#9aa4b2", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>Linux</span>
                )}
                {pendingGameInfo.platforms?.mac && (
                  <span style={{ fontSize: "10px", color: "#9aa4b2", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>macOS</span>
                )}
                {pendingGameInfo.achievements > 0 && (
                  <span style={{ fontSize: "10px", color: "#9aa4b2", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>
                    {pendingGameInfo.achievements} {t("achievements")}
                  </span>
                )}
                {pendingGameInfo.hasPtBR && (
                  <span style={{ fontSize: "10px", color: "#9aa4b2", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>PT-BR</span>
                )}
                {pendingGameInfo.sizeBytes > 0 && (
                  <span style={{ fontSize: "10px", color: "#9aa4b2", background: "rgba(255,255,255,0.07)", borderRadius: "3px", padding: "1px 6px" }}>
                    {pendingGameInfo.sizeBytes >= 1073741824
                      ? `${(pendingGameInfo.sizeBytes / 1073741824).toFixed(1)} GB`
                      : `${Math.round(pendingGameInfo.sizeBytes / 1048576)} MB`}
                  </span>
                )}
              </div>
              {pendingGameInfo.achievements > 0 && !slscheevoReady && (
                <div style={{ marginTop: "4px", fontSize: "11px", color: "#c8a84b", display: "flex", gap: "6px", alignItems: "flex-start" }}>
                  <span style={{ flexShrink: 0 }}>⚡</span>
                  <span>{t("slscheevoHint")}</span>
                </div>
              )}
            </div>
          </PanelSectionRow>
        )}
        {pendingNotices.length > 0 && (
          <PanelSectionRow>
            <div style={{
              width: "100%",
              background: "rgba(200, 168, 75, 0.08)",
              border: "1px solid rgba(200, 168, 75, 0.28)",
              borderLeft: "3px solid #c8a84b",
              borderRadius: "4px",
              padding: "8px 12px",
              display: "flex",
              flexDirection: "column",
              gap: "5px",
            }}>
              <div style={{
                fontSize: "10px",
                fontWeight: 700,
                color: "#c8a84b",
                textTransform: "uppercase",
                letterSpacing: "0.8px",
                marginBottom: "3px",
              }}>
                {t("gameNoticesTitle")}
              </div>
              {pendingNotices.map((notice, i) => (
                <div key={i} style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "7px",
                  fontSize: "12px",
                  color: "#e5e5e5",
                  lineHeight: "1.45",
                }}>
                  <span style={{ color: "#c8a84b", flexShrink: 0, marginTop: "1px" }}>▸</span>
                  <span>{notice}</span>
                </div>
              ))}
            </div>
          </PanelSectionRow>
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
                    : "#8bca68",
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
                      background: "linear-gradient(90deg, #4a9eff, #7ed36f)",
                      borderRadius: "3px",
                      transition: "width 0.4s ease",
                    }} />
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#9aa4b2" }}>
                    <span>
                      {downloadBytes.total > 0
                        ? `${(downloadBytes.read / 1073741824).toFixed(2)} / ${(downloadBytes.total / 1073741824).toFixed(2)} GB (${downloadPct}%)`
                        : `${downloadPct}%`}
                    </span>
                    {downloadSpeed > 0 && (
                      <span style={{ color: "#7ed36f" }}>
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
      </PanelSection>

      {/* Hubcap Search — extra bottom padding so keyboard doesn't hide the field */}
      <div style={{ paddingBottom: "280px" }}>
      <PanelSection title={t("searchByName")}>
        <PanelSectionRow>
          <TextField
            label={t("gameName")}
            value={searchQuery}
            onChange={(e: any) => setSearchQuery(e?.target?.value ?? "")}
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
      </PanelSection>
      </div>

      <PanelSection title={t("myGames")}>
        <PanelSectionRow>
          <TextField
            label={t("searchByName")}
            value={search}
            onChange={(e: any) => setSearch(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={cycleSortMode}>
            {t("sort")}: {sortLabels[sortMode]}
          </ButtonItem>
        </PanelSectionRow>

        {loading ? (
          <PanelSectionRow>
            <div
              style={{ textAlign: "center", padding: "20px", color: "#8b929a" }}
            >
              {t("loadingGames")}
            </div>
          </PanelSectionRow>
        ) : filtered.length === 0 ? (
          <PanelSectionRow>
            <div
              style={{ textAlign: "center", padding: "20px", color: "#8b929a" }}
            >
              {search ? t("noGamesMatch") : t("noGamesYet")}
            </div>
          </PanelSectionRow>
        ) : (
          filtered.map((game: GameInfo) => (
            <GameCard
              key={game.appid}
              game={
                activeDownloadId === game.appid
                  ? { ...game, downloadStatus: activeDownloadPhase }
                  : game
              }
              onClick={navigateToDetail}
            />
          ))
        )}
      </PanelSection>

      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => Navigation.Navigate(ROUTE_DOWNLOADS)}
          >
            {t("activeDownloads")}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => Navigation.Navigate(ROUTE_SETTINGS)}
          >
            {t("settings")}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => loadGames()}>
            {t("refresh")}
          </ButtonItem>
        </PanelSectionRow>
        {slscheevoReady && (
          <>
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
          </>
        )}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => restartSteam()}
          >
            {t("restartSteam")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
