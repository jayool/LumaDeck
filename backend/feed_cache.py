"""One rule for the small upstream feeds the status surface reads (SLSsteam's
and lumalinux's updates.yaml, headcrab's target, the release pointers): a
disk copy younger than FEED_TTL is served without going to the network, a
forced refresh (the title-bar Refresh icon, an install decision) always
fetches, and on a failed fetch the copy is used whatever its age.

The release checks (update_checks, 6 h) and Valve's manifest (steam_update_gate,
30 min) keep their own longer TTLs; this module only decides "is this file
fresh enough to skip the fetch?".
"""
import os
import time

FEED_TTL = 15 * 60  # seconds


def fresh(path: str, ttl: float = FEED_TTL) -> bool:
    """True when `path` exists and was written less than `ttl` seconds ago."""
    try:
        return (time.time() - os.stat(path).st_mtime) < ttl
    except OSError:
        return False
