"""Settings loading and saving.

`load_settings` never raises. A missing, unreadable, or corrupt config yields
defaults, because this runs inside the push path where a failure must be
indistinguishable from being muted (spec section 10).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

EVENTS: tuple[str, ...] = ("start", "success", "fail")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "blaxk-sounds"


def config_path() -> Path:
    override = os.environ.get("BLAXK_SOUNDS_CONFIG")
    if override:
        return Path(override).expanduser()
    return config_dir() / "settings.json"


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "blaxk-sounds"


def sounds_dir() -> Path:
    return data_dir() / "sounds"


def default_settings() -> dict:
    return {
        "enabled": True,
        "real_git": "/usr/bin/git",
        "sounds": {event: str(sounds_dir() / f"{event}.wav") for event in EVENTS},
    }


def load_settings() -> dict:
    """Return settings, falling back to defaults on any problem at all."""
    defaults = default_settings()
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        return defaults

    if not isinstance(raw, dict):
        return defaults

    settings = dict(defaults)
    settings.update(raw)

    # Merge per event rather than replacing the object wholesale: a config that
    # names one sound must not silently drop the other two, because the next
    # save would then persist that loss.
    sounds = dict(defaults["sounds"])
    if isinstance(raw.get("sounds"), dict):
        sounds.update(raw["sounds"])
    settings["sounds"] = sounds
    return settings


def save_settings(settings: dict) -> bool:
    """Write atomically. Returns False instead of raising."""
    tmp = None
    try:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        # os.replace adopts the temp file's mode, so set it explicitly rather
        # than letting the umask decide.
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        return True
    except Exception:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        return False
