import { ButtonItem } from "@decky/ui";
import { useT } from "../i18n";
import { ACHIEVEMENTS_ENABLED } from "../features";

export interface GameInfo {
  appid: number;
  name: string;
  hasLua?: boolean;
  isDisabled?: boolean;
  hasGameFiles?: boolean;
  hasAchievements?: boolean;
  downloadStatus?: string;
}

interface GameCardProps {
  game: GameInfo;
  onClick: (appid: number) => void;
}

export function GameCard({ game, onClick }: GameCardProps) {
  const t = useT();

  const statusColor = game.hasLua
    ? game.isDisabled
      ? "#ffaa00"
      : game.hasGameFiles
        ? "#00cc00"
        : "#ffaa00"
    : "#666";

  const statusText = game.hasLua
    ? game.isDisabled
      ? t("disabled")
      : game.hasGameFiles
        ? ACHIEVEMENTS_ENABLED && game.hasAchievements
          ? `${t("installed")} · ★`
          : t("installed")
        : t("manifestOnly")
    : t("pending");

  const activePhases = [
    "downloading",
    "checking",
    "processing",
    "configuring",
    "queued",
    "installing",
    "restarting_steam",
  ];
  const isDownloading = !!game.downloadStatus && activePhases.includes(game.downloadStatus);

  const downloadLabel = (() => {
    switch (game.downloadStatus) {
      case "downloading": return t("statusDownloading");
      case "checking": return t("statusChecking");
      case "processing": return t("statusProcessing");
      case "configuring": return t("statusConfiguring");
      case "queued": return t("statusQueued");
      case "installing": return t("statusInstalling");
      case "restarting_steam": return t("statusRestartingSteam");
      default: return game.downloadStatus || "";
    }
  })();

  return (
    <ButtonItem
      layout="below"
      onClick={() => onClick(game.appid)}
      description={
        <span style={{ color: isDownloading ? "#1a9fff" : statusColor, fontSize: "12px" }}>
          {isDownloading ? downloadLabel : statusText} · {game.appid}
        </span>
      }
    >
      {game.name}
    </ButtonItem>
  );
}
