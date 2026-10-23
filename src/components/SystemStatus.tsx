import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { useRef, useState, useEffect } from "react";
import { FaExclamationTriangle, FaArrowCircleUp } from "react-icons/fa";
import { useT } from "../i18n";

// --- The unified component-status shape (matches backend get_components_status) ---
// Canonical state set, shared by all three components. not_authed / disabled
// are CloudRedirect-only. See read_*_health() in backend/paths.py.
export type ComponentHealth =
  | "not_installed" | "not_loaded" | "not_injected" | "not_supported" | "unavailable_64"
  | "not_authed" | "disabled" | "healthy" | string;

export interface Component {
  id: "slssteam" | "cloudredirect" | "lumalinux";
  name: string;
  installed: boolean;
  health: ComponentHealth;
  cause: string | null;
  action: string | null;
  update: { installed: string | null; latest: string | null; available: boolean; supports_current_build?: boolean | null };
}

export interface ComponentsStatus {
  success: boolean;
  components: Component[];
  // Which Steam client runs (backend paths.steam_client_arch): "ubuntu12_32" or
  // "steamrt64". Data only; no row reads it yet.
  client?: { arch: string; supported: boolean };
  headcrab: {
    compatible: boolean | null;
    target: number | null;
    current: number | null;
    // v0.16: is lumalinux's pattern set published for the pinned target build?
    // null = unknown (don't hard-block). Gates the align-Steam-to-pin action so
    // we never push the user onto a build lumalinux can't hook yet.
    lumalinux_ready?: boolean | null;
    // Would the LATEST lumalinux release still hook the build the user is on now?
    // false = a newer release re-derived patterns and dropped this build, so
    // updating would break the working install → suppress the lumalinux update
    // offer. null = unknown (don't suppress). See gate on the update row below.
    current_build_supported_by_latest?: boolean | null;
  };
  plugin: { installed: string | null; latest: string | null; available: boolean };
  // The launcher's crash guard (lumalinux/setup.sh): after 3 startup crashes
  // (or 1 right after a Steam update) it latches "safe mode" and launches Steam
  // WITHOUT any injection until the stack changes or the state is cleared.
  // While latched every hook component reads not_loaded and a plain restart
  // does nothing — so the UI shows Recovery mode + Retry instead. Stack-wide.
  guard?: { active: boolean; fails: number; since: string | null; client_changed: boolean };
  // The Steam-update pin (steam.cfg). mine = written by our downgrade.sh after a
  // break-recovery downgrade; the only pin offered for lifting in place.
  // Would Fix in Desktop help? possible === false -> the Wait row, no button.
  downgrade?: { target: number | null; possible: boolean | null };
  freeze?: {
    frozen: boolean; mine: boolean;
    // Our pin holds a client the latest SLSsteam no longer hooks: installing
    // anything would break Steam, so Components hides Reinstall.
    install_blocked?: boolean;
    // Only with our pin: is it safe to let Steam update? (backend/steam_update_gate.py)
    // ready | not_yet | unknown. Advice for the text, never a lock. (A released
    // SLSsteam the user hasn't installed yet still reads ready: lift first, the
    // old SLSsteam aborts cleanly on the new build, then Update is offered.)
    gate?: {
      state: string; blocker?: string | null;
      stable_build?: number | null; slssteam_required?: string | null;
    } | null;
  };
  // Dev preview override for the Quick Install onboarding (backend/dev.py):
  // "show" forces it on, "hide" forces it off, null/absent = real behaviour.
  quickInstall?: string | null;
}

