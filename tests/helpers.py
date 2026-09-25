"""Shared test helpers.

Playback is detached by design (spec section 6 rule 5), so a test can never
assume a sound has been recorded by the time the call that requested it
returns. Every log assertion goes through `settle` first.
"""

import time
from pathlib import Path


def read_lines(log: Path) -> list[str]:
    """Non-blank lines currently in the recorder log."""
    try:
        text = log.read_text()
    except FileNotFoundError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def settle(log: Path, timeout: float = 3.0, quiet: float = 0.25) -> None:
    """Block until the log stops changing.

    Waiting for a specific expected marker would race the *other* backgrounded
    sound, and — worse — would let a negative assertion ("no sound was played")
    pass simply because the sound had not landed yet. Waiting for quiescence
    covers a positive and a negative assertion alike.
    """
    deadline = time.monotonic() + timeout
    previous: object = object()
    stable_since: float | None = None
    while time.monotonic() < deadline:
        try:
            current = log.read_text()
        except FileNotFoundError:
            current = ""
        if current == previous:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= quiet:
                return
        else:
            previous = current
            stable_since = None
        time.sleep(0.05)


def wait_until(predicate, timeout: float = 3.0, interval: float = 0.05) -> bool:
    """Poll `predicate` until it is true. Returns whether it became true.

    For conditions that are observable directly (a process dying) rather than
    through the log, waiting on the condition beats waiting on the clock.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
