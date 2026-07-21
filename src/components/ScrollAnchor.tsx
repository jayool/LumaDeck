import { PanelSectionRow, Field } from "@decky/ui";

// Invisible, focusable tail element for pages whose last real content is
// read-only text (API Credentials, Help).
//
// SteamOS Game Mode draws its system navbar over the bottom of the full-screen
// Settings pane, so the last line stays hidden behind it even once it's
// focusable — the focus reaches it but the bar covers it. This anchor sits
// BELOW that line: moving focus onto it scrolls the real content up, clear of
// the navbar. highlightOnFocus off + an empty spacer body = nothing visible,
// just a reachable scroll target with enough height to lift the text clear.
export function ScrollAnchor() {
  return (
    <PanelSectionRow>
      <Field
        focusable
        highlightOnFocus={false}
        bottomSeparator="none"
        label={<div style={{ height: "48px" }} />}
      />
    </PanelSectionRow>
  );
}
