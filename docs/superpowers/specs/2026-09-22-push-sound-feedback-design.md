# Push Sound Feedback — Design

**Date:** 2026-09-22
**Status:** Approved design, awaiting spec review before implementation planning
**Target:** Fedora Linux first (verified on this machine), Windows second

---

## 1. Summary

A sound feedback system for `git push`. When you push from your terminal, three
sounds play: one when the push starts, one when it succeeds, one when it fails.
The sounds are your own audio clips, extracted from any format into short `.wav`
files and swappable at will.

Interception happens through a `git` shim placed at `~/.local/bin/git`, which is
already first in this machine's `PATH`. Non-push commands `exec` straight to the
real git with zero overhead and zero interpreter startup. Only `git push` does
any extra work.

There is no daemon, no background service, and no root. See §4.1 for why root was
rejected.

---

## 2. Goals

- Play a distinct sound when a `git push` starts, succeeds, and fails.
- Let the user swap any sound for any audio file of their choosing.
- Extract short clips from long audio (the user's library is full-length music).
- Work transparently: type normal git commands, hear sounds, change nothing else.
- Never interfere with git. A broken sound system must be indistinguishable from
  a muted one — never from a broken git.
- Install and run with no `sudo`, ever.
- Survive reboot with nothing to restart.

## 3. Non-goals

- **No failure-reason detection.** Success vs. failure comes from the exit code
  alone. Distinguishing rejected-push from auth-failure from network-timeout would
  require matching git's stderr text, which git rewords between versions. The exit
  code is stable; the wording is not.
- **No random pick from a folder.** One file per event. The user chose this
  explicitly over the shuffle-a-library option.
- **No per-repository sound profiles.** Same sounds for every repo.
- **No events other than push.** Commit, pull, merge, and clone are out of scope.
  Adding a sound *file* for an existing event is a config change; adding a new
  *event* requires a shim change, because the exit-code-to-event mapping lives in
  the shim (§4.4). The claim that new events are config-only would be false.
- **No IDE, GUI, or non-interactive coverage.** Terminal only, by choice. See
  §12.
- **No Windows work in phase 1.** Phase 2. See §14.

---

## 4. Decisions and rationale

### 4.1 Root and background processes were rejected

The original request was to run this as a root background process. Two findings
ruled that out:

**Root cannot reach the audio session.** Audio playback goes through the user's
session socket at `/run/user/1000/pipewire-0`. A root process runs with
`XDG_RUNTIME_DIR=/run/user/0` and cannot open `pw-play`'s default PulseAudio-compat
socket, which lives in a `drwx------` directory owned by the user. Measured on this
machine: the native PipeWire socket is mode `0666`, so root could reach it *if*
deliberately pointed at `/run/user/1000` — but that is hand-wiring root into a
user's session, and it is impossible on Windows regardless, where a session-0
service has no audio device and `winsound` is silent.

**A background process does not intercept anything.** Catching `git push` is a
`PATH` lookup that happens in the shell when the command is typed. A resident
daemon never sees the command. The interception must happen at the call site, as
the user.

The system-wide reach the root request was reaching for is available without root
— see §12 — but this design stays terminal-only per the user's choice.

### 4.2 The shim, not a hook

`git` provides a `pre-push` hook but **no `post-push` hook**. A hook therefore
cannot learn the push's outcome, which is the entire point. Hooks are also
per-repository and require setup in every repo. The `PATH` shim is global, needs
no per-repo setup, and sees the exit code.

### 4.3 Clips are pre-extracted to `.wav`

The user's library is 680 full-length music files, mostly `.mp3`. Playing a
three-minute track on every push is not feedback. Two options were considered:

- Play source files directly via `ffplay` with seek flags at runtime. Rejected:
  requires ffmpeg installed at runtime on both platforms, spawns a decoder per
  push, and stores per-file seek offsets that must be passed every time.
- Extract clips to `.wav` once, at setup time. **Chosen.** After extraction the
  runtime plays a plain `.wav`, which every backend on both platforms handles
  natively. Windows needs nothing installed.

Clipping also gives a single place to normalize format, sample rate, and volume —
so the runtime has no per-backend volume variance to reason about. See §7.3.

### 4.4 Python core with a thin bash shim, and git execution stays in bash

The user chose a Python core over pure bash, primarily because phase 2 (Windows)
then becomes a small `.bat` shim plus path branches rather than a second
implementation of the logic.

However, the original sketch had Python orchestrating the push — play start, run
git, read exit code, play result. Working through failure modes revealed a hole:
**git's execution would depend on Python starting.** If `python3` were removed,
broken by an upgrade, or the module failed to import, `git push` would not run at
all. That is the one failure the "sound can never break git" rule cannot swallow,
because no code remains running to swallow it.

So the shim owns git execution and the exit code, and Python is only a sound
player in the push path:

```bash
# REAL_GIT is baked into this file by the installer as a literal (§5.2)
python3 -m blaxk_sounds.play start >/dev/null 2>&1 &     # detached; dies silently
"$REAL_GIT" "$@"; rc=$?
if [ "$rc" -ne 130 ]; then
    event=$([ "$rc" -eq 0 ] && echo success || echo fail)
    python3 -m blaxk_sounds.play "$event" >/dev/null 2>&1 &
fi
exit "$rc"
```

Remove Python entirely and git still pushes with correct exit codes — you get
silence. The safety rules in §6 stop being a coding discipline and become a
structural property: there is no code path by which a sound problem reaches git.

### 4.5 Real git path is resolved at install, not at runtime

The legacy spec claimed both that the real git path is "resolved at install time
and hardcoded ... to prevent PATH hijacking" *and* that the wrapper "locates real
git by finding first `git` binary NOT in `/usr/local/bin`". Those are different
programs; only the first provides the stated protection.

This design resolves once at install, stores the result in config, and re-verifies
it in `doctor`. Verified on this machine: `/usr/bin/git` is a real ELF binary
(not a symlink), root-owned, and **the only git on the system** — so hardcoding is
safe and a runtime `PATH` search would be pure downside.

**Single source of truth.** The path lives in `settings.json` as `real_git`, and
the installer *generates* the shim from a template with that value substituted in
as a literal. The shim therefore never parses config (§5.2) and the two cannot
drift by construction. `doctor` re-reads the path out of the installed shim and
compares it against config, so a hand-edited shim is caught rather than silently
diverging.

---

## 5. Architecture

### 5.1 Layout

```
~/.local/bin/git                         the shim (bash, ~25 lines, generated)
~/.local/share/blaxk-sounds/
    blaxk_sounds/                        Python package
        __init__.py
        config.py                        settings load/save
        player.py                        backend detection + playback
        clip.py                          ffmpeg wrapper
        play.py                          push-path entry: play one event
        cli.py                           user-facing commands
        doctor.py                        chain verification
    sounds/
        start.wav
        success.wav
        fail.wav
~/.config/blaxk-sounds/settings.json     config
$XDG_RUNTIME_DIR/blaxk-sounds.pid        currently-playing sound pid
```

Config and data are deliberately separated: settings you edit vs. wavs you
accumulate. `uninstall` can remove either without destroying the other.

Source repository layout:

```
blaxk_sounds/
    blaxk_sounds/            the Python package (installed to ~/.local/share)
    shim/
        git.sh.template      shim template, REAL_GIT substituted at install
        git.bat.template     phase 2
    install/
        install.sh           no-sudo installer
    tests/
    docs/superpowers/specs/  this document
    README.md
    CLAUDE.md                legacy, to be rewritten (§15)
```

### 5.2 The shim's job

The shim does exactly three things:

1. Determine whether the invocation is a `push` (§5.3).
2. If not, `exec "$REAL_GIT" "$@"` — the shell process is *replaced*, no
   interpreter starts, no overhead.
3. If so, run the sequence in §4.4.

It performs no config parsing and no sound logic. Every line of cleverness added
to the shim is a line that can break git, so it is kept short enough to read in
full when something goes wrong.

The shim is **generated at install from a template**, not copied verbatim. The
only substitution is the `REAL_GIT` literal (§4.5) — which is what lets the shim
avoid parsing config while still knowing where git lives. Regenerating the shim is
how a moved git is accommodated: `doctor` reports the drift, and re-running
install rewrites it.

`enabled` (§8) is deliberately *not* checked here. Muting is handled in
`play.py`, so a disabled system still delegates to Python and Python exits
immediately without playing. This keeps the shim free of config parsing; the cost
is one interpreter start per push while muted, which is tens of milliseconds
against a push that takes seconds.

### 5.3 Subcommand detection

The legacy spec's rule — "is `push` anywhere in the arguments" — is incorrect and
would be noticeable in daily use. `git branch push`, `git log push`, and
`git checkout push` would all fire the success sound.

The correct rule: git's subcommand is the first bare word after the leading
global options. The scanner must skip options *and* the values of options that
consume one.

```bash
# Returns the subcommand on stdout, or nothing if there is none.
find_subcommand() {
    local skip_next=0 arg
    for arg in "$@"; do
        if [ "$skip_next" = 1 ]; then skip_next=0; continue; fi
        case "$arg" in
            -C|-c|--git-dir|--work-tree|--namespace|--exec-path|--config-env)
                skip_next=1 ;;
            -C?*|-c?*)                       # value attached: -C/path, -cfoo=bar
                ;;
            -*)                              # any other option, takes no value
                ;;
            *)   printf '%s' "$arg"; return 0 ;;
        esac
    done
    return 1
}
```

Verified behaviour:

| Invocation | Result | Correct? |
|---|---|---|
| `git push origin main` | push | ✓ |
| `git -C ~/code push` | push | ✓ |
| `git -C~/code push` | push | ✓ |
| `git -c core.pager=cat push` | push | ✓ |
| `git --git-dir=/x/.git push` | push | ✓ |
| `git -p push` | push | ✓ |
| `git branch push` | (none) | ✓ |
| `git log push --oneline` | (none) | ✓ |
| `git checkout push` | (none) | ✓ |
| `git --version` | (none) | ✓ |
| `git` | (none) | ✓ |

**Safety property:** detection only gates *sound*. It never affects how git is
invoked or what it returns. A detection bug can therefore cause a wrong sound,
never wrong git behaviour.

---

## 6. Safety rules

Six rules, all structural rather than aspirational. Rules 1–3 are properties of
the interfaces in §5.1 and §4.4, not invariants a future edit could quietly
violate.

1. **Inherit stdin, stdout, stderr exactly. Never capture.** If the shim consumed
   stdin, a `git push` prompting for credentials would hang forever. This is the
   single most likely way to make git unusable, and it is the reason the shim
   uses `exec` and direct child execution rather than any captured-output call.
2. **Exit code is git's, passed through untouched** — including 128, 129, and 130.
3. **Every sound failure is swallowed.** The shim runs git regardless of what
   happens in the sound path. `player.play()` returns a bool and never raises, and
   `python3 -m blaxk_sounds.play` exiting non-zero or not starting at all changes
   nothing about the push.
4. **Ctrl-C exits 130 with no sound.** Handled natively by the `rc -ne 130` test.
   You already know you cancelled; a failure sound would be wrong.
5. **Sounds are detached** so they outlive the shim. The shim backgrounds the
   player with fds redirected to `/dev/null`; `player.py` additionally spawns the
   audio backend with `start_new_session=True`. A sound is never killed by the
   shim exiting.
6. **A new sound kills the previous one.** The player records its pid in
   `$XDG_RUNTIME_DIR/blaxk-sounds.pid`, kills any still-running predecessor
   before playing, and writes its own. Without this, pushing twice quickly
   overlaps the start sound under the result sound. `$XDG_RUNTIME_DIR` is tmpfs,
   cleared each login — the pidfile needs no cleanup of its own.

---

## 7. Sound system

### 7.1 Events

| Event | Fires |
|---|---|
| `start` | Immediately, before git runs |
| `success` | After git exits 0 |
| `fail` | After git exits non-zero (except 130) |

`git push --dry-run` plays sounds: it is a push subcommand and the rule has no
flag-specific special cases.

### 7.2 Backend selection

Detected at runtime, in priority order. Verified against this machine:

| Probe order | Backend | Present here | Notes |
|---|---|---|---|
| 1 | `pw-play` | ✓ `/usr/bin/pw-play` | Native PipeWire. **Correct first choice on Fedora 44.** |
| 2 | `paplay` | **✗ not installed** | PulseAudio. Kept at position 2 for portability to PulseAudio systems; absent here |
| 3 | `ffplay` | ✓ `/usr/bin/ffplay` | Broadest format support |
| 4 | `aplay` | ✓ `/usr/bin/aplay` | ALSA, `.wav` only |
| — | `winsound` | phase 2 | Windows stdlib, `.wav` only. Selected on Windows instead of this list |

`canberra-gtk-play` is present on this machine but deliberately not probed: it is
designed for desktop event sounds by name, and routing a file path through it adds
a dependency for no gain over `pw-play`.

The legacy spec's priority list is wrong for this machine in both directions: it
ranks `paplay` first when `paplay` is absent, and never mentions `pw-play`, which
is the correct choice here.

Probing means "resolvable on `PATH`", checked in order, falling through on
absence. If no probe succeeds, playback is a silent no-op (§10).

### 7.3 The clip command

```
blaxk-sounds clip <source> --from <time> --len <seconds> --as <event> [--volume 0.0-1.0]
```

Extracts via ffmpeg into a normalized `.wav`: 44.1 kHz, mono, 16-bit PCM. Output
is written to `~/.local/share/blaxk-sounds/sounds/<event>.wav`, overwriting any
existing file for that event, and the event's config entry is updated to point at
it. Normalization is applied at clip time rather than playback time:

- **Format normalization** — every backend on both platforms plays this.
- **Volume** — baked in with `-af volume=N`, default `1.0`. At playback time,
  `pw-play` and `ffplay` accept a volume flag but `aplay` and `winsound` do not,
  which would mean volume that silently does nothing on two of four backends.
  Normalizing at clip time gives one behaviour everywhere. Changing volume means
  re-running `clip`, which is cheap.
- **Length capping** — clips longer than **10 seconds** are refused, since the
  point is feedback, not playback.

`--from` accepts `SS`, `MM:SS`, or `HH:MM:SS`. `--len` accepts seconds as a
decimal. Both are validated against the source's real duration, read with
`ffprobe`; an out-of-range `--from` or a `--len` that overruns the end is
rejected with the actual duration in the message. The source file is never
modified.

Resulting command shape:

```
ffmpeg -nostdin -y -ss <from> -t <len> -i <source> \
       -af volume=<vol> -ac 1 -ar 44100 -c:a pcm_s16le <out>
```

### 7.4 Placeholder sounds

The installer synthesizes three tones with ffmpeg so the system gives feedback the
moment it is installed, rather than presenting an empty config:

- `start` — a short soft blip
- `success` — a rising two-note chime
- `fail` — a low dull thud

Replaced at leisure with `blaxk-sounds clip`. This avoids the dead-end where a
freshly installed system appears to do nothing.

---

## 8. Configuration

`~/.config/blaxk-sounds/settings.json`:

```json
{
  "enabled": true,
  "real_git": "/usr/bin/git",
  "sounds": {
    "start":   "/home/blaxk/.local/share/blaxk-sounds/sounds/start.wav",
    "success": "/home/blaxk/.local/share/blaxk-sounds/sounds/success.wav",
    "fail":    "/home/blaxk/.local/share/blaxk-sounds/sounds/fail.wav"
  }
}
```

Paths are stored expanded and absolute, never with `~` (§9) — the runtime does no
shell expansion. `real_git` is written at install (§4.5). `enabled` is the mute
switch. Environment overrides, checked before config:

| Variable | Effect |
|---|---|
| `BLAXK_SOUNDS_DISABLED=1` | Skip sounds for one command |
| `BLAXK_SOUNDS_CONFIG` | Alternate config path |
| `BLAXK_SOUNDS_PLAYER` | Replace the audio backend command — used by the test suite (§11) |

A missing or corrupt config is regenerated with defaults rather than raising, per
safety rule 3.

---

## 9. CLI

```
blaxk-sounds clip <source> --from <t> --len <s> --as <event>   extract a clip
blaxk-sounds set <event> <path>                                point an event at a file
blaxk-sounds test [event]                                      play it now
blaxk-sounds doctor                                            verify the whole chain
blaxk-sounds enable | disable                                  mute without uninstalling
blaxk-sounds list                                              show current sounds
blaxk-sounds uninstall [--purge]                               remove the shim
```

`test` with no argument plays all three in event order (`start`, `success`,
`fail`) with a one-second gap between them, so they are distinguishable. With an
event name it plays just that one.

`set <event> <path>` validates before writing: the path must exist, be readable,
and be recognized as audio by `ffprobe`. Paths are stored expanded and absolute —
`~` is resolved at write time, not at playback time, so the runtime does no shell
expansion. A file that fails validation is rejected and config is left untouched.

`enable` / `disable` toggle `enabled` in config (§5.2). `list` prints each event,
its file path, and whether that file currently exists — a fast way to spot a
deleted clip without running the full `doctor`.

### 9.1 `doctor`

This is not a nicety. The system is invisible when it works and invisible when it
breaks, so without `doctor` a failure presents as "I guess I'm not hearing
sounds" with ten possible causes. It walks the chain and prints one line per
check:

| Check | Detects |
|---|---|
| Shim installed at `~/.local/bin/git`, executable | clobbered, deleted, chmod lost |
| Shim wins the `PATH` race over `real_git` | a later `PATH` entry shadowing it |
| `real_git` exists, is executable | git moved or removed |
| `real_git` is not the shim itself | **recursion guard** — catastrophic if missed |
| Shim's baked `REAL_GIT` agrees with config | hand-edited shim, or git moved (§4.5) |
| Each wav exists, is readable, parses as audio | deleted or corrupt clips |
| An audio backend is available | all four probes failed |
| PipeWire/PulseAudio session is reachable | audio session down |
| Config parses | corrupt config |
| `ffmpeg` present | `clip` unavailable (warning, not fatal) |

Exit code is non-zero if any check fails, so it can be run from a script.

---

## 10. Error handling

Every runtime failure has the same resolution: **the push proceeds, the sound is
skipped.** No runtime failure is ever surfaced to the user during a push.

| Failure | Result |
|---|---|
| wav missing or corrupt | silence, push proceeds |
| No audio backend found | silence, push proceeds |
| PipeWire/PulseAudio down | silence, push proceeds |
| Config missing or corrupt | defaults regenerated, push proceeds |
| Pidfile unwritable | silence, push proceeds |
| Previous-sound kill fails | proceed, play anyway |
| `python3` missing or broken | silence, push proceeds |
| Unexpected exception anywhere | silence, push proceeds |

Install-time failures are the only loud ones, because you are watching:

| Failure | Behaviour |
|---|---|
| Real git not found | abort install |
| `~/.local/bin/git` exists and is not ours | **refuse, do not clobber** |
| Shim does not win the `PATH` race | install completes, loud warning |
| `ffmpeg` absent | install completes, `clip` disabled, `doctor` reports it |
| No audio backend | install completes, loud warning |

---

## 11. Testing

TDD. Tests are written before the code they cover.

### 11.1 The recorder player

`BLAXK_SOUNDS_PLAYER` (§8) replaces the audio backend with a recorder script that
appends the event name to a file instead of playing. This is what makes the system
testable: assertions are on *which sound fired*, with no noise during test runs,
and no audio session required in the test environment.

### 11.2 End-to-end pushes without a network

Tests push to a **local bare repository**. Real git, real exit codes, real
non-fast-forward rejections — no network, no credentials, no flakiness.

### 11.3 Test plan

| Test | Asserts |
|---|---|
| Shim argv table | Every row of §5.3, run against the **real shim as a subprocess**, not a Python reimplementation |
| End-to-end success | push to bare repo → exit 0 → `success` recorded |
| End-to-end rejection | non-fast-forward push → non-zero → `fail` recorded |
| Start sound ordering | Against a stub git that sleeps, `start` is recorded before the stub exits. Cannot be asserted against a fast real push — the player is backgrounded by design (§6 rule 5), so ordering is only observable when git is slow |
| Exit code fidelity | Break config and player deliberately; git's exit code unchanged |
| stdout/stderr passthrough | git's output reaches the test's captured fds unmodified |
| stdin not consumed | push with stdin supplied is not blocked |
| Ctrl-C / exit 130 | No sound recorded |
| `player.play()` never raises | Missing file, dead backend, garbage bytes → returns `False` |
| Backend probe order | Fake `PATH` with subsets of backends → correct selection, correct fallthrough |
| `clip` argv construction | ffmpeg argv correct for each `--from` format |
| `clip` real extraction | Generate a tone with ffmpeg, clip it, assert duration and format via `ffprobe` |
| `clip` range validation | Out-of-range `--from` rejected with the real duration in the message |
| Pidfile takeover | Second sound kills the first |
| Config round-trip | Save, load, defaults on corrupt |
| `disable` honored | Muted push records no sound; push still exits correctly |
| `set` validation | Missing file, non-audio file both rejected, config unchanged |
| Shim generation | Installer substitutes `REAL_GIT` correctly; regenerating after a move works |
| `doctor` | Deliberately break each check in §9.1, assert each is detected |

### 11.4 What is not tested

- Actual audible output. Verifying a human hears a sound is out of scope; tests
  verify the correct backend was *invoked with the correct file*.
- Windows behaviour, in phase 1.

---

## 12. Reach and known limitations

The shim lives at `~/.local/bin/git`. Verified: this directory is **already first
in `PATH`** (`.zshrc:9` commented out, `.zshrc:128` and `.bashrc:9` active), ahead
of `/usr/local/bin` at position 6 and `/usr/bin` at position 7. No `PATH` surgery
and no `sudo` is required.

Consequences, accepted deliberately:

| Limitation | Cause |
|---|---|
| **No IDE or GUI coverage.** VS Code's git panel, IDE plugins, and terminal-in-IDE pushes are silent. | `~/.zshrc` is sourced only for interactive shells, and `~/.zshenv` does not exist on this machine |
| **Non-interactive scripts are silent.** | Same cause. Considered desirable and also safer: a loop doing ten pushes does not fire ten sounds |
| **Git aliases do not trigger.** `alias.pp = push` means the shim sees `pp`. | Resolving aliases costs a `git config` call in the push path |
| **`/usr/bin/git push` bypasses the shim entirely.** | Inherent to `PATH` interception |

If IDE coverage is wanted later, installing the same shim to `/usr/local/bin/git`
(one `sudo` at install time, nothing running as root) covers GUI applications. Not
in scope for phase 1.

---

## 13. Install and uninstall

**Install** — no `sudo` at any point, idempotent and safe to re-run:

1. Verify `python3` and locate real git; abort if git is missing.
2. Refuse if `~/.local/bin/git` exists and is not ours.
3. Copy the package to `~/.local/share/blaxk-sounds/`.
4. Generate the shim from `shim/git.sh.template` (§5.2), substituting the real git
   path, and write it to `~/.local/bin/git`, mode `0755`.
5. Write default config.
6. Synthesize the three placeholder tones (§7.4).
7. Run `doctor`, print results, warn loudly on any failure.

The project is a git repository so a new machine or a wiped `/home` is a clone
plus one command.

**Uninstall** — `blaxk-sounds uninstall`:

1. Remove `~/.local/bin/git`, and verify real git is reachable afterwards.
2. Remove the Python package directory,
   `~/.local/share/blaxk-sounds/blaxk_sounds/`.
3. **Leave `sounds/` and config in place**, so a reinstall keeps your clips and
   your `real_git` setting.

`--purge` additionally removes `~/.local/share/blaxk-sounds/sounds/` and
`~/.config/blaxk-sounds/`. Note the split from step 2: the package is always
removed, the user's sounds and settings are not.

Emergency manual undo, always available and always sufficient:

```bash
rm ~/.local/bin/git
```

---

## 14. Phase 2 — Windows

Not built in phase 1. Design intent only, so phase 1 does not preclude it:

- **Shim**: `git.bat` in a directory ordered before Git for Windows in the system
  `PATH`. Must invoke real git by absolute path recorded at install, or it
  recurses into itself.
- **Argument forwarding**: `%*` forwards all arguments; quoting and wildcard
  re-expansion are the known hazards and need testing on a real machine.
- **Audio**: `winsound` from the stdlib, `.wav` only — already satisfied, since
  §4.3 normalizes every clip to `.wav` at extraction time.
- **Shared logic**: `config.py`, `clip.py`, and the event lookup are
  platform-neutral and carry over. `player.py` gains a `winsound` branch.
- **Verification**: the author cannot test Windows (this machine is native Fedora,
  no WSL). Phase 2 code ships untested and must be validated by the user.

---

## 15. Legacy document

`CLAUDE.md` in the repository root describes a different system and is wrong in
several load-bearing places:

- Lists `paplay` as the priority-1 backend; it is not installed here, and `pw-play`
  — the correct choice — is never mentioned.
- Claims the real git path is both hardcoded at install *and* resolved at runtime
  by `PATH` search. These contradict.
- Installs to `/opt` and `/usr/local/bin` via `sudo`, which this design rejects.
- Describes the "is `push` in args" detection rule, which misfires on
  `git branch push`.
- Lists `watchdog` as a dependency for "future features" and installs it under
  `sudo`; nothing uses it.

It should be rewritten to describe this design once implementation lands.

---

## 16. Environment verified against

Measured, not assumed:

| | |
|---|---|
| OS | Fedora 44 (Forty Four), kernel 7.1.8-200.fc44.x86_64 |
| Shell | zsh, with bash also present |
| `/home` | LUKS-encrypted btrfs — survives reboot and in-place upgrades |
| Audio | PipeWire + pipewire-pulse active; PulseAudio inactive |
| Audio backends | `pw-play`, `ffplay`, `aplay`, `canberra-gtk-play` present; **`paplay` absent** |
| Python | 3.14.6 |
| ffmpeg | 8.1.2 |
| git | 2.55.0, `/usr/bin/git`, real ELF binary, the only git on the system |
| `PATH` | `~/.local/bin` first; `/usr/local/bin` 6th; `/usr/bin` 7th |
| `~/.zshenv` | does not exist |
| Existing wrapper | none — `/usr/local/bin/git` is absent |
