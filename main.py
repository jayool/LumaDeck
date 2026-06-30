"""LumaDeck — Decky Loader Plugin entry point.

Exposes all backend functions as async methods callable from the frontend
via serverAPI.callPluginMethod().

IMPORTANT: Every method must return a JSON **string** (via json.dumps),
because the frontend api.ts parseResult() calls JSON.parse(raw).
"""

import sys
import os
import json

# Add backend/ to module search path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "backend"))

try:
    import decky  # type: ignore
    logger = decky.logger
except ImportError:
    import logging
    logger = logging.getLogger("lumadeck")


def _j(obj) -> str:
    """Ensure we always return a JSON string to the frontend."""
    if isinstance(obj, str):
        # Already serialized — pass through only if it's valid JSON
        try:
            json.loads(obj)
            return obj
        except (json.JSONDecodeError, TypeError):
            pass
    return json.dumps(obj)


_injection_repaired_on_startup: bool = False


class Plugin:
    # ==========================================================================
    # Lifecycle
    # ==========================================================================

    async def _main(self):
        global _injection_repaired_on_startup
        logger.info("LumaDeck: Plugin loaded")
        try:
            from api_manifest import init_apis
            from downloads import init_applist, init_games_db
            from paths import get_platform_summary, verify_slssteam_injected

            # Apply a staged self-update (#23) before anything else, so a pending
            # zip from a previous session lands on disk for this load's restart.
            try:
                from self_update import apply_pending_update_if_any
                apply_pending_update_if_any()
            except Exception as exc:
                logger.warning(f"LumaDeck: pending update check failed: {exc}")

            # Check + auto-repair SLSsteam injection before anything else
            try:
                inj = verify_slssteam_injected()
                if inj.get("patched"):
                    _injection_repaired_on_startup = True
                    logger.info("LumaDeck: SLSsteam injection was missing — patched steam.sh. Steam restart required.")
                elif inj.get("already_ok"):
                    logger.info("LumaDeck: SLSsteam injection OK")
                else:
                    logger.warning(f"LumaDeck: SLSsteam injection check: {inj}")
            except Exception as exc:
                logger.warning(f"LumaDeck: SLSsteam injection check failed: {exc}")

            summary = get_platform_summary()
            logger.info(f"LumaDeck: Platform summary: {json.dumps(summary)}")

            await init_apis()
            # Restore Hubcap key / Ryuu cookie from the settings-dir store if a
            # reinstall wiped backend/data/ (Decky replaces the whole plugin dir).
            try:
                from api_manifest import restore_credentials_from_settings
                restore_credentials_from_settings()
            except Exception as exc:
                logger.warning(f"LumaDeck: credential restore failed: {exc}")
            await init_applist()
            await init_games_db()
        except Exception as exc:
            logger.error(f"LumaDeck: _main init error: {exc}")

    async def _unload(self):
        logger.info("LumaDeck: Plugin unloading")
        try:
            from http_client import close_http_client
            from downloads import DOWNLOAD_TASKS
            # Cancel active downloads
            for task in DOWNLOAD_TASKS.values():
                if not task.done():
                    task.cancel()
            await close_http_client("unload")
        except Exception as exc:
            logger.error(f"LumaDeck: _unload error: {exc}")

    # ==========================================================================
    # Platform & Paths
    # ==========================================================================

    async def get_injection_status(self) -> str:
        """Return whether SLSsteam injection is OK and if it was repaired on startup."""
        from paths import verify_slssteam_injected
        result = verify_slssteam_injected()
        result["was_repaired_on_startup"] = _injection_repaired_on_startup
        return _j(result)

    async def get_slssteam_health(self) -> str:
        """Resolve SLSsteam into a single UI state (healthy/broken/not_active/...)."""
        from paths import read_slssteam_health
        return _j(read_slssteam_health())

    async def get_lumalinux_health(self) -> str:
        """Resolve lumalinux into a single UI state (healthy/hash_blocked/...)."""
        from paths import read_lumalinux_health
        return _j(read_lumalinux_health())

    async def get_cloudredirect_health(self) -> str:
        """Resolve CloudRedirect into a single UI state (healthy/broken/not_authed/...)."""
        from paths import read_cloudredirect_health
        return _j(read_cloudredirect_health())

    async def check_cloudredirect_update(self) -> str:
        """{installed, latest, has_update, url} via GitHub Releases (cached 6h)."""
        from paths import read_cloudredirect_health
        from update_checks import has_update
        installed = read_cloudredirect_health().get("version")
        return _j(await has_update("Selectively11", "CloudRedirect", installed))

    async def check_lumalinux_update(self) -> str:
        """{installed, latest, has_update, url} via GitHub Releases (cached 6h)."""
        from paths import read_lumalinux_health
        from update_checks import has_update
        installed = read_lumalinux_health().get("version")
        return _j(await has_update("jayool", "lumalinux", installed))

    async def get_components_status(self) -> str:
        """Unified per-component health + update + headcrab gate + plugin, in one
        call. See the Component model spec in DESIGN_UI.md. Additive — wraps the
        existing per-component checks."""
        from components import get_components_status
        return _j(await get_components_status())

    async def restart_steam(self) -> str:
        """Shutdown Steam as deck user (Game Mode auto-restarts it)."""
        import subprocess, os
        steam_bin = "/home/deck/.local/share/Steam/ubuntu12_32/steam"
        # Try IPC shutdown as deck user first
        for cmd in [
            ["sudo", "-u", "deck", steam_bin, "-shutdown"],
            ["su", "-c", f"{steam_bin} -shutdown", "deck"],
        ]:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return _j({"success": True})
            except Exception:
                continue
        # Fallback: SIGTERM to steam process owned by deck
        try:
            import signal
            result = subprocess.run(
                ["pgrep", "-u", "deck", "-f", "ubuntu12_32/steam"],
                capture_output=True, text=True
            )
            for pid_str in result.stdout.strip().splitlines():
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except Exception:
                    pass
            return _j({"success": True})
        except Exception as exc:
            return _j({"success": False, "error": str(exc)})

    async def get_platform_summary(self) -> str:
        from paths import get_platform_summary
        return _j(get_platform_summary())

    async def verify_slssteam_injected(self) -> str:
        from paths import verify_slssteam_injected
        return _j(verify_slssteam_injected())

    async def check_slssteam_hash_status(self) -> str:
        from slssteam_ops import check_slssteam_hash_status
        return _j(check_slssteam_hash_status())

    async def check_headcrab_compat(self) -> str:
        from headcrab_compat import check_headcrab_compat
        return _j(await check_headcrab_compat())

    async def repair_slssteam_headcrab(self) -> str:
        from slssteam_ops import repair_slssteam_headcrab
        return _j(await repair_slssteam_headcrab())

    # ==========================================================================
    # API Manifest
    # ==========================================================================

    async def init_apis(self) -> str:
        from api_manifest import init_apis
        return _j(await init_apis())

    async def fetch_free_apis_now(self) -> str:
        from api_manifest import fetch_free_apis_now
        return _j(await fetch_free_apis_now())

    async def get_init_apis_message(self) -> str:
        from api_manifest import get_init_apis_message
        return _j(get_init_apis_message())

    async def save_ryu_cookie(self, cookie_content: str) -> str:
        from api_manifest import save_ryu_cookie
        return _j(save_ryu_cookie(cookie_content))

    async def load_ryu_cookie(self) -> str:
        from api_manifest import load_ryu_cookie
        cookie = load_ryu_cookie()
        return _j({"success": True, "cookie": cookie})

    async def import_ryuu_cookie_from_browser(self) -> str:
        from ryuu_cookie import import_ryuu_cookie_from_browser
        return _j(import_ryuu_cookie_from_browser())

    async def update_hubcap_key(self, key_content: str) -> str:
        from api_manifest import update_hubcap_key
        return _j(update_hubcap_key(key_content))

    async def load_hubcap_key(self) -> str:
        from api_manifest import load_hubcap_key
        return _j({"success": True, "key": load_hubcap_key()})

    async def search_hubcap(self, query: str) -> str:
        from api_manifest import search_hubcap
        return _j(await search_hubcap(query))

    async def get_credential_status(self) -> str:
        from api_manifest import get_credential_status
        return _j(await get_credential_status())

    async def pin_game(self, appid: int) -> str:
        from downloads import pin_game
        return _j(await pin_game(appid))

    async def unpin_game(self, appid: int) -> str:
        from downloads import unpin_game
        return _j(await unpin_game(appid))

    async def get_pin_status(self, appid: int) -> str:
        from downloads import get_pin_status
        return _j(await get_pin_status(appid))

    # ==========================================================================
    # Downloads
    # ==========================================================================

    async def start_download(self, appid: int, target_library_path: str = "") -> str:
        logger.info(f"LumaDeck: start_download called, appid={appid}, library={target_library_path or '(default)'}")
        try:
            from downloads import start_download
            result = await start_download(appid, target_library_path)
            logger.info(f"LumaDeck: start_download result={result}")
            return _j(result)
        except Exception as exc:
            logger.error(f"LumaDeck: start_download error: {exc}")
            return _j({"success": False, "error": str(exc)})

    async def get_download_status(self, appid: int) -> str:
        from downloads import get_download_status
        return _j(get_download_status(appid))

    async def get_active_downloads(self) -> str:
        from downloads import get_active_downloads
        return _j(get_active_downloads())

    async def cancel_download(self, appid: int) -> str:
        from downloads import cancel_download
        return _j(cancel_download(appid))

    async def has_luatools_for_app(self, appid: int) -> str:
        from downloads import has_luatools_for_app
        return _j(has_luatools_for_app(appid))

    async def delete_luatools_for_app(self, appid: int) -> str:
        from downloads import delete_luatools_for_app
        return _j(delete_luatools_for_app(appid))

    async def get_installed_lua_scripts(self) -> str:
        from downloads import get_installed_lua_scripts
        return _j(get_installed_lua_scripts())

    async def read_loaded_apps(self) -> str:
        from downloads import read_loaded_apps
        return _j(read_loaded_apps())

    async def dismiss_loaded_apps(self) -> str:
        from downloads import dismiss_loaded_apps
        return _j(dismiss_loaded_apps())

    async def fetch_app_name(self, appid: int) -> str:
        from downloads import fetch_app_name
        name = await fetch_app_name(appid)
        return _j({"success": True, "name": name})

    async def get_game_notices(self, appid: int) -> str:
        from downloads import get_game_notices
        return _j(await get_game_notices(appid))

    async def get_games_database(self) -> str:
        from downloads import get_games_database
        return _j(get_games_database())

    async def check_plugin_update(self) -> str:
        from self_update import check_plugin_update
        return _j(await check_plugin_update())

    async def update_plugin(self) -> str:
        from self_update import update_plugin
        return _j(await update_plugin())

    async def download_update_to_downloads(self) -> str:
        from self_update import download_update_to_downloads
        return _j(await download_update_to_downloads())

    # ==========================================================================
    # Steam Utils
    # ==========================================================================

    async def get_game_install_path(self, appid: int) -> str:
        from steam_utils import get_game_install_path_response
        return _j(get_game_install_path_response(appid))

    async def get_installed_games(self) -> str:
        from steam_utils import get_installed_games
        return _j({"success": True, "games": get_installed_games()})

    async def check_stuck_updates(self) -> str:
        from steam_utils import check_stuck_updates
        return _j(check_stuck_updates())

    async def get_steam_libraries(self) -> str:
        from steam_utils import get_steam_libraries
        return _j({"success": True, "libraries": get_steam_libraries()})

    # ==========================================================================
    # SLSsteam Config (read/write)
    # ==========================================================================

    async def read_sls_config(self) -> str:
        from slssteam_config import read_config
        return _j({"success": True, "config": read_config()})

    async def get_sls_value(self, key: str) -> str:
        from slssteam_config import get_value
        return _j({"success": True, "value": get_value(key)})

    async def set_sls_value(self, key: str, value) -> str:
        from slssteam_config import set_value
        set_value(key, value)
        return _j({"success": True})

    # ==========================================================================
    # SLSsteam Operations (FakeAppId, Token, DLC, Play, Uninstall)
    # ==========================================================================

    async def add_fake_app_id(self, appid: int, fake_id: int = 480) -> str:
        from slssteam_ops import add_fake_app_id
        return _j(add_fake_app_id(appid, fake_id))

    async def remove_fake_app_id(self, appid: int) -> str:
        from slssteam_ops import remove_fake_app_id
        return _j(remove_fake_app_id(appid))

    async def check_fake_app_id_status(self, appid: int) -> str:
        from slssteam_ops import check_fake_app_id_status
        return _j(check_fake_app_id_status(appid))

    async def add_game_token(self, appid: int) -> str:
        from slssteam_ops import add_game_token
        return _j(add_game_token(appid))

    async def remove_game_token(self, appid: int) -> str:
        from slssteam_ops import remove_game_token
        return _j(remove_game_token(appid))

    async def check_game_token_status(self, appid: int) -> str:
        from slssteam_ops import check_game_token_status
        return _j(check_game_token_status(appid))

    async def add_game_dlcs(self, appid: int) -> str:
        from slssteam_ops import add_game_dlcs
        return _j(await add_game_dlcs(appid))

    async def remove_game_dlcs(self, appid: int) -> str:
        from slssteam_ops import remove_game_dlcs
        return _j(remove_game_dlcs(appid))

    async def check_game_dlcs_status(self, appid: int) -> str:
        from slssteam_ops import check_game_dlcs_status
        return _j(check_game_dlcs_status(appid))

    async def get_sls_play_status(self) -> str:
        from slssteam_ops import get_sls_play_status
        return _j(get_sls_play_status())

    async def set_sls_play_status(self, enabled: bool) -> str:
        from slssteam_ops import set_sls_play_status
        return _j(set_sls_play_status(enabled))

    async def uninstall_game_full(self, appid: int, remove_compatdata: bool = False) -> str:
        from slssteam_ops import uninstall_game_full
        return _j(uninstall_game_full(appid, remove_compatdata))

    # ==========================================================================
    # Goldberg Steam Emulator
    # ==========================================================================

    async def check_goldberg_status(self, install_path: str) -> str:
        from goldberg import check_goldberg_status
        return _j(check_goldberg_status(install_path))

    async def apply_goldberg(self, install_path: str, appid: int) -> str:
        from goldberg import apply_goldberg
        return _j(apply_goldberg(install_path, appid))

    async def remove_goldberg(self, install_path: str, appid: int) -> str:
        from goldberg import remove_goldberg
        return _j(remove_goldberg(install_path, appid))

    # ==========================================================================
    # Achievements (SLScheevo)
    # ==========================================================================

    async def check_slscheevo_installed(self) -> str:
        from achievements import check_slscheevo_installed
        return _j(check_slscheevo_installed())

    async def check_achievements_status(self, appid: int) -> str:
        from achievements import check_achievements_status
        return _j(check_achievements_status(appid))

    async def generate_achievements(self, appid: int) -> str:
        from achievements import generate_achievements
        return _j(generate_achievements(appid))

    async def get_generate_status(self, appid: int) -> str:
        from achievements import get_generate_status
        return _j(get_generate_status(appid))

    async def download_slscheevo(self) -> str:
        from achievements import download_slscheevo
        return _j(download_slscheevo())

    async def get_slscheevo_download_status(self) -> str:
        from achievements import get_slscheevo_download_status
        return _j(get_slscheevo_download_status())

    async def check_all_achievements_status(self, appids: list) -> str:
        from achievements import check_all_achievements_status
        return _j(check_all_achievements_status(appids))

    async def generate_all_achievements(self, appids: list) -> str:
        from achievements import generate_all_achievements
        return _j(generate_all_achievements(appids))

    async def get_sync_all_status(self) -> str:
        from achievements import get_sync_all_status
        return _j(get_sync_all_status())

    # ==========================================================================
    # Fixes
    # ==========================================================================

    async def check_for_fixes(self, appid: int) -> str:
        from fixes import check_for_fixes
        return _j(await check_for_fixes(appid))

    async def apply_game_fix(self, appid: int, download_url: str, install_path: str, fix_type: str = "", game_name: str = "") -> str:
        from fixes import apply_game_fix
        return _j(await apply_game_fix(appid, download_url, install_path, fix_type, game_name))

    async def get_apply_fix_status(self, appid: int) -> str:
        from fixes import get_apply_fix_status
        return _j(get_apply_fix_status(appid))

    async def cancel_apply_fix(self, appid: int) -> str:
        from fixes import cancel_apply_fix
        return _j(cancel_apply_fix(appid))

    async def unfix_game(self, appid: int, install_path: str = "", fix_date: str = "") -> str:
        from fixes import unfix_game
        return _j(await unfix_game(appid, install_path, fix_date))

    async def get_unfix_status(self, appid: int) -> str:
        from fixes import get_unfix_status
        return _j(get_unfix_status(appid))

    async def get_installed_fixes(self) -> str:
        from fixes import get_installed_fixes
        return _j(get_installed_fixes())

    async def apply_linux_native_fix(self, install_path: str) -> str:
        from fixes import apply_linux_native_fix
        return _j(apply_linux_native_fix(install_path))

    async def compute_fix_launch_options(self, appid: int, install_path: str) -> str:
        from fixes import compute_fix_launch_options
        return _j(compute_fix_launch_options(appid, install_path))

    # ==========================================================================
    # Workshop
    # ==========================================================================

    async def start_workshop_download(self, appid: int, pubfile_id: int, target_library_path: str = "") -> str:
        from workshop import start_workshop_download
        return _j(await start_workshop_download(appid, pubfile_id, target_library_path))

    async def get_workshop_download_status(self) -> str:
        from workshop import get_workshop_download_status
        return _j(get_workshop_download_status())

    async def cancel_workshop_download(self) -> str:
        from workshop import cancel_workshop_download
        return _j(await cancel_workshop_download())

    async def save_workshop_tool_path(self, path: str) -> str:
        from workshop import save_workshop_tool_path
        return _j(save_workshop_tool_path(path))

    # ==========================================================================
    # Repair / Maintenance
    # ==========================================================================

    async def repair_appmanifest(self, appid: int) -> str:
        from downloads import repair_appmanifest
        return _j(await repair_appmanifest(appid))

    async def reconfigure_slssteam(self, appid: int) -> str:
        from slssteam_ops import reconfigure_slssteam
        return _j(await reconfigure_slssteam(appid))

    # ==========================================================================
    # Steamless DRM Removal
    # ==========================================================================

    async def check_steamless_installed(self) -> str:
        from steamless import check_steamless_installed
        return _j(check_steamless_installed())

    async def download_steamless(self) -> str:
        from steamless import download_steamless
        return _j(await download_steamless())

    async def get_steamless_download_status(self) -> str:
        from steamless import get_steamless_download_status
        return _j(get_steamless_download_status())

    async def run_steamless(self, install_path: str) -> str:
        from steamless import run_steamless
        return _j(await run_steamless(install_path))

    async def get_steamless_status(self) -> str:
        from steamless import get_steamless_status
        return _j(get_steamless_status())

    # ==========================================================================
    # Store AppID Detection
    # ==========================================================================

    async def detect_store_appid(self) -> str:
        """Query CEF debug endpoint to detect AppID from open Steam Store or library pages."""
        import re
        try:
            from http_client import get_http_client
            client = await get_http_client()
            resp = await client.get("http://localhost:8080/json", timeout=3)
            if resp.status_code == 200:
                pages = resp.json()
                # Prioritize store pages, then library pages
                patterns = [
                    (r"store\.steampowered\.com/app/(\d+)", "store"),
                    (r"steamloopback\.host/routes/library/app/(\d+)", "library"),
                    (r"/library/app/(\d+)", "library"),
                ]
                for pattern, source in patterns:
                    for page in pages:
                        url = page.get("url", "")
                        m = re.search(pattern, url)
                        if m:
                            appid = int(m.group(1))
                            title = page.get("title", "")
                            return _j({"success": True, "appid": appid, "title": title, "source": source})
            return _j({"success": False, "error": "No store page found"})
        except Exception as exc:
            logger.debug(f"LumaDeck: detect_store_appid error: {exc}")
            return _j({"success": False, "error": str(exc)})

    # ==========================================================================
    # Installer (Dependencies)
    # ==========================================================================

    async def check_dependencies(self) -> str:
        from installer import check_dependencies
        return _j(check_dependencies())

    async def install_dependencies(self) -> str:
        from installer import install_dependencies
        return _j(await install_dependencies())

    async def reinject_installed(self) -> str:
        from installer import reinject_installed
        return _j(await reinject_installed())

    async def apply_component(self, component_id: str, op: str = "repair") -> str:
        """Install/repair/update one component (or 'core'), cascade-safe. Poll
        get_quick_install_status. See the Component model spec in DESIGN_UI.md."""
        from installer import apply_component
        return _j(await apply_component(component_id, op))

    async def run_desktop_handoff_real(self) -> str:
        """Arm a one-shot Desktop autostart (REAL payload: enter-the-wired Steam
        downgrade + lumalinux re-inject) and switch to Desktop. It runs there and
        returns to Game Mode on success; stays in Desktop on failure."""
        from desktop_handoff import run_desktop_handoff_real
        return _j(run_desktop_handoff_real())

    async def run_desktop_handoff_quick_install(self) -> str:
        """Arm a Desktop hand-off that runs the FULL Quick Install (deps + CR +
        lumalinux, incl. the Steam downgrade) in Desktop, then returns to Game
        Mode. For a fresh Deck whose Steam is newer than the headcrab pin, where
        the downgrade can't run in Game Mode."""
        from desktop_handoff import run_desktop_handoff_quick_install
        return _j(run_desktop_handoff_quick_install())

    async def run_desktop_handoff_slscheevo(self) -> str:
        """Arm an interactive Desktop hand-off that opens Konsole running the
        SLScheevo binary for its one-time login, then switch to Desktop. No
        auto-return (the user logs in and switches back manually)."""
        from desktop_handoff import run_desktop_handoff_slscheevo
        return _j(run_desktop_handoff_slscheevo())

    async def disarm_desktop_handoff(self) -> str:
        from desktop_handoff import disarm_desktop_handoff
        return _j(disarm_desktop_handoff())

    async def get_install_status(self) -> str:
        from installer import get_install_status
        return _j(get_install_status())

    async def install_cloudredirect(self) -> str:
        from installer import install_cloudredirect
        return _j(await install_cloudredirect())

    async def get_cr_install_status(self) -> str:
        from installer import get_cr_install_status
        return _j(get_cr_install_status())

    async def install_lumalinux(self) -> str:
        from installer import install_lumalinux
        return _j(await install_lumalinux())

    async def get_ll_install_status(self) -> str:
        from installer import get_ll_install_status
        return _j(get_ll_install_status())

    async def quick_install(self) -> str:
        from installer import quick_install
        return _j(await quick_install())

    async def get_quick_install_status(self) -> str:
        from installer import get_quick_install_status
        return _j(get_quick_install_status())
