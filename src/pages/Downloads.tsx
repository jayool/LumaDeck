import { useEffect, useState } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  TextField,
  SidebarNavigation,
} from "@decky/ui";
import { FaDownload, FaTools } from "react-icons/fa";
import { toaster } from "@decky/api";
import { ProgressBar } from "../components/ProgressBar";
import {
  getDownloadStatus,
  cancelDownload,
  startWorkshopDownload,
  getWorkshopDownloadStatus,
  cancelWorkshopDownload,
  startDownload,
} from "../api";
import { useT } from "../i18n";

interface ActiveDownload {
  appid: number;
  status: string;
  bytesRead: number;
  totalBytes: number;
  currentApi?: string;
  error?: string;
}

export function Downloads() {
  const t = useT();
  const [downloads, setDownloads] = useState<ActiveDownload[]>([]);
  const [workshopState, setWorkshopState] = useState<any>(null);
  const [manualAppId, setManualAppId] = useState("");
  const [workshopAppId, setWorkshopAppId] = useState("");
  const [workshopPubfileId, setWorkshopPubfileId] = useState("");

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || "", duration });

  const statusLabel = (status: string): string => {
    if (status === "downloading") return t("statusDownloading");
    if (status === "checking") return t("statusChecking");
    if (status === "processing") return t("statusProcessing");
    if (status === "configuring") return t("statusConfiguring");
    // depot_download is dead code (the DDL backend no longer runs); kept
    // so a rollback would still have the matching UI label.
    if (status === "depot_download") return t("statusDownloadingGame");
    if (status === "installing") return t("statusInstalling");
    if (status === "queued") return t("statusQueued");
    if (status === "restarting_steam") return t("statusRestartingSteam");
    if (status === "done") return t("downloadComplete");
    if (status === "failed") return t("downloadFailed");
    if (status === "cancelled") return t("downloadCancelled");
    return status;
  };

  // Poll active downloads
  useEffect(() => {
    const interval = setInterval(async () => {
      const ws = await getWorkshopDownloadStatus();
      if (ws && ws.status !== "idle") {
        setWorkshopState(ws);
      } else {
        setWorkshopState(null);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleManualDownload = async () => {
    const appid = parseInt(manualAppId, 10);
    if (!appid || isNaN(appid)) {
      toast(t("toastError"), t("enterValidAppId"), 3000);
      return;
    }
    const result = await startDownload(appid);
    if (result.success) {
      setDownloads((prev: ActiveDownload[]) => [
        ...prev.filter((d: ActiveDownload) => d.appid !== appid),
        { appid, status: "queued", bytesRead: 0, totalBytes: 0 },
      ]);
      setManualAppId("");
      toast(t("toastDownloadStarted"), `AppID: ${appid}`, 2000);
    } else {
      toast(t("toastError"), result.error || t("downloadFailed"), 4000);
    }
  };

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

  // Poll individual download states
  useEffect(() => {
    if (downloads.length === 0) return;
    const interval = setInterval(async () => {
      const updated = await Promise.all(
        downloads.map(async (d: ActiveDownload) => {
          if (["done", "failed", "cancelled"].includes(d.status)) return d;
          const status = await getDownloadStatus(d.appid);
          if (status.success && status.state) {
            return { ...d, ...status.state };
          }
          return d;
        }),
      );
      setDownloads(updated);
    }, 1500);
    return () => clearInterval(interval);
  }, [downloads]);

  const pages = [
    {
      title: t("manualDownload"),
      icon: <FaDownload />,
      hideTitle: true,
      content: (
        <>
      <PanelSection title={t("manualDownload")}>
        <PanelSectionRow>
          <TextField
            label="AppID"
            value={manualAppId}
            onChange={(e: any) => setManualAppId(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleManualDownload}>
            {t("downloadManifest")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {/* Active Downloads */}
      {downloads.length > 0 && (
        <PanelSection title={t("activeDownloads")}>
          {downloads.map((d: ActiveDownload) => (
            <PanelSectionRow key={d.appid}>
              <div>
                <div style={{ fontSize: "13px", color: "#dcdedf" }}>
                  AppID: {d.appid} — {statusLabel(d.status)}
                </div>
                {d.currentApi && (
                  <div style={{ fontSize: "11px", color: "#8b929a" }}>
                    API: {d.currentApi}
                  </div>
                )}
                {d.totalBytes > 0 && (
                  <ProgressBar value={d.bytesRead} max={d.totalBytes} />
                )}
                {d.error && (
                  <div style={{ fontSize: "11px", color: "#ff4444" }}>
                    {d.error}
                  </div>
                )}
                {!["done", "failed", "cancelled"].includes(d.status) && (
                  <ButtonItem
                    layout="below"
                    onClick={async () => {
                      await cancelDownload(d.appid);
                      setDownloads((prev: ActiveDownload[]) =>
                        prev.map((x: ActiveDownload) =>
                          x.appid === d.appid
                            ? { ...x, status: "cancelled" }
                            : x,
                        ),
                      );
                    }}
                  >
                    {t("cancel")}
                  </ButtonItem>
                )}
              </div>
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}
        </>
      ),
    },
    {
      title: t("workshopDownload"),
      icon: <FaTools />,
      hideTitle: true,
      content: (
      <PanelSection title={t("workshopDownload")}>
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
              <div style={{ fontSize: "12px", color: "#dcdedf" }}>
                {workshopState.message || statusLabel(workshopState.status)}
              </div>
            </PanelSectionRow>
            {workshopState.progress > 0 &&
              workshopState.status === "downloading" && (
                <PanelSectionRow>
                  <ProgressBar
                    value={workshopState.progress}
                    max={100}
                    label={t("workshopDownload")}
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
      ),
    },
  ];

  return <SidebarNavigation title="LumaDeck" pages={pages} />;
}
