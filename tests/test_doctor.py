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
