import { useEffect, useState } from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  ToggleField,
  Navigation,
  SidebarNavigation,
} from "@decky/ui";
import { FaKey, FaShieldAlt, FaDownload, FaCog } from "react-icons/fa";
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
  getSlsPlayStatus,
  setSlsPlayStatus,
  getSteamLibraries,
  restartSteam,
  getSlssteamHealth,
  getLumalinuxHealth,
  getCloudredirectHealth,
  checkCloudredirectUpdate,
  checkLumalinuxUpdate,
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
  const [confirmInstallLL, setConfirmInstallLL] = useState(false);
  const [repairing, setRepairing] = useState(false);
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
      const [sls, ll, cr, cru, llu] = await Promise.all([
        getSlssteamHealth(), getLumalinuxHealth(),
        getCloudredirectHealth(), checkCloudredirectUpdate(),
        checkLumalinuxUpdate(),
      ]);
      if (!cancelled && sls.state) setSlssteamHealth(sls);
      if (!cancelled && ll.state)  setLumalinuxHealth(ll);
      if (!cancelled && cr.state)  setCrHealth(cr);
      if (!cancelled) setCrUpdate({
        installed: cru.installed ?? null,
        latest: cru.latest ?? null,
        has_update: !!cru.has_update,
      });
      if (!cancelled) setLlUpdate({
        installed: llu.installed ?? null,
        latest: llu.latest ?? null,
        has_update: !!llu.has_update,
      });
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

      const [sls, ll, cr, cru, llu] = await Promise.all([
        getSlssteamHealth(), getLumalinuxHealth(),
        getCloudredirectHealth(), checkCloudredirectUpdate(),
        checkLumalinuxUpdate(),
      ]);
      if (!cancelled && sls.state) setSlssteamHealth(sls);
      if (!cancelled && ll.state)  setLumalinuxHealth(ll);
      if (!cancelled && cr.state)  setCrHealth(cr);
      if (!cancelled) setCrUpdate({
        installed: cru.installed ?? null,
        latest: cru.latest ?? null,
        has_update: !!cru.has_update,
      });
      if (!cancelled) setLlUpdate({
        installed: llu.installed ?? null,
        latest: llu.latest ?? null,
        has_update: !!llu.has_update,
      });

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

  const handleOpenHubcap = () => {
    // Open Hubcap in Game Mode's built-in Steam browser so the user can log
    // in with Discord and regenerate their API key without dropping to the
    // desktop. They copy the key in the browser and paste it into the field
    // above. (We deliberately open the official site as-is — no scraping or
    // scripted regeneration, which the site bans.)
    Navigation.NavigateToExternalWeb("https://hubcapmanifest.com/api-keys");
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
    // Two-click confirm pattern (same as handleEnableCR / handleUninstall):
    // first click flips a flag and arms a 5 s timeout to reset it, second
    // click within that window triggers the actual install. The confirm is
    // not because the install kills Steam mid-flight (we patch the killall
    // out and only restart at the end), but because the install does a
    // single controlled Steam restart at the very end — same one-tap flow
    // as Install lumalinux.
    if (!confirmInstallDeps) {
      setConfirmInstallDeps(true);
      setTimeout(() => setConfirmInstallDeps(false), 5000);
      return;
    }
    setConfirmInstallDeps(false);
    setInstalling(true);
    const installResult = await installDependencies();
    const result = await checkDependencies();
    if (result.success) setDeps(result);
    setInstalling(false);
    if (installResult.success) {
      await restartSteam();
    }
  };

  const handleEnableCR = async () => {
    // Two-click confirm pattern. Install runs with Steam alive (we no-op
    // the killall in _HEADCRAB_PATCHES) so the Flatpak download finishes
    // cleanly. After success we fire one controlled `steam -shutdown` to
    // let gamescope respawn Steam with the new steam.sh + CR LD_PRELOAD
    // already in place.
    if (!confirmInstallCR) {
      setConfirmInstallCR(true);
      setTimeout(() => setConfirmInstallCR(false), 5000);
      return;
    }
    setConfirmInstallCR(false);
    setInstallingCR(true);
    const result = await installCloudredirect();
    const depsResult = await checkDependencies();
    if (depsResult.success) setDeps(depsResult);
    setInstallingCR(false);
    if (result.success) {
      await restartSteam();
    }
  };

  const handleInstallLumalinux = async () => {
    // Two-click confirm pattern (consistent with handleInstallDeps and
    // handleEnableCR): first tap arms the confirm + a 5 s reset timer,
    // second tap inside that window triggers the actual install. Same
    // reason as the other two: after success this handler fires a
    // controlled `steam -shutdown`, so the user gets a single
    // intentional Steam restart instead of being surprised by one.
    if (!confirmInstallLL) {
      setConfirmInstallLL(true);
      setTimeout(() => setConfirmInstallLL(false), 5000);
      return;
    }
    setConfirmInstallLL(false);
    setInstallingLL(true);
    const result = await installLumalinux();
    const depsResult = await checkDependencies();
    if (depsResult.success) setDeps(depsResult);
    setInstallingLL(false);
    if (result.success) {
      await restartSteam();
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
      const [sls, ll] = await Promise.all([getSlssteamHealth(), getLumalinuxHealth()]);
      if (sls.state) setSlssteamHealth(sls);
      if (ll.state)  setLumalinuxHealth(ll);
      toast(t("headcrabRepaired"), t("headcrabRepairedBody"), 6000);
    } else {
      toast(t("toastError"), result.error || `step: ${result.step}`, 6000);
    }
  };

  // Map an SLSsteam health state to its Dependencies sub-row string.
  const slssHealthLine = (h: { state: string; cause: string | null }): string | null => {
    switch (h.state) {
      case "healthy":           return t("slssHealthOk");
      case "not_active":        return t("slssHealthNotActive");
      case "injection_missing": return t("slssHealthInjectionMissing");
      case "broken":
        return h.cause === "hash"
          ? t("slssHealthBrokenHash")
          : t("slssHealthBrokenPatterns");
      default:                  return null; // not_installed → red dot already says it
    }
  };

  const pages = [
    {
      title: t("apiCredentials"),
      icon: <FaKey />,
      hideTitle: true,
      content: (
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
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleOpenHubcap}
            description={t("getHubcapKeyDesc")}
          >
            {t("getHubcapKey")}
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
        </>
      ),
    },
    {
      title: t("slssteam"),
      icon: <FaShieldAlt />,
      hideTitle: true,
      content: (
      <PanelSection title={t("slssteam")}>
        <PanelSectionRow>
          <ToggleField
            label={t("playNotOwnedGames")}
            checked={playNotOwned}
            onChange={handleTogglePlayNotOwned}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => restartSteam()}>
            {t("restartSteam")}
          </ButtonItem>
        </PanelSectionRow>
        {/* Repair / Apply-Update zone — fires when SLSsteam is broken OR when an
            update is available. Both use the same handler (headcrab.sh) and the
            same gamemode gate (compat=false → must run from Desktop). The notice
            colour changes per intent: orange for "broken", blue for "update". */}
        {(() => {
          const broken = slssteamHealth &&
            (slssteamHealth.state === "broken" || slssteamHealth.state === "injection_missing");
          const updateAvailable = slssteamHealth?.state === "healthy" &&
            headcrabCompat && !headcrabCompat.compatible;
          if (!broken && !updateAvailable) return null;
          const gamemodeBlocked = headcrabCompat && !headcrabCompat.compatible;
          return (
            <>
              <PanelSectionRow>
                <div style={{
                  fontSize: "11px",
                  color: broken ? "#ffaa00" : "#9cc4ff",
                }}>
                  {broken
                    ? <>⚠ {slssHealthLine(slssteamHealth!)}</>
                    : t("slssUpdateAvailableSub",
                         headcrabCompat?.current_build ?? "?",
                         headcrabCompat?.target ?? "?")}
                </div>
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={handleRepairHeadcrab}
                  disabled={repairing || !!gamemodeBlocked}
                >
                  {repairing ? t("repairingHeadcrab") : t("repairSlssteamHeadcrab")}
                </ButtonItem>
              </PanelSectionRow>
              {gamemodeBlocked && (
                <PanelSectionRow>
                  <div style={{
                    fontSize: "11px",
                    color: "#aaa",
                    lineHeight: "1.4",
                    padding: "4px 0",
                  }}>
                    <div style={{
                      color: broken ? "#ff8c00" : "#5b9eff",
                      fontWeight: 600,
                      marginBottom: "4px",
                    }}>
                      ⚠ {broken ? t("headcrabGameModeBlockTitle") : t("slssUpdateApplyTitle")}
                    </div>
                    <div style={{ marginBottom: "6px" }}>
                      {broken ? t("headcrabGameModeBlockBody") : t("slssUpdateApplyBody")}
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
          );
        })()}
      </PanelSection>
      ),
    },
    {
      title: t("dependencies"),
      icon: <FaDownload />,
      hideTitle: true,
      content: (
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
            {deps.slssteam && slssteamHealth && slssHealthLine(slssteamHealth) && (
              <PanelSectionRow>
                <div style={{
                  fontSize: "11px",
                  color: slssteamHealth.state === "healthy" ? "#00cc00" : "#ff8c00",
                  paddingLeft: "8px",
                }}>
                  {slssHealthLine(slssteamHealth)}
                </div>
              </PanelSectionRow>
            )}
            {deps.slssteam && slssteamHealth?.state === "healthy" &&
             headcrabCompat && !headcrabCompat.compatible && (
              <PanelSectionRow>
                <div style={{ fontSize: "11px", color: "#9cc4ff", paddingLeft: "8px" }}>
                  {t("slssUpdateAvailableSub",
                     headcrabCompat.current_build ?? "?",
                     headcrabCompat.target ?? "?")}
                </div>
              </PanelSectionRow>
            )}
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
            {deps.lumalinux && lumalinuxHealth && (() => {
              const h = lumalinuxHealth;
              if (h.state === "not_installed") return null;
              const ver = h.version || "?";
              let line: string | null = null;
              switch (h.state) {
                case "healthy":      line = t("llHealthAllOk", ver); break;
                case "hooks_failed": line = t("llHealthDegraded", ver, h.cause || "?"); break;
                case "hash_blocked": line = t("llHealthHashBlocked", ver); break;
                case "not_active":   line = t("llHealthNotActive"); break;
                case "injection_missing": line = t("llHealthInjectionMissing"); break;
              }
              if (!line) return null;
              return (
                <PanelSectionRow>
                  <div style={{
                    fontSize: "11px",
                    color: h.state === "healthy" ? "#00cc00" : "#ff8c00",
                    paddingLeft: "8px",
                  }}>
                    {line}
                  </div>
                </PanelSectionRow>
              );
            })()}
            {deps.lumalinux && lumalinuxHealth?.state === "healthy" && llUpdate?.has_update && (
              <PanelSectionRow>
                <div style={{ fontSize: "11px", color: "#9cc4ff", paddingLeft: "8px" }}>
                  {t("llUpdateAvailableSub",
                     llUpdate.installed ?? "?",
                     llUpdate.latest ?? "?")}
                </div>
              </PanelSectionRow>
            )}
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
            {deps.cloudredirect && crHealth && (() => {
              const ver = crHealth.version || "?";
              let line: string | null = null;
              let color = "#00cc00";
              switch (crHealth.state) {
                case "healthy":       line = t("crHealthOk", ver); break;
                case "broken":        line = t("crHealthBroken", ver); color = "#ff8c00"; break;
                case "not_active":    line = t("crHealthNotActive");   color = "#ff8c00"; break;
                case "not_authed":    line = t("crHealthNotAuthed");   color = "#ffaa00"; break;
                case "kill_switched": line = t("crHealthKillSwitched"); color = "#888"; break;
              }
              if (!line) return null;
              return (
                <PanelSectionRow>
                  <div style={{ fontSize: "11px", color, paddingLeft: "8px" }}>
                    {line}
                  </div>
                </PanelSectionRow>
              );
            })()}
            {deps.cloudredirect && crHealth?.state === "healthy" && crUpdate?.has_update && (
              <PanelSectionRow>
                <div style={{ fontSize: "11px", color: "#9cc4ff", paddingLeft: "8px" }}>
                  {t("crUpdateAvailableSub",
                     crUpdate.installed ?? "?",
                     crUpdate.latest ?? "?")}
                </div>
              </PanelSectionRow>
            )}
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
          <div style={{ height: "8px" }} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleInstallDeps}
            disabled={installing || (headcrabCompat ? !headcrabCompat.compatible : false)}
            description={confirmInstallDeps ? <div style={{ textAlign: "center" }}>{t("installDepsConfirmDesc")}</div> : undefined}
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
            description={confirmInstallCR ? <div style={{ textAlign: "center" }}>{t("enableCRConfirmDesc")}</div> : undefined}
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
            description={confirmInstallLL ? <div style={{ textAlign: "center" }}>{t("installLumalinuxConfirmDesc")}</div> : undefined}
          >
            {installingLL
              ? t("installingLL")
              : confirmInstallLL
                ? t("installLumalinuxConfirm")
                : t("installLumalinux")}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      ),
    },
    {
      title: t("settingsSystem"),
      icon: <FaCog />,
      hideTitle: true,
      content: (
        <>
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
        </>
      ),
    },
  ];

  return <SidebarNavigation title="LumaDeck" pages={pages} />;
}
