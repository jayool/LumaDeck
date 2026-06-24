import { PanelSectionRow } from "@decky/ui";
import { ReactNode } from "react";

// A single reusable notice box, sharing the exact frame as HealthBanner /
// UpdatesBanner (6px radius, 10px 12px padding, rgba(color, .1) fill +
// rgba(color, .4) border + a 3px accent left border). Replaces the three
// hand-rolled alert boxes that had drifted apart in tone and geometry.
//
// variant picks the accent: info (accent blue), warn (gold), danger (red).
// Optional `title` renders the uppercase eyebrow used by the game-notices box.
export type NoticeVariant = "info" | "warn" | "danger";

const VARIANTS: Record<NoticeVariant, { rgb: string; accent: string }> = {
  info: { rgb: "26, 159, 255", accent: "#1a9fff" },
  warn: { rgb: "200, 168, 75", accent: "#c8a84b" },
  danger: { rgb: "255, 68, 68", accent: "#ff4444" },
};

export function Notice({
  variant,
  title,
  children,
  gap = 6,
}: {
  variant: NoticeVariant;
  title?: string;
  children: ReactNode;
  gap?: number;
}) {
  const { rgb, accent } = VARIANTS[variant];
  return (
    <PanelSectionRow>
      <div
        style={{
          width: "100%",
          boxSizing: "border-box",
          // 8px standard clearance below every notice so a following control's
          // focus glow (e.g. Download Manifest) never touches the box.
          marginBottom: "8px",
          background: `rgba(${rgb}, 0.1)`,
          border: `1px solid rgba(${rgb}, 0.4)`,
          borderLeft: `3px solid ${accent}`,
          borderRadius: "6px",
          padding: "10px 12px",
          display: "flex",
          flexDirection: "column",
          gap: `${gap}px`,
        }}
      >
        {title && (
          <div
            style={{
              fontSize: "10px",
              fontWeight: 700,
              color: accent,
              textTransform: "uppercase",
              letterSpacing: "0.8px",
            }}
          >
            {title}
          </div>
        )}
        {children}
      </div>
    </PanelSectionRow>
  );
}
