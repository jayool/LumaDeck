import { useState } from "react";
import { Focusable } from "@decky/ui";
import { FaCloudDownloadAlt } from "react-icons/fa";

export interface GameInfo {
  appid: number;
  name: string;
  hasLua?: boolean;
  isDisabled?: boolean;
  hasGameFiles?: boolean;
  hasAchievements?: boolean;
}

interface GameCardProps {
  game: GameInfo;
  onClick: (appid: number) => void;
}

// Steam publishes per-app art on its CDN and the Steam client loads it fine.
// Portrait capsule (the native library-grid art) first; header.jpg as a
// fallback for apps without a portrait; then a plain text tile if the app has
// no art at all.
const ART_BASE = "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps";

// Grid tile for the My Games library — a Steam-style portrait cover.
export function GameCard({ game, onClick }: GameCardProps) {
  const portrait = `${ART_BASE}/${game.appid}/library_600x900.jpg`;
  const header = `${ART_BASE}/${game.appid}/header.jpg`;
  const [src, setSrc] = useState(portrait);
  const [noArt, setNoArt] = useState(false);

  // Two real states (see Library review): a game with its files present is
  // Installed → full colour. One that's only staged (manifest written but Steam
  // hasn't downloaded it yet) or externally disabled shows dimmed with a
  // download-cloud hint — the native "not installed yet" look. The transient
  // manifest-fetch "downloading" phase is intentionally not surfaced here (the
  // real game download is Steam's, shown in Steam's own library).
  const installed = !!game.hasLua && !!game.hasGameFiles && !game.isDisabled;
  const dim = !installed;

  const activate = () => onClick(game.appid);

  return (
    <Focusable
      onActivate={activate}
      onClick={activate}
      style={{ borderRadius: "6px", overflow: "hidden" }}
    >
      {/* 600:900 portrait ratio via padding-top so it holds on any CEF build. */}
      <div
        style={{
          position: "relative",
          width: "100%",
          paddingTop: "150%",
          background: "#1a2129",
          borderRadius: "6px",
          overflow: "hidden",
        }}
      >
        {noArt ? (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "8px",
              textAlign: "center",
              fontSize: "12px",
              color: "#dcdedf",
              opacity: dim ? 0.55 : 1,
            }}
          >
            {game.name}
          </div>
        ) : (
          <img
            src={src}
            onError={() => {
              if (src === portrait) setSrc(header);
              else setNoArt(true);
            }}
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              opacity: dim ? 0.4 : 1,
              filter: dim ? "grayscale(0.35)" : "none",
            }}
          />
        )}
        {dim && (
          <div
            style={{
              position: "absolute",
              top: "6px",
              right: "6px",
              width: "22px",
              height: "22px",
              borderRadius: "50%",
              background: "rgba(0,0,0,0.6)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <FaCloudDownloadAlt size={12} color="#dcdedf" />
          </div>
        )}
      </div>
      <div
        style={{
          marginTop: "6px",
          fontSize: "14px",
          fontWeight: 500,
          color: "#dcdedf",
          lineHeight: 1.25,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          opacity: dim ? 0.75 : 1,
        }}
      >
        {game.name}
      </div>
    </Focusable>
  );
}
