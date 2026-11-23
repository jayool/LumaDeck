import { PanelSectionRow, ProgressBarWithInfo } from "@decky/ui";

/**
 * Steam's own progress row for a setup.sh run: a real bar while something
 * downloads (curl's percent), indeterminate otherwise, the phase label and
 * the elapsed time in the one info line. Exactly the shape of the Add Game
 * bar (GameDetail): a DIRECT PanelSectionRow child and sOperationText only.
 * sTimeRemaining looked right in the typings but laid the info out in two
 * columns that overflowed the QAM: the bar slid off the right edge and the
 * text vanished (codespace, 2026-11-23).
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
        indeterminate={percent === null}
        nProgress={percent ?? 0}
        sOperationText={text}
      />
    </PanelSectionRow>
  );
}
