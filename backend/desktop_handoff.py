"""Desktop hand-off: arm a one-shot KDE autostart that runs a task on the next
Desktop login and returns to Game Mode.

There are two payloads:
  - DUMMY: prints visible output, always returns to Game Mode. Used to validate
    the round-trip.
  - REAL: the break-recovery downgrade (can't run in Game Mode) — downgrade.sh
    aligns Steam down + pins it, then setup.sh re-establishes the wrapper stack.
    Only returns to Game Mode on success; on failure it stays in Desktop (--hold)
    so the error is readable.

Each payload owns its own return-to-Game-Mode line, because the real one must
NOT return when the downgrade fails.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional
import pwd
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
# returns on success). The REAL payload (the break-recovery downgrade) is defined
# below, next to _SETUP_SH_URL — see its comment for the wrapper-model flow.
# The Game-Mode session target for `steamos-session-select`. Unlike the desktop
# arg (plasma vs desktop, see _desktop_arg_for), this is "gamescope" on EVERY
# supported lineage (SteamOS + the ChimeraOS lineage: CachyOS/Bazzite), so it
# does not vary by distro — centralised here so both session-select args are
# explicit. NOTE: _REAL_PAYLOAD is an f-string below; keep literal { } out of it.
_GAMEMODE_ARG = "gamescope"

# setup.sh + downgrade.sh (wrapper model) URLs — kept in sync with
# installer.SETUP_SH_URL via the same env override. Defined locally (not imported)
# to avoid a circular import at module load.
_SETUP_SH_URL = os.environ.get(
    "LUMADECK_SETUP_URL",
    "https://raw.githubusercontent.com/jayool/lumalinux/main/setup.sh",
)
_DOWNGRADE_SH_URL = os.environ.get(
    "LUMADECK_DOWNGRADE_URL",
    "https://raw.githubusercontent.com/jayool/lumalinux/main/downgrade.sh",
)

# REAL payload = the break-recovery downgrade escape-hatch. It is the ONE fix that
# can't run in Game Mode (Steam is live there): a genuinely-unsupported Steam build
# (byte patterns broke after a major update) must be aligned down to a supported
# build. FULLY decoupled from headcrab now:
#   1. downgrade.sh aligns the Steam CLIENT down to the supported build and writes
#      the pin (steam.cfg) that HOLDS it there — a faithful port of headcrab's
#      clientdowngrade (dgsc/dlm depot), but WITHOUT running headcrab, so it never
#      replaces steam.sh or reinstalls components (no double injection).
#   2. setup.sh re-establishes OUR stack + wrapper against the downgraded build.
# steam_freeze.py lifts the pin later, once the ecosystem catches up and the QAM
# offers the align-up update. Returns to Game Mode ONLY on success; on failure it
# stays in Desktop (--hold) so the konsole shows the error.
#   - `set +e`: never abort on a sub-command failure; branch on the exit codes.
#   - downgrade FIRST (fix the Steam build), then setup.sh against the good build.
# setup.sh installs the LATEST SLSsteam. If that release no longer hooks the
# client the downgrade lands on (2026-10-14: 20261014151919 only hooks
# 1791918634; on the bc54101b client it crash-looped Steam and SteamOS
# re-bootstrapped the image's client), downgrading only breaks Steam, and the
# right fix is Update (SystemStatus.updateFixesBreak). downgrade_target() picks
# the newest whitelisted build the latest SLSsteam hooks (both client lines,
# 2026-11-19) and prepare_real() refuses the hand-off when there is none.
_REAL_PAYLOAD_TEMPLATE = f"""
set +e
# pipefail so `curl … | bash` reflects curl's exit, not bash's: without it a
# 404/timeout makes curl fail while bash reads empty stdin and exits 0, and the
# `if` below would take the SUCCESS branch — returning to Game Mode on a broken,
# un-downgraded, un-pinned Steam. With pipefail the pipe returns curl's failure.
set -o pipefail
echo "================================================================"
echo " LumaDeck - Aligning Steam to the supported build"
echo " (downgrade.sh: client downgrade + pin, then setup.sh: wrapper stack)"
echo "================================================================"
echo
echo ">>> Downgrading Steam + writing the pin (downgrade.sh)..."
if curl -fsSL {_DOWNGRADE_SH_URL} | __DOWNGRADE_ENV__bash; then
  echo
  echo ">>> Downgrade finished OK (Steam downgraded and pinned)."
  echo ">>> Re-establishing the injection wrapper via setup.sh..."
  curl -fsSL {_SETUP_SH_URL} | bash
  echo ">>> setup.sh finished (exit $?)."
  echo
  echo " All done. Returning to Game Mode in 6s..."
  sleep 6
  steamos-session-select {_GAMEMODE_ARG}
