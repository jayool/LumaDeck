import { useEffect, useState } from "react";

import { getQuickInstallStatus } from "../api";
import { formatElapsed } from "../format";
import { useT } from "../i18n";

/**
 * Live progress of a setup.sh run (Quick Install, Update, Repair, Reinstall:
 * they all drive the same backend state, get_quick_install_status). While
 * `active`, polls once a second and returns the text for the row ("Step 4 of
 * 9 · Installing CloudRedirect app · 2:10": the phase through i18n, the
 * backend's English label as fallback) and the overall percent of the one bar
 * (backend/install_progress.py: byte-weighted phases filled by curl's and
 * flatpak's own numbers, a short capped time fill where nothing reports).
 * Resets when `active` drops.
 */
export function useInstallProgress(active: boolean) {
  const t = useT();
  const [label, setLabel] = useState("");
  const [percent, setPercent] = useState<number | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (!active) {
      setLabel("");
      setPercent(null);
      setStartedAt(0);
      return;
    }
    const began = Date.now();
    setStartedAt(began);
    setNow(began);
    setLabel(t("installPhase_preparing"));
    setPercent(0);
    const poll = setInterval(async () => {
      setNow(Date.now());
      try {
        const s: any = await getQuickInstallStatus();
        const key = s.phase ? `installPhase_${s.phase}` : "";
        const phaseText = key && t(key) !== key ? t(key) : (s.progress || "");
        const step = typeof s.step === "number" && s.step > 0 && typeof s.stepTotal === "number"
          ? t("installStepOf", s.step, s.stepTotal) + "  ·  "
          : "";
        if (phaseText) setLabel(step + phaseText);
        setPercent(typeof s.overall === "number" ? s.overall : null);
      } catch { }
    }, 1000);
    return () => clearInterval(poll);
    // t is stable for a given language; a language switch mid-run only
    // affects the next poll's label.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  return { label, percent, elapsed: startedAt ? formatElapsed(now - startedAt) : "" };
}
