# Achievements

**You don't need to do anything for achievements.** SLSsteam handles them natively for
the games LumaDeck adds — they unlock and persist on their own, the same as for an
owned title. There is no separate "generate achievements" step in LumaDeck today.

## What happened to the generator?

LumaDeck used to ship an achievement-schema generator (originally via SLScheevo, later
rebuilt on the **Steam Web API** — `ISteamUserStats/GetSchemaForGame` → a binary
`UserGameStatsSchema_<appid>.bin` seeded into Steam's `appcache/stats`). That code is
still in the tree (`backend/achievements.py`), but its **UI entry points are hidden**,
because SLSsteam's native path made it redundant:

```ts
// src/features.ts
export const ACHIEVEMENTS_ENABLED: boolean = false;
```

Flipping `ACHIEVEMENTS_ENABLED` to `true` brings the whole UI back — the per-game
**Generate Achievements** panel, the **Steam Web API key** + **Sync All** tab in
Settings, the QAM entry, and the game-card marker. Do that only if the native SLSsteam
path turns out not to be enough for some game. The generator then needs a free,
read-only **Steam Web API key** (from <https://steamcommunity.com/dev/apikey>) set on
the Achievements tab, and achievements appear after a Steam restart (Steam reads the
files at startup).

> If you re-enable it and a game still shows no achievements, the schema simply may not
> exist — Valve's Web API exposes nothing for games that have no achievements.
