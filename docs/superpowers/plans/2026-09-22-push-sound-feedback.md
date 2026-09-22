# Push Sound Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play a start, success, and fail sound around `git push` on Fedora Linux, via a `PATH` shim, with no daemon and no root.

**Architecture:** A generated bash shim at `~/.local/bin/git` detects whether the invocation is a push, and if so plays sounds while running real git itself. A Python package provides sound playback, clip extraction, configuration, and diagnostics; it never sits between git and its exit code.

**Tech Stack:** Bash 5, Python 3.14 (stdlib only — no third-party runtime dependencies), pytest 9 for tests, ffmpeg 8 for clip extraction.

**Spec:** `docs/superpowers/specs/2026-09-22-push-sound-feedback-design.md`

## Global Constraints

- **No `sudo`, ever.** Install writes only under `~/.local` and `~/.config`.
- **No third-party runtime dependencies.** Python stdlib only. `pytest` is a dev dependency.
- **A sound failure must never affect git.** `player.play()` returns a bool and never raises; `play.main()` always returns 0. (Spec §6, §10)
- **The shim must never use `set -e`.** `"$REAL_GIT" "$@"` legitimately exits non-zero, and `set -e` would abort before the exit code is captured. (Spec §6 rule 2)
- **Never capture stdio in the push path.** No `capture_output`, no command substitution around the git invocation. (Spec §6 rule 1)
- **Exit code is git's, untouched** — including 128, 129, 130. (Spec §6 rule 2)
- **No `Co-Authored-By`, no "Generated with" lines in any commit.** Commits are attributed to the user only.
- **Commits are frequent** — one per task, at minimum.
- **Sound files are normalized to 44.1 kHz, mono, 16-bit PCM.** (Spec §7.3)
- **Config paths are stored expanded and absolute**, never containing `~`. (Spec §9)

## File Structure

| File | Responsibility |
|---|---|
| `blaxk_sounds/__init__.py` | Package marker, `__version__` |
| `blaxk_sounds/config.py` | XDG path resolution, settings load/save. Never raises on load |
| `blaxk_sounds/player.py` | Backend probe, detached playback, pidfile takeover |
| `blaxk_sounds/play.py` | Push-path entry point. One event, always exit 0 |
| `blaxk_sounds/clip.py` | Time parsing, ffprobe duration, ffmpeg extraction |
| `blaxk_sounds/doctor.py` | Ten independent chain checks |
| `blaxk_sounds/cli.py` | User-facing subcommands |
| `shim/git.sh.template` | The shim. Two placeholders: `__REAL_GIT__`, `__INSTALL_DIR__` |
| `install/install.sh` | No-sudo installer, renders shim, synthesizes tones |
| `tests/` | pytest suite, plus stub scripts under `tests/stubs/` |
| `pyproject.toml` | pytest configuration only; the package is not pip-installed |

---

### Task 1: Package skeleton and config module

**Files:**
- Create: `pyproject.toml`, `blaxk_sounds/__init__.py`, `blaxk_sounds/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `config.EVENTS: tuple[str, ...]`; `config.config_path() -> Path`; `config.data_dir() -> Path`; `config.sounds_dir() -> Path`; `config.default_settings() -> dict`; `config.load_settings() -> dict`; `config.save_settings(dict) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import json
from pathlib import Path

import pytest

