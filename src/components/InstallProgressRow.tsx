import { PanelSectionRow, ProgressBarWithInfo } from "@decky/ui";

/**
 * Steam's own progress row for a setup.sh run: a real bar while something
 * downloads (curl's percent), indeterminate otherwise, the phase label and
 * the elapsed time underneath. A DIRECT PanelSectionRow child: nesting the
 * bar in a flex div shifted it off the right edge (Add Game, 2026-10).
 */
export function InstallProgressRow({ label, percent, elapsed }: {
  label: string;
  percent: number | null;
  elapsed: string;
}) {
  return (
    <PanelSectionRow>
      <ProgressBarWithInfo
        indeterminate={percent === null}
        nProgress={percent ?? 0}
        sOperationText={label}
        // Steam's component takes it (its download rows show it); older
        // @decky/ui typings do not list it, so it goes in untyped.
        {...({ sTimeRemaining: elapsed } as any)}
      />
    </PanelSectionRow>
  );
}
