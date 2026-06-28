import { PanelSection, PanelSectionRow, Field } from "@decky/ui";
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

      {/* Feature list → native Field per feature (name as label, the
          explanation as description). Names are technical literals. */}
      <PanelSection title={t("helpFeatures")}>
        <PanelSectionRow>
          <Field label="FakeAppId" description={t("helpFakeAppId")} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Token" description={t("helpToken")} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="DLCs" description={t("helpDlcs")} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Goldberg" description={t("helpGoldberg")} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label={t("fixes")} description={t("helpFixes")} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Linux Native" description={t("helpLinuxNative")} />
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
