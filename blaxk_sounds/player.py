"""Audio playback.

Playback is best-effort: `play` returns a bool and never raises, so a broken
sound system is indistinguishable from a muted one (spec section 6 rule 3).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path

DEVNULL = subprocess.DEVNULL


def backend_candidates() -> list[tuple[str, list[str]]]:
    """Audio backends in priority order, each with its argv prefix.

    pw-play is first because Fedora 44 is PipeWire and paplay is not installed
    there. paplay stays at position 2 for PulseAudio systems (spec section 7.2).
    canberra-gtk-play is deliberately absent: it takes sound names, not paths.
    """
    return [
        ("pw-play", ["pw-play"]),
        ("paplay", ["paplay"]),
        ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]),
        ("aplay", ["aplay", "-q"]),
    ]


def detect_backend() -> tuple[str, list[str]] | None:
    """First backend resolvable on PATH, or None if there is none."""
    for name, prefix in backend_candidates():
        if shutil.which(name):
            return name, prefix
    return None