// The "Let Steam update" row's title + description from the gate. The QAM is
// for everyone, so it speaks of "the components" like the Update row does;
// Settings → Components (detailed) names the component, the tag and the build.
export function steamHeldText(
  t: (k: string, ...a: any[]) => string,
  freeze: ComponentsStatus["freeze"] | undefined,
  detailed = false,
): { label: string; description: string } {
  const g = freeze?.gate;
  switch (g?.state) {
    case "ready":
      return {
        label: t("sysSteamReady"),
        description: detailed ? t("compSteamReadyDesc", g?.stable_build ?? "?") : t("sysSteamReadyDesc"),
      };
    case "not_yet":
      return {
        label: t("sysSteamHeld"),
        description: detailed
          ? t("compSteamNotYetDesc", g?.blocker === "lumalinux" ? "lumalinux" : "SLSsteam")
          : t("sysSteamHeldNotYetDesc"),
      };
    default:
      return { label: t("sysSteamHeld"), description: t("sysSteamHeldUnknownDesc") };
  }
}

export interface SystemStatusActions {
  restart: () => void;       // not_loaded — plain Steam restart
  retry: () => void;         // crash guard latched — clear its state, then restart
  repair: () => void;        // not_injected — re-inject steam.sh, then restart
  downgrade: () => void;     // not_supported / partial install: hand off to Desktop (downgrade + pin)
  unpin: () => void;         // our steam.cfg pin: lift it in place, then restart (Steam self-updates)
  update: () => void;        // component update(s) available
  pluginUpdate: () => void;  // LumaDeck plugin update
  openGame: (appid: number) => void; // a stuck game
}

// One rendered row. severity picks the icon colour (problem = ⚠ orange,
// info = ↑ blue). actionLabel present → ButtonItem; absent → display-only Field
// (the fix lives in Desktop, no button we can offer here).
type Row = {
  key: string;
  severity: "problem" | "info";
  label: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  // Every action that restarts Steam or leaves Game Mode asks for a second tap,
  // and the first tap SAYS which of the two it is about to do:
  //   "restart" → "Confirm (restarts Steam)"   "desktop" → "Confirm (continues in Desktop)"
  // Actions that do neither (open a game, download the plugin zip) fire at once.
  confirm?: "restart" | "desktop";
  // Label while the action runs. Default "Working..." (setup.sh + restart);
  // actions that ONLY restart Steam say so ("Restarting Steam...").
  busyLabel?: string;
  // Advice derived from what THIS plugin version knows about Steam (the
  // components' client lists, the update gate): every "Steam build not
  // supported" variant, the held-Steam advice, the component update offer.
  // An older plugin can get these wrong after a Steam change (2026-10-14: a
  // user on 0.11.0 saw nothing useful until 0.11.2), so while a LumaDeck update
  // is pending they are hidden behind the update row. Rows without this flag
  // are facts the plugin version cannot change (not loaded, guard latched, a
  // stuck game, cloud login) and stay visible.
  feedAdvice?: boolean;
};

const WARN = "#ff8c00";
const INFO = "#5b9eff";

// From the user's side there are exactly two ways to fix anything: Restart Steam
// (in place) or Fix in Desktop. Every component state maps to one of them.
//   downgrade — not_supported / partial install: hand off to Desktop
//   retry     — crash guard latched: clear its state, then restart (label: Re-enable injection)
//   reinject  — not_injected: re-patch steam.sh, then restart (label: Restart)
//   restart   — not_loaded: plain restart (label: Restart)
export type PrimaryAction = "downgrade" | "update" | "unpin" | "retry" | "reinject" | "restart" | null;

// Broken, no update fixes it, but Steam is held by a pin (ours or headcrab's)
// and the gate says the build Valve serves now is hooked by the released
// components: the fix is to let Steam update (the SteamOS-image client of
// 2026-10-14: nothing hooks it, and the only way out is up). Downgrading would
// land on a client the latest components no longer hook.
export function unpinFixesBreak(status: ComponentsStatus | null): boolean {
  return !!status?.freeze?.frozen && status?.freeze?.gate?.state === "ready";
}

