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
