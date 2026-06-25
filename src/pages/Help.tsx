import { PanelSection, PanelSectionRow } from "@decky/ui";
import { useT } from "../i18n";

// Plugin help. Surfaced as a page in the Settings sidebar (not its own route),
// so there's no back button here — the sidebar owns navigation.
export function HelpContent() {
  const t = useT();
  return (
    <>
      <PanelSection title={t("helpWhatIs")}>
        <PanelSectionRow>
          <div
            style={{ fontSize: "13px", color: "#dcdedf", lineHeight: "1.5" }}
          >
            {t("helpWhatIsDesc")}
          </div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("helpHowToAdd")}>
        <PanelSectionRow>
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
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("helpFeatures")}>
        <PanelSectionRow>
          <div
            style={{ fontSize: "12px", color: "#dcdedf", lineHeight: "1.6" }}
          >
            {t("helpFakeAppId")}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div
            style={{ fontSize: "12px", color: "#dcdedf", lineHeight: "1.6" }}
          >
            {t("helpToken")}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div
            style={{ fontSize: "12px", color: "#dcdedf", lineHeight: "1.6" }}
          >
            {t("helpDlcs")}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div
            style={{ fontSize: "12px", color: "#dcdedf", lineHeight: "1.6" }}
          >
            {t("helpGoldberg")}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div
            style={{ fontSize: "12px", color: "#dcdedf", lineHeight: "1.6" }}
          >
            {t("helpFixes")}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div
            style={{ fontSize: "12px", color: "#dcdedf", lineHeight: "1.6" }}
          >
            {t("helpLinuxNative")}
          </div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("helpTroubleshooting")}>
        <PanelSectionRow>
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
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