else
  echo
  echo "!! Downgrade FAILED. Staying in Desktop so you can read the error."
  echo "!! Close this window and switch back to Game Mode manually when ready."
fi
"""


def _real_payload(target=None, line=None, candidates=None) -> str:
    """The REAL payload with the downgrade decided here: downgrade.sh takes the
    builds it may land on (TARGET_VERSIONS, newest first: every build the
    released stack hooks below the installed one; it keeps the first one this
    install's branch ever served, so a stable install stays on builds stable
    shipped), the one-build form (TARGET_VERSION, for older scripts) and the
    client line (CLIENT_LINE, steamrt64 | ubuntu12) from its environment.
    Without them the script picks among the whitelisted builds itself."""
    env = ""
    if target:
        env += f"TARGET_VERSION={int(target)} "
    if candidates:
        env += "TARGET_VERSIONS=\"" + " ".join(str(int(c)) for c in candidates) + "\" "
    if line in ("steamrt64", "ubuntu12"):
        env += f"CLIENT_LINE={line} "
    return _REAL_PAYLOAD_TEMPLATE.replace("__DOWNGRADE_ENV__", env)


_REAL_PAYLOAD = _real_payload()


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


def downgrade_target_ok(sls_text, target_hash) -> Optional[str]:
    """Pure: None when the LATEST SLSsteam (what setup.sh installs after the
    downgrade) hooks the client with hash `target_hash`; else the reason the
    hand-off must be refused."""
    from steam_update_gate import slssteam_latest_supports
    if not target_hash:
        return "the target Steam build's client hash is unknown (lumalinux feed has no entry for it)"
    ok = slssteam_latest_supports(sls_text, target_hash)
    if ok is True:
        return None
    if ok is None:
        return "could not read SLSsteam's release feed to check the target build"
    return "the latest SLSsteam no longer supports the Steam build the downgrade would install; update the components instead"


_TARGET_CACHE = os.path.join(_HOME, ".cache", "lumadeck", "downgrade_target.json")
_TARGET_TTL = 30 * 60


def _client_line(arch: str) -> str:
    """The manifest line of client `arch`: steamrt64 for the 64-bit client,
    ubuntu12 for the 32-bit one (the names downgrade.sh and Valve use)."""
    from paths import STEAM_CLIENT_64
    return "steamrt64" if arch == STEAM_CLIENT_64 else "ubuntu12"


def pick_downgrade_target(ll_text, ll_group, sls_text, current, arch) -> dict:
    """Pure: the build downgrade.sh should land on for client `arch`, from the
    feeds. The newest build lumalinux's whitelist annotates for that arch below
    the installed one (`current`; any when unknown) that BOTH the latest
    lumalinux release (its group `ll_group`) and the latest SLSsteam for the
    arch hook — what setup.sh installs right after. Returns {"target",
    "hash", "candidates", "possible", "error"}: possible True with the pick
    (`candidates` = every qualifying build, newest first, for downgrade.sh to
    keep the first one this install's branch served); None when a candidate's
    SLSsteam support is unknown (the 64-bit feed may not list it yet) and
    nothing better exists; False when no annotated build qualifies."""
    from headcrab_compat import _hash_for_build, _supports_build, _whitelist_entries
    from steam_update_gate import slssteam_latest_supports
    if not ll_text:
        return {"target": None, "hash": None, "candidates": [], "possible": None,
                "error": "could not read lumalinux's whitelist to pick a build"}
    builds = sorted({v for _g, vs, a, _sha in _whitelist_entries(ll_text) if a == arch for v in vs},
                    reverse=True)
    good: list = []      # (build, sha) the released stack hooks, newest first
    unknown = None
    for build in builds:
        if current is not None and build >= current:
            continue
        sha = _hash_for_build(ll_text, build, arch)
        if _supports_build(ll_text, ll_group, build, arch) is not True:
            continue
        ok = slssteam_latest_supports(sls_text, sha, arch)
        if ok is True:
            good.append((build, sha))
        elif ok is None and unknown is None:
            unknown = (build, sha)
    if good:
        return {"target": good[0][0], "hash": good[0][1], "candidates": [b for b, _s in good],
                "possible": True, "error": None}
    if unknown:
        return {"target": unknown[0], "hash": unknown[1], "candidates": [unknown[0]], "possible": None,
                "error": f"downgrade to {unknown[0]}: could not read SLSsteam's release feed to check it"}
    if not builds:
        return {"target": None, "hash": None, "candidates": [], "possible": False,
                "error": f"no {_client_line(arch)} build is whitelisted below the installed one"}
    return {"target": None, "hash": None, "candidates": [], "possible": False,
            "error": "the latest SLSsteam hooks no whitelisted build below the installed one; update the components instead"}


# The tracker (SteamTracking/SteamTracking, ClientManifest/<file>): the public
# git history of every manifest Valve serves. downgrade.sh fetches the build's
# manifest from the commit of the install's OWN branch file that carried that
# version, so a candidate the branch never served (a beta-only build, or the
# same file relabelled with another number on the other branch, or anything
# before the tracker started keeping the file — 2026-11-12 for the Deck's
# 64-bit files) cannot be installed. Asked here, before the button is offered,
# with the same walk as the script's tracker_manifest_for_version: commits
# newest first, each manifest's "version", stop at the build or at the first
# smaller one. Only while a component is not_supported, cached 30 minutes.
_TRACKER_REPO = "SteamTracking/SteamTracking"
_TRACKER_API = os.environ.get("LUMADECK_TRACKER_API", f"https://api.github.com/repos/{_TRACKER_REPO}/commits")
_TRACKER_RAW = os.environ.get("LUMADECK_TRACKER_RAW", f"https://raw.githubusercontent.com/{_TRACKER_REPO}")
_TRACKER_PER_PAGE = 50
_TRACKER_MAX_PAGES = 10


def tracker_file(line: str, branch: str) -> str:
    """The tracker's file for client line `line` on Steam branch `branch`
    (package/beta): a steamdeck_* branch asks for the Deck manifests
    (`steamdeck_<channel>[_steamrt64]`), anything else the desktop ones
    (`steam_client_[publicbeta_]<line>`). Same rule as downgrade.sh's
    tracker_file."""
    channel = "publicbeta" if "publicbeta" in (branch or "") else "stable"
    if (branch or "").startswith("steamdeck"):
        return f"steamdeck_{channel}_{line}" if line == "steamrt64" else f"steamdeck_{channel}"
    return f"steam_client_{line}" if channel == "stable" else f"steam_client_{channel}_{line}"


def served_on_branch(versions_newest_first, candidates) -> list:
    """Pure: which of `candidates` (newest first) a branch served, given the
    versions its history holds newest first (None = an unreadable capture).
    A build is served when the walk meets it before meeting a smaller one."""
    served = []
    for c in candidates:
        for v in versions_newest_first:
            if v is None:
                continue
            if v == c:
                served.append(c)
                break
            if v < c:
                break
    return served


async def _tracker_commits_page(client, file: str, page: int) -> list:
    resp = await client.get(_TRACKER_API, params={"path": f"ClientManifest/{file}",
                                                   "per_page": _TRACKER_PER_PAGE, "page": page}, timeout=10.0)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return [c["sha"] for c in resp.json()]


async def _tracker_manifest_version(client, file: str, sha: str):
    from steam_update_gate import parse_manifest_version
    resp = await client.get(f"{_TRACKER_RAW}/{sha}/ClientManifest/{file}", timeout=10.0)
    if resp.status_code != 200:
        return None
    return parse_manifest_version(resp.text)


async def served_candidates(file: str, candidates: list, client=None):
    """The candidates the branch (tracker file `file`) served, newest first,
    walking its history only as far as the oldest candidate needs. None when
    the tracker cannot be read at all (GitHub down or blocked): the caller
    keeps its list and the script repeats the walk itself."""
    if not candidates:
        return []
    from http_client import ensure_http_client
    client = client or await ensure_http_client(context="desktop_handoff")
    versions: list = []

    def resolved() -> bool:   # every candidate met (served) or passed (not served)
        seen = [v for v in versions if v is not None]
        return all(any(v == c for v in seen) or any(v < c for v in seen) for c in candidates)

    try:
        for page in range(1, _TRACKER_MAX_PAGES + 1):
            shas = await _tracker_commits_page(client, file, page)
            if not shas:
                break
            for sha in shas:
                versions.append(await _tracker_manifest_version(client, file, sha))
                if resolved():
                    break
            if resolved() or len(shas) < _TRACKER_PER_PAGE:
                break
    except Exception as exc:
        logger.info("desktop_handoff: tracker history of %s unreadable (%s)", file, exc)
        if not versions:
            return None
    return served_on_branch(versions, candidates)


async def downgrade_target(force: bool = False) -> dict:
    """The build downgrade.sh would install for the running client, decided
    here (pick_downgrade_target) from the three feeds and cached 30 minutes
    with the line it is for — run_desktop_handoff_real() hands both to the
    script. {"target", "hash", "line", "possible", "error"}; the cache when
    the feeds are unreachable, else possible None."""
    import json
    import time
    from headcrab_compat import _lumalinux_updates_text, current_steam_build, latest_release_group
    from paths import steam_client_arch
    from steam_update_gate import slssteam_updates_text
    arch = steam_client_arch()
    line = _client_line(arch)
    if not force:
        try:
            with open(_TARGET_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if (time.time() - float(cached.get("at", 0)) < _TARGET_TTL
                    and cached.get("line") == line and "possible" in cached):
                return {k: cached.get(k) for k in ("target", "hash", "candidates", "line", "possible", "error", "tracker", "tracker_file")}
        except Exception:
            pass
    ll_text, ll_group, sls_text = await asyncio.gather(
        _lumalinux_updates_text(force=force), latest_release_group(force=force),
        slssteam_updates_text(force=force))
    pick = pick_downgrade_target(ll_text, ll_group, sls_text, current_steam_build(), arch)
    pick["line"] = line
    if pick.get("candidates"):
        from headcrab_compat import _hash_for_build
        from steam_update_gate import _branch
        tfile = tracker_file(line, _branch())
        served = await served_candidates(tfile, pick["candidates"])
        pick["tracker_file"] = tfile
        if served is None:
            pick["tracker"] = "unreachable"       # keep the list: the script walks the history itself
        elif not served:
            pick.update(target=None, hash=None, candidates=[], possible=False, tracker="none",
                        error=f"none of the builds the released stack hooks was served on this install's "
                              f"Steam branch ({tfile}): nothing to downgrade to; wait for the components")
        else:
            pick.update(target=served[0], hash=_hash_for_build(ll_text, served[0], arch),
                        candidates=served, tracker="ok")
    if ll_text is not None and sls_text is not None:
        try:
            os.makedirs(os.path.dirname(_TARGET_CACHE), exist_ok=True)
            with open(_TARGET_CACHE, "w", encoding="utf-8") as f:
                json.dump(dict(pick, at=time.time()), f)
        except Exception:
            pass
        return pick
    try:
        with open(_TARGET_CACHE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("line") == line and "possible" in cached:
            return {k: cached.get(k) for k in ("target", "hash", "candidates", "line", "possible", "error", "tracker", "tracker_file")}
    except Exception:
        pass
    return pick


def _cached_target() -> dict:
    """What prepare_real() last decided (the cache downgrade_target writes),
    for the hand-off itself; empty when there is none."""
    import json
    try:
        with open(_TARGET_CACHE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        return cached if cached.get("possible") else {}
    except Exception:
        return {}


async def downgrade_check(force: bool = False) -> dict:
    """Would Fix in Desktop help right now? {"target": int|None, "possible":
    True/False/None, "error": str|None}. possible is False when no whitelisted
    build below the installed one is hooked by the latest SLSsteam (downgrading
    would break Steam; the fix is Update or waiting), None when the feeds can't
    tell. Both client lines: the 64-bit client downgrades along its own
    steamrt64 line (downgrade.sh, 2026-11-19). The status payload carries it so
    the QAM offers the button only when it can work."""
    pick = await downgrade_target(force=force)
    return {"target": pick.get("target"), "possible": pick.get("possible"), "error": pick.get("error")}


async def prepare_real() -> dict:
    """Resolve the downgrade target the way downgrade.sh will (its manifest) and
    check the latest SLSsteam hooks it. Returns {"target": int} or {"error": str}."""
    chk = await downgrade_check(force=True)
    if chk.get("error"):
        return {"error": chk["error"]}
    logger.info("desktop_handoff: downgrade target %s: latest SLSsteam hooks it", chk["target"])
    return {"target": chk["target"]}


def run_desktop_handoff_real() -> dict:
    """Arm the REAL task — the break-recovery downgrade escape-hatch: downgrade.sh
    aligns Steam down to a supported build and pins it, then setup.sh re-establishes
    the injection wrapper — and switch to Desktop. Fully decoupled from headcrab.
    Returns to Game Mode only on success; stays in Desktop on failure so the error
    is readable. prepare_real() must have passed first (the latest SLSsteam hooks
    the target client); the hand-off passes its pick (build + client line) to
    downgrade.sh."""
    cached = _cached_target()
    return _run_handoff(_real_payload(cached.get("target"), cached.get("line"), cached.get("candidates")))


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
