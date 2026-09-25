import os
import subprocess
from pathlib import Path

import pytest

from blaxk_sounds import player

# tests/ has no __init__.py, so pytest prepends tests/ to sys.path.
from helpers import read_lines, settle, wait_until

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
    return read_lines(tmp_path / "recorder.log")


def test_play_records_the_path(tmp_path):
    sound = tmp_path / "a.wav"
    sound.write_bytes(b"x")
    assert player.play(str(sound)) is True
    settle(tmp_path / "recorder.log")
    assert recorder_lines(tmp_path) == [str(sound)]


def test_play_returns_false_for_missing_file(tmp_path):
    assert player.play(str(tmp_path / "nope.wav")) is False
    settle(tmp_path / "recorder.log")
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
    settle(tmp_path / "recorder.log")
    first_pid = int(recorder_lines(tmp_path)[0])
    assert _alive(first_pid)

    assert player.play(str(sound)) is True
    assert wait_until(lambda: not _alive(first_pid)), (
        "previous sound should have been killed"
    )
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
        settle(tmp_path / "recorder.log")
        assert victim.poll() is None, "must not kill a pid that is not our player"
    finally:
        victim.kill()
        victim.wait()


def _alive(pid):
    """True only while the process is still running.

    A killed child stays a zombie until it is reaped, and os.kill(pid, 0)
    succeeds for a zombie, so the state field is what separates "still playing"
    from "killed but not yet waited on". In production the parent is the
    short-lived `blaxk_sounds.play` process, so the orphan is reaped by init;
    only this long-lived test process leaves one.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            state = handle.read().rsplit(b") ", 1)[1][:1]
    except (OSError, IndexError):
        return False
    return state != b"Z"
