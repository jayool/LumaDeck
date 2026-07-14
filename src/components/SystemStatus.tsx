import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { useState } from "react";
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
export type PrimaryAction = "downgrade" | "reinject" | "restart" | null;

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
  const coreHalf =
    (!!sls?.installed && !ll?.installed) || (!sls?.installed && !!ll?.installed);
  const anyUnsupported = installed.some((c) => c.health === "not_supported");
  // lumalinux with no support for the pinned build yet — aligning wouldn't help;
  // it self-heals. No button (the status row explains it).
  if (anyUnsupported && ll?.installed && ll.health === "not_supported" &&
      status.headcrab?.lumalinux_ready === false &&
      !installed.some((c) => c.id !== "lumalinux" && c.health === "not_supported"))
    return null;
  if (anyUnsupported || coreHalf) return "downgrade";
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

  const coreHalf =
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

  // The two-action model: Fix in Desktop (not_supported or a partial install) has
  // priority over Restart (not_loaded / not_injected), because if Steam moved a
  // restart won't help.
  const fixInDesktop = (anyUnsupported || coreHalf) && !waitingForSupport;

  // ---- one system problem, by priority: Fix in Desktop > Restart ----
  if (waitingForSupport) {
    rows.push({
      key: "ll-not-ready", severity: "problem",
      label: t("sysLumalinuxNotReady"), description: t("sysLumalinuxNotReadyDesc"),
    });
  } else if (fixInDesktop) {
    // Desktop-only (Steam is live in Game Mode). The button arms a one-shot
    // autostart and switches to Desktop, where it runs (aligns Steam / finishes
    // the install) and returns automatically. Two-tap confirm because it leaves
    // Game Mode.
    rows.push({
      key: "desktop", severity: "problem",
      label: t("sysNeedsFix"), description: t("sysNeedsFixDesc"),
      actionLabel: busy ? t("sysWorking") : t("sysFixInDesktop"),
      onAction: actions.downgrade,
      confirmFirst: true,
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
  if (cr?.installed && cr.health === "not_authed" && !fixInDesktop) {
    rows.push({
      key: "cr-auth", severity: "problem",
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
  if (!fixInDesktop) {
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
            setConfirming(r.key);
            return;
          }
          setConfirming(null);
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
