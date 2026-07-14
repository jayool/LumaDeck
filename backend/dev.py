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
