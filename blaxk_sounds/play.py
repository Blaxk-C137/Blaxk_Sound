"""Push-path entry point: play one event's sound, then exit.

Invoked by the git shim as `python3 -m blaxk_sounds.play <event>`. Always exits
0 and never raises. The shim ignores the result, and a sound failure must be
indistinguishable from being muted (spec section 10).
"""

from __future__ import annotations

import os
import sys

from . import config, player


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 1:
            return 0
        if os.environ.get("BLAXK_SOUNDS_DISABLED") == "1":
            return 0

        settings = config.load_settings()
        if not settings.get("enabled", True):
            return 0

        path = (settings.get("sounds") or {}).get(argv[0])
        if not path:
            return 0

        player.play(path)
    except Exception:
        # Deliberately broad: nothing here may reach the caller as a failure.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
