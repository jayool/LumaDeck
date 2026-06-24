import { useEffect, useState, useCallback } from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  SidebarNavigation,
  Navigation,
} from "@decky/ui";
import { FaGamepad } from "react-icons/fa";
import { GameCard, GameInfo } from "../components/GameCard";
import {
  getInstalledLuaScripts,
  checkAllAchievementsStatus,
  getActiveDownloads,
} from "../api";
import { useT } from "../i18n";
import { ROUTE_GAME_DETAIL } from "../routes";

type SortMode = "name" | "appid" | "recent";

// Full-screen "My Games" library. Lives on its own route so the QAM panel
// stays a compact launcher — idiomatic Decky plugins push space-hungry lists
// out of the narrow Quick Access menu and into a dedicated page.
export function Library() {
  const t = useT();
  const [games, setGames] = useState<GameInfo[]>([]);
  const [search, setSearch] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("name");
  const [loading, setLoading] = useState(true);
  // appid -> active download phase, so cards can show live status here too.
  const [activePhases, setActivePhases] = useState<Record<number, string>>({});

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
      if (appids.length > 0) {
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

  // Poll active downloads so cards badge their live phase.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const result = await getActiveDownloads();
        if (cancelled) return;
        const map: Record<number, string> = {};
        if (result.success && result.downloads) {
          for (const key of Object.keys(result.downloads)) {
            const st = result.downloads[key];
            if (st && st.status) map[parseInt(key, 10)] = st.status;
          }
        }
        setActivePhases(map);
      } catch { }
    };
    tick();
    const interval = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const sortLabels: Record<SortMode, string> = {
    name: "A-Z",
    appid: "AppID",
    recent: "Recent",
  };

  const cycleSortMode = () => {
    setSortMode((prev) =>
      prev === "name" ? "appid" : prev === "appid" ? "recent" : "name",
    );
  };

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
    .sort((a, b) => {
      if (sortMode === "appid") return a.appid - b.appid;
      if (sortMode === "recent") return b.appid - a.appid;
      return a.name.localeCompare(b.name);
    });

  const navigateToDetail = (appid: number) => {
    Navigation.Navigate(ROUTE_GAME_DETAIL + "/" + appid);
  };

  const pages = [
    {
      title: t("myGames"),
      icon: <FaGamepad />,
      hideTitle: true,
      content: (
        <PanelSection title={t("myGames")}>
          <PanelSectionRow>
            <TextField
              label={t("filterGames")}
              value={search}
              onChange={(e: any) => setSearch(e?.target?.value ?? "")}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={cycleSortMode}>
              {t("sort")}: {sortLabels[sortMode]}
            </ButtonItem>
          </PanelSectionRow>

          {loading ? (
            <PanelSectionRow>
              <div
                style={{ textAlign: "center", padding: "20px", color: "#8b929a" }}
              >
                {t("loadingGames")}
              </div>
            </PanelSectionRow>
          ) : filtered.length === 0 ? (
            <PanelSectionRow>
              <div
                style={{ textAlign: "center", padding: "20px", color: "#8b929a" }}
              >
                {search ? t("noGamesMatch") : t("noGamesYet")}
              </div>
            </PanelSectionRow>
          ) : (
            filtered.map((game: GameInfo) => (
              <GameCard
                key={game.appid}
                game={
                  activePhases[game.appid]
                    ? { ...game, downloadStatus: activePhases[game.appid] }
                    : game
                }
                onClick={navigateToDetail}
              />
            ))
          )}
        </PanelSection>
      ),
    },
  ];

  return <SidebarNavigation title="LumaDeck" pages={pages} />;
}
