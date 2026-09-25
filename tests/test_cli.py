from pathlib import Path
import subprocess

import pytest

from blaxk_sounds import cli, config

# tests/ has no __init__.py, so pytest prepends tests/ to sys.path.
from helpers import read_lines, settle

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
    return read_lines(tmp_path / "recorder.log")


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
    settle(tmp_path / "recorder.log", expect=1)
    assert records(tmp_path) == [str(sound)]


def test_test_with_no_argument_plays_all_three(tmp_path):
    settings = config.default_settings()
    for event in config.EVENTS:
        sound = tmp_path / f"{event}.wav"
        sound.write_bytes(b"x")
        settings["sounds"][event] = str(sound)
    config.save_settings(settings)

    assert cli.main(["test"]) == 0
    # _cmd_test spaces the three plays 1s apart, so all three have been spawned
    # by the time it returns; give the last one room to land.
    settle(tmp_path / "recorder.log", timeout=6.0, expect=3)
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
    wav = tmp_path / "good.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.2", "-y", str(wav)],
        check=True,
    )
    assert cli.main(["set", "success", str(wav)]) == 0
    assert config.load_settings()["sounds"]["success"] == str(wav)


def test_set_rejects_an_unknown_event(tmp_path, capsys):
    # The path has to be valid audio. With a path that does not exist, the file
    # check rejects it first and this test passes without ever reaching the event
    # guard — verified by deleting the guard and watching this still pass.
    wav = tmp_path / "good.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.2", "-y", str(wav)],
        check=True,
    )
    assert cli.main(["set", "banana", str(wav)]) != 0
    assert "banana" not in (config.load_settings().get("sounds") or {})
    assert "banana" in capsys.readouterr().err


def test_doctor_subcommand_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.doctor, "run_checks", lambda: [
        cli.doctor.Check("shim installed", True, "fine")
    ])
    assert cli.main(["doctor"]) == 0
    assert "shim installed" in capsys.readouterr().out


def test_no_subcommand_prints_help(capsys):
    assert cli.main([]) != 0
    assert "usage" in capsys.readouterr().out.lower()


def _our_shim(path):
    path.write_text("#!/bin/sh\n# blaxk-sounds git shim\nexec /usr/bin/git \"$@\"\n")
    path.chmod(0o755)
    return path


def _our_wrapper(path):
    path.write_text("#!/bin/sh\n# blaxk-sounds CLI wrapper. GENERATED\n")
    path.chmod(0o755)
    return path


def test_uninstall_refuses_a_foreign_git(tmp_path, monkeypatch):
    foreign = tmp_path / "git"
    foreign.write_text("#!/bin/sh\necho not ours\n")
    monkeypatch.setattr(cli.doctor, "shim_path", lambda: foreign)
    assert cli.main(["uninstall"]) != 0
    assert foreign.read_text() == "#!/bin/sh\necho not ours\n"


def test_uninstall_purge_still_refuses_a_foreign_git(tmp_path, monkeypatch):
    # --purge is documented as dropping *your sounds and config*. It must not
    # double as an override of the guard that protects someone else's git.
    foreign = tmp_path / "git"
    foreign.write_text("#!/bin/sh\necho not ours\n")
    monkeypatch.setattr(cli.doctor, "shim_path", lambda: foreign)
    assert cli.main(["uninstall", "--purge"]) != 0
    assert foreign.read_text() == "#!/bin/sh\necho not ours\n"


def test_uninstall_removes_the_shim_and_the_cli_wrapper(tmp_path, monkeypatch):
    shim = _our_shim(tmp_path / "git")
    wrapper = _our_wrapper(tmp_path / "blaxk-sounds")
    monkeypatch.setattr(cli.doctor, "shim_path", lambda: shim)
    monkeypatch.setattr(cli.doctor, "cli_path", lambda: wrapper)
    assert cli.main(["uninstall"]) == 0
    assert not shim.exists()
    assert not wrapper.exists()


def test_uninstall_refuses_a_foreign_cli_wrapper(tmp_path, monkeypatch):
    shim = _our_shim(tmp_path / "git")
    foreign = tmp_path / "blaxk-sounds"
    foreign.write_text("#!/bin/sh\necho not ours either\n")
    monkeypatch.setattr(cli.doctor, "shim_path", lambda: shim)
    monkeypatch.setattr(cli.doctor, "cli_path", lambda: foreign)
    assert cli.main(["uninstall"]) != 0
    assert foreign.read_text() == "#!/bin/sh\necho not ours either\n"
    assert shim.exists()  # checked before removing anything, so nothing is half-done


def test_uninstall_keeps_config_unless_purged(tmp_path, monkeypatch):
    shim = _our_shim(tmp_path / "git")
    wrapper = _our_wrapper(tmp_path / "blaxk-sounds")
    monkeypatch.setattr(cli.doctor, "shim_path", lambda: shim)
    monkeypatch.setattr(cli.doctor, "cli_path", lambda: wrapper)
    config.save_settings(config.default_settings())
    assert cli.main(["uninstall"]) == 0
    assert config.config_path().exists()
