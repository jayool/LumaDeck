"""Desktop hand-off: arm a one-shot KDE autostart that runs a task on the next
Desktop login and returns to Game Mode.

DUMMY payload first, to validate the round-trip (Game Mode -> Desktop -> run
something visible -> back to Game Mode) before wiring the real enter-the-wired /
headcrab downgrade (+ the lumalinux re-inject at the end).
"""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

_HOME = "/home/deck"
_AUTOSTART = os.path.join(_HOME, ".config", "autostart")
_DESKTOP_FILE = os.path.join(_AUTOSTART, "lumadeck-handoff.desktop")
_SCRIPT_DIR = os.path.join(_HOME, ".local", "share", "lumadeck")
_SCRIPT_FILE = os.path.join(_SCRIPT_DIR, "handoff.sh")

# Stand-in for enter-the-wired/headcrab: just prints visible output so we can see
# the round-trip work on-device before trusting it with the real downgrade.
_DUMMY_PAYLOAD = """
echo "============================================="
echo " LumaDeck - Desktop hand-off TEST (dummy)"
echo " This is where enter-the-wired / headcrab would run."
echo "============================================="
for i in 1 2 3 4 5; do echo "  ... step $i/5"; sleep 1; done
echo
echo " Dummy task done."
"""


def _deck_ids() -> tuple[int, int]:
    p = pwd.getpwnam("deck")
    return p.pw_uid, p.pw_gid


def _write_as_deck(path: str, content: str, mode: int) -> None:
    """Write a file owned by deck. The parent dir is also chowned to deck so the
    script (which runs as deck) can later delete the .desktop from it — the
    one-shot self-removal needs write access to ~/.config/autostart."""
    uid, gid = _deck_ids()
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    try:
        os.chown(d, uid, gid)
    except Exception:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, mode)
    os.chown(path, uid, gid)


def _build_script(payload: str) -> str:
    return (
        "#!/bin/bash\n"
        "# One-shot LumaDeck Desktop hand-off. Delete the autostart entry FIRST so\n"
        "# a crash or reboot can never re-run this on every Desktop login.\n"
        f'rm -f "{_DESKTOP_FILE}"\n'
        "\n"
        f"{payload}\n"
        "\n"
        'echo " Returning to Game Mode in 4s..."\n'
        "sleep 4\n"
        "steamos-session-select gamescope\n"
    )


def _arm(payload: str) -> dict:
    try:
        _write_as_deck(_SCRIPT_FILE, _build_script(payload), 0o755)
        # Plain freedesktop autostart entry (Type=Application + Exec). NO
        # X-KDE-AutostartScript — that legacy key makes Plasma route it through
        # the login-script path and can make it ignore a Type=Application entry.
        desktop_entry = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=LumaDeck Desktop Hand-off\n"
            # --hold keeps the terminal open if the gamescope switch fails, so a
            # failed run is visible instead of vanishing.
            f"Exec=konsole --hold -e {_SCRIPT_FILE}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        # 0755 so a Plasma build that requires autostart .desktop files to be
        # executable still runs it.
        _write_as_deck(_DESKTOP_FILE, desktop_entry, 0o755)
        logger.info("LumaDeck: armed desktop hand-off (%s)", _SCRIPT_FILE)
        return {"success": True}
    except Exception as exc:
        logger.exception("LumaDeck: arm failed: %s", exc)
        return {"success": False, "error": f"arm: {exc}"}


def _find_session_select() -> str | None:
    for p in (
        "/usr/bin/steamos-session-select",
        "/usr/local/bin/steamos-session-select",
        shutil.which("steamos-session-select") or "",
    ):
        if p and os.path.isfile(p):
            return p
    return None


def run_desktop_handoff_dummy() -> dict:
    """Arm the dummy task and switch to Desktop. Returns a DIAGNOSTIC dict (every
    step's outcome) so the test button can show exactly what happened: whether
    files armed, whether steamos-session-select was found, whether the switch
    launched. If the switch can't fire, the user can switch to Desktop manually
    to test the autostart half."""
    info: dict = {"success": False}
    armed = _arm(_DUMMY_PAYLOAD)
    info["armed"] = bool(armed.get("success"))
    if not armed.get("success"):
        info["error"] = armed.get("error")
        return _dump(info)

    info["scriptExists"] = os.path.isfile(_SCRIPT_FILE)
    info["desktopExists"] = os.path.isfile(_DESKTOP_FILE)

    sel = _find_session_select()
    info["sessionSelect"] = sel or "(not found)"
    if not sel:
        info["success"] = True
        info["switchLaunched"] = False
        info["note"] = "armed OK; steamos-session-select not found — switch to Desktop manually to test the autostart"
        return _dump(info)

    uid, _gid = _deck_ids()
    runtime = f"/run/user/{uid}"
    try:
        # sudo strips the env, so set the session vars on the command line via
        # `env`. steamos-session-select needs deck's session bus to trigger the
        # switch — the root backend isn't in that session by default.
        # NOTE: steamos-session-select has NO "desktop" case — valid args are
        # plasma / plasma-wayland / gamescope / ...-persistent. We use "plasma"
        # (non-persistent X11 desktop) so the default login mode stays Game Mode
        # and we land back in Game Mode after the task.
        subprocess.Popen(
            ["sudo", "-u", "deck", "env",
             f"XDG_RUNTIME_DIR={runtime}",
             f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
             "HOME=/home/deck",
             sel, "plasma"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        info["success"] = True
        info["switchLaunched"] = True
        info["switchRuntime"] = runtime
    except Exception as exc:
        logger.exception("LumaDeck: switch to desktop failed: %s", exc)
        info["success"] = True   # armed fine; only the auto-switch failed
        info["switchLaunched"] = False
        info["switchError"] = str(exc)
        info["note"] = "armed OK; auto-switch failed — switch to Desktop manually to test the autostart"
    return _dump(info)


# Full diagnostic written to a file so a tiny toast doesn't truncate it: the user
# can `cat /home/deck/lh.json` in Konsole for the complete result.
_DIAG_FILE = os.path.join(_HOME, "lh.json")


def _dump(info: dict) -> dict:
    import json
    try:
        _write_as_deck(_DIAG_FILE, json.dumps(info, indent=2), 0o644)
        info["diagFile"] = _DIAG_FILE
    except Exception:
        pass
    return info


def disarm_desktop_handoff() -> dict:
    """Remove the armed files (manual cleanup / safety)."""
    for p in (_DESKTOP_FILE, _SCRIPT_FILE):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except Exception:
            pass
    return {"success": True}
