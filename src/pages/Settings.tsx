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
  installCloudredirect,
  installLumalinux,
  getPlatformSummary,
  verifySlssteamInjected,
  getSlsPlayStatus,
  setSlsPlayStatus,
  getSteamLibraries,
  restartSteam,
  checkSlssteamHashStatus,
  checkHeadcrabCompat,
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
  const [confirmInstallDeps, setConfirmInstallDeps] = useState(false);
  const [installingCR, setInstallingCR] = useState(false);
  const [confirmInstallCR, setConfirmInstallCR] = useState(false);
  const [installingLL, setInstallingLL] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [unknownHash, setUnknownHash] = useState(false);
  const [headcrabCompat, setHeadcrabCompat] = useState<{
    current_build: number | null;
    target: number | null;
    compatible: boolean;
  } | null>(null);
  const [lang, setLang] = useState(getLanguage());
  const [libraries, setLibraries] = useState<any[]>([]);

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || "", duration });

  useEffect(() => {
    let cancelled = false;

    const refreshDeps = async () => {
      if (cancelled) return;
      const depsResult = await checkDependencies();
      if (!cancelled && depsResult.success) setDeps(depsResult);
    };

    const load = async () => {
      const cookieResult = await loadRyuCookie();
      if (!cancelled && cookieResult.success && cookieResult.cookie) {
        setRyuCookie(cookieResult.cookie);
      }

      const keyResult = await loadHubcapKey();
      if (!cancelled && keyResult.success && keyResult.key) {
        setHubcapKey(keyResult.key);
      }

      await refreshDeps();

      const platformResult = await getPlatformSummary();
      if (!cancelled) setPlatform(platformResult);

      const playResult = await getSlsPlayStatus();
      if (!cancelled && playResult.success) setPlayNotOwned(playResult.enabled);

      const hashResult = await checkSlssteamHashStatus();
      if (!cancelled && hashResult.success) setUnknownHash(hashResult.unknown_hash);

      const compatResult = await checkHeadcrabCompat();
      if (!cancelled && compatResult.success) {
        setHeadcrabCompat({
          current_build: compatResult.current_build,
          target: compatResult.target,
          compatible: compatResult.compatible,
        });
      }

      const libResult = await getSteamLibraries();
      if (!cancelled && libResult.success && libResult.libraries) setLibraries(libResult.libraries);
    };

    load();

    // Issue #18: when an install button kicks `steam -shutdown` mid-flight,
    // the plugin UI gets torn down and re-mounted before the backend chain
    // has finished (flatpak install can take 30 s). The initial useEffect
    // fetches deps too early and the panel sticks on stale "not found".
    // Poll a few times after mount so the eventual finished state lands.
    const retries = [3000, 7000, 12000];
    const timers = retries.map((delay) => setTimeout(refreshDeps, delay));

    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
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
    // Two-click confirm pattern (same as the uninstall flow in
    // GameDetail.tsx): first click flips a flag and arms a 5 s timeout to
    // reset it, second click within that window triggers the actual
    // install. Justified here because enter-the-wired → headcrab.sh runs
    // `killall steam` unconditionally early in its flow, so pulling the
    // trigger drops the user's gamemode session.
    if (!confirmInstallDeps) {
      setConfirmInstallDeps(true);
      setTimeout(() => setConfirmInstallDeps(false), 5000);
      return;
    }
    setConfirmInstallDeps(false);
    setInstalling(true);
    toast(t("installingDeps"), "", 2000);
    const installResult = await installDependencies();
    const result = await checkDependencies();
    if (result.success) setDeps(result);
    setInstalling(false);
    if (installResult.success) {
      toast(t("toastDepsInstalled"));
    } else {
      toast(t("toastError"), installResult.error || "", 6000);
    }
  };

  const handleEnableCR = async () => {
    // Same two-click pattern as the deps install — headcrab.pages.dev's
    // nuketheclient() calls `killall steam` unconditionally, so this also
    // drops the user's gamemode session.
    if (!confirmInstallCR) {
      setConfirmInstallCR(true);
      setTimeout(() => setConfirmInstallCR(false), 5000);
      return;
    }
    setConfirmInstallCR(false);
    setInstallingCR(true);
    toast(t("installingCR"), "", 2000);
    const result = await installCloudredirect();
    const depsResult = await checkDependencies();
    if (depsResult.success) setDeps(depsResult);
    setInstallingCR(false);
    if (result.success) {
      // Provider sign-in is GUI-only — surface the desktop-mode step.
      // If the user already had tokens from a previous setup, suppress
      // the nudge (re-running the install shouldn't ask them again).
      if (!depsResult.cloudredirectAuthed) {
        toast(t("crInstalled"), t("crInstalledBody"), 8000);
      } else {
        toast(t("crInstalled"));
      }
    } else {
      toast(t("toastError"), "", 4000);
    }
  };

  const handleInstallLumalinux = async () => {
    // lumalinux/install.sh only patches steam.sh + drops the .so. It doesn't
    // kill Steam by itself. We do trigger a clean `steam -shutdown` after
    // success though, to mirror the deps/CR buttons: the user gets a "one
    // tap → done" flow instead of having to remember to restart Steam
    // separately to actually load lumalinux. `steam -shutdown` is the same
    // IPC the Restart Steam button uses, and gamescope-session treats it
    // as a clean exit (no recovery loop).
    setInstallingLL(true);
    toast(t("installingLL"), "", 2000);
    const result = await installLumalinux();
    const depsResult = await checkDependencies();
    if (depsResult.success) setDeps(depsResult);
    setInstallingLL(false);
    if (result.success) {
      toast(t("llInstalled"), t("llInstalledBody"), 4000);
      await restartSteam();
    } else {
      toast(t("toastError"), "", 4000);
    }
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
                disabled={repairing || (headcrabCompat ? !headcrabCompat.compatible : false)}
              >
                {repairing ? t("repairingHeadcrab") : t("repairSlssteamHeadcrab")}
              </ButtonItem>
            </PanelSectionRow>
            {headcrabCompat && !headcrabCompat.compatible && (
              <PanelSectionRow>
                <div style={{
                  fontSize: "11px",
                  color: "#aaa",
                  lineHeight: "1.4",
                  padding: "4px 0",
                }}>
                  <div style={{ color: "#ff8c00", fontWeight: 600, marginBottom: "4px" }}>
                    ⚠ {t("headcrabGameModeBlockTitle")}
                  </div>
                  <div style={{ marginBottom: "6px" }}>
                    {t("headcrabGameModeBlockBody")}
                  </div>
                  <div style={{
                    fontFamily: "monospace",
                    fontSize: "10px",
                    color: "#ccc",
                    background: "rgba(0,0,0,0.3)",
                    padding: "4px 6px",
                    borderRadius: "3px",
                    wordBreak: "break-all",
                  }}>
                    {t("headcrabGameModeBlockCommand")}
                  </div>
                </div>
              </PanelSectionRow>
            )}
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
            {deps.cloudredirect && (
              <PanelSectionRow>
                <div
                  style={{
                    fontSize: "12px",
                    color: deps.cloudredirectAuthed ? "#00cc00" : "#ffaa00",
                  }}
                >
                  {t("cloudredirectProvider")}:{" "}
                  {deps.cloudredirectAuthed
                    ? t("providerConfigured")
                    : t("providerNotConfigured")}
                </div>
              </PanelSectionRow>
            )}
          </>
        )}
        {headcrabCompat && (
          <PanelSectionRow>
            <div
              style={{
                fontSize: "12px",
                color: headcrabCompat.compatible ? "#00cc00" : "#ff8c00",
              }}
            >
              {headcrabCompat.compatible
                ? t("steamBuildOk", headcrabCompat.current_build ?? "?")
                : t("steamBuildMismatch", headcrabCompat.current_build ?? "?", headcrabCompat.target ?? "?")}
            </div>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleInstallDeps}
            disabled={installing || (headcrabCompat ? !headcrabCompat.compatible : false)}
            description={confirmInstallDeps ? t("installDepsConfirmDesc") : undefined}
          >
            {installing
              ? t("installing")
              : confirmInstallDeps
                ? t("installDepsConfirm")
                : t("installReinstallDeps")}
          </ButtonItem>
        </PanelSectionRow>
        {headcrabCompat && !headcrabCompat.compatible && (
          <PanelSectionRow>
            <div style={{
              fontSize: "11px",
              color: "#aaa",
              lineHeight: "1.4",
              padding: "4px 0",
            }}>
              <div style={{ color: "#ff8c00", fontWeight: 600, marginBottom: "4px" }}>
                ⚠ {t("headcrabGameModeBlockTitle")}
              </div>
              <div style={{ marginBottom: "6px" }}>
                {t("headcrabGameModeBlockBody")}
              </div>
              <div style={{
                fontFamily: "monospace",
                fontSize: "10px",
                color: "#ccc",
                background: "rgba(0,0,0,0.3)",
                padding: "4px 6px",
                borderRadius: "3px",
                wordBreak: "break-all",
              }}>
                {t("headcrabGameModeBlockCommand")}
              </div>
            </div>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleEnableCR}
            disabled={installingCR}
            description={confirmInstallCR ? t("enableCRConfirmDesc") : undefined}
          >
            {installingCR
              ? t("installingCR")
              : confirmInstallCR
                ? t("enableCRConfirm")
                : t("enableCloudRedirect")}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleInstallLumalinux}
            disabled={installingLL}
          >
            {installingLL ? t("installingLL") : t("installLumalinux")}
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
