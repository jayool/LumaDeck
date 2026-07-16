import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { useRef, useState, useEffect } from "react";
import { FaExclamationTriangle, FaArrowCircleUp } from "react-icons/fa";
import { useT } from "../i18n";

// --- The unified component-status shape (matches backend get_components_status) ---
// Canonical state set, shared by all three components. not_authed / disabled
// are CloudRedirect-only. See read_*_health() in backend/paths.py.
export type ComponentHealth =
  | "not_installed" | "not_loaded" | "not_injected" | "not_supported"
  | "not_authed" | "disabled" | "healthy" | string;

export interface Component {
  id: "slssteam" | "cloudredirect" | "lumalinux";
  name: string;
  installed: boolean;
  health: ComponentHealth;
  cause: string | null;
  action: string | null;
  update: { installed: string | null; latest: string | null; available: boolean };
}

export interface ComponentsStatus {
  success: boolean;
  components: Component[];
  headcrab: {
    compatible: boolean | null;
    target: number | null;
    current: number | null;
    // v0.16: is lumalinux's pattern set published for the pinned target build?
    // null = unknown (don't hard-block). Gates the align-Steam-to-pin action so
    // we never push the user onto a build lumalinux can't hook yet.
    lumalinux_ready?: boolean | null;
  };
  plugin: { installed: string | null; latest: string | null; available: boolean };
  // Dev preview override for the Quick Install onboarding (backend/dev.py):
  // "show" forces it on, "hide" forces it off, null/absent = real behaviour.
  quickInstall?: string | null;
}

export interface SystemStatusActions {
  restart: () => void;       // not_loaded — plain Steam restart
  repair: () => void;        // not_injected — re-inject steam.sh, then restart
  reinstallCore: () => void; // (unused since the 2-action model; kept for callers)
  downgrade: () => void;     // not_supported / partial install: hand off to Desktop
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
  // Destructive / Desktop-switching actions ask for a second tap before firing.
  confirmFirst?: boolean;
};

const WARN = "#ff8c00";
const INFO = "#5b9eff";

// From the user's side there are exactly two ways to fix anything: Restart Steam
// (in place) or Fix in Desktop. Every component state maps to one of them.
//   downgrade — not_supported / partial install: hand off to Desktop
//   reinject  — not_injected: re-patch steam.sh, then restart (label: Restart)
//   restart   — not_loaded: plain restart (label: Restart)
export type PrimaryAction = "downgrade" | "core" | "reinject" | "restart" | null;

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
  // lumalinux with no support for the pinned build yet — aligning wouldn't help;
  // it self-heals. No button (the status row explains it).
  if (anyUnsupported && ll?.installed && ll.health === "not_supported" &&
      status.headcrab?.lumalinux_ready === false &&
      !installed.some((c) => c.id !== "lumalinux" && c.health === "not_supported"))
    return null;
  if (anyUnsupported) return "downgrade";
  if (notComplete) return "core"; // at-pin (else it'd be not_supported) → in place
  if (installed.some((c) => c.health === "not_injected")) return "reinject";
  if (installed.some((c) => c.health === "not_loaded")) return "restart";
  return null;
}

