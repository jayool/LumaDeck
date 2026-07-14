import { useEffect, useState, useRef } from "react";
import { ACHIEVEMENTS_ENABLED } from "../features";
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
  DropdownItem,
} from "@decky/ui";
import { FaKey, FaShieldAlt, FaDownload, FaCog, FaInfoCircle, FaQuestionCircle, FaCheckCircle, FaExclamationTriangle, FaTrophy } from "react-icons/fa";
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
  getPlatformSummary,
  getSteamLibraries,
  restartSteam,
  getSlssteamHealth,
  getLumalinuxHealth,
  getCloudredirectHealth,
  checkCloudredirectUpdate,
  checkLumalinuxUpdate,
  checkHeadcrabCompat,
  getComponentsStatus,
  reinjectInstalled,
  applyComponent,
  listAdditionalApps,
  addToAdditionalApps,
  removeFromAdditionalApps,
  listFakeAppIds,
  addFakeAppId,
  removeFakeAppId,
} from "../api";
import { checkPluginUpdate, downloadUpdateToDownloads, runDesktopHandoffQuickInstall } from "../api";
import { getDevState, setDevState, clearDevState } from "../api";
import { requestRefresh } from "../refresh";
import {
  getInstalledLuaScripts,
  getApiKeyStatus,
  setSteamApiKey,
  checkAllAchievementsStatus,
  generateAllAchievements,
  getSyncAllStatus,
} from "../api";
import { useT, getLanguage, setLanguage } from "../i18n";
import { primarySystemAction, ComponentsStatus } from "../components/SystemStatus";

