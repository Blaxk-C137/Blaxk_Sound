import json
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


def test_installer_does_not_mask_a_bad_path(home):
    # doctor is run BY the installer, so it is the last line of defence for a
    # PATH that does not actually put the shim first. If the installer prepends
    # the shim's directory, the check passes by construction and the user gets
    # "All checks passed" followed by silence.
    result = run_installer(home, extra_env={"PATH": "/usr/bin:/bin"})
    assert "[FAIL] shim wins PATH" in result.stdout, result.stdout


def test_reinstall_repairs_a_stale_real_git(home):
    # Spec 4.5: re-running install is the remedy for a git that moved. doctor
    # says "re-run install" when the shim's REAL_GIT and config.real_git drift,
    # so re-running install has to actually reconcile them.
    assert run_installer(home).returncode == 0
    shim = home / ".local" / "bin" / "git"
    baked = next(
        l.split('"')[1] for l in shim.read_text().splitlines() if l.startswith("REAL_GIT=")
    )
    cfg = home / ".config" / "blaxk-sounds" / "settings.json"
    settings = json.loads(cfg.read_text())
    settings["real_git"] = "/nonexistent/git"
    cfg.write_text(json.dumps(settings))

    assert run_installer(home).returncode == 0
    assert json.loads(cfg.read_text())["real_git"] == baked


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
