import { useEffect, useState } from "react";

import { getQuickInstallStatus } from "../api";
import { formatElapsed } from "../format";
import { useT } from "../i18n";

/**
 * Live progress of a setup.sh run (Quick Install, Update, Repair, Reinstall:
 * they all drive the same backend state, get_quick_install_status). While
 * `active`, polls once a second and returns the translated phase label
 * (installer.INSTALL_PHASES ids → installPhase_* strings, the backend's
 * English text as fallback), curl's percent for the download in flight (null
 * between downloads → indeterminate bar) and the time elapsed, so a silent
 * minutes-long step still reads as alive. Resets when `active` drops.
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
    const poll = setInterval(async () => {
      setNow(Date.now());
      try {
        const s: any = await getQuickInstallStatus();
        const key = s.phase ? `installPhase_${s.phase}` : "";
        const text = key && t(key) !== key ? t(key) : (s.progress || "");
        if (text) setLabel(text);
        setPercent(typeof s.percent === "number" ? s.percent : null);
      } catch { }
    }, 1000);
    return () => clearInterval(poll);
    // t is stable for a given language; a language switch mid-run only
    // affects the next poll's label.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  return { label, percent, elapsed: startedAt ? formatElapsed(now - startedAt) : "" };
}
