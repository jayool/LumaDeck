import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { FaExclamationTriangle } from "react-icons/fa";

// One unhealthy component, normalized to the native model (DESIGN_UI.md §3c):
//   - label:       impact + component, e.g. "SLSsteam — games won't launch"
//   - description: the plain-language cause / instruction
//   - actionLabel + onAction PRESENT  → a ButtonItem (fixable from here)
//   - actionLabel ABSENT              → a display-only Field (not fixable here;
//                                       the instruction lives in description)
export type HealthProblem = {
  key: string;
  label: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  actionDisabled?: boolean;
};

// Warning accent — severity is carried by the ⚠ icon colour, not a coloured box.
const WARN = "#ff8c00";

// Native health rows: no coloured box, no hand-rolled button. Each component is
// one native row. Renders nothing when there are no problems, so callers can
// wire it unconditionally and let the data decide.
export function HealthBanner({ problems }: { problems: HealthProblem[] }) {
  if (problems.length === 0) return null;

  return (
    <PanelSection>
      {problems.map((p) =>
        p.actionLabel && p.onAction ? (
          <PanelSectionRow key={p.key}>
            <ButtonItem
              layout="below"
              icon={<FaExclamationTriangle color={WARN} />}
              label={p.label}
              description={p.description}
              onClick={p.onAction}
              disabled={p.actionDisabled}
            >
              {p.actionLabel}
            </ButtonItem>
          </PanelSectionRow>
        ) : (
          <PanelSectionRow key={p.key}>
            <Field
              icon={<FaExclamationTriangle color={WARN} />}
              label={p.label}
              description={p.description}
            />
          </PanelSectionRow>
        ),
      )}
    </PanelSection>
  );
}