// A Steam update broke a component, and a RELEASED update of that component
// hooks the client on disk: the fix is Update, not a downgrade. True only when
// every broken component can be fixed that way (one that can't still needs
// Desktop). Backend: components[].update.supports_current_build, from the
// components' own feeds against the sha256 of the installed steamclient.so.
export function updateFixesBreak(status: ComponentsStatus | null): boolean {
  const installed = (status?.components || []).filter((c) => c.installed);
  const broken = installed.filter((c) => c.health === "not_supported");
  if (broken.length === 0) return false;
  return broken.every((c) => !!c.update?.available && c.update?.supports_current_build === true);
}

// The single highest-priority SYSTEM action for the current status, exported so
// the Dependencies page drives its one morphing button from the same logic as
// the QAM's problem row. Priority: Fix in Desktop > Restart. Keep in sync with
// buildRows.
export function primarySystemAction(status: ComponentsStatus | null): PrimaryAction {
  if (!status?.success) return null;
  const comps = status.components || [];
  const installed = comps.filter((c) => c.installed);
  const sls = comps.find((c) => c.id === "slssteam");
  const ll = comps.find((c) => c.id === "lumalinux");
  const notComplete =
    (!!sls?.installed && !ll?.installed) || (!sls?.installed && !!ll?.installed);
  const anyUnsupported = installed.some((c) => c.health === "not_supported");
  // Same order as buildRows: a fix that exists outranks "wait".
  if (anyUnsupported && updateFixesBreak(status)) return "update";
  if (anyUnsupported && unpinFixesBreak(status)) return "unpin";
  // lumalinux with no support for the pinned build yet — aligning wouldn't help;
  // it self-heals. No button (the status row explains it).
  if (anyUnsupported && ll?.installed && ll.health === "not_supported" &&
      status.headcrab?.lumalinux_ready === false &&
      !installed.some((c) => c.id !== "lumalinux" && c.health === "not_supported"))
    return null;
  if (anyUnsupported && status.downgrade?.possible === false) return null; // wait
  if (anyUnsupported) return "downgrade";
  // Guard latched: the not_loaded/not_injected below are its SYMPTOM, and their
  // restart/repair can't lift it (the launcher goes vanilla again) — Retry can.
  if (status.guard?.active) return "retry";
  // A core half-install (SLSsteam xor lumalinux) is the same repair as
  // not_injected: one setup.sh run, then restart.
  if (notComplete || installed.some((c) => c.health === "not_injected")) return "reinject";
  if (installed.some((c) => c.health === "not_loaded")) return "restart";
  return null;
}

