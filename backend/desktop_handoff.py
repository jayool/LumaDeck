"""Desktop hand-off: arm a one-shot KDE autostart that runs a task on the next
Desktop login and returns to Game Mode.

There are two payloads:
  - DUMMY: prints visible output, always returns to Game Mode. Used to validate
    the round-trip.
  - REAL: runs headcrab (the Steam downgrade that can't run in
    Game Mode) and re-injects lumalinux afterwards. Only returns to Game Mode on
    success; on failure it stays in Desktop (--hold) so the error is readable.

Each payload owns its own return-to-Game-Mode line, because the real one must
NOT return when the downgrade fails.
"""

from __future__ import annotations

import os
import pwd
import shlex
import shutil
import subprocess

from paths import real_home, real_user

try:
    import platform_info as _platform  # session-lineage detection (guarded)
except Exception:  # pragma: no cover - present in-tree
    _platform = None  # type: ignore

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")

# Real user's home (on SteamOS /home/deck). NOTE: the session-switch tooling in
# this module (steamos-session-select, KDE autostart/konsole) is still SteamOS-
# specific — that's Phase 2 (CachyOS uses the ChimeraOS gamescope-session).
_HOME = real_home()
_AUTOSTART = os.path.join(_HOME, ".config", "autostart")
_DESKTOP_FILE = os.path.join(_AUTOSTART, "lumadeck-handoff.desktop")
_SCRIPT_DIR = os.path.join(_HOME, ".local", "share", "lumadeck")
_SCRIPT_FILE = os.path.join(_SCRIPT_DIR, "handoff.sh")

# Each payload ends with its own return-to-Game-Mode logic (the real one only
# returns on success).
#
# REAL payload: aligns Steam to headcrab's pin, then re-injects
# lumalinux so the native-download hooks survive the regenerated steam.sh. This
# is the ONE fix that can't run in Game Mode (Steam is live there).
#
#   - `set +e`: never abort the script on a sub-command failure; we branch
#     explicitly on the headcrab exit code.
#   - lumalinux re-inject is GATED on lumalinux being installed (the .so present)
#     and mirrors install_lumalinux(): download install.sh from main and bash it.
#     It's patch-only and idempotent, and MUST run last (after headcrab
#     regenerates steam.sh) so its hooks aren't wiped.
#   - Returns to Game Mode ONLY on success. On failure it stays in Desktop so the
#     konsole window (--hold) shows the error.
# The Game-Mode session target for `steamos-session-select`. Unlike the desktop
# arg (plasma vs desktop, see _desktop_arg_for), this is "gamescope" on EVERY
# supported lineage (SteamOS + the ChimeraOS lineage: CachyOS/Bazzite), so it
# does not vary by distro — centralised here so both session-select args are
# explicit. NOTE: _REAL_PAYLOAD is an f-string below; keep literal { } out of it.
_GAMEMODE_ARG = "gamescope"

_REAL_PAYLOAD = f"""
set +e
echo "================================================================"
echo " LumaDeck - Aligning Steam to the supported build"
echo " (this runs headcrab, then re-injects lumalinux)"
echo "================================================================"
echo
echo ">>> Running headcrab (Steam downgrade)..."
if curl -fsSL headcrab.pages.dev | bash; then
  echo
  echo ">>> headcrab finished OK."
  if [ -f "$HOME/.local/share/lumalinux/liblumalinux.so" ]; then
    echo ">>> Re-injecting lumalinux..."
    curl -fsSL https://raw.githubusercontent.com/jayool/lumalinux/main/install.sh | bash
    echo ">>> lumalinux re-inject finished (exit $?)."
  else
    echo ">>> lumalinux not installed, skipping re-inject."
  fi
  echo
  echo " All done. Returning to Game Mode in 6s..."
  sleep 6
  steamos-session-select {_GAMEMODE_ARG}
else
  echo
  echo "!! headcrab FAILED. Staying in Desktop so you can read the error."
  echo "!! Close this window and switch back to Game Mode manually when ready."
fi
"""


