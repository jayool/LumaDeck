import { Field, PanelSectionRow, ProgressBar } from "@decky/ui";

/**
 * Progress of a setup.sh run in the QAM: "Step N of M · phase · elapsed" as
 * a Field's label, and Decky's plain ProgressBar below it, full width
 * (childrenLayout="below" + childrenContainerWidth="max"), showing the
 * overall percent of the run (backend/install_progress.py); indeterminate
 * only before the first status arrives.
 *
 * Not ProgressBarWithInfo: that one is an Item (label column left, control
 * right) and in the QAM's width the bar landed in the right half, off the
 * edge, with the text clipped; layout="below" did not move it (codespace
 * screenshots, 2026-11-23).
 */
export function InstallProgressRow({ label, percent, elapsed }: {
  label: string;
  percent: number | null;
  elapsed: string;
}) {
  const text = elapsed ? `${label}  ·  ${elapsed}` : label;
  // Description-sized text (the small grey of "LumaDeck isn't set up yet…"),
  // not the Field's label size: at label size the line wrapped in the QAM
  // ("Step 4 of 9 · Installing" / "CloudRedirect app · 0:14", recordings
  // 2026-11-23).
  const small = (
    <span style={{ fontSize: "12px", fontWeight: "normal", color: "#8b929a", whiteSpace: "nowrap" }}>
      {text}
    </span>
  );
  return (
    <PanelSectionRow>
      <Field label={small} childrenLayout="below" childrenContainerWidth="max" bottomSeparator="none">
        {/* No transition and never indeterminate once the run started: the
            bar is measured monotonic in the backend, and the only dips left
            on the recordings (codespace 2026-11-23, 5 frames/s) were the
            component animating from 0 at a phase change. */}
        <ProgressBar key="install-bar" indeterminate={false} nProgress={percent ?? 0} nTransitionSec={0} />
      </Field>
    </PanelSectionRow>
  );
}