// Collapse the per-component status into the minimum the user needs: at most one
// system "problem" row (by priority), CloudRedirect login if pending, any stuck
// games, then the update track. See DESIGN_UI.md "Component model".
function buildRows(
  t: (k: string, ...a: any[]) => string,
  status: ComponentsStatus,
  stuck: { appid: number; name: string }[],
  busy: boolean,
  actions: SystemStatusActions,
): Row[] {
  const rows: Row[] = [];
  const comps = status.components || [];
  const get = (id: string) => comps.find((c) => c.id === id);
  const sls = get("slssteam");
  const cr = get("cloudredirect");
  const ll = get("lumalinux");
  const compatible = status.headcrab?.compatible === true;
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
  //   Waiting > Steam-unsupported (Desktop) > incomplete install (in place) > Restart
  if (waitingForSupport) {
    // Nothing is broken and nothing to do — only new downloads are paused until
    // lumalinux catches up with Steam, and it self-heals. Info track, not a warning.
    rows.push({
      key: "ll-not-ready", severity: "info",
      label: t("sysLumalinuxNotReady"), description: t("sysLumalinuxNotReadyDesc"),
    });
  } else if (anyUnsupported) {
    // Steam moved off a build the hooks can handle. Only a Steam re-align fixes it,
    // and that can't run in Game Mode → hand off to Desktop. Two-tap confirm.
    rows.push({
      key: "desktop", severity: "problem",
      label: t("sysUnsupported"), description: t("sysUnsupportedDesc"),
      actionLabel: busy ? t("sysWorking") : t("sysFixInDesktop"),
      onAction: actions.downgrade,
      confirmFirst: true,
    });
  } else if (notComplete) {
    // A core component is missing. Steam is at the pin here (if it weren't, the
    // installed component would be not_supported and the row above would win), so
    // finishing the install is safe in Game Mode — no Desktop hand-off.
    rows.push({
      key: "incomplete", severity: "problem",
      label: t("sysNotComplete"), description: t("sysNotCompleteDesc"),
      actionLabel: busy ? t("sysWorking") : t("sysFinishSetup"),
      onAction: actions.reinstallCore,
    });
  } else if (anyInjectLost || anyNotLoaded) {
    rows.push({
      key: "restart", severity: "problem",
      label: t("sysNeedsRestart"), description: t("sysNeedsRestartDesc"),
      actionLabel: busy ? t("sysWorking") : t("restartSteam"),
      // not_injected needs steam.sh re-patched first (repair = reinject + restart);
      // a plain not_loaded just needs the restart. Same button label either way.
      onAction: anyInjectLost ? actions.repair : actions.restart,
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
  // lumalinux is independent of headcrab (patch-only, validates itself via its
  // hash check) → its update shows whenever available, regardless of the Steam
  // pin. SLSsteam/CloudRedirect updates RIDE headcrab — re-running it would move
  // the Steam build — so they're only offered when Steam is already at the pin.
  if (!anyUnsupported) {
    // Steam sits BEHIND Headcrab's pin (the pin was bumped forward) and lumalinux
    // is confirmed ready for the new target — offer to move Steam up to the pin as
    // a normal update (info, not a problem). Requires lumalinux_ready === true, not
    // just "not false": pushing a WORKING user up to a build lumalinux can't hook
    // yet would regress them, so only nudge when support is positively published.
    // The button reuses the downgrade hand-off — headcrab.sh applies the pinned
    // Steam build in either direction, so aligning UP is the same machinery.
    const target = status.headcrab?.target;
    const current = status.headcrab?.current;
    const steamBehindPin = target != null && current != null && current < target;
    if (steamBehindPin && llReady === true) {
      rows.push({
        key: "steam-update", severity: "info",
        label: t("sysSteamUpdateAvailable"), description: t("sysSteamUpdateAvailableDesc"),
        actionLabel: busy ? t("sysWorking") : t("sysSteamUpdateBtn"),
        onAction: actions.downgrade,
        confirmFirst: true,
      });
    }

    const llUpdate = !!ll?.installed && !!ll.update?.available;
    // SLSsteam updates are NOT surfaced (choice B): it exposes no readable
    // installed version, and it rides headcrab + is gated anyway. Of the
    // headcrab bundle, only CloudRedirect has a checkable update here.
    const crUpdate = compatible && !!cr?.installed && !!cr.update?.available;
    if (llUpdate || crUpdate) {
      rows.push({
        key: "update", severity: "info",
        label: t("sysUpdateAvailable"), description: t("sysUpdateAvailableDesc"),
        actionLabel: busy ? t("sysWorking") : t("sysUpdate"),
        onAction: actions.update,
      });
    }
  }
  if (status.plugin?.available) {
    rows.push({
      key: "plugin", severity: "info",
      label: t("sysPluginUpdate"), description: t("sysPluginUpdateDesc"),
      actionLabel: busy ? t("sysWorking") : t("sysPluginUpdateBtn"),
      onAction: actions.pluginUpdate,
    });
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

  const rows = buildRows(t, status, stuck, busy, actions);
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
        // A confirmFirst row turns its first tap into "tap again to confirm"; the
        // second tap fires. Other rows fire on the first tap.
        const handleClick = () => {
          if (!r.onAction) return;
          if (r.confirmFirst && !isConfirming) {
            armConfirm(r.key);
            return;
          }
          clearConfirm();
          r.onAction();
        };
        const buttonLabel = r.confirmFirst && isConfirming
          ? t("sysConfirmTap")
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
