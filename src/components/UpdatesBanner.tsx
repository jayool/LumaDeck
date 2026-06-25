import { PanelSection, PanelSectionRow, Field } from "@decky/ui";
import { FaArrowCircleUp } from "react-icons/fa";

// One row inside the banner — a short informational line about an available
// update (no button, no body). Severity is "info" (blue): non-critical, not an
// emergency. The action lives in Settings, intentionally.
export type UpdateNotice = {
  key: string;   // stable react key (component id)
  text: string;
};

// Info accent — same idea as HealthBanner's ⚠ colour, but blue: updates are
// routine, not problems. Severity rides on the icon, not a coloured box.
const INFO = "#5b9eff";

// Native update rows — one display-only Field per available update, mirroring
// HealthBanner (no hand-built coloured card). Renders nothing when empty.
export function UpdatesBanner({ updates }: { updates: UpdateNotice[] }) {
  if (updates.length === 0) return null;

  return (
    <PanelSection>
      {updates.map((u) => (
        <PanelSectionRow key={u.key}>
          <Field icon={<FaArrowCircleUp color={INFO} />} label={u.text} />
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}
