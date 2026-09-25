"""Extract short, normalized clips from any audio file.

Normalizing here rather than at playback time means every backend on every
platform plays the result with no per-backend volume or format variance
(spec section 7.3).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import config

MAX_CLIP_SECONDS = 10.0
MIN_VOLUME = 0.0
MAX_VOLUME = 2.0


def parse_time(text: str) -> float:
    """Accept SS, MM:SS, or HH:MM:SS. Raise ValueError otherwise."""
    parts = str(text).strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"invalid time {text!r}: expected SS, MM:SS, or HH:MM:SS")
    values = []
    for part in parts:
        try:
            value = float(part)
        except ValueError:
            raise ValueError(f"invalid time {text!r}: {part!r} is not a number") from None
        if value < 0:
            raise ValueError(f"invalid time {text!r}: negative values are not allowed")
        values.append(value)
    seconds = 0.0
    for value in values:
        seconds = seconds * 60 + value
    return seconds


def probe_duration(path: str) -> float:
    """Real duration of an audio file, via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def extract(
    source: str,
    from_s: float,
    length_s: float,
    event: str,
    volume: float = 1.0,
) -> Path:
    """Cut `length_s` seconds from `source` at `from_s` into the event's wav."""
    if event not in config.EVENTS:
        raise ValueError(
            f"unknown event {event!r}: expected one of {', '.join(config.EVENTS)}"
        )
    if not MIN_VOLUME <= volume <= MAX_VOLUME:
        raise ValueError(
            f"volume {volume} out of range: expected {MIN_VOLUME} to {MAX_VOLUME}"
        )
    if length_s <= 0:
        raise ValueError(f"length {length_s} must be greater than zero")
    if length_s > MAX_CLIP_SECONDS:
        raise ValueError(
            f"length {length_s} exceeds the {MAX_CLIP_SECONDS:g}s maximum. "
            "Clips are feedback, not playback."
        )

    duration = probe_duration(source)
    if from_s < 0:
        raise ValueError(f"--from {from_s} is negative")
    if from_s >= duration:
        raise ValueError(
            f"--from {from_s:g}s is past the end of the file, "
            f"which is {duration:.1f}s long"
        )
    if from_s + length_s > duration + 0.05:
        raise ValueError(
            f"--from {from_s:g}s + --len {length_s:g}s runs past the end of the "
            f"file, which is {duration:.1f}s long"
        )

    destination = config.sounds_dir() / f"{event}.wav"
    destination.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-ss", str(from_s), "-t", str(length_s), "-i", str(source),
         "-af", f"volume={volume}",
         "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
         str(destination)],
        check=True,
    )

    settings = config.load_settings()
    settings.setdefault("sounds", {})[event] = str(destination)
    config.save_settings(settings)
    return destination
