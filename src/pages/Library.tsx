import { useEffect, useState, useCallback } from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  Navigation,
  Focusable,
} from "@decky/ui";
import { GameCard, GameInfo } from "../components/GameCard";
import {
  getInstalledLuaScripts,
  checkAllAchievementsStatus,
} from "../api";
import { useT } from "../i18n";
import { ACHIEVEMENTS_ENABLED } from "../features";
import { ROUTE_GAME_DETAIL } from "../routes";

// Full-screen "My Games" library. Lives on its own route so the QAM panel
// stays a compact launcher — idiomatic Decky plugins push space-hungry lists
// out of the narrow Quick Access menu and into a dedicated page. A single
// list needs no sidebar, so this is a plain scrollable page (not
// SidebarNavigation). Games are always name-sorted; type to filter.
export function Library() {
  const t = useT();
  const [games, setGames] = useState<GameInfo[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  const loadGames = useCallback(async () => {
    try {
      const luaResult = await getInstalledLuaScripts();
      const gameList: GameInfo[] = [];

      if (luaResult.success && luaResult.scripts) {
        for (const s of luaResult.scripts) {
          gameList.push({
            appid: s.appid,
            name: s.gameName || `Unknown (${s.appid})`,
            hasLua: true,
            isDisabled: s.isDisabled,
            hasGameFiles: s.hasGameFiles,
          });
        }
      }

      const appids = gameList.map((g) => g.appid);
      if (ACHIEVEMENTS_ENABLED && appids.length > 0) {
        try {
          const achResult = await checkAllAchievementsStatus(appids);
          if (achResult.success && achResult.map) {
            for (const g of gameList) {
              g.hasAchievements = !!achResult.map[g.appid];
            }
          }
        } catch { }
      }

      gameList.sort((a, b) => a.name.localeCompare(b.name));
      setGames(gameList);
    } catch (err) {
      console.error("Library: load error", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGames();
  }, [loadGames]);

  const filtered = (
    search
      ? games.filter(
        (g: GameInfo) =>
          g.name.toLowerCase().includes(search.toLowerCase()) ||
          String(g.appid).includes(search),
      )
      : games
  )
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));

  const navigateToDetail = (appid: number) => {
    Navigation.Navigate(ROUTE_GAME_DETAIL + "/" + appid);
  };

  return (
    <div style={{ marginTop: "72px", height: "calc(100% - 72px)", overflowY: "scroll" }}>
      <PanelSection title={t("myGames")}>
        <PanelSectionRow>
          <TextField
            label={t("filterGames")}
            value={search}
            onChange={(e: any) => setSearch(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
      </PanelSection>

      {loading ? (
        <div style={{ textAlign: "center", padding: "20px", color: "#8b929a" }}>
          {t("loadingGames")}
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: "center", padding: "20px", color: "#8b929a" }}>
          {search ? t("noGamesMatch") : t("noGamesYet")}
        </div>
      ) : (
        // Steam-style portrait grid: responsive columns (~5-6 across on the Deck,
        // adapts to width). One Focusable wrapper; Steam's spatial gamepad nav
        // moves across the tiles by their on-screen position.
        <Focusable
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))",
            gap: "16px",
            padding: "4px 16px 24px",
          }}
        >
          {filtered.map((game: GameInfo) => (
            <GameCard key={game.appid} game={game} onClick={navigateToDetail} />
          ))}
        </Focusable>
      )}
    </div>
  );
}
