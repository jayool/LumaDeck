// The QAM's system-status rows: which row shows, with which button, for each
// component state. buildRows is the one place that turns the backend's status
// payload into what the user sees, and it has been reworked three times in a
// week (2026-10-14/15/19); these cases pin the agreed behaviour. `t` returns
// the i18n key, so assertions name keys, not English text.
import { describe, expect, it } from "vitest";
import {
  buildRows, primarySystemAction, type ComponentsStatus, type Component,
} from "./SystemStatus";

const t = (k: string, ..._a: any[]) => k;

const actions = {
  restart: () => {}, retry: () => {}, repair: () => {}, downgrade: () => {},
  unpin: () => {}, update: () => {}, pluginUpdate: () => {}, openGame: (_: number) => {},
};

function comp(id: Component["id"], over: Partial<Component> = {}): Component {
  return {
    id, name: id, installed: true, health: "healthy", cause: null, action: null,
    update: { installed: "1", latest: "1", available: false, supports_current_build: null },
    ...over,
  };
}

function status(over: Partial<ComponentsStatus> = {}, comps?: Component[]): ComponentsStatus {
  return {
    success: true,
    components: comps ?? [comp("slssteam"), comp("cloudredirect"), comp("lumalinux")],
    headcrab: { compatible: true, target: 1, current: 1, lumalinux_ready: true, current_build_supported_by_latest: true },
    plugin: { installed: "0.11.4", latest: "0.11.4", available: false },
    guard: { active: false, fails: 0, since: null, client_changed: false },
    freeze: { frozen: false, mine: false, install_blocked: false, gate: null },
    downgrade: { target: 1, possible: true },
    ...over,
  } as ComponentsStatus;
}

const rows = (s: ComponentsStatus, stuck: { appid: number; name: string }[] = []) =>
  buildRows(t, s, stuck, actions);
const keys = (s: ComponentsStatus, stuck: { appid: number; name: string }[] = []) =>
  rows(s, stuck).map((r) => r.key);

describe("nothing to say", () => {
  it("renders no rows when every component is healthy and nothing is pending", () => {
    expect(keys(status())).toEqual([]);
    expect(primarySystemAction(status())).toBeNull();
  });
});

describe("a Steam update broke a component (not_supported)", () => {
  const broken = (upd: Partial<Component["update"]> = {}) =>
    [comp("slssteam", { health: "not_supported", update: { installed: "1", latest: "2", available: true, supports_current_build: null, ...upd } }),
     comp("cloudredirect"), comp("lumalinux")];

  it("Update when the released component hooks the client on disk", () => {
    const s = status({}, broken({ supports_current_build: true }));
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["update-fix"]);
    expect(r[0].actionLabel).toBe("sysUpdate");
    expect(r[0].severity).toBe("problem");
    expect(primarySystemAction(s)).toBe("update");
  });

  it("Let Steam update when a pin holds a client nothing hooks and Valve's build is ready", () => {
    const s = status({ freeze: { frozen: true, mine: true, install_blocked: false, gate: { state: "ready", blocker: null } } }, broken());
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["unpin-fix"]);
    expect(r[0].actionLabel).toBe("sysLetSteamUpdate");
    expect(primarySystemAction(s)).toBe("unpin");
  });

  it("Wait, with no button, while lumalinux has no support for the build yet", () => {
    const s = status(
      { headcrab: { compatible: true, target: 1, current: 1, lumalinux_ready: false } },
      [comp("slssteam"), comp("cloudredirect"), comp("lumalinux", { health: "not_supported" })],
    );
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["wait"]);
    expect(r[0].actionLabel).toBeUndefined();
    expect(primarySystemAction(s)).toBeNull();
  });

  it("Wait when the downgrade would land on a client the latest SLSsteam no longer hooks", () => {
    const s = status({ downgrade: { target: 1, possible: false } }, broken());
    expect(keys(s)).toEqual(["wait"]);
    expect(primarySystemAction(s)).toBeNull();
  });

  it("Fix in Desktop otherwise", () => {
    const s = status({}, broken());
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["desktop"]);
    expect(r[0].actionLabel).toBe("sysFixInDesktop");
    expect(r[0].confirm).toBe("desktop");
    expect(primarySystemAction(s)).toBe("downgrade");
  });

  it("offers no component update and no cloud login while anything is not_supported", () => {
    const s = status(
      { freeze: { frozen: true, mine: true, install_blocked: false, gate: { state: "not_yet", blocker: null } } },
      [comp("slssteam", { health: "not_supported" }),
       comp("cloudredirect", { health: "not_authed" }),
       comp("lumalinux", { update: { installed: "1", latest: "2", available: true } })],
    );
    expect(keys(s)).toEqual(["desktop"]);
  });
});