// Collapse the per-component status into the minimum the user needs: at most one
// system "problem" row (by priority), CloudRedirect login if pending, any stuck
// games, then the update track. See DESIGN_UI.md "Component model".
// Exported for the unit tests (src/components/SystemStatus.test.ts).
export function buildRows(
  t: (k: string, ...a: any[]) => string,
  status: ComponentsStatus,
  stuck: { appid: number; name: string }[],
  actions: SystemStatusActions,
): Row[] {
  const rows: Row[] = [];
  const comps = status.components || [];
  const get = (id: string) => comps.find((c) => c.id === id);
  const sls = get("slssteam");
  const cr = get("cloudredirect");
  const ll = get("lumalinux");
  const installed = comps.filter((c) => c.installed);

  // A core component is installed but its partner isn't (a failed/partial install).
  const notComplete =
    (!!sls?.installed && !ll?.installed) || (!sls?.installed && !!ll?.installed);

  const anyUnsupported = installed.some((c) => c.health === "not_supported");
  const anyInjectLost = installed.some((c) => c.health === "not_injected");
  const anyNotLoaded = installed.some((c) => c.health === "not_loaded");

  // lumalinux has no published support for the pinned Steam build yet — aligning
  // Steam wouldn't help, it self-heals on the next launch once support ships. Only
  // when lumalinux is the ONLY unsupported thing (others would still need Desktop).
  const llReady = status.headcrab?.lumalinux_ready;
  const waitingForSupport =
    anyUnsupported && llReady === false &&
    !!ll?.installed && ll.health === "not_supported" &&
    !installed.some((c) => c.id !== "lumalinux" && c.health === "not_supported");

  // ---- one system problem, by priority ----
  //   Steam-unsupported (Update / Let Steam update / Wait / Desktop) > Recovery > Restart
  // "A Steam update broke a component" is ONE row with one mould: the title is
  // always "Steam build not supported"; the description names the button that
  // fixes it (Update / Fix in Desktop / Let Steam update), or says to wait when
  // nothing can. Orange in every case: adding games does not work.
  if (anyUnsupported && updateFixesBreak(status)) {
    // The component already shipped support for the new build: Update (one
    // setup.sh run) is the fix. Downgrading here would pin Steam on an old
    // client the updated component no longer hooks.
    rows.push({
      key: "update-fix", feedAdvice: true, severity: "problem",
      label: t("sysUnsupported"), description: t("sysUnsupportedFix", t("sysUpdate")),
      actionLabel: t("sysUpdate"),
      onAction: actions.update,
      confirm: "restart",
    });
  } else if (anyUnsupported && unpinFixesBreak(status)) {
    // Broken on a client nothing hooks, held by our pin, and Valve's current
    // build is supported: let Steam update.
    rows.push({
      key: "unpin-fix", feedAdvice: true, severity: "problem",
      label: t("sysUnsupported"), description: t("sysUnsupportedFix", t("sysLetSteamUpdate")),
      actionLabel: t("sysLetSteamUpdate"),
      onAction: actions.unpin,
      confirm: "restart", busyLabel: t("restartingSteam"),
    });
  } else if (waitingForSupport || (anyUnsupported && status.downgrade?.possible === false)) {
    // Nothing can fix it from here: lumalinux has not published support for
    // this build yet (it self-heals once the cron does), or the downgrade would
    // land on a client the latest SLSsteam no longer hooks.
    rows.push({
      key: "wait", feedAdvice: true, severity: "problem",
      label: t("sysUnsupported"), description: t("sysUnsupportedWait"),
    });
  } else if (anyUnsupported) {
    // Steam moved off a build the hooks can handle and the latest components
    // still hook the downgrade target: hand off to Desktop. Two-tap confirm.
    rows.push({
      key: "desktop", feedAdvice: true, severity: "problem",
      label: t("sysUnsupported"), description: t("sysUnsupportedFix", t("sysFixInDesktop")),
      actionLabel: t("sysFixInDesktop"),
      onAction: actions.downgrade,
      confirm: "desktop",
    });
  } else if (status.guard?.active) {
    // The launcher's crash guard is latched: Steam runs with NO injection until
    // its state is cleared. A restart alone cannot lift it, so the restart row
    // below (which the not_loaded symptom would otherwise trigger) must not
    // show. Retry clears the guard's state files and restarts; if the cause is
    // still there the guard re-latches after three more crashes.
    rows.push({
      key: "guard", severity: "problem",
      label: t("sysRecovery"), description: t("sysRecoveryDesc"),
      actionLabel: t("sysReenable"),
      onAction: actions.retry,
      confirm: "restart", busyLabel: t("restartingSteam"),
    });
  } else if (anyInjectLost || notComplete || anyNotLoaded) {
    // not_injected and a core half-install (SLSsteam xor lumalinux) need
    // setup.sh first (repair = one setup.sh run + restart); a plain not_loaded
    // just needs the restart. Same row and button either way; the busy label
    // tells them apart (setup.sh runs before the restart).
    const needsSetup = anyInjectLost || notComplete;
    rows.push({
      key: "restart", severity: "problem",
      label: t("sysNeedsRestart"), description: t("sysNeedsRestartDesc"),
      actionLabel: t("restartSteam"),
      onAction: needsSetup ? actions.repair : actions.restart,
      confirm: "restart", busyLabel: needsSetup ? undefined : t("restartingSteam"),
    });
  } else if (sls?.installed && sls.health === "unavailable_64") {
    // Steam runs its 64-bit client and there is no 64-bit SLSsteam build on
    // disk (none published yet): nothing to press. Added games don't work.
    rows.push({
      key: "x64-sls", severity: "problem",
      label: t("sysX64NotReady"), description: t("sysX64NotReadyDesc"),
    });
  } else if (cr?.installed && cr.health === "unavailable_64") {
    // Same client, SLSsteam fine, CloudRedirect 32-bit only: cloud saves off.
    rows.push({
      key: "x64-cr", severity: "problem",
      label: t("sysX64NoCloud"), description: t("sysX64NoCloudDesc"),
    });
  }

  // ---- CloudRedirect sign-in (optional, Desktop, independent of the above) ----
  // Not a failure — nothing is broken, cloud saves just aren't linked yet — so it
  // rides the info track (blue ↑), not the warning track.
  if (cr?.installed && cr.health === "not_authed" && !anyUnsupported) {
    rows.push({
      key: "cr-auth", severity: "info",
      label: t("sysCloudLogin"), description: t("sysCloudLoginDesc"),
    });
  }

  // ---- stuck games (per-game problem, "with the errors") ----
  for (const s of stuck) {
    rows.push({
      key: `stuck-${s.appid}`, severity: "problem",
      label: t("sysStuck", s.name), description: t("sysStuckDesc"),
      actionLabel: t("sysOpenGame"), onAction: () => actions.openGame(s.appid),
    });
  }

  // ---- updates (info track) ----
  // Component updates roll independently of the Steam build: applying one re-runs
  // setup.sh (wrapper model), which is Steam-build-agnostic, so each is offered
  // whenever a newer version exists — no per-build gate. The one guard is the
  // abnormal state: while Steam has broken the hooks (any component not_supported)
  // the whole block is skipped (the downgrade row above owns that case), and
  // updates resume once the stack hooks the build again.
  if (!anyUnsupported) {
    // A steam.cfg pin, whoever wrote it (our downgrade.sh signs it; headcrab's
    // installer writes an unsigned one): Steam is held at an older build so the
    // stack keeps working. Lifting it needs no Desktop: strip steam.cfg and
    // restart, Steam self-updates on the way up. Offered whenever a pin is on;
    // the gate (steamHeldText) says whether the released components are ready
    // for Valve's build. Advice, never a lock. (The old "Steam update available /
    // Update in Desktop" row for a headcrab pin went with lift-on-install,
    // 2026-10-15.)
    if (status.freeze?.frozen) {
      const txt = steamHeldText(t, status.freeze);
      rows.push({
        key: "steam-held", feedAdvice: true, severity: "info",
        label: txt.label, description: txt.description,
        actionLabel: t("sysLetSteamUpdate"),
        onAction: actions.unpin,
        confirm: "restart", busyLabel: t("restartingSteam"),
      });
    }

    // No per-build gate: an update just re-runs setup.sh, which handles any Steam
    // build. The abnormal case (hooks broken → not_supported) is already excluded
    // by the enclosing `if (!anyUnsupported)`, so here we only ask "is there a
    // newer version of an installed component?".
    const llUpdate = !!ll?.installed && !!ll.update?.available;
    const crUpdate = !!cr?.installed && !!cr.update?.available;
    // An SLSsteam release that no longer hooks the client on disk is not an
    // update to offer: installing it is the 2026-10-14 crash loop. While the
    // pin holds that client, the held row says to let Steam update first.
    const slsUpdate = !!sls?.installed && !!sls.update?.available &&
      sls.update?.supports_current_build !== false;
    if (llUpdate || crUpdate || slsUpdate) {
      rows.push({
        key: "update", feedAdvice: true, severity: "info",
        label: t("sysUpdateAvailable"), description: t("sysUpdateAvailableDesc"),
        actionLabel: t("sysUpdate"),
        onAction: actions.update,
        confirm: "restart",
      });
    }
  }
  // A pending LumaDeck update goes first and hides the feedAdvice rows (see
  // Row): when Steam breaks something, the right advice usually ships in the
  // plugin, and an old plugin's reading of the feeds is what went wrong on
  // 2026-10-14. The fact rows stay below it — a Restart or a stuck game is
  // true whatever the plugin version, and hiding them for days while the
  // update waits cost more than it protected. Orange when a hidden row was a
  // problem, blue otherwise. Settings ▸ Components keeps its button.
  if (status.plugin?.available) {
    const hidesProblem = rows.some((r) => r.feedAdvice && r.severity === "problem");
    return [{
      key: "plugin", severity: hidesProblem ? "problem" : "info",
      label: t("sysPluginUpdate"), description: t("sysPluginUpdateDesc"),
      actionLabel: t("sysPluginUpdateBtn"),
      onAction: actions.pluginUpdate,
    }, ...rows.filter((r) => !r.feedAdvice)];
  }

  return rows;
}

