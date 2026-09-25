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


def pidfile() -> Path:
    """Where the currently-playing sound records its pid.

    XDG_RUNTIME_DIR is tmpfs and cleared at logout, so the file needs no
    cleanup of its own (spec section 6 rule 6).
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isdir(runtime):
        return Path(runtime) / "blaxk-sounds.pid"
    return Path(f"/tmp/blaxk-sounds-{os.getuid()}.pid")


def build_command(path: str) -> list[str] | None:
    """Full argv to play `path`, or None if nothing can play it."""
    override = os.environ.get("BLAXK_SOUNDS_PLAYER")
    if override:
        return [override, path]
    found = detect_backend()
    if found is None:
        return None
    return found[1] + [path]


def _player_tokens() -> tuple[str, ...]:
    """Strings that identify a process as one of ours."""
    names = [name for name, _ in backend_candidates()]
    override = os.environ.get("BLAXK_SOUNDS_PLAYER")
    if override:
        names.append(os.path.basename(override))
    return tuple(names)


def _kill_previous() -> None:
    """Stop a sound still playing from an earlier push.

    The pid is only signalled if its command line still looks like our player,
    so a recycled pid belonging to something else is left alone.
    """
    try:
        pid = int(pidfile().read_text().strip())
    except Exception:
        return
    if pid <= 0 or pid == os.getpid():
        return
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
    except Exception:
        return
    if not any(token in cmdline for token in _player_tokens()):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def play(path: str) -> bool:
    """Play `path` detached from this process. Never raises."""
    try:
        if not path or not os.path.isfile(path):
            return False
        command = build_command(path)
        if command is None:
            return False
        _kill_previous()
        process = subprocess.Popen(
            command,
            stdin=DEVNULL,
            stdout=DEVNULL,
            stderr=DEVNULL,
            start_new_session=True,
        )
        try:
            pidfile().write_text(str(process.pid))
        except Exception:
            pass
        return True
    except Exception:
        return False