from blaxk_sounds import config


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point every path at tmp_path so tests never touch the real config."""
    monkeypatch.setenv("BLAXK_SOUNDS_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


def test_load_missing_config_returns_defaults():
    settings = config.load_settings()
    assert settings["enabled"] is True
    assert set(settings["sounds"]) == {"start", "success", "fail"}


def test_default_sound_paths_are_absolute_and_have_no_tilde(tmp_path):
    settings = config.default_settings()
    for path in settings["sounds"].values():
        assert path.startswith("/")
        assert "~" not in path


def test_round_trip(tmp_path):
    settings = config.default_settings()
    settings["enabled"] = False
    settings["sounds"]["fail"] = "/tmp/custom.wav"
    assert config.save_settings(settings) is True

    assert config.load_settings()["enabled"] is False
    assert config.load_settings()["sounds"]["fail"] == "/tmp/custom.wav"


def test_corrupt_json_returns_defaults():
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text("{not json at all")
    assert config.load_settings()["enabled"] is True


def test_non_dict_json_returns_defaults():
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text('["a", "list"]')
    assert config.load_settings()["enabled"] is True


def test_partial_config_is_merged_with_defaults():
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"enabled": False}))
    settings = config.load_settings()
    assert settings["enabled"] is False
    assert set(settings["sounds"]) == {"start", "success", "fail"}


def test_non_dict_sounds_is_replaced():
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"sounds": "nonsense"}))
    assert set(config.load_settings()["sounds"]) == {"start", "success", "fail"}


def test_save_returns_false_rather_than_raising(tmp_path):
    monkeypatch_target = tmp_path / "a-file-not-a-dir"
    monkeypatch_target.write_text("x")
    import os

    os.environ["BLAXK_SOUNDS_CONFIG"] = str(monkeypatch_target / "settings.json")
    assert config.save_settings(config.default_settings()) is False


def test_sounds_dir_follows_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config.sounds_dir() == tmp_path / "xdg" / "blaxk-sounds" / "sounds"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'blaxk_sounds'`

- [ ] **Step 3: Write the implementation**

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

```python
# blaxk_sounds/__init__.py
"""Sound feedback for git push."""

__version__ = "1.0.0"
```

```python
# blaxk_sounds/config.py
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
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        return default_settings()

    if not isinstance(raw, dict):
        return default_settings()

    settings = default_settings()
    settings.update(raw)
    if not isinstance(settings.get("sounds"), dict):
        settings["sounds"] = default_settings()["sounds"]
    return settings


def save_settings(settings: dict) -> bool:
    """Write atomically. Returns False instead of raising."""
    try:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml blaxk_sounds/__init__.py blaxk_sounds/config.py tests/test_config.py
git commit -m "Add config module with XDG paths and fault-tolerant loading"
```

---

### Task 2: Audio backend detection

**Files:**
- Create: `blaxk_sounds/player.py`
- Test: `tests/test_player_detect.py`

**Interfaces:**
- Consumes: nothing
- Produces: `player.backend_candidates() -> list[tuple[str, list[str]]]`; `player.detect_backend() -> tuple[str, list[str]] | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_player_detect.py
import pytest

from blaxk_sounds import player


def test_probe_order_is_pw_play_then_paplay_then_ffplay_then_aplay():
    names = [name for name, _ in player.backend_candidates()]
    assert names == ["pw-play", "paplay", "ffplay", "aplay"]


def test_detects_pw_play_first(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("pw-play", "aplay"):
        (bindir / name).write_text("#!/bin/sh\n")
        (bindir / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert player.detect_backend()[0] == "pw-play"


def test_falls_through_to_aplay_when_others_absent(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aplay").write_text("#!/bin/sh\n")
    (bindir / "aplay").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert player.detect_backend()[0] == "aplay"


def test_returns_none_when_nothing_available(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert player.detect_backend() is None


def test_argv_prefix_matches_backend(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ffplay").write_text("#!/bin/sh\n")
    (bindir / "ffplay").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    name, prefix = player.detect_backend()
    assert name == "ffplay"
    assert prefix == ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_player_detect.py -v`
Expected: FAIL — `ImportError: cannot import name 'player'`

- [ ] **Step 3: Write the implementation**

Create `blaxk_sounds/player.py` containing only the detection half for now. The playback half arrives in Task 3.

```python
# blaxk_sounds/player.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_player_detect.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add blaxk_sounds/player.py tests/test_player_detect.py
git commit -m "Add audio backend detection with PipeWire-first probe order"
```

---

### Task 3: Detached playback and pidfile takeover

**Files:**
- Modify: `blaxk_sounds/player.py`
- Create: `tests/stubs/recorder.sh`, `tests/stubs/sleeper.sh`
- Test: `tests/test_player_play.py`

**Interfaces:**
- Consumes: `player.backend_candidates()`, `player.detect_backend()` from Task 2
- Produces: `player.build_command(path: str) -> list[str] | None`; `player.play(path: str) -> bool`; `player.pidfile() -> Path`

- [ ] **Step 1: Write the failing test**

```bash
# tests/stubs/recorder.sh
#!/usr/bin/env bash
# Stands in for an audio backend. Records what it was asked to play.
printf '%s\n' "$*" >> "${RECORDER_LOG:?RECORDER_LOG must be set}"
```

```bash
# tests/stubs/sleeper.sh
#!/usr/bin/env bash
# Stands in for a long sound, so takeover behaviour can be observed.
printf '%s\n' "$$" >> "${RECORDER_LOG:?RECORDER_LOG must be set}"
sleep "${SLEEPER_SECONDS:-30}"
```

```python
# tests/test_player_play.py
import os
import subprocess
import time
from pathlib import Path

import pytest

from blaxk_sounds import player

STUBS = Path(__file__).parent / "stubs"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    monkeypatch.setenv("RECORDER_LOG", str(tmp_path / "recorder.log"))
    monkeypatch.setenv("BLAXK_SOUNDS_PLAYER", str(STUBS / "recorder.sh"))
    (STUBS / "recorder.sh").chmod(0o755)
    monkeypatch.delenv("BLAXK_SOUNDS_DISABLED", raising=False)


def recorder_lines(tmp_path):
    log = tmp_path / "recorder.log"
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line.strip()]


def test_play_records_the_path(tmp_path):
    sound = tmp_path / "a.wav"
    sound.write_bytes(b"x")
    assert player.play(str(sound)) is True
    time.sleep(0.3)
    assert recorder_lines(tmp_path) == [str(sound)]


def test_play_returns_false_for_missing_file(tmp_path):
    assert player.play(str(tmp_path / "nope.wav")) is False
    time.sleep(0.2)
    assert recorder_lines(tmp_path) == []


def test_play_returns_false_for_directory(tmp_path):
    assert player.play(str(tmp_path)) is False


def test_play_returns_false_for_none(tmp_path):
    """Must not raise on nonsense input."""
    assert player.play(None) is False


def test_play_returns_false_when_no_backend(tmp_path, monkeypatch):
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("BLAXK_SOUNDS_PLAYER", raising=False)
    sound = tmp_path / "a.wav"
    sound.write_bytes(b"x")
    assert player.play(str(sound)) is False


def test_build_command_honours_player_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BLAXK_SOUNDS_PLAYER", "/custom/player")
    assert player.build_command("/x.wav") == ["/custom/player", "/x.wav"]


def test_build_command_returns_none_without_backend(tmp_path, monkeypatch):
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("BLAXK_SOUNDS_PLAYER", raising=False)
    assert player.build_command("/x.wav") is None


def test_new_sound_kills_the_previous_one(tmp_path, monkeypatch):
    monkeypatch.setenv("BLAXK_SOUNDS_PLAYER", str(STUBS / "sleeper.sh"))
    (STUBS / "sleeper.sh").chmod(0o755)
    monkeypatch.setenv("SLEEPER_SECONDS", "30")

    sound = tmp_path / "a.wav"
    sound.write_bytes(b"x")

    assert player.play(str(sound)) is True
    time.sleep(0.4)
    first_pid = int(recorder_lines(tmp_path)[0])
    assert _alive(first_pid)

    assert player.play(str(sound)) is True
    time.sleep(0.4)
    assert not _alive(first_pid), "previous sound should have been killed"
    player.pidfile().unlink(missing_ok=True)


def test_stale_pidfile_pointing_at_unrelated_process_is_not_killed(tmp_path):
    # A real unrelated process, distinct from ours, so the cmdline check is
    # what protects it - not the pid == os.getpid() guard.
    victim = subprocess.Popen(["sleep", "30"])
    try:
        player.pidfile().write_text(str(victim.pid))
        sound = tmp_path / "a.wav"
        sound.write_bytes(b"x")
        player.play(str(sound))
        time.sleep(0.3)
        assert victim.poll() is None, "must not kill a pid that is not our player"
    finally:
        victim.kill()
        victim.wait()


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_player_play.py -v`
Expected: FAIL — `AttributeError: module 'blaxk_sounds.player' has no attribute 'play'`

- [ ] **Step 3: Write the implementation**

Append to `blaxk_sounds/player.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_player_play.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add blaxk_sounds/player.py tests/test_player_play.py tests/stubs/
git commit -m "Add detached playback with pidfile takeover of the previous sound"
```

---

### Task 4: Push-path entry point

**Files:**
- Create: `blaxk_sounds/play.py`
- Test: `tests/test_play.py`

**Interfaces:**
- Consumes: `config.load_settings()` (Task 1), `player.play()` (Task 3)
- Produces: `play.main(argv: list[str]) -> int` — always returns 0

- [ ] **Step 1: Write the failing test**

```python
# tests/test_play.py
import json
import time
from pathlib import Path

import pytest

from blaxk_sounds import config, play

STUBS = Path(__file__).parent / "stubs"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    monkeypatch.setenv("RECORDER_LOG", str(tmp_path / "recorder.log"))
    monkeypatch.setenv("BLAXK_SOUNDS_PLAYER", str(STUBS / "recorder.sh"))
    monkeypatch.setenv("BLAXK_SOUNDS_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("BLAXK_SOUNDS_DISABLED", raising=False)
    (STUBS / "recorder.sh").chmod(0o755)


def write_config(tmp_path, **overrides):
    settings = config.default_settings()
    for event in config.EVENTS:
        sound = tmp_path / f"{event}.wav"
        sound.write_bytes(b"x")
        settings["sounds"][event] = str(sound)
    settings.update(overrides)
    config.save_settings(settings)
    return settings


def records(tmp_path):
    log = tmp_path / "recorder.log"
    return [line for line in log.read_text().splitlines() if line] if log.exists() else []


def test_plays_the_requested_event(tmp_path):
    settings = write_config(tmp_path)
    assert play.main(["success"]) == 0
    time.sleep(0.3)
    assert records(tmp_path) == [settings["sounds"]["success"]]


def test_disabled_setting_plays_nothing(tmp_path):
    write_config(tmp_path, enabled=False)
    assert play.main(["success"]) == 0
    time.sleep(0.3)
    assert records(tmp_path) == []


def test_disabled_env_var_plays_nothing(tmp_path, monkeypatch):
    write_config(tmp_path)
    monkeypatch.setenv("BLAXK_SOUNDS_DISABLED", "1")
    assert play.main(["success"]) == 0
    time.sleep(0.3)
    assert records(tmp_path) == []


def test_unknown_event_plays_nothing(tmp_path):
    write_config(tmp_path)
    assert play.main(["banana"]) == 0
    time.sleep(0.3)
    assert records(tmp_path) == []


def test_wrong_argument_count_plays_nothing(tmp_path):
    write_config(tmp_path)
    assert play.main([]) == 0
    assert play.main(["a", "b"]) == 0
    time.sleep(0.3)
    assert records(tmp_path) == []


def test_corrupt_config_still_returns_zero(tmp_path):
    config.config_path().write_text("{{{ not json")
    assert play.main(["success"]) == 0


def test_missing_sound_file_still_returns_zero(tmp_path):
    settings = config.default_settings()
    config.save_settings(settings)  # points at files that do not exist
    assert play.main(["success"]) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_play.py -v`
Expected: FAIL — `ImportError: cannot import name 'play'`

- [ ] **Step 3: Write the implementation**

```python
# blaxk_sounds/play.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_play.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add blaxk_sounds/play.py tests/test_play.py
git commit -m "Add push-path entry point that never fails the caller"
```

---

### Task 5: The shim and subcommand detection

**Files:**
- Create: `shim/git.sh.template`
- Test: `tests/test_shim.py`

**Interfaces:**
- Consumes: `blaxk_sounds.play` as a module invocable by `python3 -m blaxk_sounds.play` (Task 4)
- Produces: the shim template, with `__REAL_GIT__` and `__INSTALL_DIR__` placeholders

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shim.py
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "shim" / "git.sh.template"

STUB_GIT = """#!/usr/bin/env bash
printf 'GIT:%s\\n' "$*" >> "$LOG"
exit "${STUB_GIT_RC:-0}"
"""

STUB_PYTHON = """#!/usr/bin/env bash
printf 'PLAY:%s\\n' "$*" >> "$LOG"
exit 0
"""


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()

    real_git = tmp_path / "realgit"
    real_git.write_text(STUB_GIT)
    real_git.chmod(0o755)

    (bindir / "python3").write_text(STUB_PYTHON)
    (bindir / "python3").chmod(0o755)

    shim = tmp_path / "git"
    shim.write_text(
        TEMPLATE.read_text()
        .replace("__REAL_GIT__", str(real_git))
        .replace("__INSTALL_DIR__", str(tmp_path))
    )
    shim.chmod(0o755)

    log = tmp_path / "log"
    log.write_text("")

    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.setenv("LOG", str(log))
    return {"shim": shim, "log": log, "tmp": tmp_path}


def run(sandbox, *args, env=None):
    result = subprocess.run(
        [str(sandbox["shim"]), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    # The start sound is backgrounded, so give it a moment to land in the log.
    for _ in range(30):
        time.sleep(0.05)
        if "PLAY:" in sandbox["log"].read_text() or not args:
            break
        if args and args[0] not in ("push",):
            break
    return result


def lines(sandbox):
    return [line for line in sandbox["log"].read_text().splitlines() if line]


@pytest.mark.parametrize(
    "args",
    [
        ["push", "origin", "main"],
        ["-C", "/some/path", "push"],
        ["-C/some/path", "push"],
        ["-c", "core.pager=cat", "push"],
        ["-ccore.pager=cat", "push"],
        ["--git-dir=/x/.git", "push"],
        ["--work-tree", "/x", "push"],
        ["-p", "push"],
        ["--no-pager", "push"],
    ],
)
def test_push_is_detected(sandbox, args):
    run(sandbox, *args)
    recorded = lines(sandbox)
    assert any(line.startswith("PLAY:-m blaxk_sounds.play start") for line in recorded)
    assert "GIT:" + " ".join(args) in recorded


@pytest.mark.parametrize(
    "args",
    [
        ["branch", "push"],
        ["log", "push", "--oneline"],
        ["checkout", "push"],
        ["--version"],
        [],
        ["status"],
        ["-C", "/some/path", "status"],
    ],
)
def test_non_push_does_not_play(sandbox, args):
    run(sandbox, *args)
    recorded = lines(sandbox)
    assert not any(line.startswith("PLAY:") for line in recorded)
    assert "GIT:" + " ".join(args) in recorded


def test_non_push_replaces_the_process(sandbox):
    """exec means the shim's own pid is gone; the stub is what ran."""
    result = run(sandbox, "status")
    assert result.returncode == 0


