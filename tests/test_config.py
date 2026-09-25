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


def test_save_returns_false_rather_than_raising(tmp_path, monkeypatch):
    # A path whose parent is a regular file, so mkdir fails.
    not_a_dir = tmp_path / "a-file-not-a-dir"
    not_a_dir.write_text("x")

    # monkeypatch, not os.environ: a leaked var would point later tests at a
    # tmp_path that no longer exists.
    monkeypatch.setenv("BLAXK_SOUNDS_CONFIG", str(not_a_dir / "settings.json"))
    assert config.save_settings(config.default_settings()) is False


def test_sounds_dir_follows_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config.sounds_dir() == tmp_path / "xdg" / "blaxk-sounds" / "sounds"


def test_partial_sounds_object_keeps_the_other_events():
    """A config naming one sound must not drop the rest."""
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(
        json.dumps({"sounds": {"success": "/custom/success.wav"}})
    )
    sounds = config.load_settings()["sounds"]
    assert sounds["success"] == "/custom/success.wav"
    assert sounds["start"].endswith("start.wav")
    assert sounds["fail"].endswith("fail.wav")


def test_empty_sounds_object_falls_back_to_all_defaults():
    config.config_path().parent.mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(json.dumps({"sounds": {}}))
    assert set(config.load_settings()["sounds"]) == {"start", "success", "fail"}


def test_default_settings_shape_is_pinned():
    """Tasks 8, 9 and 10 consume these keys, and EVENTS drives CLI choices."""
    settings = config.default_settings()
    assert config.EVENTS == ("start", "success", "fail")
    assert settings["enabled"] is True
    assert settings["real_git"].startswith("/")


def test_save_is_atomic_so_a_failed_write_cannot_truncate(monkeypatch):
    """A non-atomic write would destroy the previous config."""
    assert config.save_settings(config.default_settings()) is True
    original = config.config_path().read_text()

    def boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(config.os, "replace", boom)
    settings = config.default_settings()
    settings["enabled"] = False
    assert config.save_settings(settings) is False

    # The old config must survive intact, not be half-written.
    assert config.config_path().read_text() == original
    assert config.load_settings()["enabled"] is True


def test_failed_save_leaves_no_temp_file_behind(monkeypatch):
    assert config.save_settings(config.default_settings()) is True
    tmp = config.config_path().with_suffix(config.config_path().suffix + ".tmp")

    def boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(config.os, "replace", boom)
    assert config.save_settings(config.default_settings()) is False
    assert not tmp.exists()


def test_save_restricts_config_permissions():
    assert config.save_settings(config.default_settings()) is True
    assert config.config_path().stat().st_mode & 0o777 == 0o600
