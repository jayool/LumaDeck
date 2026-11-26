// The Quick Install row's text from the backend's status (installRowText):
// step, then filler > sub-phase > phase. The status payloads are the ones
// get_quick_install_status returned on the fake run of 2026-11-24, and `t`
// is the real English translator so the strings themselves are checked
// (the recording of the same day showed "Installing CloudRedirect app" for
// the whole phase because the backend dropped `sub`/`filler`: this pins
// both ends).
import { describe, expect, it } from "vitest";
import { installRowText } from "./installRowText";
import { translate } from "./i18n";

const t = translate;

describe("installRowText", () => {
  it("names the phase with its step", () => {
    expect(installRowText({ step: 2, stepTotal: 9, phase: "slssteam" }, t)).toBe("2/9 · Downloading SLSsteam…");
    expect(installRowText({ step: 4, stepTotal: 9, phase: "cloudredirect_app", sub: null, filler: null }, t))
      .toBe("4/9 · Installing CloudRedirect app");
  });
  it("prefers the app phase's sub-phase over the phase", () => {
    const base = { step: 4, stepTotal: 9, phase: "cloudredirect_app", filler: null };
    expect(installRowText({ ...base, sub: "app_download" }, t)).toBe("4/9 · Downloading CloudRedirect app");
    expect(installRowText({ ...base, sub: "runtime_download" }, t)).toBe("4/9 · Downloading KDE runtime");
    expect(installRowText({ ...base, sub: "app_install" }, t)).toBe("4/9 · Installing CloudRedirect app");
  });
  it("prefers the filler over everything, in the chosen order, and has all eight", () => {
    const base = { step: 4, stepTotal: 9, phase: "cloudredirect_app", sub: "runtime_download" };
    expect(installRowText({ ...base, filler: 0 }, t)).toBe("4/9 · Unpacking files…");
    expect(installRowText({ ...base, filler: 7 }, t)).toBe("4/9 · Finishing up…");
    const seen = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => installRowText({ ...base, filler: i }, t));
    expect(new Set(seen).size).toBe(8);
    expect(seen.every((x) => !x.includes("installFiller_"))).toBe(true);
  });
  it("no byte counts in the text", () => {
    const s = { step: 4, stepTotal: 9, phase: "cloudredirect_app", sub: "runtime_download", filler: null, mbDone: 147, mbTotal: 702, writing: false };
    expect(installRowText(s, t)).toBe("4/9 · Downloading KDE runtime");
  });
  it("falls back to the backend's English label for an unknown phase", () => {
    expect(installRowText({ step: 1, stepTotal: 9, phase: "weird", progress: "Doing things" }, t)).toBe("1/9 · Doing things");
    expect(installRowText({}, t)).toBe("");
  });
});