def test_success_plays_success_event(sandbox):
    run(sandbox, "push", env={"STUB_GIT_RC": "0"})
    recorded = lines(sandbox)
    assert any(line.endswith("blaxk_sounds.play success") for line in recorded)


def test_failure_plays_fail_event(sandbox):
    run(sandbox, "push", env={"STUB_GIT_RC": "1"})
    recorded = lines(sandbox)
    assert any(line.endswith("blaxk_sounds.play fail") for line in recorded)


def test_exit_code_is_passed_through(sandbox):
    assert run(sandbox, "push", env={"STUB_GIT_RC": "0"}).returncode == 0
    assert run(sandbox, "push", env={"STUB_GIT_RC": "7"}).returncode == 7
    assert run(sandbox, "push", env={"STUB_GIT_RC": "128"}).returncode == 128


def test_interrupt_exit_130_plays_nothing(sandbox):
    run(sandbox, "push", env={"STUB_GIT_RC": "130"})
    recorded = lines(sandbox)
    assert any(line.startswith("PLAY:-m blaxk_sounds.play start") for line in recorded)
    assert not any(
        line.endswith(("blaxk_sounds.play success", "blaxk_sounds.play fail"))
        for line in recorded
    )


def test_git_output_reaches_stdout(sandbox):
    (sandbox["tmp"] / "realgit").write_text(
        '#!/usr/bin/env bash\necho "hello from git"\nexit 0\n'
    )
    (sandbox["tmp"] / "realgit").chmod(0o755)
    result = run(sandbox, "status")
    assert "hello from git" in result.stdout


def test_shim_does_not_set_errexit(sandbox):
    """set -e would abort before the exit code is captured."""
    text = sandbox["shim"].read_text()
    assert "set -e" not in text
    assert "set -eu" not in text


def test_start_sound_precedes_a_slow_git(sandbox):
    """Spec 11.3: the start sound is backgrounded, so ordering is only
    observable when git is slow. A fast git would make this a race."""
    slow = sandbox["tmp"] / "realgit"
    slow.write_text(
        "#!/usr/bin/env bash\n"
        "sleep 1\n"
        'printf \'GIT-DONE\\n\' >> "$LOG"\n'
        "exit 0\n"
    )
    slow.chmod(0o755)

    subprocess.run(
        [str(sandbox["shim"]), "push"],
        capture_output=True,
        text=True,
        env=os.environ,
    )
    time.sleep(0.5)

    recorded = lines(sandbox)
    assert "GIT-DONE" in recorded, "the stub git never ran"
    start_index = next(
        i for i, l in enumerate(recorded) if l.startswith("PLAY:-m blaxk_sounds.play start")
    )
    assert start_index < recorded.index("GIT-DONE"), (
        "start sound must be recorded before git finishes"
    )


def test_git_receives_all_of_stdin(sandbox):
    """A backgrounded player that inherited stdin would eat bytes meant for git."""
    reader = sandbox["tmp"] / "realgit"
    reader.write_text(
        "#!/usr/bin/env bash\n"
        'cat > "$LOG.stdin"\n'
        'printf \'GIT-DONE\\n\' >> "$LOG"\n'
        "exit 0\n"
    )
    reader.chmod(0o755)

    payload = "line one\nline two\n"
    subprocess.run(
        [str(sandbox["shim"]), "push"],
        input=payload,
        text=True,
        capture_output=True,
        env=os.environ,
    )
    time.sleep(0.3)
    assert (sandbox["tmp"] / "log.stdin").read_text() == payload
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_shim.py -v`
Expected: FAIL — `FileNotFoundError: shim/git.sh.template`

- [ ] **Step 3: Write the implementation**

```bash
#!/usr/bin/env bash
# blaxk-sounds git shim.
#
# GENERATED FILE - do not edit by hand. Re-run install/install.sh instead.
# The two values below are substituted at install time.
#
# Deliberately NO `set -e`: "$REAL_GIT" "$@" exits non-zero on a failed push,
# and errexit would abort before the exit code is captured.
#
# Deliberately NO captured output: stdin, stdout and stderr must pass straight
# through, or a credential prompt would hang.

REAL_GIT="__REAL_GIT__"
INSTALL_DIR="__INSTALL_DIR__"

find_subcommand() {
    local skip_next=0 arg
    for arg in "$@"; do
        if [ "$skip_next" = 1 ]; then skip_next=0; continue; fi
        case "$arg" in
            -C|-c|--git-dir|--work-tree|--namespace|--exec-path|--config-env)
                skip_next=1 ;;
            -C?*|-c?*)
                ;;                                  # value attached to the option
            -*)
                ;;                                  # any other option, takes no value
            *)
                printf '%s' "$arg"
                return 0 ;;
        esac
    done
    return 1
}

subcommand="$(find_subcommand "$@")"

if [ "$subcommand" != "push" ]; then
    exec "$REAL_GIT" "$@"
fi

# PYTHONPATH is set per-invocation rather than exported, so it never leaks into
# git's environment and from there into your hooks.
PLAYER_PYTHONPATH="$INSTALL_DIR${PYTHONPATH:+:$PYTHONPATH}"

PYTHONPATH="$PLAYER_PYTHONPATH" python3 -m blaxk_sounds.play start >/dev/null 2>&1 &

"$REAL_GIT" "$@"
rc=$?

if [ "$rc" -ne 130 ]; then
    if [ "$rc" -eq 0 ]; then
        event=success
    else
        event=fail
    fi
    PYTHONPATH="$PLAYER_PYTHONPATH" python3 -m blaxk_sounds.play "$event" >/dev/null 2>&1 &
fi

exit "$rc"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_shim.py -v`
Expected: PASS, 25 tests (9 push rows, 7 non-push rows, plus 9 individual tests)

- [ ] **Step 5: Commit**

```bash
git add shim/git.sh.template tests/test_shim.py
git commit -m "Add git shim with correct subcommand detection

Detects the subcommand as the first bare word after global options, so
commands like 'git branch push' no longer fire push sounds. Runs git
directly rather than through Python, so a broken interpreter yields
silence instead of a git that will not run."
```

---

### Task 6: End-to-end push against a real repository

**Files:**
- Test: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5
- Produces: nothing new — this task only adds a test

- [ ] **Step 1: Write the failing test**

```python
# tests/test_end_to_end.py
"""Real git, real exit codes, real non-fast-forward rejection. No network."""

