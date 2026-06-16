import { PanelSection } from "@decky/ui";

// One row inside the banner — a short informational line about an available
// update (no button, no body). Severity is "info" (blue): non-critical, not an
// emergency. The action lives in Settings, intentionally.
export type UpdateNotice = {
  key: string;   // stable react key (component id)
  text: string;
};

// A pale-blue banner with one line per available update. Lower visual weight
// than HealthBanner — updates are routine, not problems. Renders nothing when
// updates is empty.
export function UpdatesBanner({ updates }: { updates: UpdateNotice[] }) {
  if (updates.length === 0) return null;

  return (
    <PanelSection>
      <div style={{
        background: "rgba(91, 158, 255, 0.08)",
        border: "1px solid rgba(91, 158, 255, 0.30)",
        borderLeft: "3px solid #5b9eff",
        borderRadius: "6px",
        padding: "6px 10px",
      }}>
        {updates.map((u, i) => (
          <div
            key={u.key}
            style={{
              fontSize: "11px",
              color: "#9cc4ff",
              marginTop: i === 0 ? 0 : "4px",
            }}
          >
            {u.text}
          </div>
        ))}
      </div>
    </PanelSection>
  );
}
