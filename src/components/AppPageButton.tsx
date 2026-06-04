import { useState, useEffect, FC } from "react";
import { getInstalledLuaScripts } from "../api";
import { useT } from "../i18n";

function useAppIdFromPath(): number {
  const match = window.location.pathname.match(/\/library\/app\/(\d+)/);
  return match ? parseInt(match[1], 10) : 0;
}

export const AppPageButton: FC = () => {
  const appid = useAppIdFromPath();
  const [installed, setInstalled] = useState(false);
  const t = useT();

  useEffect(() => {
    let cancelled = false;
    if (!appid) return;
    (async () => {
      try {
        const result = await getInstalledLuaScripts();
        if (!cancelled && result.success && result.scripts) {
          const found = result.scripts.find((s: any) => s.appid === appid);
          if (found) setInstalled(true);
        }
      } catch (_) {}
    })();
    return () => {
      cancelled = true;
    };
  }, [appid]);

  if (!appid || appid <= 0 || !installed) return null;

  return (
    <div
      style={{
        padding: "8px 16px",
        margin: "4px 0",
      }}
    >
      <div
        style={{
          color: "#8bca68",
          fontSize: "13px",
          textAlign: "center",
        }}
      >
        {t("addedViaLumaDeck")}
      </div>
    </div>
  );
};