import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "shim" / "git.sh.template"
STUBS = Path(__file__).parent / "stubs"


def git(*args, cwd, check=True):
    return subprocess.run(
        ["/usr/bin/git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


@pytest.fixture
def workspace(tmp_path):
    """A working repo with a bare remote, plus a rendered shim wired to npm."""
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    settings_path = tmp_path / "settings.json"

    import json

    sounds_map = {}
    for event in ("start", "success", "fail"):
        wav = sounds / f"{event}.wav"
        wav.write_bytes(b"RIFF____WAVE")
        sounds_map[event] = str(wav)

    settings_path.write_text(
        json.dumps(
            {"enabled": True, "real_git": "/usr/bin/git", "sounds": sounds_map}
        )
    )

    recorder = STUBS / "recorder.sh"
    recorder.chmod(0o755)
    log = tmp_path / "recorder.log"

    shim = tmp_path / "git"
    shim.write_text(
        TEMPLATE.read_text()
        .replace("__REAL_GIT__", "/usr/bin/git")
        .replace("__INSTALL_DIR__", str(REPO_ROOT))
    )
    shim.chmod(0o755)

    remote = tmp_path / "remote.git"
    git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    work = tmp_path / "work"
    work.mkdir()
    git("init", "-b", "main", str(work), cwd=tmp_path)
    git("config", "user.email", "test@example.invalid", cwd=work)
    git("config", "user.name", "Test", cwd=work)
    git("remote", "add", "origin", str(remote), cwd=work)
    (work / "file.txt").write_text("hello\n")
    git("add", "file.txt", cwd=work)
    git("commit", "-m", "first", cwd=work)

    env = {
        **os.environ,
        "BLAXK_SOUNDS_PLAYER": str(recorder),
        "BLAXK_SOUNDS_CONFIG": str(settings_path),
        "RECORDER_LOG": str(log),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
    }
    (tmp_path / "run").mkdir(exist_ok=True)

    return {"shim": shim, "work": work, "env": env, "log": log, "sounds": sounds_map}


def push(workspace, *args):
    result = subprocess.run(
        [str(workspace["shim"]), "push", *args],
        cwd=workspace["work"],
        capture_output=True,
        text=True,
        env=workspace["env"],
    )
    time.sleep(0.5)  # let the backgrounded result sound land
    return result


def played(workspace):
    log = workspace["log"]
    return [line for line in log.read_text().splitlines() if line] if log.exists() else []


def test_successful_push_plays_start_then_success(workspace):
    result = push(workspace, "-u", "origin", "main")
    assert result.returncode == 0, result.stderr
    assert played(workspace) == [
        workspace["sounds"]["start"],
        workspace["sounds"]["success"],
    ]


def test_rejected_push_plays_fail(workspace):
    assert push(workspace, "-u", "origin", "main").returncode == 0
    workspace["log"].unlink()

    # Rewrite history so the second push is a non-fast-forward.
    (workspace["work"] / "file.txt").write_text("rewritten\n")
    git("add", "file.txt", cwd=workspace["work"])
    git("commit", "--amend", "-m", "amended", cwd=workspace["work"])

    result = push(workspace, "origin", "main")
    assert result.returncode != 0
    assert played(workspace)[-1] == workspace["sounds"]["fail"]


def test_git_output_is_not_swallowed(workspace):
    result = push(workspace, "-u", "origin", "main")
    assert "main" in result.stderr or "main" in result.stdout


def test_push_to_up_to_date_remote_still_sounds(workspace):
    assert push(workspace, "-u", "origin", "main").returncode == 0
    workspace["log"].unlink()
    result = push(workspace, "origin", "main")  # everything up-to-date, exit 0
    assert result.returncode == 0
    assert played(workspace)[-1] == workspace["sounds"]["success"]


def test_broken_player_does_not_affect_the_push(workspace):
    workspace["env"]["BLAXK_SOUNDS_PLAYER"] = "/nonexistent/player"
    result = push(workspace, "-u", "origin", "main")
    assert result.returncode == 0


def test_missing_sound_files_do_not_affect_the_push(workspace, tmp_path):
    for wav in workspace["sounds"].values():
        Path(wav).unlink()
    result = push(workspace, "-u", "origin", "main")
    assert result.returncode == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_end_to_end.py -v`
Expected: The first tests may pass already if Tasks 1–5 are correct — that is the point of this task. If `test_successful_push_plays_start_then_success` fails, the integration between shim and package is broken; fix before continuing.

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest -v`
Expected: PASS. All previous tests still green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_end_to_end.py
git commit -m "Add end-to-end push tests against a local bare repository"
```

---

### Task 7: Clip extraction

**Files:**
- Create: `blaxk_sounds/clip.py`
- Test: `tests/test_clip.py`

**Interfaces:**
- Consumes: `config.sounds_dir()`, `config.load_settings()`, `config.save_settings()`, `config.EVENTS` (Task 1)
- Produces: `clip.MAX_CLIP_SECONDS: float`; `clip.parse_time(str) -> float`; `clip.probe_duration(str) -> float`; `clip.extract(source, from_s, length_s, event, volume=1.0) -> Path`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clip.py
import subprocess
from pathlib import Path

import pytest

from blaxk_sounds import clip, config


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLAXK_SOUNDS_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


@pytest.fixture
def tone(tmp_path):
    """A 3-second 440Hz mono tone, courtesy of ffmpeg itself."""
    path = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", "-y", str(path)],
        check=True,
    )
    return path


@pytest.mark.parametrize(
    "text,expected",
    [("5", 5.0), ("1:30", 90.0), ("0:07.5", 7.5), ("1:02:03", 3723.0)],
)
def test_parse_time(text, expected):
    assert clip.parse_time(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "abc", "1:2:3:4", "-5", "1:-2"])
def test_parse_time_rejects_bad_input(text):
    with pytest.raises(ValueError):
        clip.parse_time(text)


def test_probe_duration_reads_the_real_length(tone):
    assert clip.probe_duration(str(tone)) == pytest.approx(3.0, abs=0.1)


def test_extract_writes_a_normalized_wav(tone):
    out = clip.extract(str(tone), from_s=0.5, length_s=1.0, event="success")
    assert out.exists()
    assert out == config.sounds_dir() / "success.wav"

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,sample_rate,channels", "-of", "default=nw=1", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "codec_name=pcm_s16le" in probe
    assert "sample_rate=44100" in probe
    assert "channels=1" in probe
    assert clip.probe_duration(str(out)) == pytest.approx(1.0, abs=0.15)


def test_extract_updates_the_config(tone):
    clip.extract(str(tone), from_s=0.0, length_s=0.5, event="fail")
    assert config.load_settings()["sounds"]["fail"] == str(
        config.sounds_dir() / "fail.wav"
    )


def test_extract_rejects_clips_over_the_limit(tone):
    with pytest.raises(ValueError, match="10"):
        clip.extract(str(tone), from_s=0.0, length_s=11.0, event="start")


def test_extract_rejects_start_past_the_end(tone):
    with pytest.raises(ValueError, match="3.0"):
        clip.extract(str(tone), from_s=5.0, length_s=1.0, event="start")


def test_extract_rejects_length_running_past_the_end(tone):
    with pytest.raises(ValueError, match="3.0"):
        clip.extract(str(tone), from_s=2.5, length_s=2.0, event="start")


def test_extract_does_not_modify_the_source(tone):
    before = tone.stat().st_size
    clip.extract(str(tone), from_s=0.0, length_s=0.5, event="start")
    assert tone.stat().st_size == before


@pytest.mark.parametrize("volume", [0.0, 0.5, 1.0, 2.0])
def test_extract_accepts_valid_volume(tone, volume):
    assert clip.extract(
        str(tone), from_s=0.0, length_s=0.5, event="start", volume=volume
    ).exists()


@pytest.mark.parametrize("volume", [-0.1, 2.1])
def test_extract_rejects_invalid_volume(tone, volume):
    with pytest.raises(ValueError):
        clip.extract(str(tone), from_s=0.0, length_s=0.5, event="start", volume=volume)


def test_extract_rejects_unknown_event(tone):
    with pytest.raises(ValueError, match="event"):
        clip.extract(str(tone), from_s=0.0, length_s=0.5, event="banana")


@pytest.mark.parametrize(
    "text,expected",
    [("0.5", "0.5"), ("0:02", "2.0"), ("0:00:01", "1.0")],
)
def test_extract_passes_parsed_seconds_to_ffmpeg(tone, monkeypatch, text, expected):
    """Spec 11.3: ffmpeg argv correct for each --from format."""
    captured = {}
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "ffmpeg":
            captured["cmd"] = list(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, *args, **kwargs)  # ffprobe must stay real

    monkeypatch.setattr(clip.subprocess, "run", fake_run)
    clip.extract(
        str(tone), from_s=clip.parse_time(text), length_s=0.5, event="start"
    )

    cmd = captured["cmd"]
    assert cmd[cmd.index("-ss") + 1] == expected
    assert cmd[cmd.index("-t") + 1] == "0.5"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-ar") + 1] == "44100"
    assert cmd[cmd.index("-c:a") + 1] == "pcm_s16le"
    assert cmd[-1].endswith("start.wav")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_clip.py -v`
Expected: FAIL — `ImportError: cannot import name 'clip'`

- [ ] **Step 3: Write the implementation**

```python
# blaxk_sounds/clip.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_clip.py -v`
Expected: PASS, 27 tests

- [ ] **Step 5: Commit**

```bash
git add blaxk_sounds/clip.py tests/test_clip.py
git commit -m "Add clip extraction normalizing to mono 44.1kHz 16-bit PCM"
```

---

### Task 8: The doctor

**Files:**
- Create: `blaxk_sounds/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `config` (Task 1), `player.detect_backend()` (Task 2)
- Produces: `doctor.Check` (NamedTuple with `name: str`, `ok: bool`, `detail: str`, `fatal: bool`); the individual `check_*` functions; `doctor.run_checks() -> list[Check]`; `doctor.main(argv) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor.py
import subprocess
from pathlib import Path

import pytest

from blaxk_sounds import config, doctor

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "shim" / "git.sh.template"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLAXK_SOUNDS_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()


@pytest.fixture
def shim(tmp_path):
    path = tmp_path / "git"
    path.write_text(
        TEMPLATE.read_text()
        .replace("__REAL_GIT__", "/usr/bin/git")
        .replace("__INSTALL_DIR__", str(tmp_path))
    )
    path.chmod(0o755)
    return path


def test_check_shim_installed_passes(shim):
    assert doctor.check_shim_installed(shim).ok is True


def test_check_shim_installed_detects_missing(tmp_path):
    assert doctor.check_shim_installed(tmp_path / "absent").ok is False


def test_check_shim_installed_detects_not_executable(tmp_path, shim):
    shim.chmod(0o644)
    assert doctor.check_shim_installed(shim).ok is False


def test_check_real_git_passes():
    assert doctor.check_real_git("/usr/bin/git").ok is True


def test_check_real_git_detects_missing(tmp_path):
    assert doctor.check_real_git(str(tmp_path / "nope")).ok is False


def test_recursion_guard_fires_when_real_git_is_the_shim(tmp_path, shim):
    check = doctor.check_not_recursive(str(shim), shim)
    assert check.ok is False
    assert check.fatal is True


def test_recursion_guard_passes_for_a_different_binary(shim):
    assert doctor.check_not_recursive("/usr/bin/git", shim).ok is True


def test_check_shim_literals_passes_when_they_agree(tmp_path, shim):
    settings = {"real_git": "/usr/bin/git"}
    assert doctor.check_shim_literals(shim, settings, tmp_path).ok is True


def test_check_shim_literals_detects_a_hand_edited_shim(tmp_path, shim):
    settings = {"real_git": "/usr/bin/git"}
    shim.write_text(shim.read_text().replace("/usr/bin/git", "/opt/other/git"))
    check = doctor.check_shim_literals(shim, settings, tmp_path)
    assert check.ok is False


def test_check_sounds_passes_for_real_wavs(tmp_path):
    sounds = {}
    for event in config.EVENTS:
        wav = tmp_path / f"{event}.wav"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=0.2", "-y", str(wav)],
            check=True,
        )
        sounds[event] = str(wav)
    checks = doctor.check_sounds({"sounds": sounds})
    assert all(check.ok for check in checks)


def test_check_sounds_detects_a_missing_file(tmp_path):
    sounds = {event: str(tmp_path / f"{event}.wav") for event in config.EVENTS}
    checks = doctor.check_sounds({"sounds": sounds})
    assert not all(check.ok for check in checks)


def test_check_sounds_detects_a_file_that_is_not_audio(tmp_path):
    sounds = {}
    for event in config.EVENTS:
        path = tmp_path / f"{event}.wav"
        path.write_bytes(b"this is not a wav file at all")
        sounds[event] = str(path)
    checks = doctor.check_sounds({"sounds": sounds})
    assert not all(check.ok for check in checks)


def test_check_config_parses_returns_ok_for_valid_config():
    assert doctor.check_config_parses().ok is True


def test_run_checks_returns_one_entry_per_check(shim, monkeypatch):
    monkeypatch.setattr(doctor, "shim_path", lambda: shim)
    names = [check.name for check in doctor.run_checks()]
    assert "shim installed" in names
    assert "recursion guard" in names
    assert "config parses" in names
    assert len(names) >= 10


def test_main_exits_non_zero_when_a_fatal_check_fails(shim, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "shim_path", lambda: shim)
    monkeypatch.setattr(doctor, "check_real_git", lambda path: doctor.Check(
        "real git", False, "missing", True
    ))
    assert doctor.main([]) != 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_doctor.py -v`
Expected: FAIL — `ImportError: cannot import name 'doctor'`

- [ ] **Step 3: Write the implementation**

```python
# blaxk_sounds/doctor.py
"""Verify the whole chain.

This system is invisible when it works and invisible when it breaks, so without
a doctor a failure presents as "I guess I'm not hearing sounds" with ten
possible causes (spec section 9.1).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from . import config, player


class Check(NamedTuple):
    name: str
    ok: bool
    detail: str
    fatal: bool = True


def shim_path() -> Path:
    return Path.home() / ".local" / "bin" / "git"


def install_dir() -> Path:
    return config.data_dir()


def check_shim_installed(shim: Path) -> Check:
    if not shim.exists():
        return Check("shim installed", False, f"not found at {shim}")
    if not os.access(shim, os.X_OK):
        return Check("shim installed", False, f"{shim} is not executable")
    return Check("shim installed", True, str(shim))


def check_shim_wins_path(shim: Path) -> Check:
    resolved = shutil.which("git")
    if resolved is None:
        return Check("shim wins PATH", False, "no git found on PATH")
    if Path(resolved).resolve() != shim.resolve():
        return Check(
            "shim wins PATH",
            False,
            f"PATH resolves git to {resolved}, not {shim}",
        )
    return Check("shim wins PATH", True, f"{shim} is first")


def check_real_git(path: str) -> Check:
    if not path or not os.path.isfile(path):
        return Check("real git", False, f"{path} does not exist")
    if not os.access(path, os.X_OK):
        return Check("real git", False, f"{path} is not executable")
    return Check("real git", True, path)


def check_not_recursive(real_git: str, shim: Path) -> Check:
    try:
        same = Path(real_git).resolve() == shim.resolve()
    except Exception:
        same = False
    if same:
        return Check(
            "recursion guard",
            False,
            f"real git IS the shim ({real_git}) - every git call would recurse",
        )
    return Check("recursion guard", True, "real git differs from the shim")


def _read_literal(text: str, name: str) -> str | None:
    match = re.search(rf'^{name}="([^"]*)"', text, re.MULTILINE)
    return match.group(1) if match else None


def check_shim_literals(shim: Path, settings: dict, expected_install_dir: Path) -> Check:
    try:
        text = shim.read_text(encoding="utf-8")
    except Exception as exc:
        return Check("shim literals", False, f"cannot read shim: {exc}")

    baked_git = _read_literal(text, "REAL_GIT")
    baked_dir = _read_literal(text, "INSTALL_DIR")
    if baked_git is None or baked_dir is None:
        return Check("shim literals", False, "shim is missing REAL_GIT or INSTALL_DIR")

    configured = settings.get("real_git")
    if baked_git != configured:
        return Check(
            "shim literals",
            False,
            f"shim has REAL_GIT={baked_git} but config says {configured}; re-run install",
        )
    if Path(baked_dir) != Path(expected_install_dir):
        return Check(
            "shim literals",
            False,
            f"shim has INSTALL_DIR={baked_dir}, expected {expected_install_dir}",
        )
    return Check("shim literals", True, f"{baked_git} / {baked_dir}")


def check_sounds(settings: dict) -> list[Check]:
    checks = []
    sounds = settings.get("sounds") or {}
    for event in config.EVENTS:
        name = f"sound: {event}"
        path = sounds.get(event)
        if not path:
            checks.append(Check(name, False, "no file configured"))
            continue
        if not os.path.isfile(path):
            checks.append(Check(name, False, f"{path} does not exist"))
            continue
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as exc:
            checks.append(Check(name, False, f"ffprobe failed: {exc}", fatal=False))
            continue
        if probe.returncode != 0 or not probe.stdout.strip():
            checks.append(Check(name, False, f"{path} is not readable as audio"))
        else:
            checks.append(Check(name, True, f"{path} ({probe.stdout.strip()})"))
    return checks


def check_backend() -> Check:
    found = player.detect_backend()
    if found is None:
        return Check("audio backend", False, "none of pw-play, paplay, ffplay, aplay found")
    return Check("audio backend", True, found[0])


def check_audio_session() -> Check:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        return Check("audio session", False, "XDG_RUNTIME_DIR is not set")
    root = Path(runtime)
    for candidate in ("pipewire-0", "pulse/native"):
        if (root / candidate).exists():
            return Check("audio session", True, str(root / candidate))
    return Check("audio session", False, f"no socket under {root}")


def check_config_parses() -> Check:
    path = config.config_path()
    if not path.exists():
        return Check("config parses", True, f"{path} absent, defaults will be used", fatal=False)
    try:
        config.load_settings()
    except Exception as exc:  # load_settings never raises, but be explicit
        return Check("config parses", False, str(exc))
    return Check("config parses", True, str(path))


def check_ffmpeg() -> Check:
    if shutil.which("ffmpeg") is None:
        return Check("ffmpeg present", False, "clip extraction unavailable", fatal=False)
    return Check("ffmpeg present", True, shutil.which("ffmpeg"))


def run_checks() -> list[Check]:
    settings = config.load_settings()
    shim = shim_path()
    checks = [
        check_shim_installed(shim),
        check_shim_wins_path(shim),
        check_real_git(settings.get("real_git", "")),
        check_not_recursive(settings.get("real_git", ""), shim),
        check_shim_literals(shim, settings, install_dir()),
        check_config_parses(),
        check_backend(),
        check_audio_session(),
        check_ffmpeg(),
    ]
    checks.extend(check_sounds(settings))
    return checks


def main(argv: list[str]) -> int:
    checks = run_checks()
    failed = 0
    for check in checks:
        mark = "ok  " if check.ok else ("FAIL" if check.fatal else "warn")
        print(f"[{mark}] {check.name}: {check.detail}")
        if not check.ok and check.fatal:
            failed += 1
    print()
    if failed:
        print(f"{failed} check(s) failed.")
    else:
        print("All checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_doctor.py -v`
Expected: PASS, 14 tests

- [ ] **Step 5: Commit**

```bash
git add blaxk_sounds/doctor.py tests/test_doctor.py
git commit -m "Add doctor verifying the ten-link push-sound chain"
```

---

### Task 9: Command-line interface

**Files:**
- Create: `blaxk_sounds/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `config` (Task 1), `player.play` (Task 3), `clip.extract` (Task 7), `doctor.main` (Task 8)
- Produces: `cli.main(argv: list[str]) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import time
from pathlib import Path

import pytest

from blaxk_sounds import cli, config

STUBS = Path(__file__).parent / "stubs"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLAXK_SOUNDS_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("RECORDER_LOG", str(tmp_path / "recorder.log"))
    monkeypatch.setenv("BLAXK_SOUNDS_PLAYER", str(STUBS / "recorder.sh"))
    (tmp_path / "run").mkdir()
    (STUBS / "recorder.sh").chmod(0o755)


def records(tmp_path):
    log = tmp_path / "recorder.log"
    return [line for line in log.read_text().splitlines() if line] if log.exists() else []


def test_enable_and_disable_toggle_config():
    assert cli.main(["disable"]) == 0
    assert config.load_settings()["enabled"] is False
    assert cli.main(["enable"]) == 0
    assert config.load_settings()["enabled"] is True


def test_list_marks_missing_files(tmp_path, capsys):
    assert cli.main(["list"]) == 0
    output = capsys.readouterr().out
    assert "start" in output
    assert "missing" in output


def test_list_marks_present_files(tmp_path, capsys):
    settings = config.default_settings()
    sound = tmp_path / "s.wav"
    sound.write_bytes(b"x")
    settings["sounds"]["start"] = str(sound)
    config.save_settings(settings)
    assert cli.main(["list"]) == 0
    line = next(
        l for l in capsys.readouterr().out.splitlines() if l.startswith("start")
    )
    assert "ok" in line
    assert "missing" not in line


def test_test_plays_one_event(tmp_path):
    settings = config.default_settings()
    sound = tmp_path / "s.wav"
    sound.write_bytes(b"x")
    settings["sounds"]["success"] = str(sound)
    config.save_settings(settings)

    assert cli.main(["test", "success"]) == 0
    time.sleep(0.3)
    assert records(tmp_path) == [str(sound)]


def test_test_with_no_argument_plays_all_three(tmp_path):
    settings = config.default_settings()
    for event in config.EVENTS:
        sound = tmp_path / f"{event}.wav"
        sound.write_bytes(b"x")
        settings["sounds"][event] = str(sound)
    config.save_settings(settings)

    assert cli.main(["test"]) == 0
    time.sleep(3.5)
    assert len(records(tmp_path)) == 3


def test_set_rejects_a_missing_file(tmp_path, capsys):
    assert cli.main(["set", "success", str(tmp_path / "nope.wav")]) != 0
    assert "not" in capsys.readouterr().err.lower()


def test_set_rejects_a_non_audio_file(tmp_path, capsys):
    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"definitely not audio")
    assert cli.main(["set", "success", str(junk)]) != 0
    assert config.load_settings()["sounds"]["success"] != str(junk)


def test_set_stores_an_absolute_expanded_path(tmp_path):
    import subprocess

    wav = tmp_path / "good.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.2", "-y", str(wav)],
        check=True,
    )
    assert cli.main(["set", "success", str(wav)]) == 0
    assert config.load_settings()["sounds"]["success"] == str(wav)


def test_set_rejects_an_unknown_event(tmp_path):
    assert cli.main(["set", "banana", "/tmp/x.wav"]) != 0


def test_doctor_subcommand_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.doctor, "run_checks", lambda: [
        cli.doctor.Check("shim installed", True, "fine")
    ])
    assert cli.main(["doctor"]) == 0
    assert "shim installed" in capsys.readouterr().out


def test_no_subcommand_prints_help(capsys):
    assert cli.main([]) != 0
    assert "usage" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'cli'`

- [ ] **Step 3: Write the implementation**

```python
# blaxk_sounds/cli.py
"""User-facing commands."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from . import clip, config, doctor, player


def _is_audio(path: str) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _cmd_set(args) -> int:
    if args.event not in config.EVENTS:
        print(
            f"unknown event {args.event!r}: expected one of {', '.join(config.EVENTS)}",
            file=sys.stderr,
        )
        return 1

    path = Path(args.path).expanduser()
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 1
    if not _is_audio(str(path)):
        print(f"not readable as audio: {path}", file=sys.stderr)
        return 1

    settings = config.load_settings()
    settings.setdefault("sounds", {})[args.event] = str(path.resolve())
    if not config.save_settings(settings):
        print(f"could not write config at {config.config_path()}", file=sys.stderr)
        return 1
    print(f"{args.event} -> {path.resolve()}")
    return 0


def _cmd_clip(args) -> int:
    try:
        from_s = clip.parse_time(args.from_)
        length_s = float(args.len)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        out = clip.extract(args.source, from_s, length_s, args.event, args.volume)
    except Exception as exc:
        print(f"clip failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.event} -> {out}")
    return 0


def _cmd_test(args) -> int:
    settings = config.load_settings()
    events = [args.event] if args.event else list(config.EVENTS)
    for index, event in enumerate(events):
        path = (settings.get("sounds") or {}).get(event)
        if not path:
            print(f"{event}: no sound configured", file=sys.stderr)
            continue
        player.play(path)
        print(f"{event}: {path}")
        if index < len(events) - 1:
            time.sleep(1.0)
    return 0


def _cmd_list(args) -> int:
    settings = config.load_settings()
    sounds = settings.get("sounds") or {}
    print(f"enabled: {settings.get('enabled', True)}")
    print(f"real git: {settings.get('real_git')}")
    print(f"config: {config.config_path()}")
    print()
    for event in config.EVENTS:
        path = sounds.get(event)
        if not path:
            state = "missing (not configured)"
        elif os.path.isfile(path):
            state = "ok"
        else:
            state = "missing"
        print(f"{event:8} {state:22} {path}")
    return 0


def _cmd_enable(args) -> int:
    settings = config.load_settings()
    settings["enabled"] = bool(args.enabled)
    if not config.save_settings(settings):
        print("could not write config", file=sys.stderr)
        return 1
    print("sounds enabled" if args.enabled else "sounds disabled")
    return 0


def _cmd_uninstall(args) -> int:
    shim = doctor.shim_path()
    if shim.exists():
        if not args.purge:
            try:
                text = shim.read_text(encoding="utf-8")
            except Exception:
                text = ""
            if "blaxk-sounds git shim" not in text:
                print(
                    f"{shim} does not look like our shim; refusing to remove it",
                    file=sys.stderr,
                )
                return 1
        shim.unlink()
        print(f"removed {shim}")

    package = config.data_dir() / "blaxk_sounds"
    if package.exists():
        import shutil as _shutil

        _shutil.rmtree(package)
        print(f"removed {package}")

    if args.purge:
        import shutil as _shutil

        for target in (config.sounds_dir(), config.config_path().parent):
            if target.exists():
                _shutil.rmtree(target)
                print(f"removed {target}")
        print("purged sounds and config")
    else:
        print("kept your sounds and config; pass --purge to remove them")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blaxk-sounds", description="Sound feedback for git push."
    )
    sub = parser.add_subparsers(dest="command")

    set_p = sub.add_parser("set", help="point an event at a sound file")
    set_p.add_argument("event", choices=config.EVENTS)
    set_p.add_argument("path")
    set_p.set_defaults(func=_cmd_set)

    clip_p = sub.add_parser("clip", help="extract a clip from an audio file")
    clip_p.add_argument("source")
    clip_p.add_argument("--from", dest="from_", required=True, help="SS, MM:SS, or HH:MM:SS")
    clip_p.add_argument("--len", required=True, help="length in seconds")
    clip_p.add_argument("--as", dest="event", required=True, choices=config.EVENTS)
    clip_p.add_argument("--volume", type=float, default=1.0)
    clip_p.set_defaults(func=_cmd_clip)

    test_p = sub.add_parser("test", help="play a sound now")
    test_p.add_argument("event", nargs="?", choices=config.EVENTS)
    test_p.set_defaults(func=_cmd_test)

    list_p = sub.add_parser("list", help="show current sounds")
    list_p.set_defaults(func=_cmd_list)

    for name, value, help_text in (
        ("enable", True, "turn sounds on"),
        ("disable", False, "turn sounds off"),
    ):
        toggle = sub.add_parser(name, help=help_text)
        toggle.set_defaults(func=_cmd_enable, enabled=value)

    uninstall_p = sub.add_parser("uninstall", help="remove the shim")
    uninstall_p.add_argument("--purge", action="store_true")
    uninstall_p.set_defaults(func=_cmd_uninstall)

    doctor_p = sub.add_parser("doctor", help="verify the whole chain")
    doctor_p.set_defaults(func=lambda args: doctor.main([]))

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add blaxk_sounds/cli.py tests/test_cli.py
git commit -m "Add command-line interface for set, clip, test, list and uninstall"
```

---

### Task 10: Installer

**Files:**
- Create: `install/install.sh`, `install/blaxk-sounds.template`
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: the rendered shim (Task 5), `doctor.main` (Task 8)
- Produces: `install/install.sh` — idempotent, no sudo

- [ ] **Step 1: Write the failing test**

```python
# tests/test_install.py
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "install" / "install.sh"


