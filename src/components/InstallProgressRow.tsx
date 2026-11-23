import { PanelSectionRow, ProgressBarWithInfo } from "@decky/ui";

/**
 * Steam's own progress row for a setup.sh run: a real bar while something
 * downloads (curl's percent), indeterminate otherwise, the phase label and
 * the elapsed time in the one info line. Exactly the shape of the Add Game
 * bar (GameDetail): a DIRECT PanelSectionRow child and sOperationText only.
 * sTimeRemaining is not used: it adds a second column to the info line that
 * the QAM has no room for.
 */
export function InstallProgressRow({ label, percent, elapsed }: {
  label: string;
  percent: number | null;
  elapsed: string;
}) {
  const text = elapsed ? `${label}  ·  ${elapsed}` : label;
  return (
    <PanelSectionRow>
      <ProgressBarWithInfo
        // An Item: without layout="below" it keeps the left half for an empty
        // label and squeezes the bar into the right half, off the QAM's edge,
        // with the text clipped top-right (screenshot, codespace 2026-11-23).
        layout="below"
        indeterminate={percent === null}
        nProgress={percent ?? 0}
        sOperationText={text}
      />
    </PanelSectionRow>
  );
}
