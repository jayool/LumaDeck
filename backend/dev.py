"""Dev-only state overrides for previewing the real plugin UI in states that
are hard to reproduce naturally (a broken component, an expired credential,
etc.).

Nothing here runs unless an override file exists at data/dev_overrides.json.
On a normal install the file is absent, every getter returns None, and the
real code paths run untouched. The Dev tab in Settings writes this file; the
health readers and get_credential_status consult it at the top and, if an
override is set, return a synthesized value so the real banners / System
Status / Dependencies / credential rows render that state.

This is a preview harness, not a feature. It only forges what the UI reads;
it never touches SLSsteam, steam.sh or any real file.
"""
import json
import os

_DIR = os.path.dirname(__file__)
_FILE = os.path.join(_DIR, "data", "dev_overrides.json")

# action per (component, state), mirroring the real read_*_health() functions
# so the components model dispatches the same button it would in reality.
_ACTION = {
    "slssteam": {"not_installed": "install", "not_loaded": "restart",
                 "not_injected": "restart", "not_supported": "downgrade",
                 "healthy": None},
    "lumalinux": {"not_installed": "install", "not_loaded": "restart",
                  "not_injected": "restart", "not_supported": "downgrade",
                  "healthy": None},
    "cloudredirect": {"not_installed": "install", "disabled": None,
                      "not_loaded": "restart", "not_injected": "restart",
                      "not_supported": "downgrade", "not_authed": "configure_desktop",
                      "healthy": None},
}


def _load() -> dict:
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get(key: str):
    """Return the override for key, or None. Treats disabled sentinels as None."""
    val = _load().get(key)
    if val in (None, "", "off", "real", "default"):
        return None
    return val


def all_() -> dict:
    return _load()


def set_(key: str, value) -> dict:
    d = _load()
    if value in (None, "", "off", "real", "default"):
        d.pop(key, None)
    else:
        d[key] = value
    os.makedirs(os.path.dirname(_FILE), exist_ok=True)
    tmp = _FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, _FILE)
    return d


def clear() -> None:
    try:
        os.remove(_FILE)
    except Exception:
        pass


def health(component: str, state: str, version: str = "9.9.9") -> dict:
    """Synthesize the dict shape returned by read_<component>_health()."""
    return {
        "state": state,
        "cause": None,
        "version": (None if state == "not_installed" else version),
        "action": _ACTION.get(component, {}).get(state),
    }


def _cred_one(state: str) -> dict:
    d = {"state": state, "days_left": None, "expires_at": "2026-07-20T00:00:00Z"}
    if state == "ok":
        d["days_left"] = 3
    elif state == "soon":
        d["days_left"] = 1
    elif state == "expired":
        d["expires_at"] = "2026-07-12T00:00:00Z"
    elif state in ("none", "unknown"):
        d["expires_at"] = None
    return d


def cred(hubcap_state, ryuu_state) -> dict:
    hubcap = _cred_one(hubcap_state or "ok")
    hubcap["daily_usage"] = 12
    hubcap["daily_limit"] = 120
    ryuu = _cred_one(ryuu_state or "ok")
    return {"success": True, "hubcap": hubcap, "ryuu": ryuu}


# Real, well-known AppIDs so the dev fake-games list shows real cover art in the
# library grid. Cycled/sliced to the requested count.
_FAKE_APP_POOL = [
    (2379780, "Balatro"),
    (1091500, "Cyberpunk 2077"),
    (1245620, "ELDEN RING"),
    (413150, "Stardew Valley"),
    (620, "Portal 2"),
    (1174180, "Red Dead Redemption 2"),
    (271590, "Grand Theft Auto V"),
    (292030, "The Witcher 3: Wild Hunt"),
    (1086940, "Baldur's Gate 3"),
    (1145360, "Hades"),
    (367520, "Hollow Knight"),
    (275850, "No Man's Sky"),
    (1593500, "God of War"),
    (990080, "Hogwarts Legacy"),
    (1817070, "Marvel's Spider-Man Remastered"),
    (546560, "Half-Life: Alyx"),
    (322330, "Don't Starve Together"),
    (1237970, "Titanfall 2"),
    (582010, "Monster Hunter: World"),
    (1811260, "EA SPORTS FC 24"),
]


def fake_games(count) -> list:
    """Synthesize N library entries for Settings ▸ Dev ▸ Fake games. Uses real
    AppIDs so cover art loads in the grid, and alternates hasGameFiles so both
    states show up (installed = full colour, manifest-only = dimmed). Dev-only;
    appended to get_installed_lua_scripts()."""
    try:
        n = int(count)
    except Exception:
        return []
    out = []
    pool = _FAKE_APP_POOL
    for i in range(max(0, n)):
        appid, name = pool[i % len(pool)]
        if i >= len(pool):
            # Past the pool: bump the id so keys stay unique (art falls back).
            appid = appid + i
            name = f"{name} #{i // len(pool) + 1}"
        out.append({
            "appid": appid,
            "gameName": name,
            "isDisabled": False,
            "hasGameFiles": (i % 2 == 0),
        })
    return out
