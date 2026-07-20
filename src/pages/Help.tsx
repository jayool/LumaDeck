import { PanelSection, PanelSectionRow, Focusable } from "@decky/ui";
import { useT } from "../i18n";

// Plugin help. Surfaced as a page in the Settings sidebar (not its own route),
// so there's no back button here — the sidebar owns navigation.
//
// SidebarNavigation's content pane scrolls by FOCUS: it only scrolls to reach a
// focusable element. This page is otherwise pure read-only text, so without a
// focus anchor in each block the gamepad has nowhere to move and the page can't
// be scrolled at all (you couldn't read past the first screen). We make every
// block reachable: the plain-text divs are wrapped in <Focusable noFocusRing>
// and the feature Fields get `focusable` — both with the visual highlight off so
// the read-only text doesn't look selectable.
export function HelpContent() {
  const t = useT();
  return (
    <>
      <PanelSection title={t("helpWhatIs")}>
        <PanelSectionRow>
          <Focusable noFocusRing>
            <div
              style={{ fontSize: "13px", color: "#dcdedf", lineHeight: "1.5" }}
            >
              {t("helpWhatIsDesc")}
            </div>
          </Focusable>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("helpHowToAdd")}>
        <PanelSectionRow>
          <Focusable noFocusRing>
            <div
              style={{
                fontSize: "13px",
                color: "#dcdedf",
                lineHeight: "1.6",
                whiteSpace: "pre-line",
              }}
            >
              {t("helpHowToAddSteps")}
            </div>
          </Focusable>
        </PanelSectionRow>
      </PanelSection>

      {/* Feature list. Same plain-text treatment as the prose sections above
          (bold name + description) rather than native Fields, so the whole
          page reads as one consistent text block instead of mixing boxed
          Field rows with unboxed paragraphs. Each stays its own Focusable so
          the gamepad can still scroll to it. */}
      <PanelSection title={t("helpFeatures")}>
        {[
          { name: "FakeAppId", desc: t("helpFakeAppId") },
          { name: "Goldberg", desc: t("helpGoldberg") },
          { name: t("fixes"), desc: t("helpFixes") },
          { name: "Linux Native", desc: t("helpLinuxNative") },
        ].map((f) => (
          <PanelSectionRow key={f.name}>
            <Focusable noFocusRing>
              <div style={{ fontSize: "13px", color: "#dcdedf", lineHeight: "1.5" }}>
                <div style={{ fontWeight: 600, marginBottom: "2px" }}>{f.name}</div>
                {f.desc}
              </div>
            </Focusable>
          </PanelSectionRow>
        ))}
      </PanelSection>

      <PanelSection title={t("helpTroubleshooting")}>
        <PanelSectionRow>
          <Focusable noFocusRing>
            <div
              style={{
                fontSize: "12px",
                color: "#dcdedf",
                lineHeight: "1.6",
                whiteSpace: "pre-line",
              }}
            >
              {t("helpTroubleshootingTips")}
            </div>
          </Focusable>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