def _deck_ids() -> tuple[int, int]:
    # Real user's uid/gid (on SteamOS that's the deck user).
    p = pwd.getpwnam(real_user())
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
    # The payload owns its own return-to-Game-Mode line, so we don't append one
    # here (the real payload must NOT return when the downgrade fails).
    return (
        "#!/bin/bash\n"
        "# One-shot LumaDeck Desktop hand-off. Delete the autostart entry FIRST so\n"
        "# a crash or reboot can never re-run this on every Desktop login.\n"
        f'rm -f "{_DESKTOP_FILE}"\n'
        "\n"
        f"{payload}\n"
    )


def _arm(payload: str) -> dict:
    try:
        _write_as_deck(_SCRIPT_FILE, _build_script(payload), 0o755)
        # Plain freedesktop autostart entry (Type=Application + Exec). NO
        # X-KDE-AutostartScript — that legacy key makes Plasma route it through
        # the login-script path and can make it ignore a Type=Application entry.
        # Open the script in whatever terminal is installed (konsole on KDE,
        # else a GNOME-family/X terminal). If none is found, run it headless —
        # the script still writes ~/lumadeck-quickinstall.json + the diag file,
        # the user just doesn't see a live window instead of the run silently
        # never happening (the old konsole-only Exec on a non-KDE distro).
        term = _terminal_exec_prefix()
        exec_line = f"Exec={term} {_SCRIPT_FILE}\n" if term else f"Exec={_SCRIPT_FILE}\n"
        desktop_entry = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=LumaDeck Desktop Hand-off\n"
            + exec_line
            + "Terminal=false\n"
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


# Lineages whose `steamos-session-select` exposes a 'desktop' case (ChimeraOS
# gamescope-session-plus). NOTE: CachyOS Handheld is NOT here — its
# gamescope-session-cachyos is forked from *Valve/SteamOS*, not ChimeraOS
# (verified against CachyOS/gamescope-session @cachyos: usr/lib/steamos/…). Its
# steamos-session-select accepts ONLY plasma / gamescope / persistent / oneshot;
# passing 'desktop' hits the `*)` case and exits 1, breaking the hand-off. So
# CachyOS resolves to 'plasma', exactly like the tested SteamOS path.
# Bazzite IS ChimeraOS/GamerOS lineage (bazzite-org/gamescope-session), so it
# keeps 'desktop' — but that is inferred from lineage, not yet source-verified
# on a Bazzite image (Bazzite is a deferred Phase-3 target).
_CHIMERAOS_LINEAGE = frozenset({"bazzite", "chimeraos"})


def _desktop_arg_for(family: str) -> str:
    """The `steamos-session-select` arg that reaches the desktop session, by
    lineage. SteamOS (HoloISO) AND CachyOS Handheld (a Valve/SteamOS fork) expose
    'plasma' with NO 'desktop' case; the ChimeraOS gamescope-session-plus lineage
    (Bazzite) uses 'desktop'. Pure. Default 'plasma' (the tested SteamOS platform)
    for steamos, cachyos, AND anything we can't positively classify — only switch
    to 'desktop' when the lineage is a known ChimeraOS one."""
    return "desktop" if family in _CHIMERAOS_LINEAGE else "plasma"


def _desktop_session_arg() -> str:
    try:
        if _platform is not None:
            return _desktop_arg_for(_platform.session_family())
    except Exception:
        pass
    return "plasma"


# DE-agnostic terminal resolution for the hand-off window. konsole is KDE-only
# (present on the tested SteamOS/Plasma path, and on CachyOS Handheld / Bazzite
# default which are Plasma), but the GNOME-family targets (ChimeraOS, Bazzite-
# GNOME) don't ship it. Each entry is the argv prefix that runs a command in a
# visible terminal; picked by availability at ARM time (same machine runs it at
# next login). `--hold`/`-hold` where available keeps the window open on failure.
_TERMINALS = (
    ("konsole", "konsole --hold -e"),          # KDE — SteamOS / CachyOS / Bazzite-Plasma
    ("ptyxis", "ptyxis --"),                   # new GNOME default (Fedora/Bazzite-GNOME)
    ("kgx", "kgx -e"),                          # GNOME Console
    ("gnome-terminal", "gnome-terminal --"),   # GNOME
    ("foot", "foot"),                          # wlroots / sway
    ("alacritty", "alacritty -e"),
    ("xterm", "xterm -hold -e"),               # X fallback
)


