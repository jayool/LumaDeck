import { PanelSection } from "@decky/ui";

// One problem row inside the banner — title, body, and an optional action
// (label + click handler). The parent decides which components are unhealthy
// and what their action should do.
export type HealthProblem = {
  key: string;        // stable react key (component id)
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
  actionDisabled?: boolean;
};

// A single orange banner that renders one row per problem. Same frame whether
// there is one problem or several — keeps the QAM uncluttered while still
// surfacing every unhealthy component with its specific cause and fix.
//
// Renders nothing when problems is empty (so callers can wire it
// unconditionally and let the data decide).
export function HealthBanner({
  problems,
  multiTitle,
}: {
  problems: HealthProblem[];
  multiTitle: string;
}) {
  if (problems.length === 0) return null;

  return (
    <PanelSection>
      <div style={{
        background: "rgba(255, 140, 0, 0.1)",
        border: "1px solid rgba(255, 140, 0, 0.4)",
        borderLeft: "3px solid #ff8c00",
        borderRadius: "6px",
        padding: "10px 12px",
      }}>
        {problems.length > 1 && (
          <div style={{
            fontWeight: 600,
            color: "#ffaa33",
            fontSize: "13px",
            marginBottom: "8px",
          }}>
            {multiTitle}
          </div>
        )}
        {problems.map((p, i) => (
          <div
            key={p.key}
            style={{
              marginTop: i === 0 ? 0 : "12px",
              paddingTop: i === 0 ? 0 : "10px",
              borderTop: i === 0 ? "none" : "1px solid rgba(255, 140, 0, 0.25)",
            }}
          >
            <div style={{
              fontWeight: 600,
              color: "#ffaa33",
              fontSize: "13px",
              marginBottom: "4px",
            }}>
              {p.title}
            </div>
            <div style={{
              fontSize: "12px",
              color: "#aaa",
              marginBottom: p.actionLabel ? "10px" : "0",
            }}>
              {p.body}
            </div>
            {p.actionLabel && p.onAction && (
              <button
                onClick={p.onAction}
                disabled={p.actionDisabled}
                style={{
                  background: p.actionDisabled ? "#555" : "#ff8c00",
                  color: "#fff",
                  border: "none",
                  borderRadius: "4px",
                  padding: "6px 14px",
                  fontSize: "12px",
                  fontWeight: 600,
                  cursor: p.actionDisabled ? "default" : "pointer",
                  width: "100%",
                }}
              >
                {p.actionLabel}
              </button>
            )}
          </div>
        ))}
      </div>
    </PanelSection>
  );
}