@pytest.fixture
def home(tmp_path):
    """A throwaway HOME so the installer never touches the real one."""
    fake = tmp_path / "home"
    (fake / ".local" / "bin").mkdir(parents=True)
    return fake


def run_installer(home, *args, extra_env=None):
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_RUNTIME_DIR": str(home / "run"),
            **(extra_env or {}),
        },
    )


def test_installer_is_idempotent(home):
    first = run_installer(home)
    assert first.returncode == 0, first.stderr
    second = run_installer(home)
    assert second.returncode == 0, second.stderr


def test_installer_writes_the_shim(home):
    assert run_installer(home).returncode == 0
    shim = home / ".local" / "bin" / "git"
    assert shim.exists()
    assert os.access(shim, os.X_OK)


def test_shim_has_no_unsubstituted_placeholders(home):
    run_installer(home)
    text = (home / ".local" / "bin" / "git").read_text()
    assert "__REAL_GIT__" not in text
    assert "__INSTALL_DIR__" not in text


def test_shim_points_at_a_real_git(home):
    run_installer(home)
    text = (home / ".local" / "bin" / "git").read_text()
    line = next(l for l in text.splitlines() if l.startswith("REAL_GIT="))
    real_git = line.split('"')[1]
    assert os.path.isfile(real_git)
    assert os.access(real_git, os.X_OK)


