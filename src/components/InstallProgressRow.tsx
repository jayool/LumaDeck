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
  return (
    <PanelSectionRow>
      <Field label={text} childrenLayout="below" childrenContainerWidth="max" bottomSeparator="none">
        <ProgressBar indeterminate={percent === null} nProgress={percent ?? 0} />
      </Field>
    </PanelSectionRow>
  );
}
