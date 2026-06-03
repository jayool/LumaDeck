"""Central configuration constants for the LumaDeck backend."""

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "SteamDB",
    "User-Agent": "https://github.com/BossSloth/Steam-SteamDB-extension",
    "Origin": "https://github.com/BossSloth/Steam-SteamDB-extension",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

API_MANIFEST_URL = "https://raw.githubusercontent.com/Star123451/LuaToolsLinux/main/backend/api.json"
API_MANIFEST_PROXY_URL = ""
API_JSON_FILE = "api.json"

HTTP_TIMEOUT_SECONDS = 15
HTTP_PROXY_TIMEOUT_SECONDS = 15

USER_AGENT = "lumadeck-v0-decky"

LOADED_APPS_FILE = "loadedappids.txt"
APPID_LOG_FILE = "appidlogs.txt"

# Steam's official endpoint for the full app list. Returns
#   {"applist": {"apps": [{"appid": N, "name": "..."}, ...]}}
# Primary because it never goes down. We fall back to the legacy Morrenus
# applist (now under the Hubcap rebrand) if the official endpoint fails for
# some reason — and that fallback returns the bare list, no wrapper.
APPLIST_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
APPLIST_URL_FALLBACK = "https://applist.morrenus.xyz/"
APPLIST_FILE_NAME = "all-appids.json"
APPLIST_DOWNLOAD_TIMEOUT = 300

GAMES_DB_FILE_NAME = "games.json"
GAMES_DB_URL = "https://toolsdb.piqseu.cc/games.json"