def test_installer_writes_the_cli_wrapper(home):
    run_installer(home)
    wrapper = home / ".local" / "bin" / "blaxk-sounds"
    assert wrapper.exists()
    assert os.access(wrapper, os.X_OK)


def test_installer_synthesizes_three_sounds(home):
    assert run_installer(home).returncode == 0
    sounds = home / ".local" / "share" / "blaxk-sounds" / "sounds"
    for event in ("start", "success", "fail"):
        assert (sounds / f"{event}.wav").exists()


def test_installer_writes_config_pointing_at_those_sounds(home):
    run_installer(home)
    import json

    settings = json.loads(
        (home / ".config" / "blaxk-sounds" / "settings.json").read_text()
    )
    for event in ("start", "success", "fail"):
        assert settings["sounds"][event].endswith(f"{event}.wav")
    assert settings["real_git"].startswith("/")


def test_installer_refuses_to_clobber_a_foreign_git(home):
    foreign = home / ".local" / "bin" / "git"
    foreign.write_text("#!/bin/sh\necho not ours\n")
    foreign.chmod(0o755)
    result = run_installer(home)
    assert result.returncode != 0
    assert "refus" in (result.stderr + result.stdout).lower()
    assert foreign.read_text() == "#!/bin/sh\necho not ours\n"


