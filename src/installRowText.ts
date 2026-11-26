/**
 * The row's text from one status poll: "4/9 · Downloading KDE runtime" (the
 * step, then the filler line if the backend set one, else the app phase's
 * sub-phase, else the phase through i18n with the backend's English label as
 * fallback). Short enough for the QAM's one line (the long form was clipped
 * at "147 of 7", recording 2026-11-23). No byte counts: the sub-phase and the
 * fillers say what is going on instead (chosen 2026-11-24). Pure, so the
 * mapping is tested without the hook.
 */
export function installRowText(s: any, t: (key: string, ...args: any[]) => string): string {
  const key = s.phase ? `installPhase_${s.phase}` : "";
  const phaseText = key && t(key) !== key ? t(key) : (s.progress || "");
  const step = typeof s.step === "number" && s.step > 0 && typeof s.stepTotal === "number"
    ? t("installStepOf", s.step, s.stepTotal) + " · "
    : "";
  const fillerKey = typeof s.filler === "number" ? `installFiller_${s.filler}` : "";
  const subKey = s.sub ? `installSub_${s.sub}` : "";
  const text = fillerKey && t(fillerKey) !== fillerKey ? t(fillerKey)
    : subKey && t(subKey) !== subKey ? t(subKey)
    : phaseText;
  return text ? step + text : "";
}