describe("recovery and restart", () => {
  it("Recovery mode with Re-enable injection when the crash guard is latched, even though components read not_loaded", () => {
    const s = status(
      { guard: { active: true, fails: 3, since: "x", client_changed: false } },
      [comp("slssteam", { health: "not_loaded" }), comp("cloudredirect"), comp("lumalinux", { health: "not_loaded" })],
    );
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["guard"]);
    expect(r[0].actionLabel).toBe("sysReenable");
    expect(primarySystemAction(s)).toBe("retry");
  });

  it("Restart (plain) when a component is installed but not loaded", () => {
    const s = status({}, [comp("slssteam", { health: "not_loaded" }), comp("cloudredirect"), comp("lumalinux")]);
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["restart"]);
    expect(r[0].onAction).toBe(actions.restart);
    expect(r[0].busyLabel).toBe("restartingSteam");
    expect(primarySystemAction(s)).toBe("restart");
  });

  it("Restart via repair (setup.sh first) when injection was lost or the core install is half there", () => {
    const lost = status({}, [comp("slssteam", { health: "not_injected" }), comp("cloudredirect"), comp("lumalinux")]);
    expect(rows(lost)[0].onAction).toBe(actions.repair);
    expect(primarySystemAction(lost)).toBe("reinject");

    const half = status({}, [comp("slssteam"), comp("cloudredirect"), comp("lumalinux", { installed: false, health: "not_installed" })]);
    expect(rows(half)[0].key).toBe("restart");
    expect(rows(half)[0].onAction).toBe(actions.repair);
    expect(primarySystemAction(half)).toBe("reinject");
  });
});

describe("Steam runs its 64-bit client (unavailable_64)", () => {
  it("one orange row, no button, when SLSsteam has no 64-bit build; CloudRedirect's row yields to it", () => {
    const s = status({}, [
      comp("slssteam", { health: "unavailable_64" }),
      comp("cloudredirect", { health: "unavailable_64" }),
      comp("lumalinux"),
    ]);
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["x64-sls"]);
    expect(r[0].label).toBe("sysX64NotReady");
    expect(r[0].severity).toBe("problem");
    expect(r[0].actionLabel).toBeUndefined();
    // Not a half-install and not "not loaded": no restart / repair.
    expect(primarySystemAction(s)).toBeNull();
  });

  it("the cloud-saves row when only CloudRedirect lacks a 64-bit build", () => {
    const s = status({}, [comp("slssteam"), comp("cloudredirect", { health: "unavailable_64" }), comp("lumalinux")]);
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["x64-cr"]);
    expect(r[0].label).toBe("sysX64NoCloud");
    expect(r[0].actionLabel).toBeUndefined();
    expect(primarySystemAction(s)).toBeNull();
  });

  it("a real problem still outranks it", () => {
    const s = status({}, [comp("slssteam", { health: "unavailable_64" }), comp("cloudredirect", { health: "unavailable_64" }), comp("lumalinux", { health: "not_loaded" })]);
    expect(rows(s).map((x) => x.key)).toEqual(["restart"]);
  });
});