def test_cli_wrapper_runs_the_package(home):
    run_installer(home)
    result = subprocess.run(
        [str(home / ".local" / "bin" / "blaxk-sounds"), "list"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
        },
    )
    assert result.returncode == 0, result.stderr
    assert "success" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_install.py -v`
Expected: FAIL — `install/install.sh` does not exist

- [ ] **Step 3: Write the implementation**

```bash
# install/blaxk-sounds.template
#!/usr/bin/env bash
# blaxk-sounds CLI wrapper. GENERATED - re-run install/install.sh instead.
INSTALL_DIR="__INSTALL_DIR__"
exec env PYTHONPATH="$INSTALL_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m blaxk_sounds.cli "$@"
```

```bash
#!/usr/bin/env bash
# install/install.sh - no sudo, idempotent, safe to re-run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHIM_DEST="$HOME/.local/bin/git"
CLI_DEST="$HOME/.local/bin/blaxk-sounds"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/blaxk-sounds"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/blaxk-sounds"
SOUNDS_DIR="$INSTALL_DIR/sounds"

warn() { printf 'warning: %s\n' "$*" >&2; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- 1. Preconditions -------------------------------------------------------
command -v python3 >/dev/null 2>&1 || fail "python3 not found on PATH"

REAL_GIT=""
for candidate in /usr/bin/git /usr/local/bin/git /bin/git; do
    if [ -x "$candidate" ] && [ "$candidate" != "$SHIM_DEST" ]; then
        REAL_GIT="$candidate"
        break
    fi
done
[ -n "$REAL_GIT" ] || fail "could not find a real git binary"

# --- 2. Refuse to clobber something that is not ours ------------------------
if [ -e "$SHIM_DEST" ] && ! grep -q "blaxk-sounds git shim" "$SHIM_DEST" 2>/dev/null; then
    fail "$SHIM_DEST exists and is not ours; refusing to overwrite it"
fi

# --- 3. Install the package -------------------------------------------------
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/blaxk_sounds"
cp -r "$REPO_ROOT/blaxk_sounds" "$INSTALL_DIR/blaxk_sounds"

# --- 4. Generate the shim ---------------------------------------------------
mkdir -p "$(dirname "$SHIM_DEST")"
sed -e "s|__REAL_GIT__|$REAL_GIT|g" \
    -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    "$REPO_ROOT/shim/git.sh.template" > "$SHIM_DEST"
chmod 0755 "$SHIM_DEST"

# --- 4b. Generate the CLI wrapper -------------------------------------------
sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    "$REPO_ROOT/install/blaxk-sounds.template" > "$CLI_DEST"
chmod 0755 "$CLI_DEST"

# --- 5. Default config ------------------------------------------------------
mkdir -p "$CONFIG_DIR"
if [ ! -e "$CONFIG_DIR/settings.json" ]; then
    mkdir -p "$SOUNDS_DIR"
    cat > "$CONFIG_DIR/settings.json" <<JSON
{
  "enabled": true,
  "real_git": "$REAL_GIT",
  "sounds": {
    "start": "$SOUNDS_DIR/start.wav",
    "success": "$SOUNDS_DIR/success.wav",
    "fail": "$SOUNDS_DIR/fail.wav"
  }
}
JSON
fi

# --- 6. Placeholder tones, so it works immediately --------------------------
# Spec 7.4: a short soft blip, a rising two-note chime, and a low dull thud.
if command -v ffmpeg >/dev/null 2>&1; then
    mkdir -p "$SOUNDS_DIR"
    normalize() { # $1 dest, $2 lavfi source, $3 audio filter
        ffmpeg -hide_banner -loglevel error -f lavfi -i "$2" \
            -af "$3" -ac 1 -ar 44100 -c:a pcm_s16le -y "$1"
    }
    [ -e "$SOUNDS_DIR/start.wav" ] || normalize "$SOUNDS_DIR/start.wav" \
        "sine=frequency=700:duration=0.08" "volume=0.30"
    if [ ! -e "$SOUNDS_DIR/success.wav" ]; then
        # Two rising notes (660Hz then 990Hz) concatenated into one chime.
        ffmpeg -hide_banner -loglevel error \
            -f lavfi -i "sine=frequency=660:duration=0.09" \
            -f lavfi -i "sine=frequency=990:duration=0.16" \
            -filter_complex "[0:a][1:a]concat=n=2:v=0:a=1,volume=0.40" \
            -ac 1 -ar 44100 -c:a pcm_s16le -y "$SOUNDS_DIR/success.wav"
    fi
    [ -e "$SOUNDS_DIR/fail.wav" ] || normalize "$SOUNDS_DIR/fail.wav" \
        "sine=frequency=150:duration=0.32" "volume=0.45"
else
    warn "ffmpeg not found: placeholder tones not generated and 'clip' unavailable"
fi

# --- 7. Verify --------------------------------------------------------------
PATH="$(dirname "$SHIM_DEST"):$PATH" \
PYTHONPATH="$INSTALL_DIR" \
    python3 -m blaxk_sounds.doctor || warn "doctor reported problems (see above)"

echo
echo "installed. Try:  blaxk-sounds test"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_install.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest -v`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add install/ tests/test_install.py
git commit -m "Add no-sudo installer that generates the shim and placeholder tones"
```

---

### Task 11: Documentation

**Files:**
- Create: `README.md`
- Modify: `CLAUDE.md` (rewrite — it currently documents a different, incorrect system)

**Interfaces:**
- Consumes: everything
- Produces: accurate docs

- [ ] **Step 1: Write `README.md`**

Cover, in this order: what it does; the one-command install; the three events;
`blaxk-sounds clip` with a worked example using a real music file; the full
command list; how to mute; how to uninstall; and the known limitations from spec
§12 (no IDE coverage, git aliases do not trigger, non-interactive shells are
silent, `/usr/bin/git` bypasses it). Point at `blaxk-sounds doctor` as the first
stop when sound stops working.

- [ ] **Step 2: Rewrite `CLAUDE.md`**

Replace the existing content entirely. It currently documents a system that was
never built and is wrong in five load-bearing ways (spec §15): it lists `paplay`
as the priority-1 backend when `paplay` is not installed, it claims the real git
path is both hardcoded and resolved at runtime, it installs via `sudo` to `/opt`,
it describes the misfiring "is `push` in args" detection rule, and it lists an
unused `watchdog` dependency.

The replacement should describe the architecture actually built, kept short
enough to stay true.

- [ ] **Step 3: Verify the install works end to end by hand**

Run:
```bash
bash install/install.sh
blaxk-sounds doctor
blaxk-sounds test
```
Expected: doctor reports all checks passed; `test` plays three tones.

- [ ] **Step 4: Real-world verification**

In a scratch repository with a real remote, run a real `git push` and confirm the
start and success sounds play; then force a rejection and confirm the fail sound.
This is the only check that proves the system works outside the test harness.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "Document the push sound feedback system

CLAUDE.md previously described a different, unbuilt system: it named paplay
as the priority-1 backend though paplay is not installed, claimed the real
git path was both baked in and resolved at runtime, installed via sudo to
/opt, and documented a detection rule that misfires on 'git branch push'."
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: §4.4/§5.2/§5.3 → Task 5;
§4.5 → Tasks 5 and 8; §6 rules 1–3 → Tasks 3, 4, 5; rules 4–6 → Tasks 3, 5;
§7.2 → Task 2; §7.3 → Task 7; §7.4 → Task 10; §8 → Task 1; §9/§9.1 → Tasks 8, 9;
§10 → Tasks 3, 4, 6; §13 → Tasks 9, 10. §12 and §14 are documented rather than
built (Task 11).

**§11.3's test plan, row by row.** Shim argv table → Task 5 (against the real shim
as a subprocess, per the spec). End-to-end success and rejection → Task 6. Start
sound ordering → Task 5, against a stub git that sleeps; the spec is explicit
that this cannot be asserted against a fast push because the player is
backgrounded by design. Exit code fidelity → Tasks 5 and 6. stdout/stderr
passthrough → Tasks 5 and 6. stdin not consumed → Task 5, by having a stub git
`cat` stdin and comparing bytes. Exit 130 → Task 5. `player.play()` never raises →
Task 3. Backend probe order → Task 2. `clip` argv per `--from` format → Task 7.
`clip` real extraction → Task 7. `clip` range validation → Task 7. Pidfile
takeover → Task 3. Config round-trip → Task 1. `disable` honored → Tasks 4 and 6.
`set` validation → Task 9. Shim generation → Task 10. `doctor` per-check → Task 8.

