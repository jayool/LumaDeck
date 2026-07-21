import { PanelSection, PanelSectionRow, Field } from "@decky/ui";
import { useT } from "../i18n";
import { ScrollAnchor } from "../components/ScrollAnchor";

// Plugin help. Surfaced as a page in the Settings sidebar (not its own route),
// so there's no back button here — the sidebar owns navigation.
//
// SidebarNavigation's content pane scrolls by FOCUS: it only scrolls to reach a
// focusable element. This page is pure read-only text, so each block must carry
// a focus anchor or the gamepad has nowhere to move and the page can't be
// scrolled (you couldn't read past the first screen). A plain <div> inside
// <Focusable noFocusRing> did NOT reliably take gamepad focus, so the page was
// stuck; every block is now a `Field focusable` (highlightOnFocus off, so the
// read-only text doesn't look selectable) — the reliable scroll anchor.
export function HelpContent() {
  const t = useT();
  const textStyle = { fontSize: "13px", color: "#dcdedf", lineHeight: "1.5" } as const;
  return (
    <>
      <PanelSection title={t("helpWhatIs")}>
        <PanelSectionRow>
          <Field
            focusable
            highlightOnFocus={false}
            bottomSeparator="none"
            label={<div style={textStyle}>{t("helpWhatIsDesc")}</div>}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("helpHowToAdd")}>
        <PanelSectionRow>
          <Field
            focusable
            highlightOnFocus={false}
            bottomSeparator="none"
            label={
              <div style={{ ...textStyle, lineHeight: "1.6", whiteSpace: "pre-line" }}>
                {t("helpHowToAddSteps")}
              </div>
            }
          />
        </PanelSectionRow>
      </PanelSection>

      {/* Feature list. Same plain-text treatment as the prose sections above
          (bold name + description) rather than boxed native Field rows, so the
          whole page reads as one consistent text block. Each is its own
          focusable Field so the gamepad can still scroll to it. */}
      <PanelSection title={t("helpFeatures")}>
        {[
          { name: "FakeAppId", desc: t("helpFakeAppId") },
          { name: "Goldberg", desc: t("helpGoldberg") },
          { name: t("fixes"), desc: t("helpFixes") },
          { name: "Linux Native", desc: t("helpLinuxNative") },
        ].map((f) => (
          <PanelSectionRow key={f.name}>
            <Field
              focusable
              highlightOnFocus={false}
              bottomSeparator="none"
              label={
                <div style={textStyle}>
                  <div style={{ fontWeight: 600, marginBottom: "2px" }}>{f.name}</div>
                  {f.desc}
                </div>
              }
            />
          </PanelSectionRow>
        ))}
      </PanelSection>

      <PanelSection title={t("helpTroubleshooting")}>
        <PanelSectionRow>
          <Field
            focusable
            highlightOnFocus={false}
            bottomSeparator="none"
            label={
              <div style={{ ...textStyle, fontSize: "12px", lineHeight: "1.6", whiteSpace: "pre-line" }}>
                {t("helpTroubleshootingTips")}
              </div>
            }
          />
        </PanelSectionRow>
        {/* Tail anchor: without it, Game Mode's navbar covers this last block. */}
        <ScrollAnchor />
      </PanelSection>
    </>
  );
}
