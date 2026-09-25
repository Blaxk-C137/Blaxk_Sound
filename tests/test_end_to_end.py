"""Real git, real exit codes, real non-fast-forward rejection. No network."""

import os
import subprocess
from pathlib import Path

import pytest

# tests/ has no __init__.py, so pytest prepends tests/ to sys.path.
from helpers import read_lines, settle

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


def push(workspace, *args, expect=0):
    result = subprocess.run(
        [str(workspace["shim"]), "push", *args],
        cwd=workspace["work"],
        capture_output=True,
        text=True,
        env=workspace["env"],
    )
    # The start and result sounds are both backgrounded, so a positive
    # assertion has to say how many lines it needs before quiescence is
    # meaningful. See helpers.settle.
    settle(workspace["log"], expect=expect)
    return result


def played(workspace):
    return read_lines(workspace["log"])


def test_successful_push_plays_start_then_success(workspace):
    result = push(workspace, "-u", "origin", "main", expect=2)
    assert result.returncode == 0, result.stderr
    assert played(workspace) == [
        workspace["sounds"]["start"],
        workspace["sounds"]["success"],
    ]


def test_rejected_push_plays_fail(workspace):
    assert push(workspace, "-u", "origin", "main", expect=2).returncode == 0
    workspace["log"].unlink()

    # Rewrite history so the second push is a non-fast-forward.
    (workspace["work"] / "file.txt").write_text("rewritten\n")
    git("add", "file.txt", cwd=workspace["work"])
    git("commit", "--amend", "-m", "amended", cwd=workspace["work"])

    result = push(workspace, "origin", "main", expect=2)
    assert result.returncode != 0
    assert played(workspace)[-1] == workspace["sounds"]["fail"]


def test_git_output_is_not_swallowed(workspace):
    result = push(workspace, "-u", "origin", "main")
    assert "main" in result.stderr or "main" in result.stdout


def test_push_to_up_to_date_remote_still_sounds(workspace):
    assert push(workspace, "-u", "origin", "main", expect=2).returncode == 0
    workspace["log"].unlink()
    result = push(workspace, "origin", "main", expect=2)  # up-to-date, exit 0
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
