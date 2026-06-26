import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { useState } from "react";
import { FaExclamationTriangle, FaArrowCircleUp } from "react-icons/fa";
import { useT } from "../i18n";

// --- The unified component-status shape (matches backend get_components_status) ---
export type ComponentHealth =
  | "not_installed" | "not_active" | "injection_missing" | "hash_blocked"
  | "hooks_failed" | "broken" | "not_authed" | "kill_switched" | "healthy" | string;

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
  headcrab: { compatible: boolean | null; target: number | null; current: number | null };
  plugin: { installed: string | null; latest: string | null; available: boolean };
}

export interface SystemStatusActions {
  restart: () => void;       // not_active
  repair: () => void;        // injection_missing / hooks_failed / broken (Steam OK)
  reinstallCore: () => void; // core half-installed
  downgrade: () => void;     // Steam too new: hand off to Desktop for the downgrade
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

const REPAIRABLE = ["injection_missing", "hooks_failed", "broken"];
const UNSUPPORTED = ["broken", "hash_blocked"]; // "can't hook this Steam build"

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
  const incompatible = status.headcrab?.compatible === false;

  const coreHalf =
    (!!sls?.installed && !ll?.installed) || (!sls?.installed && !!ll?.installed);

  const anyUnsupported = comps.some((c) => c.installed && UNSUPPORTED.includes(c.health));
  // "Steam too new" only when headcrab confirms Steam is off its pin; otherwise a
  // broken/hash_blocked is a genuine reinstall, handled by Repair.
  const needsDowngrade = anyUnsupported && incompatible;

  // ---- one system problem, by priority ----
  if (needsDowngrade) {
    rows.push({
      key: "downgrade", severity: "problem",
      label: t("sysSteamTooNew"), description: t("sysSteamTooNewDesc"),
      // The downgrade is Desktop-only (Steam is live in Game Mode). The button
      // arms a one-shot autostart and switches to Desktop, where it runs and
      // returns automatically. Two-tap confirm because it leaves Game Mode.
      actionLabel: busy ? t("sysWorking") : t("sysFixInDesktop"),
      onAction: actions.downgrade,
      confirmFirst: true,
    });
  } else if (coreHalf) {
    rows.push({
      key: "core", severity: "problem",
      label: t("sysCoreIncomplete"), description: t("sysCoreIncompleteDesc"),
      actionLabel: busy ? t("sysWorking") : t("sysReinstall"),
      onAction: actions.reinstallCore,
    });
  } else {
    const anyRepair = comps.some((c) => c.installed && REPAIRABLE.includes(c.health));
    const anyInactive = comps.some((c) => c.installed && c.health === "not_active");
    if (anyRepair) {
      rows.push({
        key: "repair", severity: "problem",
        label: t("sysNeedsRepair"), description: t("sysNeedsRepairDesc"),
        actionLabel: busy ? t("sysWorking") : t("sysRepair"),
        onAction: actions.repair,
      });
    } else if (anyInactive) {
      rows.push({
        key: "restart", severity: "problem",
        label: t("sysNeedsRestart"), description: t("sysNeedsRestartDesc"),
        actionLabel: busy ? t("sysWorking") : t("restartSteam"),
        onAction: actions.restart,
      });
    }
  }

  // ---- CloudRedirect login (optional, Desktop, independent of the above) ----
  if (cr?.installed && cr.health === "not_authed" && !needsDowngrade) {
    rows.push({
      key: "cr-auth", severity: "problem",
      label: t("sysCloudLogin"), description: t("sysCloudLoginDesc"),
    });
  }

  // ---- unsupported on the CURRENT (pinned) build — hash_blocked while Steam IS
  // at the pin. Not a downgrade (already at the pin; going lower breaks SLS/CR),
  // not a repair (reinstalling the latest gives the same block — the component
  // genuinely doesn't support this Steam build yet). Informational, no action. ----
  if (compatible) {
    for (const c of comps) {
      if (c.installed && c.health === "hash_blocked") {
        rows.push({
          key: `unsup-${c.id}`, severity: "problem",
          label: t("sysUnsupportedBuild", c.name),
          description: t("sysUnsupportedBuildDesc"),
        });
      }
    }
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
  if (!needsDowngrade) {
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
