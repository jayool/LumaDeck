#!/usr/bin/env python3
"""Standalone launcher for the Desktop Quick-Install hand-off.

Decky does NOT run in Desktop mode, so the off-pin onboarding can't use the live
plugin backend there. This script runs the SAME `installer.quick_install()` code
under the system Python, in the Desktop session, where the Steam downgrade is
safe — `gamemode=False` so headcrab keeps its Steam kills (the downgrade needs
them to restart Steam).

It is invoked by the konsole the Desktop hand-off opens. It streams progress to
stdout (so the user sees activity) and writes a full diagnostic to
~/lumadeck-quickinstall.json so a failure is debuggable after the fact.

Exit codes: 0 = success, 1 = a step failed, 2 = the launcher itself crashed
(e.g. an import error if the system Python can't load the backend).
"""

import os
import sys
import json
import asyncio
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)  # so `import installer` (and its siblings) resolve.

_DIAG = os.path.join(os.path.expanduser("~"), "lumadeck-quickinstall.json")


def _dump(info: dict) -> None:
    try:
        with open(_DIAG, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
    except Exception:
        pass


async def _run() -> dict:
    # Imported here (not at top) so an ImportError surfaces in main()'s handler
    # and lands in the diagnostic file instead of a bare traceback.
    from installer import quick_install, get_quick_install_status

    done = asyncio.Event()

    async def _printer():
        last = ""
        while not done.is_set():
            try:
                st = get_quick_install_status()
                # stepIndex is 0-based; show the 1-based current step (1/2, 2/2).
                _tot = st.get("totalSteps") or 2
                _cur = min((st.get("stepIndex") or 0) + 1, _tot)
                line = (
                    f"[{_cur}/{_tot}] "
                    f"{st.get('step', '')}: {st.get('progress', '')}"
                )
                if line != last:
                    print(line, flush=True)
                    last = line
            except Exception:
                pass
            await asyncio.sleep(1)

    printer = asyncio.create_task(_printer())
    try:
        return await quick_install(gamemode=False)
    finally:
        done.set()
        try:
            await printer
        except Exception:
            pass


def main() -> int:
    info = {"launcher": "quick_install_cli", "gamemode": False, "python": sys.executable}
    print("=== LumaDeck Quick Install (Desktop) ===", flush=True)
    try:
        result = asyncio.run(_run())
        info["result"] = result
        _dump(info)
        print(f"\n>>> Result: {result}", flush=True)
        return 0 if isinstance(result, dict) and result.get("success") else 1
    except Exception as exc:
        info["error"] = str(exc)
        info["traceback"] = traceback.format_exc()
        _dump(info)
        print(f"\n!! quick_install_cli crashed: {exc}", flush=True)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
