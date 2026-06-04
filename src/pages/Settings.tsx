import { useEffect, useState } from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  ToggleField,
  Navigation,
} from "@decky/ui";
import { toaster } from "@decky/api";
import {
  saveRyuCookie,
  loadRyuCookie,
  updateHubcapKey,
  loadHubcapKey,
  fetchFreeApisNow,
  checkDependencies,
  installDependencies,
  getPlatformSummary,
  verifySlssteamInjected,
  getSlsPlayStatus,
  setSlsPlayStatus,
  getSteamLibraries,
  restartSteam,
  checkSlssteamHashStatus,
  repairSlssteamHeadcrab,
} from "../api";
import { useT, getLanguage, setLanguage } from "../i18n";

export function Settings() {
  const t = useT();
  const [ryuCookie, setRyuCookie] = useState("");
  const [hubcapKey, setHubcapKey] = useState("");
  const [deps, setDeps] = useState<any>(null);
  const [platform, setPlatform] = useState<any>(null);
  const [playNotOwned, setPlayNotOwned] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [unknownHash, setUnknownHash] = useState(false);
  const [lang, setLang] = useState(getLanguage());
  const [libraries, setLibraries] = useState<any[]>([]);

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || "", duration });

  useEffect(() => {
    const load = async () => {
      const cookieResult = await loadRyuCookie();
      if (cookieResult.success && cookieResult.cookie) {
        setRyuCookie(cookieResult.cookie);
      }

      const keyResult = await loadHubcapKey();
      if (keyResult.success && keyResult.key) {
        setHubcapKey(keyResult.key);
      }

      const depsResult = await checkDependencies();
      if (depsResult.success) setDeps(depsResult);

      const platformResult = await getPlatformSummary();
      setPlatform(platformResult);

      const playResult = await getSlsPlayStatus();
      if (playResult.success) setPlayNotOwned(playResult.enabled);

      const hashResult = await checkSlssteamHashStatus();
      if (hashResult.success) setUnknownHash(hashResult.unknown_hash);

      const libResult = await getSteamLibraries();
      if (libResult.success && libResult.libraries) setLibraries(libResult.libraries);
    };
    load();
  }, []);

  const handleSaveCookie = async () => {
    const result = await saveRyuCookie(ryuCookie);
    if (result.success || result.message) {
      toast(t("toastCookieSaved"));
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleSaveHubcapKey = async () => {
    const result = await updateHubcapKey(hubcapKey);
    if (result.success || result.message) {
      toast(t("toastApiKeySaved"));
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleUpdateApis = async () => {
    toast(t("updatingApis"), "", 2000);
    const result = await fetchFreeApisNow();
    if (result.success) {
      toast(t("toastApisUpdated", result.count));
    } else {
      toast(t("toastError"), result.error || t("updateFailed"), 4000);
    }
  };

  const handleInstallDeps = async () => {
    setInstalling(true);
    toast(t("installingDeps"), "", 2000);
    await installDependencies();
    const result = await checkDependencies();
    if (result.success) setDeps(result);
    setInstalling(false);
    toast(t("toastDepsInstalled"));
  };

  const handleVerifyInjection = async () => {
    const result = await verifySlssteamInjected();
    if (result.already_ok) {
      toast(t("toastInjectionOk"));
    } else if (result.patched) {
      toast(t("toastInjectionPatched"));
    } else {
      toast(
        t("toastError"),
        `${t("slssteamInjection")}: ${result.error || "Failed"}`,
        4000,
      );
    }
  };

  const handleTogglePlayNotOwned = async (value: boolean) => {
    setPlayNotOwned(value);
    await setSlsPlayStatus(value);
  };

  const handleRepairHeadcrab = async () => {
    setRepairing(true);
    toast(t("repairingHeadcrab"), t("repairingHeadcrabBody"), 20000);
    const result = await repairSlssteamHeadcrab();
    setRepairing(false);
    if (result.success) {
      setUnknownHash(false);
      toast(t("headcrabRepaired"), t("headcrabRepairedBody"), 6000);
    } else {
      toast(t("toastError"), result.error || `step: ${result.step}`, 6000);
    }
  };

  return (
    <>
      <PanelSection title={t("apiCredentials")}>
        <PanelSectionRow>
          <TextField
            label={t("ryuCookie")}
            value={ryuCookie}
            onChange={(e: any) => setRyuCookie(e?.target?.value ?? "")}
            bIsPassword
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleSaveCookie}>
            {t("saveCookie")}
          </ButtonItem>
        </PanelSectionRow>

        <PanelSectionRow>
          <TextField
            label={t("hubcapApiKey")}
            value={hubcapKey}
            onChange={(e: any) => setHubcapKey(e?.target?.value ?? "")}
            bIsPassword
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleSaveHubcapKey}>
            {t("saveHubcapKey")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("apis")}>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleUpdateApis}>
            {t("updateFreeApis")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("slssteam")}>
        <PanelSectionRow>
          <ToggleField
            label={t("playNotOwnedGames")}
            checked={playNotOwned}
            onChange={handleTogglePlayNotOwned}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleVerifyInjection}>
            {t("verifySlssteamInjection")}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => restartSteam()}>
            {t("restartSteam")}
          </ButtonItem>
        </PanelSectionRow>
        {unknownHash && (
          <>
            <PanelSectionRow>
              <div style={{ fontSize: "11px", color: "#ffaa00" }}>
                ⚠ {t("slssteamUnknownHash")}
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={handleRepairHeadcrab}
                disabled={repairing}
              >
                {repairing ? t("repairingHeadcrab") : t("repairSlssteamHeadcrab")}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      <PanelSection title={t("dependencies")}>
        {deps && (
          <>
            <PanelSectionRow>
              <div
                style={{
                  fontSize: "12px",
                  color: deps.accela ? "#00cc00" : "#ff4444",
                }}
              >
                ACCELA:{" "}
                {deps.accela
                  ? `${t("installed")} (${deps.accelaPath})`
                  : t("notFound")}
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <div
                style={{
                  fontSize: "12px",
                  color: deps.slssteam ? "#00cc00" : "#ff4444",
                }}
              >
                SLSsteam:{" "}
                {deps.slssteam
                  ? `${t("installed")} (${deps.slssteamPath})`
                  : t("notFound")}
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <div
                style={{
                  fontSize: "12px",
                  color: deps.dotnet ? "#00cc00" : "#ff4444",
                }}
              >
                .NET Runtime: {deps.dotnet ? t("installed") : t("notFound")}
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <div
                style={{
                  fontSize: "12px",
                  color: deps.lumalinux ? "#00cc00" : "#ff4444",
                }}
              >
                lumalinux:{" "}
                {deps.lumalinux
                  ? `${t("installed")} (${deps.lumalinuxPath})`
                  : t("notFound")}
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <div
                style={{
                  fontSize: "12px",
                  color: deps.cloudredirect ? "#00cc00" : "#ff4444",
                }}
              >
                CloudRedirect:{" "}
                {deps.cloudredirect
                  ? `${t("installed")} (${deps.cloudredirectPath})`
                  : t("notFound")}
              </div>
            </PanelSectionRow>
          </>
        )}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleInstallDeps}
            disabled={installing}
          >
            {installing ? t("installing") : t("installReinstallDeps")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("languageIdioma")}>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => {
              const next = lang === "en" ? "pt-BR" : "en";
              setLanguage(next as any);
              setLang(next as any);
            }}
          >
            {lang === "en" ? "Português (BR)" : "English"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div
            style={{ fontSize: "11px", color: "#8b929a", textAlign: "center" }}
          >
            {lang === "en" ? t("currentEnglish") : t("currentPortuguese")}
          </div>
        </PanelSectionRow>
      </PanelSection>

      {platform && (
        <PanelSection title={t("platform")}>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", color: "#8b929a" }}>
              Steam: {platform.steam_root || t("notFound")}
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      {libraries.length > 0 && (
        <PanelSection title={t("steamLibraries")}>
          {libraries.map((lib: any, idx: number) => {
            const freeGB = (lib.freeBytes / (1024 * 1024 * 1024)).toFixed(1);
            const totalGB = (lib.totalBytes / (1024 * 1024 * 1024)).toFixed(1);
            const usedPercent = lib.totalBytes > 0
              ? Math.round(((lib.totalBytes - lib.freeBytes) / lib.totalBytes) * 100)
              : 0;
            return (
              <PanelSectionRow key={lib.path}>
                <div>
                  <div style={{ fontSize: "12px", color: "#dcdedf" }}>
                    {lib.path} {idx === 0 && `(${t("defaultLibrary")})`}
                  </div>
                  <div style={{ fontSize: "11px", color: "#8b929a" }}>
                    {t("freeSpace", `${freeGB} / ${totalGB} GB`)} — {t("libraryGames", lib.gameCount)}
                  </div>
                  <div style={{
                    height: "4px",
                    background: "#2a2d35",
                    borderRadius: "2px",
                    marginTop: "4px",
                    overflow: "hidden",
                  }}>
                    <div style={{
                      height: "100%",
                      width: `${usedPercent}%`,
                      background: usedPercent > 90 ? "#ff4444" : usedPercent > 75 ? "#ffaa00" : "#1a9fff",
                      borderRadius: "2px",
                    }} />
                  </div>
                </div>
              </PanelSectionRow>
            );
          })}
        </PanelSection>
      )}

      <PanelSection>
        <ButtonItem layout="below" onClick={() => Navigation.NavigateBack()}>
          {t("back")}
        </ButtonItem>
      </PanelSection>

      <div style={{ height: "48px" }} />
    </>
  );
}
