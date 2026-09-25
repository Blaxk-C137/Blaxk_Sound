import os
import re
import subprocess
from pathlib import Path

import pytest

# tests/ has no __init__.py, so pytest prepends tests/ to sys.path.
from helpers import settle

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

# A `set` command (not a mention in a comment) that turns on errexit, in any of
# its spellings: set -e, set -eu, set -euo pipefail, set -o errexit.
ERREXIT = re.compile(r"^\s*set\s+.*(-[a-zA-Z]*e[a-zA-Z]*\b|errexit)", re.MULTILINE)


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


def run(sandbox, *args, env=None, expect=0):
    result = subprocess.run(
        [str(sandbox["shim"]), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    # Both the start and the result sound are backgrounded, so neither has
    # necessarily landed by the time the shim exits. Waiting for quiescence is
    # what makes both the positive and the negative assertions sound; `expect`
    # is how many log lines a positive assertion needs before quiet means
    # anything, and it stays 0 for the negative ones.
    settle(sandbox["log"], expect=expect)
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
    run(sandbox, *args, expect=1)
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
    run(sandbox, "push", env={"STUB_GIT_RC": "0"}, expect=2)
    recorded = lines(sandbox)
    assert any(line.endswith("blaxk_sounds.play success") for line in recorded)


def test_failure_plays_fail_event(sandbox):
    run(sandbox, "push", env={"STUB_GIT_RC": "1"}, expect=2)
    recorded = lines(sandbox)
    assert any(line.endswith("blaxk_sounds.play fail") for line in recorded)


def test_exit_code_is_passed_through(sandbox):
    assert run(sandbox, "push", env={"STUB_GIT_RC": "0"}).returncode == 0
    assert run(sandbox, "push", env={"STUB_GIT_RC": "7"}).returncode == 7
    assert run(sandbox, "push", env={"STUB_GIT_RC": "128"}).returncode == 128


def test_interrupt_exit_130_plays_nothing(sandbox):
    run(sandbox, "push", env={"STUB_GIT_RC": "130"}, expect=1)
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
    """set -e would abort before the exit code is captured (spec section 6 rule 2).

    Matched as a command on a non-comment line. The shipped template documents
    the deliberate omission in a comment, and a bare substring check flags its
    own documentation rather than the property.
    """
    text = sandbox["shim"].read_text()
    assert not ERREXIT.search(text)


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
    settle(sandbox["log"], expect=1)

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
    settle(sandbox["log"])
    assert (sandbox["tmp"] / "log.stdin").read_text() == payload