**§11.4 is honored.** No task attempts to verify audible output; every assertion
is that the correct backend was invoked with the correct file. Windows is absent
by design.

**Type consistency.** `config.EVENTS` is a tuple defined once in Task 1 and
consumed unchanged in Tasks 4, 7, 8, 9. `player.detect_backend()` returns
`tuple[str, list[str]] | None` in Task 2, and both call sites — `build_command` in
Task 3 and `check_backend` in Task 8 — guard the `None` case before indexing.
`doctor.Check` is defined once in Task 8 with four fields and constructed with
those fields in Task 9's test. `clip.extract` takes
`(source, from_s, length_s, event, volume)` in Task 7 and is called positionally
in that order from `cli._cmd_clip` in Task 9.

**Fixed during this review.** Four defects, all corrected above rather than
noted: a dead `fake_path` fixture containing a broken conditional expression in
Task 2's test; a pidfile test that short-circuited before reaching the code it
claimed to verify; a `list` assertion that would pass against the wrong line; and
an unset `$SHIM_DEST_DIR` in the installer that would abort every run under
`set -u`. Three §11.3 rows with no test were added (start ordering, stdin,
`clip` argv), and §7.4's rising two-note chime replaced a single tone — verified
to produce 0.25s of `pcm_s16le` 44.1kHz mono.

**Known weak point, flagged deliberately.** Task 5's `run()` helper polls the log
rather than synchronising properly, because the start sound is backgrounded by
design. It is adequate but not airtight; if it proves flaky, replace the polling
with a wait on the recorder's own file lock rather than adding a longer sleep.
