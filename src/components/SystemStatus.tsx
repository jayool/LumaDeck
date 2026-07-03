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

export type PrimaryAction = "downgrade" | "core" | "repair" | "restart" | null;

// The single highest-priority SYSTEM action for the current status — the exact
// priority buildRows() uses for its one system-problem row (downgrade > core >
// repair > restart), exported so the Dependencies page can drive its one
// morphing action button from the same logic. Keep in sync with buildRows.
export function primarySystemAction(status: ComponentsStatus | null): PrimaryAction {
  if (!status?.success) return null;
  const comps = status.components || [];
  const sls = comps.find((c) => c.id === "slssteam");
  const ll = comps.find((c) => c.id === "lumalinux");
  const incompatible = status.headcrab?.compatible === false;
  const coreHalf =
    (!!sls?.installed && !ll?.installed) || (!sls?.installed && !!ll?.installed);
  const anyUnsupported = comps.some((c) => c.installed && UNSUPPORTED.includes(c.health));
  // Align-Steam-to-pin only helps when lumalinux ALSO supports the pinned build;
  // if it doesn't (lumalinux_ready === false) there's no good action — the status
  // row explains it. null = unknown -> keep the prior behaviour (offer it).
  if (anyUnsupported && incompatible)
    return status.headcrab?.lumalinux_ready === false ? null : "downgrade";
  if (coreHalf) return "core";
  if (comps.some((c) => c.installed && REPAIRABLE.includes(c.health))) return "repair";
  if (comps.some((c) => c.installed && c.health === "not_active")) return "restart";
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
  const incompatible = status.headcrab?.compatible === false;

  const coreHalf =
    (!!sls?.installed && !ll?.installed) || (!sls?.installed && !!ll?.installed);

  const anyUnsupported = comps.some((c) => c.installed && UNSUPPORTED.includes(c.health));
  // v0.16: is lumalinux ready for the pinned target build? Aligning Steam to the
  // pin only helps when it is; if not, don't push the align — surface a "waiting
  // for lumalinux" info instead (it self-heals on next launch once support ships).
  // null = unknown -> keep prior behaviour (offer the align).
  const llReady = status.headcrab?.lumalinux_ready;
  // "Steam too new" only when headcrab confirms Steam is off its pin; otherwise a
  // broken/hash_blocked is a genuine reinstall, handled by Repair.
  const needsDowngrade = anyUnsupported && incompatible && llReady !== false;
  const lumalinuxNotReady = anyUnsupported && incompatible && llReady === false;

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
  } else if (lumalinuxNotReady) {
    // Steam is off the pin AND lumalinux has no published support for the pinned
    // build yet — aligning Steam wouldn't fix lumalinux. No action: it self-heals
    // on the next launch once the pattern set is published.
    rows.push({
      key: "ll-not-ready", severity: "problem",
      label: t("sysLumalinuxNotReady"), description: t("sysLumalinuxNotReadyDesc"),
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
