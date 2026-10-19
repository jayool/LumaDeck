import { useEffect, useMemo, useState } from "react";
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

// Where the cover comes from, in order:
//  1. Steam's own library art. The client already holds the portrait of every
//     app the library has shown (appcache/librarycache), serves it without the
//     network, and returns the user's custom art (SteamGridDB etc.) when set —
//     the same call the native grid makes.
//  2. The store CDN: portrait capsule, then header.jpg for apps without one.
//  3. A plain text tile — and a retry after a while, since a CDN miss is
//     usually the network (resume from sleep, a slow wifi, 30 tiles at once),
//     not a missing cover. The old sticky text tile is what users reported as
//     "posters often don't show".
const ART_BASE = "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps";
const RETRY_MS = 15000;

function steamLibraryArt(appid: number): string | null {
  try {
    const store = (window as any).appStore;
    const overview = store?.GetAppOverviewByAppID?.(appid);
    if (!overview) return null;
    const url = store.GetVerticalCapsuleURLForApp?.(overview);
    return typeof url === "string" && url.length > 0 ? url : null;
  } catch {
    return null;
  }
}

// Grid tile for the My Games library — a Steam-style portrait cover.
export function GameCard({ game, onClick }: GameCardProps) {
  const [idx, setIdx] = useState(0);
  const [attempt, setAttempt] = useState(0);
  // Re-asked on every retry: Steam may not have had the app's overview yet
  // when the tile first mounted (a game added moments ago).
  const candidates = useMemo(() => {
    const list: string[] = [];
    const local = steamLibraryArt(game.appid);
    if (local) list.push(local);
    list.push(`${ART_BASE}/${game.appid}/library_600x900.jpg`);
    list.push(`${ART_BASE}/${game.appid}/header.jpg`);
    return list;
  }, [game.appid, attempt]);
  const noArt = idx >= candidates.length;
  // A CDN URL gets a changing query on each retry so the browser doesn't hand
  // back its cached failure; Steam's own URL is left exactly as given.
  const src = noArt ? "" : (
    attempt > 0 && candidates[idx].startsWith(ART_BASE)
      ? `${candidates[idx]}?r=${attempt}` : candidates[idx]);

  useEffect(() => {
    if (!noArt) return;
    const timer = setTimeout(() => { setAttempt((a) => a + 1); setIdx(0); }, RETRY_MS);
    return () => clearTimeout(timer);
  }, [noArt]);

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
            onError={() => setIdx((i) => i + 1)}
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
