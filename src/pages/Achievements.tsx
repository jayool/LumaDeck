import { useEffect, useState, useRef } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  ProgressBarWithInfo,
} from "@decky/ui";
import { toaster } from "@decky/api";
import {
  getInstalledLuaScripts,
  checkSlscheevoInstalled,
  checkAllAchievementsStatus,
  downloadSlscheevo,
  getSlscheevoDownloadStatus,
  runDesktopHandoffSlscheevo,
  generateAllAchievements,
  getSyncAllStatus,
  restartSteam,
} from "../api";
import { useT } from "../i18n";
import { FaCheckCircle, FaExclamationTriangle } from "react-icons/fa";

// Full-screen global Achievements page (route ROUTE_ACHIEVEMENTS). Everything
// GLOBAL to SLScheevo lives here — installing the binary, the one-time login,
// and "Sync All". Per-game generation stays on the game page (GameDetail).
// No SidebarNavigation: it's a single concern, so a plain scroll page (same
// wrapper as Downloads/Library) reads cleaner than a one-item sidebar.
export function Achievements() {
  const t = useT();
  const [slscheevo, setSlscheevo] = useState<{
    installed: boolean;
    loginReady: boolean;
    binaryPath?: string | null;
  }>({ installed: false, loginReady: false, binaryPath: null });
  const [overview, setOverview] = useState<{ done: number; total: number } | null>(null);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [syncState, setSyncState] = useState<any>(null);

  const dlPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dlTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || "", duration });

  // Appids of games with a Lua and downloaded files — the sync set. Also used
  // for the "X of Y generated" overview.
  const loadState = async () => {
    const [sls, lua] = await Promise.all([
      checkSlscheevoInstalled(),
      getInstalledLuaScripts(),
    ]);
    if (sls?.success) {
      setSlscheevo({
        installed: !!sls.installed,
        loginReady: !!sls.loginReady,
        binaryPath: sls.binaryPath,
      });
    }
    const appids: number[] =
      lua?.success && lua.scripts
        ? lua.scripts.filter((s: any) => s.hasGameFiles).map((s: any) => s.appid)
        : [];
    if (appids.length > 0) {
      try {
        const ach = await checkAllAchievementsStatus(appids);
        if (ach?.success && ach.map) {
          const done = appids.filter((id) => ach.map[id]).length;
          setOverview({ done, total: appids.length });
        }
      } catch {
        setOverview(null);
      }
    } else {
      setOverview({ done: 0, total: 0 });
    }
  };

  useEffect(() => {
    loadState();
    return () => {
      if (dlPollRef.current) clearInterval(dlPollRef.current);
      if (dlTimeoutRef.current) clearTimeout(dlTimeoutRef.current);
      if (syncPollRef.current) clearInterval(syncPollRef.current);
    };
  }, []);

  const handleDownload = async () => {
    setDownloadBusy(true);
    const result = await downloadSlscheevo();
    if (!result.success) {
      setDownloadBusy(false);
      toast(t("toastError"), result.error || "", 4000);
      return;
    }
    dlPollRef.current = setInterval(async () => {
      const status = await getSlscheevoDownloadStatus();
      if (status?.success && status.state) {
        if (status.state.status === "done") {
          if (dlPollRef.current) clearInterval(dlPollRef.current);
          if (dlTimeoutRef.current) clearTimeout(dlTimeoutRef.current);
          setDownloadBusy(false);
          await loadState();
          toast(t("toastSlscheevoInstalled"));
        } else if (status.state.status === "error") {
          if (dlPollRef.current) clearInterval(dlPollRef.current);
          if (dlTimeoutRef.current) clearTimeout(dlTimeoutRef.current);
          setDownloadBusy(false);
          toast(t("toastSlscheevoDownloadFailed"), status.state.error || "", 5000);
        }
      }
    }, 1000);
    dlTimeoutRef.current = setTimeout(() => {
      if (dlPollRef.current) clearInterval(dlPollRef.current);
      setDownloadBusy(false);
    }, 120000);
  };

  const handleConfigureLogin = async () => {
    // SLScheevo's login is an interactive terminal flow — Desktop only. Arm a
    // hand-off that opens Konsole already running it, then switch to Desktop.
    const r: any = await runDesktopHandoffSlscheevo();
    if (r?.switchLaunched) toast(t("achievements"), t("slscheevoConfigSwitching"), 8000);
    else if (r?.armed) toast(t("achievements"), t("slscheevoConfigManual"), 12000);
    else toast(t("toastError"), r?.error || "", 6000);
  };

  const handleSyncAll = async () => {
    const lua = await getInstalledLuaScripts();
    const appids: number[] =
      lua?.success && lua.scripts
        ? lua.scripts.filter((s: any) => s.hasGameFiles).map((s: any) => s.appid)
        : [];
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
        if (status?.success && status.state) {
          setSyncState(status.state);
          if (status.state.status === "done") {
            if (syncPollRef.current) clearInterval(syncPollRef.current);
            syncPollRef.current = null;
            toast(t("toastSyncComplete"));
            await loadState();
            setTimeout(() => setSyncState(null), 3000);
          }
        }
      } catch {}
    }, 2000);
  };

  const scheevoDir = slscheevo.binaryPath
    ? slscheevo.binaryPath.substring(0, slscheevo.binaryPath.lastIndexOf("/"))
    : "";
  const scheevoBin = slscheevo.binaryPath
    ? slscheevo.binaryPath.substring(slscheevo.binaryPath.lastIndexOf("/") + 1)
    : "";
  const syncing = syncState?.status === "running";

  // Plain full-screen page (same wrapper as Downloads/Library): no sidebar.
  return (
    <div style={{ marginTop: "72px", height: "calc(100% - 72px)", overflowY: "scroll" }}>
      <PanelSection title={t("achievements")}>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8 }}>{t("achievementsPageIntro")}</div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("achievementsSetup")}>
        {/* Status: binary + login */}
        <PanelSectionRow>
          <Field focusable highlightOnFocus={false} label="SLScheevo">
            <span style={{ color: slscheevo.installed ? "#00cc00" : "#ff4444" }}>
              {slscheevo.installed ? t("installed") : t("notFound")}
            </span>
          </Field>
        </PanelSectionRow>
        {slscheevo.installed && (
          <PanelSectionRow>
            <Field focusable highlightOnFocus={false} label={t("achievementsLogin")}>
              <span style={{ color: slscheevo.loginReady ? "#00cc00" : "#ffaa00" }}>
                {slscheevo.loginReady ? t("slscheevoLoginReady") : t("slscheevoLoginNeeded")}
              </span>
            </Field>
          </PanelSectionRow>
        )}

        {/* Step 1: install the binary */}
        {!slscheevo.installed && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={downloadBusy} onClick={handleDownload}>
              {downloadBusy ? t("downloadingSlscheevo") : t("downloadSlscheevo")}
            </ButtonItem>
          </PanelSectionRow>
        )}

        {/* Step 2: one-time login (Desktop) */}
        {slscheevo.installed && !slscheevo.loginReady && (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleConfigureLogin}>
                {t("configureInDesktop")}
              </ButtonItem>
            </PanelSectionRow>
            {slscheevo.binaryPath && (
              <PanelSectionRow>
                <Field
                  label={t("slscheevoRunInTerminal")}
                  description={
                    <span style={{ fontFamily: "monospace", wordBreak: "break-all" }}>
                      {t("slscheevoPath", scheevoDir, scheevoBin)}
                    </span>
                  }
                />
              </PanelSectionRow>
            )}
          </>
        )}

        {slscheevo.installed && slscheevo.loginReady && (
          <PanelSectionRow>
            <Field icon={<FaCheckCircle color="#00cc00" />} label={t("achievementsReadyAll")} />
          </PanelSectionRow>
        )}
      </PanelSection>

      {/* Sync All + overview — only once setup is done */}
      {slscheevo.installed && slscheevo.loginReady && (
        <PanelSection title={t("syncAllAchievements")}>
          {overview && (
            <PanelSectionRow>
              <Field label={t("achievementsOverview", overview.done, overview.total)} />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={syncing} onClick={handleSyncAll}>
              {syncing ? t("syncingAchievements") : t("syncAllAchievements")}
            </ButtonItem>
          </PanelSectionRow>
          {syncing && (
            <PanelSectionRow>
              <ProgressBarWithInfo
                nProgress={
                  syncState.total > 0
                    ? Math.round((syncState.done / syncState.total) * 100)
                    : 0
                }
                sOperationText={`${syncState.done || 0} / ${syncState.total || 0}`}
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <Field
              icon={<FaExclamationTriangle color="#c8a84b" />}
              label={t("achievementsRestartHint")}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => restartSteam()}>
              {t("restartSteam")}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}
    </div>
  );
}
