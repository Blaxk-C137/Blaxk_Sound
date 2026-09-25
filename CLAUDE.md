# CLAUDE.md

Guidance for working in this repository.

## What this is

Sound feedback for `git push` on Linux. A short blip when the push starts, a
rising chime on success, a low thud on failure. The user types normal git
commands; the shim plays sounds around them.

Fedora 44 / PipeWire is the target. Nothing here is Windows-aware.

## Layout

```
blaxk_sounds/
  config.py     settings load/save, XDG paths, the EVENTS tuple
  player.py     backend probe order, detached playback, pidfile takeover
  play.py       push-path entry point; plays one event and exits 0, always
  clip.py       ffmpeg clip extraction, normalized
  doctor.py     the ten-link chain check
  cli.py        the blaxk-sounds command
shim/
  git.sh.template   the git shim, with __REAL_GIT__ / __INSTALL_DIR__ placeholders
install/
  install.sh              no-sudo installer
  blaxk-sounds.template   CLI wrapper, generated with __INSTALL_DIR__
tests/                    pytest; tests/stubs/ holds fake players and fake gits
```

## How interception works

`install.sh` renders `shim/git.sh.template` to `~/.local/bin/git`, which is
already first in `PATH`. The real git binary is **not** modified or moved.

```
git push             -> shim detects "push" -> plays start, runs real git,
                                               plays success or fail, exits rc
git status           -> shim detects "status" -> exec real git (process replaced)
```

Non-push commands go through `exec`, so the shim process is replaced by git:
no Python starts and the overhead is one `case` statement.

**Subcommand detection is `find_subcommand` in the shim**, and it is subtler than
it looks. It returns the first bare word after skipping global options, because
the naive rule ("is `push` anywhere in argv") misfires on `git branch push`,
`git log push --oneline` and `git checkout push` — all of which would play push
sounds. Options that take a value (`-C`, `-c`, `--git-dir`, `--work-tree`,
`--namespace`, `--exec-path`, `--config-env`) are skipped along with their value,
including when written attached (`-C/path`). `tests/test_shim.py` pins this
against the real shim run as a subprocess.

## Data locations

| What | Where |
|---|---|
| Shim | `~/.local/bin/git` |
| CLI | `~/.local/bin/blaxk-sounds` |
| Package | `$XDG_DATA_HOME/blaxk-sounds/blaxk_sounds` (default `~/.local/share`) |
| Sounds | `$XDG_DATA_HOME/blaxk-sounds/sounds/{start,success,fail}.wav` |
| Config | `$XDG_CONFIG_HOME/blaxk-sounds/settings.json` |
| Pidfile | `$XDG_RUNTIME_DIR/blaxk-sounds.pid` |

## Events

`config.EVENTS` is `("start", "success", "fail")`, defined once and consumed by
`play.py`, `clip.py`, `doctor.py` and `cli.py`. Add an event there and in the
installer's config heredoc, not in four places.

## The safety rules

These are load-bearing. Breaking one changes behavior the user will notice.

1. **Nothing in the push path may fail the push.** `config.load_settings` returns
   defaults rather than raising; `play.main` catches everything and returns 0.
   Spec §10: a sound failure must be indistinguishable from being muted.
2. **Output is never captured.** The shim does not capture stdout/stderr, or a
   credential prompt would hang.
3. **stdin is passed through untouched**, for the same reason.
4. **The shim never uses `set -e`.** The real git exits non-zero on a failed push;
   errexit would abort before the exit code is captured. Exit code fidelity is
   the whole point.
5. **Sounds are detached** (`start_new_session=True`, fds to `/dev/null`), so
   playback never delays git's exit.
6. **A new sound kills the previous one** via the pidfile, so a fast push does not
   leave the start blip playing over the result. The kill is guarded by checking
   `/proc/<pid>/cmdline` against the player tokens, so it can never kill an
   unrelated process that reused the pid.
7. **Exit 130 is silent.** Ctrl-C during a push is not a failure.

## Backend probe order

`pw-play` → `paplay` → `ffplay` → `aplay`, first found wins. `pw-play` is first
because Fedora 44 is PipeWire and `paplay` is not installed there; `paplay` stays
second for PulseAudio systems.

`BLAXK_SOUNDS_PLAYER` overrides the backend entirely. The test suite uses this to
substitute recorder scripts for real audio.

## Environment variables

| Variable | Effect |
|---|---|
| `BLAXK_SOUNDS_DISABLED=1` | Mute for one command |
| `BLAXK_SOUNDS_CONFIG` | Override the config file path |
| `BLAXK_SOUNDS_PLAYER` | Override the audio player executable |

## Testing

```bash
python3 -m pytest              # full suite
python3 -m pytest tests/test_shim.py -v
```

No third-party dependencies, in the package or the tests. `pytest` config lives in
`pyproject.toml` (`pythonpath = ["."]`, `addopts = "-q"`, prepend import mode, so
`tests/` has no `__init__.py` and imports `helpers` directly).

Two habits this suite depends on:

- **`settle()` in `tests/helpers.py` takes `expect=<lines>`.** It declares
  quiescence after the log stops changing, and an *empty* log is stable from the
  start, so it cannot by itself tell "nothing has played yet" from "nothing will
  play". Positive assertions must pass `expect`; negative assertions must not.
- **Mutation-check new tests.** Several tests here initially passed for reasons
  unrelated to their names. Delete the code under test and confirm the test fails.

`tests/stubs/recorder.sh` must stay byte-identical to what the tests expect; it
records `"$*"` to `$RECORDER_LOG`.

## Install and uninstall

```bash
bash install/install.sh        # no sudo, idempotent, refuses to clobber a foreign git
blaxk-sounds doctor            # verify all ten links in the chain
blaxk-sounds uninstall         # remove the shim; --purge also drops sounds and config
```

## Limitations

See README.md and spec §12. The short version: no IDE/GUI coverage, non-interactive
shells are silent, git aliases do not trigger, and `/usr/bin/git push` bypasses the
shim. All inherent to `PATH` interception.