export function Settings() {
  const t = useT();
  const [ryuCookie, setRyuCookie] = useState("");
  const [hubcapKey, setHubcapKey] = useState("");
  const [cred, setCred] = useState<any>(null);
  const [deps, setDeps] = useState<any>(null);
  const [componentsStatus, setComponentsStatus] = useState<ComponentsStatus | null>(null);
  const [applyingFix, setApplyingFix] = useState(false);
  const [platform, setPlatform] = useState<any>(null);
  const [devState, setDevStateLocal] = useState<Record<string, string>>({});
  // SLSsteam advanced config editors (AdditionalApps list + FakeAppIds map).
  const [addlApps, setAddlApps] = useState<string[]>([]);
  const [newAddlApp, setNewAddlApp] = useState("");
  const [fakeAppIds, setFakeAppIds] = useState<Record<string, string>>({});
  const [newFakeReal, setNewFakeReal] = useState("");
  const [newFakeFake, setNewFakeFake] = useState("");
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

  // Achievements tab (Steam Web API key + Sync All). Moved here from the old
  // full-screen page — the "global setup" is now just a credential.
  const [keySet, setKeySet] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [achOverview, setAchOverview] = useState<{ done: number; total: number } | null>(null);
  const [syncState, setSyncState] = useState<any>(null);
  const syncPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  // Re-fetch everything the Dependencies view renders (component state + the
  // unified status the morphing button reads).
  const reloadStatus = async () => {
    const [d, cs, sls, ll, cr] = await Promise.all([
      checkDependencies(), getComponentsStatus(),
      getSlssteamHealth(), getLumalinuxHealth(), getCloudredirectHealth(),
    ]);
    if (d?.success) setDeps(d);
    if (cs?.success) setComponentsStatus(cs);
    if (sls?.state) setSlssteamHealth(sls);
    if (ll?.state) setLumalinuxHealth(ll);
    if (cr?.state) setCrHealth(cr);
  };

  // Run a fix action (reinject / apply_component / install), then restart Steam
  // to apply and refresh the view. All of these own the steam.sh ordering.
  const runFix = async (fn: () => Promise<any>) => {
    setApplyingFix(true);
    const r: any = await fn();
    if (r?.success) {
      await restartSteam();
      await reloadStatus();
    } else {
      toast(t("toastError"), r?.failedStep || r?.error || "", 4000);
    }
    setApplyingFix(false);
  };

  useEffect(() => {
    let cancelled = false;

    const refreshDeps = async () => {
      if (cancelled) return;
      const depsResult = await checkDependencies();
      if (!cancelled && depsResult.success) setDeps(depsResult);
      const cs = await getComponentsStatus();
      if (!cancelled && cs?.success) setComponentsStatus(cs);
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

      const devResult = await getDevState();
      if (!cancelled && devResult?.success) setDevStateLocal(devResult.overrides || {});

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

  // ── Achievements tab state ────────────────────────────────────────────────
  const loadAchState = async () => {
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
          setAchOverview({ done, total: appids.length });
        }
      } catch {
        setAchOverview(null);
      }
    } else {
      setAchOverview({ done: 0, total: 0 });
    }
  };

  useEffect(() => {
    loadAchState();
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
      await loadAchState();
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
            await loadAchState();
            setTimeout(() => setSyncState(null), 3000);
          }
        }
      } catch {}
    }, 2000);
  };

  const syncing = syncState?.status === "running";

  const handleOpenSteamApiKey = () => {
    // Same pattern as Hubcap: open the official key page in Game Mode's built-in
    // Steam browser so the user can log in and register a key without dropping to
    // the desktop, then copy it into the field above. (No scraping — the page is
    // opened as-is; registering a new key needs the Steam mobile confirmation.)
    Navigation.NavigateToExternalWeb("https://steamcommunity.com/dev/apikey");
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


  // Canonical state → shared Dependencies sub-row text. Identical wording for
  // every component: from the user's side there are only two fixes, "Restart
  // Steam" and "Fix in Desktop", so a broken component only ever says one of
  // those. healthy / not_installed / not_authed / disabled are handled elsewhere.
  const healthLine = (state: string): string | null => {
    switch (state) {
      case "not_loaded":
      case "not_injected":  return t("healthNotLoaded");
      case "not_supported": return t("healthNeedsDesktop");
      default:              return null;
    }
  };

  // Right-side status for a component. Hook components (SLSsteam / lumalinux /
  // CloudRedirect) read "Installed & Loaded" when healthy; anything installed but
  // not fully working just says "Installed" and a warning line explains below.
  const compStatus = (present: boolean, healthy?: boolean) =>
    !present ? t("notFound") : healthy ? t("installedLoaded") : t("installed");

  // A small colored line under the component (where the path used to be). Nothing
  // renders when healthy and up to date, so the normal screen is just the list.
  // warn = amber ⚠ (something wrong), muted = grey • (benign), info = blue ↑
  // (update available — same subtext slot as the warnings, per component).
  const warnDesc = (line: string | null | undefined, kind: "warn" | "muted" | "info" = "warn") => {
    if (!line) return undefined;
    const color = kind === "muted" ? "#888" : kind === "info" ? "#9cc4ff" : "#ff8c00";
    const marker = kind === "muted" ? "•" : kind === "info" ? "↑" : "⚠";
    return <span style={{ color }}>{marker} {line}</span>;
  };

  const slssHealthDesc = () => {
    const h = slssteamHealth;
    if (!deps?.slssteam) return undefined;
    if (h && h.state !== "healthy") return warnDesc(healthLine(h.state));
    // Healthy → surface the update (headcrab pin ahead of the local Steam build)
    // in the same subtext slot as the warnings.
    if (h?.state === "healthy" && headcrabCompat && !headcrabCompat.compatible)
      return warnDesc(
        t("slssUpdateAvailableSub", headcrabCompat.current_build ?? "?", headcrabCompat.target ?? "?"),
        "info");
    return undefined;
  };

  const llHealthDesc = () => {
    const h = lumalinuxHealth;
    if (!deps?.lumalinux || !h || h.state === "not_installed") return undefined;
    if (h.state !== "healthy") return warnDesc(healthLine(h.state));
    // Healthy → update available in the same subtext slot.
    if (llUpdate?.has_update)
      return warnDesc(t("llUpdateAvailableSub", llUpdate.installed ?? "?", llUpdate.latest ?? "?"), "info");
    return undefined;
  };

  // CloudRedirect: a hook warning (if the hooks broke) and/or a sign-in warning
  // (provider not configured). Nothing when healthy + signed in.
  const crHealthDesc = () => {
    if (!deps?.cloudredirect) return undefined;
    const lines: any[] = [];
    if (crHealth && crHealth.state !== "healthy" && crHealth.state !== "not_authed") {
      // disabled is a deliberate opt-out → muted grey line, no warning. Every
      // other non-healthy state maps to the shared restart/desktop wording.
      const isDisabled = crHealth.state === "disabled";
      const line = isDisabled ? t("healthDisabled") : healthLine(crHealth.state);
      const d = warnDesc(line, isDisabled ? "muted" : "warn");
      if (d) lines.push(d);
    }
    if (!deps.cloudredirectAuthed) {
      // Sign-in is a pending step, not a failure → info blue, matches the QAM.
      const d = warnDesc(t("providerNotConfigured"), "info");
      if (d) lines.push(d);
    }
    // Update available → same subtext slot (blue ↑), only when the hooks are OK.
    if (crHealth?.state === "healthy" && crUpdate?.has_update) {
      const d = warnDesc(t("crUpdateAvailableSub", crUpdate.installed ?? "?", crUpdate.latest ?? "?"), "info");
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

  // ── Dev preview: force UI states (backend/dev.py). Only forges what the UI
  //    reads (health + credentials); nothing real is touched. ────────────────
  const devControls = [
    { key: "slssteam_health", label: "SLSsteam health", opts: ["real", "healthy", "not_installed", "not_loaded", "not_injected", "not_supported"] },
    { key: "lumalinux_health", label: "lumalinux health", opts: ["real", "healthy", "not_installed", "not_loaded", "not_injected", "not_supported"] },
    { key: "cloudredirect_health", label: "CloudRedirect health", opts: ["real", "healthy", "not_installed", "not_loaded", "not_injected", "not_supported", "not_authed", "disabled"] },
    { key: "hubcap_cred", label: "Hubcap key", opts: ["real", "ok", "soon", "expired", "none", "unknown"] },
    { key: "ryuu_cred", label: "Ryuu cookie", opts: ["real", "ok", "soon", "expired", "none", "unknown"] },
  ];
  const reloadAfterDev = async () => {
    const [sls, ll, cr] = await Promise.all([getSlssteamHealth(), getLumalinuxHealth(), getCloudredirectHealth()]);
    if (sls.state) setSlssteamHealth(sls);
    if (ll.state) setLumalinuxHealth(ll);
    if (cr.state) setCrHealth(cr);
    const cs = await getComponentsStatus(true);
    if (cs?.success) setComponentsStatus(cs);
    const c = await getCredentialStatus();
    if (c.success) setCred(c);
    requestRefresh();
  };
  const handleSetDev = async (key: string, value: string) => {
    setDevStateLocal((s) => ({ ...s, [key]: value }));
    const r = await setDevState(key, value);
    if (r?.success) setDevStateLocal(r.overrides || {});
    await reloadAfterDev();
  };
  const handleClearDev = async () => {
    await clearDevState();
    setDevStateLocal({});
    await reloadAfterDev();
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
    ...(ACHIEVEMENTS_ENABLED ? [{
      title: t("achievements"),
      icon: <FaTrophy />,
      hideTitle: true,
      content: (
        <>
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
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={handleOpenSteamApiKey}
                description={t("getSteamApiKeyDesc")}
              >
                {t("getSteamApiKey")}
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
          {achOverview && (
            <PanelSectionRow>
              <Field label={t("achievementsOverview", achOverview.done, achOverview.total)} />
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
        </>
      ),
    }] : []),
    {
      title: t("slssteam"),
      icon: <FaShieldAlt />,
      hideTitle: true,
      content: (
      <PanelSection title={t("slssteam")}>
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
              <Field focusable highlightOnFocus={false} label="SLSsteam" description={slssHealthDesc()}>
                <span style={{ color: deps.slssteam ? "#00cc00" : "#ff4444" }}>
                  {compStatus(deps.slssteam, slssteamHealth?.state === "healthy")}
                </span>
              </Field>
            </PanelSectionRow>
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
            <PanelSectionRow>
              <Field focusable highlightOnFocus={false} label="CloudRedirect" description={crHealthDesc()}>
                <span style={{ color: deps.cloudredirect ? "#00cc00" : "#ff4444" }}>
                  {compStatus(deps.cloudredirect, crHealth?.state === "healthy")}
                </span>
              </Field>
            </PanelSectionRow>
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
        {/* ONE morphing action button, same priority/dispatch as the QAM
            (SystemStatus). Off-pin or not_supported → Fix in Desktop; else the
            highest-priority in-place fix from primarySystemAction (Restart Steam,
            which re-injects steam.sh first when a component is not_injected); else
            a manual Install / Reinstall. Every fix owns the shared steam.sh
            ordering (reinject / apply_component), so there are no per-component
            installers that could wipe the others. */}
        {(() => {
          const offPin = !!headcrabCompat && !headcrabCompat.compatible;
          const coreInstalled = !!(deps?.slssteam && deps?.lumalinux);
          const primary = offPin ? "downgrade" : primarySystemAction(componentsStatus);
          let label = t("installReinstallDeps");
          let desc: string | undefined;
          let onClick: () => any;
          if (offPin || primary === "downgrade") {
            label = t("sysFixInDesktop");
            desc = t("sysSteamTooNewFixDesc");
            onClick = () => fixInDesktop(runDesktopHandoffQuickInstall);
          } else if (primary === "core") {
            // Partial install, Steam at the pin → install the missing core in
            // place (Game Mode safe), then restart.
            label = t("sysFinishSetup");
            onClick = () => runFix(() => applyComponent("core", "install"));
          } else if (primary === "reinject") {
            // not_injected: steam.sh lost the line. Re-patch it, then restart.
            // Same "Restart Steam" label the user sees in the QAM.
            label = t("restartSteam");
            onClick = () => runFix(() => reinjectInstalled());
          } else if (primary === "restart") {
            label = t("restartSteam");
            onClick = () => runFix(async () => ({ success: true })); // restart + refresh
          } else {
            // healthy on-pin: manual maintenance. Reflect the real state in the
            // label — "Reinstall" when the core is already there (nothing is
            // missing), "Install" only on a fresh device.
            label = coreInstalled ? t("reinstallDeps") : t("installDeps");
            onClick = () => runFix(() =>
              coreInstalled ? reinjectInstalled() : applyComponent("core", "install"));
          }
          return (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={applyingFix}
                description={desc} onClick={onClick}>
                {applyingFix ? t("installing") : label}
              </ButtonItem>
            </PanelSectionRow>
          );
        })()}
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
                  sOperationText={`${t("freeSpace", `${freeGB} / ${totalGB} GB`)} · ${t("libraryGames", lib.gameCount)}`}
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
            <Field label={t("pluginInstalled", pluginUpdate?.installed || "?")}>
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
    {
      title: "Dev",
      icon: <FaCog />,
      hideTitle: true,
      content: (
        <PanelSection title="Dev — force UI states">
          <PanelSectionRow>
            <div style={{ fontSize: "12px", color: "#8b929e", lineHeight: 1.4 }}>
              Forge what the UI reads (health + credentials) to preview banners,
              System Status and credential rows. Nothing real is touched. Reopen
              the QAM after changing a value to see the main-page banners update.
            </div>
          </PanelSectionRow>
          {devControls.map((c) => (
            <PanelSectionRow key={c.key}>
              <DropdownItem
                label={c.label}
                rgOptions={c.opts.map((o) => ({ data: o, label: o }))}
                selectedOption={devState[c.key] || "real"}
                onChange={(o: any) => handleSetDev(c.key, o.data)}
              />
            </PanelSectionRow>
          ))}
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={handleClearDev}>
              Reset all to real
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      ),
    },
  ];

  return <SidebarNavigation title="LumaDeck" pages={pages} />;
}
