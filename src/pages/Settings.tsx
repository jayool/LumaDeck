import { useEffect, useState } from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  ToggleField,
  Field,
  ProgressBarWithInfo,
  Navigation,
  SidebarNavigation,
} from "@decky/ui";
import { FaKey, FaShieldAlt, FaDownload, FaCog, FaInfoCircle, FaQuestionCircle, FaCheckCircle, FaExclamationTriangle } from "react-icons/fa";
import { toaster } from "@decky/api";
import { HelpContent } from "./Help";
import {
  saveRyuCookie,
  loadRyuCookie,
  importRyuuCookieFromBrowser,
  updateHubcapKey,
  loadHubcapKey,
  getCredentialStatus,
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
  listAdditionalApps,
  addToAdditionalApps,
  removeFromAdditionalApps,
  listFakeAppIds,
  addFakeAppId,
  removeFakeAppId,
} from "../api";
import { checkPluginUpdate, downloadUpdateToDownloads, runDesktopHandoffReal, runDesktopHandoffQuickInstall } from "../api";
import { useT, getLanguage, setLanguage } from "../i18n";

export function Settings() {
  const t = useT();
  const [ryuCookie, setRyuCookie] = useState("");
  const [hubcapKey, setHubcapKey] = useState("");
  const [cred, setCred] = useState<any>(null);
  const [deps, setDeps] = useState<any>(null);
  const [platform, setPlatform] = useState<any>(null);
  const [playNotOwned, setPlayNotOwned] = useState(false);
  // SLSsteam advanced config editors (AdditionalApps list + FakeAppIds map).
  const [addlApps, setAddlApps] = useState<string[]>([]);
  const [newAddlApp, setNewAddlApp] = useState("");
  const [fakeAppIds, setFakeAppIds] = useState<Record<string, string>>({});
  const [newFakeReal, setNewFakeReal] = useState("");
  const [newFakeFake, setNewFakeFake] = useState("");
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
  const [pluginUpdate, setPluginUpdate] = useState<{
    installed: string | null;
    latest: string | null;
    has_update: boolean;
  } | null>(null);
  const [updatingPlugin, setUpdatingPlugin] = useState(false);
  const [pluginMsg, setPluginMsg] = useState<string | null>(null);

  const toast = (title: string, body?: string, duration = 3000) =>
    toaster.toast({ title, body: body || "", duration });

  // Off-pin repairs need the Steam downgrade, which can't run in Game Mode.
  // Arm the one-shot Desktop hand-off (same mechanism the QAM "Fix in Desktop"
  // uses) instead of making the user type the headcrab command in a Desktop
  // terminal by hand. The command line is kept below as a manual fallback.
  const fixInDesktop = async (fn: () => Promise<any>) => {
    const r: any = await fn();
    if (r?.switchLaunched) toast(t("sysSteamTooNew"), t("sysHandoffSwitching"), 8000);
    else if (r?.armed) toast(t("sysSteamTooNew"), t("sysHandoffManual"), 12000);
    else toast(t("toastError"), r?.error || "", 6000);
  };

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

      const credResult = await getCredentialStatus();
      if (!cancelled && credResult.success) setCred(credResult);

      await refreshDeps();

      const platformResult = await getPlatformSummary();
      if (!cancelled) setPlatform(platformResult);

      const playResult = await getSlsPlayStatus();
      if (!cancelled && playResult.success) setPlayNotOwned(playResult.enabled);

      const [addl, fake] = await Promise.all([listAdditionalApps(), listFakeAppIds()]);
      if (!cancelled && addl?.success) setAddlApps(addl.appids ?? []);
      if (!cancelled && fake?.success) setFakeAppIds(fake.entries ?? {});

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

      const pu = await checkPluginUpdate();
      if (!cancelled && pu.success) setPluginUpdate({
        installed: pu.installed ?? null,
        latest: pu.latest ?? null,
        has_update: !!pu.has_update,
      });
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

  const refreshCred = async () => {
    const credResult = await getCredentialStatus();
    if (credResult.success) setCred(credResult);
  };

  // Humanise days-left: whole days normally, hours when under a day (matters
  // for the short-lived Ryuu cookie). fmtDate → short "Jun 25" style label.
  const fmtLeft = (d: number) =>
    d >= 1 ? t("credDays", Math.floor(d)) : t("credHours", Math.max(1, Math.round(d * 24)));
  const fmtDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    } catch {
      return iso;
    }
  };

  // One status line per credential, styled like the Dependencies health rows.
  const renderCredLine = (kind: "hubcap" | "ryuu") => {
    const c = kind === "hubcap" ? cred?.hubcap : cred?.ryuu;
    if (!c) return null;
    const K = (suffix: string) => (kind === "hubcap" ? `credHubcap${suffix}` : `credRyuu${suffix}`);
    let text = "";
    // Colour signal carried by an icon (native Field), per the GameDetail choice.
    let icon: JSX.Element | undefined;
    switch (c.state) {
      case "ok":
        text = t(K("Ok"), fmtLeft(c.days_left), fmtDate(c.expires_at));
        icon = <FaCheckCircle color="#00cc00" />;
        break;
      case "soon":
        text = t(K("Soon"), fmtLeft(c.days_left), fmtDate(c.expires_at));
        icon = <FaExclamationTriangle color="#ff8c00" />;
        break;
      case "expired":
        text = t(K("Expired"), fmtDate(c.expires_at));
        icon = <FaExclamationTriangle color="#ff4444" />;
        break;
      case "none":
        text = t(K("None"));
        break;
      default: // "unknown"
        text = t(K("Unknown"));
        break;
    }
    return (
      <PanelSectionRow>
        <Field icon={icon} label={text} />
      </PanelSectionRow>
    );
  };

  // Hubcap-only sub-line: today's request usage, when stats were reachable.
  const renderHubcapUsage = () => {
    const c = cred?.hubcap;
    if (!c || (c.state !== "ok" && c.state !== "soon") || c.daily_limit == null) return null;
    return (
      <PanelSectionRow>
        <Field label={t("credHubcapUsage", c.daily_usage ?? 0, c.daily_limit)} />
      </PanelSectionRow>
    );
  };

  const handleSaveCookie = async () => {
    const result = await saveRyuCookie(ryuCookie);
    if (result.success || result.message) {
      toast(t("toastCookieSaved"));
      refreshCred();
    } else {
      toast(t("toastError"), result.error || "", 4000);
    }
  };

  const handleOpenRyuu = () => {
    // Open Ryuu in Game Mode's built-in Steam browser so the user can log in
    // with Discord. The session cookie it sets is then importable below
    // (no DevTools / copy-paste needed).
    Navigation.NavigateToExternalWeb("https://generator.ryuu.lol/");
  };

  const handleImportRyuuCookie = async () => {
    const result = await importRyuuCookieFromBrowser();
    if (result.success) {
      // Refresh the displayed value from the saved cookie file.
      const reloaded = await loadRyuCookie();
      if (reloaded.success && reloaded.cookie) setRyuCookie(reloaded.cookie);
      refreshCred();
      toast(result.message || t("ryuuCookieImported"));
    } else {
      toast(t("toastError"), result.error || "", 5000);
    }
  };

  const handleSaveHubcapKey = async () => {
    const result = await updateHubcapKey(hubcapKey);
    if (result.success || result.message) {
      toast(t("toastApiKeySaved"));
      refreshCred();
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

  // SLSsteam advanced editors — re-read the config after every change so the UI
  // always shows the real on-disk values. Changes apply after a Steam restart.
  const refreshSlsAdvanced = async () => {
    const [addl, fake] = await Promise.all([listAdditionalApps(), listFakeAppIds()]);
    if (addl?.success) setAddlApps(addl.appids ?? []);
    if (fake?.success) setFakeAppIds(fake.entries ?? {});
  };

  const handleAddAddlApp = async () => {
    const id = parseInt(newAddlApp.trim(), 10);
    if (!Number.isFinite(id)) return;
    await addToAdditionalApps(id);
    setNewAddlApp("");
    await refreshSlsAdvanced();
  };

  const handleRemoveAddlApp = async (appid: string) => {
    await removeFromAdditionalApps(parseInt(appid, 10));
    await refreshSlsAdvanced();
  };

  const handleAddFakeAppId = async () => {
    const real = parseInt(newFakeReal.trim(), 10);
    const fake = parseInt(newFakeFake.trim(), 10);
    if (!Number.isFinite(real) || !Number.isFinite(fake)) return;
    await addFakeAppId(real, fake);
    setNewFakeReal("");
    setNewFakeFake("");
    await refreshSlsAdvanced();
  };

  const handleRemoveFakeAppId = async (real: string) => {
    await removeFakeAppId(parseInt(real, 10));
    await refreshSlsAdvanced();
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

  // Right-side status for a component. Hook components (SLSsteam / lumalinux /
  // CloudRedirect) read "Installed & Loaded" when healthy; anything installed but
  // not fully working just says "Installed" and a warning line explains below.
  const compStatus = (present: boolean, healthy?: boolean) =>
    !present ? t("notFound") : healthy ? t("installedLoaded") : t("installed");

  // A warning shown ONLY when something is wrong — as a small colored line under
  // the component (where the path used to be). Nothing renders when healthy, so
  // the normal screen is just the component list. warn = amber ⚠, muted = grey •.
  const warnDesc = (line: string | null | undefined, kind: "warn" | "muted" = "warn") => {
    if (!line) return undefined;
    return <span style={{ color: kind === "muted" ? "#888" : "#ff8c00" }}>
      {kind === "muted" ? "•" : "⚠"} {line}
    </span>;
  };

  const slssHealthDesc = () => {
    const h = slssteamHealth;
    if (!deps?.slssteam || !h || h.state === "healthy") return undefined;
    return warnDesc(slssHealthLine(h));
  };

  const llHealthDesc = () => {
    const h = lumalinuxHealth;
    if (!deps?.lumalinux || !h || h.state === "healthy" || h.state === "not_installed")
      return undefined;
    let line: string | null = null;
    switch (h.state) {
      case "hooks_failed":      line = t("llHealthDegraded"); break;
      case "hash_blocked":      line = t("llHealthHashBlocked"); break;
      case "not_active":        line = t("llHealthNotActive"); break;
      case "injection_missing": line = t("llHealthInjectionMissing"); break;
    }
    return warnDesc(line);
  };

  // CloudRedirect: a hook warning (if the hooks broke) and/or a sign-in warning
  // (provider not configured). Nothing when healthy + signed in.
  const crHealthDesc = () => {
    if (!deps?.cloudredirect) return undefined;
    const lines: any[] = [];
    if (crHealth && crHealth.state !== "healthy" && crHealth.state !== "not_authed") {
      let line: string | null = null;
      let kind: "warn" | "muted" = "warn";
      switch (crHealth.state) {
        case "broken":        line = t("crHealthBroken"); break;
        case "not_active":    line = t("crHealthNotActive"); break;
        case "kill_switched": line = t("crHealthKillSwitched"); kind = "muted"; break;
      }
      const d = warnDesc(line, kind);
      if (d) lines.push(d);
    }
    if (!deps.cloudredirectAuthed) {
      const d = warnDesc(t("providerNotConfigured"));
      if (d) lines.push(d);
    }
    if (lines.length === 0) return undefined;
    return <>{lines.map((n, i) => <div key={i}>{n}</div>)}</>;
  };

  const handleCheckPluginUpdate = async () => {
    setPluginMsg(t("checking"));
    const pu = await checkPluginUpdate();
    if (pu.success) {
      setPluginUpdate({
        installed: pu.installed ?? null,
        latest: pu.latest ?? null,
        has_update: !!pu.has_update,
      });
      setPluginMsg(pu.has_update ? t("pluginUpdateAvailable", pu.latest || "") : t("pluginUpToDate"));
    } else {
      setPluginMsg(t("pluginUpdateCheckFailed"));
    }
  };

  // Download the new zip into ~/Downloads instead of trying to overwrite the
  // plugin dir in place — the plugin process runs as `deck` and the install dir
  // is root-owned, so in-place self-update can't write there. This only touches
  // the deck-owned Downloads folder, so it's safe and always works.
  const handleDownloadUpdate = async () => {
    setUpdatingPlugin(true);
    setPluginMsg(t("downloadingUpdateZip"));
    const result = await downloadUpdateToDownloads();
    setUpdatingPlugin(false);
    if (result.success && result.downloaded) {
      setPluginMsg(t("updateZipSaved", result.path || "~/Downloads"));
    } else if (result.success && !result.downloaded) {
      setPluginMsg(t("pluginUpToDate"));
    } else {
      setPluginMsg(result.error || t("updateFailed"));
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
        {renderCredLine("hubcap")}
        {renderHubcapUsage()}

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
          <ButtonItem layout="below" onClick={handleOpenRyuu}>
            {t("openRyuu")}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleImportRyuuCookie}
            description={t("importRyuuCookieDesc")}
          >
            {t("importRyuuCookie")}
          </ButtonItem>
        </PanelSectionRow>
        {renderCredLine("ryuu")}
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

        {/* ── Advanced: AdditionalApps — force specific AppIDs as owned ── */}
        <PanelSectionRow>
          <Field focusable highlightOnFocus={false}
            label={t("slssAddlAppsTitle")} description={t("slssAddlAppsDesc")} />
        </PanelSectionRow>
        {addlApps.map((id) => (
          <PanelSectionRow key={`addl-${id}`}>
            <ButtonItem layout="below" onClick={() => handleRemoveAddlApp(id)}>
              {id}   ✕
            </ButtonItem>
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <TextField label={t("slssAppIdLabel")} value={newAddlApp}
            onChange={(e: any) => setNewAddlApp(e?.target?.value ?? "")} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleAddAddlApp}>{t("slssAddButton")}</ButtonItem>
        </PanelSectionRow>

        {/* ── Advanced: FakeAppIds — remap AppIDs for networking ── */}
        <PanelSectionRow>
          <Field focusable highlightOnFocus={false}
            label={t("slssFakeIdsTitle")} description={t("slssFakeIdsDesc")} />
        </PanelSectionRow>
        {Object.entries(fakeAppIds).map(([real, fake]) => (
          <PanelSectionRow key={`fake-${real}`}>
            <ButtonItem layout="below" onClick={() => handleRemoveFakeAppId(real)}>
              {real === "0" ? t("slssFakeAllUnowned") : real} → {fake}   ✕
            </ButtonItem>
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <TextField label={t("slssFakeRealLabel")} value={newFakeReal}
            onChange={(e: any) => setNewFakeReal(e?.target?.value ?? "")} />
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField label={t("slssFakeFakeLabel")} value={newFakeFake}
            onChange={(e: any) => setNewFakeFake(e?.target?.value ?? "")} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleAddFakeAppId}>{t("slssAddButton")}</ButtonItem>
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
                <Field
                  icon={broken
                    ? <FaExclamationTriangle color="#ffaa00" />
                    : <FaInfoCircle color="#9cc4ff" />}
                  label={broken
                    ? slssHealthLine(slssteamHealth!)
                    : t("slssUpdateAvailableSub",
                         headcrabCompat?.current_build ?? "?",
                         headcrabCompat?.target ?? "?")}
                />
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
                <>
                  {/* Must-run-in-Desktop notice → native Field (title + body) +
                      a monospace command line (no dark box). */}
                  <PanelSectionRow>
                    <Field
                      icon={<FaExclamationTriangle color={broken ? "#ff8c00" : "#5b9eff"} />}
                      label={broken ? t("headcrabGameModeBlockTitle") : t("slssUpdateApplyTitle")}
                      description={broken ? t("headcrabGameModeBlockBody") : t("slssUpdateApplyBody")}
                    />
                  </PanelSectionRow>
                  <PanelSectionRow>
                    <ButtonItem layout="below" onClick={() => fixInDesktop(runDesktopHandoffReal)}>
                      {t("sysFixInDesktop")}
                    </ButtonItem>
                  </PanelSectionRow>
                  <PanelSectionRow>
                    <Field
                      description={
                        <span style={{ fontFamily: "monospace", wordBreak: "break-all" }}>
                          {t("headcrabGameModeBlockCommand")}
                        </span>
                      }
                    />
                  </PanelSectionRow>
                </>
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
              <Field focusable highlightOnFocus={false} label="ACCELA">
                <span style={{ color: deps.accela ? "#00cc00" : "#ff4444" }}>
                  {deps.accela ? t("installed") : t("notFound")}
                </span>
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field focusable highlightOnFocus={false} label="SLSsteam" description={slssHealthDesc()}>
                <span style={{ color: deps.slssteam ? "#00cc00" : "#ff4444" }}>
                  {compStatus(deps.slssteam, slssteamHealth?.state === "healthy")}
                </span>
              </Field>
            </PanelSectionRow>
            {deps.slssteam && slssteamHealth?.state === "healthy" &&
             headcrabCompat && !headcrabCompat.compatible && (
              <PanelSectionRow>
                <Field
                  focusable highlightOnFocus={false}
                  icon={<FaInfoCircle color="#9cc4ff" />}
                  label={t("slssUpdateAvailableSub",
                     headcrabCompat.current_build ?? "?",
                     headcrabCompat.target ?? "?")}
                />
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <Field focusable highlightOnFocus={false} label=".NET Runtime">
                <span style={{ color: deps.dotnet ? "#00cc00" : "#ff4444" }}>
                  {deps.dotnet ? t("installed") : t("notFound")}
                </span>
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field focusable highlightOnFocus={false} label="lumalinux" description={llHealthDesc()}>
                <span style={{ color: deps.lumalinux ? "#00cc00" : "#ff4444" }}>
                  {compStatus(deps.lumalinux, lumalinuxHealth?.state === "healthy")}
                </span>
              </Field>
            </PanelSectionRow>
            {deps.lumalinux && lumalinuxHealth?.state === "healthy" && llUpdate?.has_update && (
              <PanelSectionRow>
                <Field
                  focusable highlightOnFocus={false}
                  icon={<FaInfoCircle color="#9cc4ff" />}
                  label={t("llUpdateAvailableSub",
                     llUpdate.installed ?? "?",
                     llUpdate.latest ?? "?")}
                />
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <Field focusable highlightOnFocus={false} label="CloudRedirect" description={crHealthDesc()}>
                <span style={{ color: deps.cloudredirect ? "#00cc00" : "#ff4444" }}>
                  {compStatus(deps.cloudredirect, crHealth?.state === "healthy")}
                </span>
              </Field>
            </PanelSectionRow>
            {deps.cloudredirect && crHealth?.state === "healthy" && crUpdate?.has_update && (
              <PanelSectionRow>
                <Field
                  focusable highlightOnFocus={false}
                  icon={<FaInfoCircle color="#9cc4ff" />}
                  label={t("crUpdateAvailableSub",
                     crUpdate.installed ?? "?",
                     crUpdate.latest ?? "?")}
                />
              </PanelSectionRow>
            )}
          </>
        )}
        {headcrabCompat && !headcrabCompat.compatible && (
          <PanelSectionRow>
            <Field
              focusable highlightOnFocus={false}
              icon={<FaExclamationTriangle color="#ff8c00" />}
              label={t("steamBuildMismatch", headcrabCompat.current_build ?? "?", headcrabCompat.target ?? "?")}
            />
          </PanelSectionRow>
        )}
        {/* Off-pin: the main install can't run in Game Mode (headcrab's downgrade
            crashes gamescope), so the button MORPHS into "Fix in Desktop" (runs
            the full quick install in Desktop). On-pin it's the normal install. */}
        <PanelSectionRow>
          {headcrabCompat && !headcrabCompat.compatible ? (
            <ButtonItem
              layout="below"
              onClick={() => fixInDesktop(runDesktopHandoffQuickInstall)}
              description={t("sysSteamTooNewFixDesc")}
            >
              {t("sysFixInDesktop")}
            </ButtonItem>
          ) : (
            <ButtonItem
              layout="below"
              onClick={handleInstallDeps}
              disabled={installing}
              description={confirmInstallDeps ? t("installDepsConfirmDesc") : undefined}
            >
              {installing
                ? t("installing")
                : confirmInstallDeps
                  ? t("installDepsConfirm")
                  : t("installReinstallDeps")}
            </ButtonItem>
          )}
        </PanelSectionRow>
        {/* Enable CloudRedirect also runs headcrab, so it's hidden off-pin
            (would crash gamescope, and "Fix in Desktop" already installs CR). */}
        {(!headcrabCompat || headcrabCompat.compatible) && (
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
        )}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleInstallLumalinux}
            disabled={installingLL}
            description={confirmInstallLL ? t("installLumalinuxConfirmDesc") : undefined}
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
          <Field label={lang === "en" ? t("currentEnglish") : t("currentPortuguese")} />
        </PanelSectionRow>
      </PanelSection>

      {platform && (
        <PanelSection title={t("platform")}>
          <PanelSectionRow>
            <Field label="Steam" description={platform.steam_root || t("notFound")} />
          </PanelSectionRow>
        </PanelSection>
      )}

      {libraries.length > 0 && (
        <PanelSection title={t("steamLibraries")}>
          {libraries.flatMap((lib: any, idx: number) => {
            const freeGB = (lib.freeBytes / (1024 * 1024 * 1024)).toFixed(1);
            const totalGB = (lib.totalBytes / (1024 * 1024 * 1024)).toFixed(1);
            const usedPercent = lib.totalBytes > 0
              ? Math.round(((lib.totalBytes - lib.freeBytes) / lib.totalBytes) * 100)
              : 0;
            return [
              <PanelSectionRow key={lib.path}>
                <Field label={`${lib.path}${idx === 0 ? ` (${t("defaultLibrary")})` : ""}`} />
              </PanelSectionRow>,
              <PanelSectionRow key={`${lib.path}-bar`}>
                {/* Native usage bar. The old custom bar tinted red >90% / amber
                    >75%; ProgressBarWithInfo has no threshold colour, but the
                    free/total + game count ride in sOperationText. */}
                <ProgressBarWithInfo
                  nProgress={usedPercent}
                  sOperationText={`${t("freeSpace", `${freeGB} / ${totalGB} GB`)} — ${t("libraryGames", lib.gameCount)}`}
                />
              </PanelSectionRow>,
            ];
          })}
        </PanelSection>
      )}
        </>
      ),
    },
    {
      title: t("about"),
      icon: <FaInfoCircle />,
      hideTitle: true,
      content: (
        <PanelSection title={t("about")}>
          <PanelSectionRow>
            <Field description={t("aboutBlurb")} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("pluginInstalled", pluginUpdate?.installed || "—")}>
              {pluginUpdate?.latest && (
                <span style={{ color: pluginUpdate.has_update ? "#9cc4ff" : "#8b929a" }}>
                  {t("pluginLatest", pluginUpdate.latest)}
                </span>
              )}
            </Field>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={handleCheckPluginUpdate}
              disabled={updatingPlugin}
            >
              {t("checkForUpdates")}
            </ButtonItem>
          </PanelSectionRow>
          {pluginUpdate?.has_update && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={handleDownloadUpdate}
                disabled={updatingPlugin}
              >
                {updatingPlugin
                  ? t("downloadingUpdateZip")
                  : `${t("downloadUpdateZip")} (${pluginUpdate.latest})`}
              </ButtonItem>
            </PanelSectionRow>
          )}
          {pluginMsg && (
            <PanelSectionRow>
              <Field label={pluginMsg} />
            </PanelSectionRow>
          )}
        </PanelSection>
      ),
    },
    {
      title: t("help"),
      icon: <FaQuestionCircle />,
      hideTitle: true,
      content: <HelpContent />,
    },
  ];

  return <SidebarNavigation title="LumaDeck" pages={pages} />;
}
