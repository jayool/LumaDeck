import { ButtonItem, PanelSectionRow } from "@decky/ui";
import { CSSProperties } from "react";

interface ActionButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  description?: string;
  variant?: "danger" | "default";
}

export function ActionButton({
  label,
  onClick,
  disabled,
  description,
  variant = "default",
}: ActionButtonProps) {
  const labelStyle: CSSProperties = {};

  // Only 'danger' tints the label (red), matching Steam's destructive-action
  // cue. Everything else keeps the native white label — Steam signals the main
  // action with the focus fill, not coloured text (which reads as non-native).
  if (variant === "danger") {
    labelStyle.color = "#ff4444";
  }

  // Wrap in PanelSectionRow so ActionButtons get the same tight native row
  // rhythm as plain <PanelSectionRow><ButtonItem> rows (used in Settings). Used
  // bare (as a direct PanelSection child) they picked up an extra gap between
  // consecutive buttons.
  return (
    <PanelSectionRow>
      <ButtonItem
        layout="below"
        onClick={onClick}
        disabled={disabled}
        description={description}
      >
        <span style={labelStyle}>{label}</span>
      </ButtonItem>
    </PanelSectionRow>
  );
}