describe("info track", () => {
  it("cloud login as a blue row when CloudRedirect is installed but not signed in", () => {
    const s = status({}, [comp("slssteam"), comp("cloudredirect", { health: "not_authed" }), comp("lumalinux")]);
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["cr-auth"]);
    expect(r[0].severity).toBe("info");
  });

  it("one orange row per stuck game, with Open game", () => {
    const r = rows(status(), [{ appid: 10, name: "A" }, { appid: 20, name: "B" }]);
    expect(r.map((x) => x.key)).toEqual(["stuck-10", "stuck-20"]);
    expect(r[0].severity).toBe("problem");
    expect(r[0].actionLabel).toBe("sysOpenGame");
  });

  it("Steam held: Let Steam update is offered whenever a pin is on", () => {
    const s = status({ freeze: { frozen: true, mine: false, install_blocked: false, gate: { state: "ready", blocker: null } } });
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["steam-held"]);
    expect(r[0].actionLabel).toBe("sysLetSteamUpdate");
    expect(r[0].label).toBe("sysSteamReady");
  });

  it("component update offered for lumalinux, and for SLSsteam only when the release still hooks the client", () => {
    const ll = status({}, [comp("slssteam"), comp("cloudredirect"), comp("lumalinux", { update: { installed: "1", latest: "2", available: true } })]);
    expect(keys(ll)).toEqual(["update"]);

    const slsBad = status({}, [comp("slssteam", { update: { installed: "1", latest: "2", available: true, supports_current_build: false } }), comp("cloudredirect"), comp("lumalinux")]);
    expect(keys(slsBad)).toEqual([]);

    const slsOk = status({}, [comp("slssteam", { update: { installed: "1", latest: "2", available: true, supports_current_build: true } }), comp("cloudredirect"), comp("lumalinux")]);
    expect(keys(slsOk)).toEqual(["update"]);
  });
});

describe("a LumaDeck update is pending", () => {
  const pending = { plugin: { installed: "0.11.3", latest: "0.11.4", available: true } };

  it("is the only row, blue, when nothing else is going on", () => {
    const r = rows(status(pending));
    expect(r.map((x) => x.key)).toEqual(["plugin"]);
    expect(r[0].severity).toBe("info");
    expect(r[0].actionLabel).toBe("sysPluginUpdateBtn");
  });

  it("keeps the fact rows under it: Restart, the cloud login, a stuck game", () => {
    const s = status(pending, [comp("slssteam", { health: "not_loaded" }), comp("cloudredirect", { health: "not_authed" }), comp("lumalinux")]);
    const r = rows(s, [{ appid: 10, name: "A" }]);
    expect(r.map((x) => x.key)).toEqual(["plugin", "restart", "cr-auth", "stuck-10"]);
    // The restart row carries the orange itself; the update row stays blue.
    expect(r[0].severity).toBe("info");
    expect(r[1].severity).toBe("problem");
  });

  it("keeps Recovery mode under it", () => {
    const s = status({ ...pending, guard: { active: true, fails: 3, since: "x", client_changed: false } },
      [comp("slssteam", { health: "not_loaded" }), comp("cloudredirect"), comp("lumalinux")]);
    expect(keys(s)).toEqual(["plugin", "guard"]);
  });

  it("hides the feed-based advice (Steam build not supported, held Steam, component updates) and turns orange when it hid a problem", () => {
    const s = status(pending, [comp("slssteam", { health: "not_supported" }), comp("cloudredirect"), comp("lumalinux")]);
    const r = rows(s);
    expect(r.map((x) => x.key)).toEqual(["plugin"]);
    expect(r[0].severity).toBe("problem");

    const held = status({ ...pending, freeze: { frozen: true, mine: true, install_blocked: false, gate: { state: "ready", blocker: null } } },
      [comp("slssteam"), comp("cloudredirect"), comp("lumalinux", { update: { installed: "1", latest: "2", available: true } })]);
    const rh = rows(held);
    expect(rh.map((x) => x.key)).toEqual(["plugin"]);
    expect(rh[0].severity).toBe("info");
  });
});