// One native surface for both "something's wrong" and "something's new". Renders
// nothing when there's nothing to say. Replaces HealthBanner + UpdatesBanner.
export function SystemStatus({
  status, stuck, busy, actions,
}: {
  status: ComponentsStatus | null;
  stuck: { appid: number; name: string }[];
  busy: boolean;
  actions: SystemStatusActions;
}) {
  const t = useT();
  // Which row is mid-confirm (first tap done, waiting for the second).
  const [confirming, setConfirming] = useState<string | null>(null);
  // Auto-revert the two-tap confirm, mirroring the Quick Install button: a first
  // tap arms the row, and if the second tap doesn't come within 5s the label
  // reverts to the action instead of staying "Press again to confirm" forever.
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const armConfirm = (key: string) => {
    if (confirmTimer.current) clearTimeout(confirmTimer.current);
    setConfirming(key);
    confirmTimer.current = setTimeout(() => setConfirming(null), 5000);
  };
  const clearConfirm = () => {
    if (confirmTimer.current) { clearTimeout(confirmTimer.current); confirmTimer.current = null; }
    setConfirming(null);
  };
  useEffect(() => () => { if (confirmTimer.current) clearTimeout(confirmTimer.current); }, []);
  if (!status?.success) return null;

  const rows = buildRows(t, status, stuck, actions);
  if (rows.length === 0) return null;

  return (
    <PanelSection>
      {rows.map((r) => {
        const icon =
          r.severity === "problem" ? (
            <FaExclamationTriangle color={WARN} />
          ) : (
            <FaArrowCircleUp color={INFO} />
          );
        const isConfirming = confirming === r.key;
        // A row with `confirm` turns its first tap into the explicit confirm
        // label (what is about to happen); the second tap fires. Rows without
        // it fire on the first tap.
        const handleClick = () => {
          if (!r.onAction) return;
          if (r.confirm && !isConfirming) {
            armConfirm(r.key);
            return;
          }
          clearConfirm();
          r.onAction();
        };
        const buttonLabel = busy
          ? (r.busyLabel ?? t("sysWorking"))
          : r.confirm && isConfirming
            ? t(r.confirm === "desktop" ? "confirmContinuesDesktop" : "confirmRestartsSteam")
            : r.actionLabel;
        return (
          <PanelSectionRow key={r.key}>
            {r.actionLabel && r.onAction ? (
              <ButtonItem
                layout="below"
                icon={icon}
                label={r.label}
                description={r.description}
                onClick={handleClick}
                disabled={busy}
              >
                {buttonLabel}
              </ButtonItem>
            ) : (
              <Field icon={icon} label={r.label} description={r.description} />
            )}
          </PanelSectionRow>
        );
      })}
    </PanelSection>
  );
}