def _terminal_exec_prefix() -> str | None:
    """The command prefix that opens the hand-off script in whatever terminal is
    installed, or None if none is found (caller runs the script headless). konsole
    first (the tested KDE path); GNOME-family terminals follow so the hand-off
    works on ChimeraOS / Bazzite-GNOME too."""
    for name, prefix in _TERMINALS:
        if shutil.which(name):
            return prefix
    return None


def _find_session_select() -> str | None:
    for p in (
        "/usr/bin/steamos-session-select",
        "/usr/local/bin/steamos-session-select",
        shutil.which("steamos-session-select") or "",
    ):
        if p and os.path.isfile(p):
            return p
    return None


def _run_handoff(payload: str) -> dict:
    """Arm a payload and switch to Desktop. Returns a DIAGNOSTIC dict (every
    step's outcome) so the caller can show exactly what happened: whether files
    armed, whether steamos-session-select was found, whether the switch launched.
    If the switch can't fire, the user can switch to Desktop manually to run the
    armed task."""
    info: dict = {"success": False}
    armed = _arm(payload)
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
        # `env`. steamos-session-select needs the user's session bus to trigger
        # the switch — the root backend isn't in that session by default.
        # The desktop arg is lineage-specific: SteamOS(HoloISO) has NO "desktop"
        # case (valid args plasma / plasma-wayland / gamescope), while the
        # ChimeraOS gamescope-session lineage (CachyOS Handheld, Bazzite) uses
        # "desktop". _desktop_session_arg() picks the right one (default "plasma",
        # the tested SteamOS value). Either way the default login mode stays Game
        # Mode, so we land back in Game Mode after the task.
        desktop_arg = _desktop_session_arg()
        subprocess.Popen(
            ["sudo", "-u", real_user(), "env",
             f"XDG_RUNTIME_DIR={runtime}",
             f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
             f"HOME={real_home()}",
             sel, desktop_arg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        info["desktopArg"] = desktop_arg
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


def run_desktop_handoff_real() -> dict:
    """Arm the REAL task (headcrab downgrade + lumalinux re-inject) and
    switch to Desktop. Returns to Game Mode only on success; stays in Desktop on
    failure so the error is readable."""
    return _run_handoff(_REAL_PAYLOAD)


def run_desktop_handoff_quick_install() -> dict:
    """Arm a Desktop hand-off that runs the FULL Quick Install in Desktop, then
    returns to Game Mode on success.

    WS2: quick_install now runs lumalinux/setup.sh (wrapper model) — SLSsteam +
    CloudRedirect + netsock + lumalinux + .NET, no Steam downgrade, no freeze. So
    this hand-off is no longer downgrade-related; it just runs the installer in a
    visible Desktop konsole (handy for a first setup / seeing progress).

    It runs quick_install_cli.py (which calls installer.quick_install(
    gamemode=False)) under the system Python — the real installer code, nothing
    re-implemented, so no step is forgotten. On failure it stays in Desktop with
    the konsole held; the launcher also writes ~/lumadeck-quickinstall.json."""
    launcher = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quick_install_cli.py")
    if not os.path.isfile(launcher):
        return {"success": False, "error": f"launcher not found: {launcher}"}
    qlauncher = shlex.quote(launcher)
    payload = (
        'echo "================================================================"\n'
        'echo " LumaDeck - Full setup in Desktop (Quick Install)"\n'
        'echo " Installs SLSsteam + CloudRedirect + lumalinux and aligns Steam."\n'
        'echo " This can take a few minutes and Steam may restart. Do NOT close"\n'
        'echo " this window."\n'
        'echo "================================================================"\n'
        'echo\n'
        'PY="$(command -v python3 || echo /usr/bin/python3)"\n'
        f'"$PY" {qlauncher}\n'
        'rc=$?\n'
        'if [ "$rc" -eq 0 ]; then\n'
        '  echo\n'
        '  echo " All done. Returning to Game Mode in 8s..."\n'
        '  sleep 8\n'
        f'  steamos-session-select {_GAMEMODE_ARG}\n'
        'else\n'
        '  echo\n'
        '  echo "!! Setup failed (exit $rc). Staying in Desktop so you can read it."\n'
        '  echo "!! Details: ~/lumadeck-quickinstall.json"\n'
        'fi\n'
    )
    return _run_handoff(payload)


# Full diagnostic written to a file so a tiny toast doesn't truncate it: the user
# can `cat ~/lh.json` in Konsole for the complete result.
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
