import { useEffect, useState } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  TextField,
  Field,
  ProgressBarWithInfo,
} from "@decky/ui";
import { toaster } from "@decky/api";
import {
  startWorkshopDownload,
  getWorkshopDownloadStatus,
  cancelWorkshopDownload,
} from "../api";
import { useT } from "../i18n";

// The QAM "Workshop" entry (route still ROUTE_DOWNLOADS internally). Adding games
// is done from the QAM's Add Game now, so the old "Manual Download" tab + the
// active-downloads list were dropped: this is a single Workshop screen.
export function Downloads() {
  const t = useT();
  const [workshopState, setWorkshopState] = useState<any>(null);
  const [workshopAppId, setWorkshopAppId] = useState("");
  const [workshopPubfileId, setWorkshopPubfileId] = useState("");

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || "", duration });

  const statusLabel = (status: string): string => {
    if (status === "downloading") return t("statusDownloading");
    if (status === "checking") return t("statusChecking");
    if (status === "processing") return t("statusProcessing");
    if (status === "configuring") return t("statusConfiguring");
    if (status === "installing") return t("statusInstalling");
    if (status === "queued") return t("statusQueued");
    if (status === "done") return t("downloadComplete");
    if (status === "failed") return t("downloadFailed");
    if (status === "cancelled") return t("downloadCancelled");
    return status;
  };

  // Poll the workshop download until it goes idle.
  useEffect(() => {
    const interval = setInterval(async () => {
      const ws = await getWorkshopDownloadStatus();
      if (ws && ws.status !== "idle") setWorkshopState(ws);
      else setWorkshopState(null);
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleWorkshopDownload = async () => {
    const appid = parseInt(workshopAppId, 10);
    const pubfileId = parseInt(workshopPubfileId, 10);
    if (!appid || !pubfileId || isNaN(appid) || isNaN(pubfileId)) {
      toast(t("toastError"), t("enterValidIds"), 3000);
      return;
    }
    const result = await startWorkshopDownload(appid, pubfileId);
    if (result.success) {
      setWorkshopState({
        status: "downloading",
        progress: 0,
        message: t("startingDownload"),
      });
      toast(t("toastDownloadStarted"), `Workshop ${pubfileId}`, 2000);
    } else {
      toast(t("toastError"), result.error || t("downloadFailed"), 4000);
    }
  };

  const handleCancelWorkshop = async () => {
    await cancelWorkshopDownload();
  };

  // Plain full-screen page (same wrapper as Library): no SidebarNavigation now
  // that there's a single screen.
  return (
    <div style={{ marginTop: "72px", height: "calc(100% - 72px)", overflowY: "scroll" }}>
      <PanelSection title={t("workshop")}>
        <PanelSectionRow>
          <TextField
            label="AppID"
            value={workshopAppId}
            onChange={(e: any) => setWorkshopAppId(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField
            label={t("workshopItemId")}
            value={workshopPubfileId}
            onChange={(e: any) => setWorkshopPubfileId(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleWorkshopDownload}>
            {t("downloadWorkshopItem")}
          </ButtonItem>
        </PanelSectionRow>
        {workshopState && (
          <>
            <PanelSectionRow>
              <Field label={workshopState.message || statusLabel(workshopState.status)} />
            </PanelSectionRow>
            {workshopState.progress > 0 && workshopState.status === "downloading" && (
              <PanelSectionRow>
                <ProgressBarWithInfo
                  nProgress={workshopState.progress}
                  sOperationText={statusLabel(workshopState.status)}
                />
              </PanelSectionRow>
            )}
            {workshopState.status === "downloading" && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={handleCancelWorkshop}>
                  {t("cancelWorkshopDownload")}
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>
    </div>
  );
}
