import json
from pathlib import Path

import pytest

from blaxk_sounds import config, play

# tests/ has no __init__.py, so pytest prepends tests/ to sys.path.
from helpers import read_lines, settle

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
    return read_lines(tmp_path / "recorder.log")


def test_plays_the_requested_event(tmp_path):
    settings = write_config(tmp_path)
    assert play.main(["success"]) == 0
    settle(tmp_path / "recorder.log", expect=1)
    assert records(tmp_path) == [settings["sounds"]["success"]]


def test_disabled_setting_plays_nothing(tmp_path):
    write_config(tmp_path, enabled=False)
    assert play.main(["success"]) == 0
    settle(tmp_path / "recorder.log")
    assert records(tmp_path) == []


def test_disabled_env_var_plays_nothing(tmp_path, monkeypatch):
    write_config(tmp_path)
    monkeypatch.setenv("BLAXK_SOUNDS_DISABLED", "1")
    assert play.main(["success"]) == 0
    settle(tmp_path / "recorder.log")
    assert records(tmp_path) == []


def test_unknown_event_plays_nothing(tmp_path):
    write_config(tmp_path)
    assert play.main(["banana"]) == 0
    settle(tmp_path / "recorder.log")
    assert records(tmp_path) == []


def test_wrong_argument_count_plays_nothing(tmp_path):
    write_config(tmp_path)
    assert play.main([]) == 0
    assert play.main(["a", "b"]) == 0
    settle(tmp_path / "recorder.log")
    assert records(tmp_path) == []


def test_corrupt_config_still_returns_zero(tmp_path):
    config.config_path().write_text("{{{ not json")
    assert play.main(["success"]) == 0


def test_missing_sound_file_still_returns_zero(tmp_path):
    settings = config.default_settings()
    config.save_settings(settings)  # points at files that do not exist
    assert play.main(["success"]) == 0
