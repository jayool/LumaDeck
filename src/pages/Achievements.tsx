import { useEffect, useState, useRef } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  TextField,
  ProgressBarWithInfo,
} from "@decky/ui";
import { toaster } from "@decky/api";
import {
  getInstalledLuaScripts,
  getApiKeyStatus,
  setSteamApiKey,
  checkAllAchievementsStatus,
  generateAllAchievements,
  getSyncAllStatus,
  restartSteam,
} from "../api";
import { useT } from "../i18n";
import { FaCheckCircle, FaExclamationTriangle } from "react-icons/fa";

// Full-screen global Achievements page (route ROUTE_ACHIEVEMENTS). Everything
// GLOBAL lives here — the Steam Web API key and "Sync All". Per-game generation
// stays on the game page (GameDetail). No SidebarNavigation: single concern.
export function Achievements() {
  const t = useT();
  const [keySet, setKeySet] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [overview, setOverview] = useState<{ done: number; total: number } | null>(null);
  const [syncState, setSyncState] = useState<any>(null);

  const syncPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || "", duration });

  const loadState = async () => {
    const [ks, lua] = await Promise.all([getApiKeyStatus(), getInstalledLuaScripts()]);
    if (ks?.success) setKeySet(!!ks.keySet);
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
      if (syncPollRef.current) clearInterval(syncPollRef.current);
    };
  }, []);

  const handleSaveKey = async () => {
    setSavingKey(true);
    const r = await setSteamApiKey(keyInput.trim());
    setSavingKey(false);
    if (r?.success) {
      setKeyInput("");
      await loadState();
      toast(t("apiKeySaved"));
    } else {
      toast(t("toastError"), r?.error || "", 5000);
    }
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

  const syncing = syncState?.status === "running";

  return (
    <div style={{ marginTop: "72px", height: "calc(100% - 72px)", overflowY: "scroll" }}>
      <PanelSection title={t("achievements")}>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8 }}>{t("achievementsPageIntro")}</div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("achievementsSetup")}>
        <PanelSectionRow>
          <Field focusable highlightOnFocus={false} label={t("apiKeyLabel")}>
            <span style={{ color: keySet ? "#00cc00" : "#ffaa00" }}>
              {keySet ? t("apiKeySet") : t("apiKeyMissing")}
            </span>
          </Field>
        </PanelSectionRow>

        {!keySet && (
          <>
            <PanelSectionRow>
              <div style={{ fontSize: "12px", opacity: 0.8 }}>
                {t("apiKeyHelp")}{" "}
                <span style={{ fontFamily: "monospace", wordBreak: "break-all" }}>
                  steamcommunity.com/dev/apikey
                </span>
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <TextField
                label={t("apiKeyLabel")}
                value={keyInput}
                bIsPassword={true}
                onChange={(e: any) => setKeyInput(e?.target?.value ?? "")}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={savingKey || keyInput.trim().length < 32}
                onClick={handleSaveKey}
              >
                {savingKey ? t("saving") : t("saveApiKey")}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}

        {keySet && (
          <PanelSectionRow>
            <Field icon={<FaCheckCircle color="#00cc00" />} label={t("achievementsReadyAll")} />
          </PanelSectionRow>
        )}
      </PanelSection>

      {keySet && (
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
