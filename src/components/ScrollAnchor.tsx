import { Focusable } from "@decky/ui";

// Invisible, focusable tail spacer for pages whose last real content is
// read-only text (API Credentials, Help). Game Mode's system navbar overdraws
// the bottom of the full-screen Settings pane, hiding the last (focusable) line
// behind it; moving focus onto this spacer scrolls the real content up, clear
// of the bar.
//
// It's a BARE <Focusable>, NOT a Field: a Field draws its own row chrome (a
// background box), which is very much visible — that was the bug. A Focusable is
// just a transparent focus node: no background, no border, nothing drawn. The
// no-op onActivate keeps it a real, reachable focus target.
export function ScrollAnchor() {
  return (
    <Focusable
      onActivate={() => {}}
      noFocusRing
      style={{ height: "48px", width: "100%" }}
    >
      <div />
    </Focusable>
  );
}
