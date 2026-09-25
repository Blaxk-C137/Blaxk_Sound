# blaxk-sounds

Sound feedback for `git push`. A short blip when the push starts, a rising chime
when it succeeds, a low thud when it fails. You type normal git commands; the
sound happens on its own.

## Install

```bash
bash install/install.sh
```

No `sudo`. It installs a shim at `~/.local/bin/git`, the `blaxk-sounds` command
next to it, a copy of the package under `~/.local/share/blaxk-sounds`, and three
placeholder tones. Safe to re-run, and it refuses to overwrite a `git` at that
path that is not its own.

`~/.local/bin` has to come before `/usr/bin` in your `PATH`. It already does on
this machine. If `which git` does not print `~/.local/bin/git` after installing,
`blaxk-sounds doctor` will say so.

## The three events

| Event | When it fires |
|---|---|
| `start` | The moment a push begins, before git runs |
| `success` | git exited 0 |
| `fail` | git exited non-zero (rejected, no network, auth, anything) |

A new sound always kills the previous one, so a fast push does not leave the
start blip playing over the result.

## Using a real sound

The placeholder tones are there so it works the moment it is installed. To use a
piece of actual music, cut a clip out of it:

```bash
blaxk-sounds clip ~/Music/track.mp3 --from 1:12 --len 0.6 --as success
blaxk-sounds test success
```

`--from` takes `SS`, `MM:SS`, or `HH:MM:SS`. `--len` is in seconds and is capped
at 10, because this is feedback, not playback. Optional `--volume 0.7` scales it.
Clips are normalized to mono 44.1 kHz 16-bit PCM so every backend plays them with
no per-backend volume or format surprises.

`clip` writes the result into the sounds directory and points the event at it, so
there is no second step.

To point an event at a file you already have:

```bash
blaxk-sounds set success ~/Sounds/win.wav
```

`set` checks the file exists, is readable, and `ffprobe` recognizes it as audio
before writing anything.

## Commands

```
blaxk-sounds set <event> <path>     point an event at a sound file
blaxk-sounds clip <src> --from T --len S --as <event>   cut a clip from audio
blaxk-sounds test [event]           play one event, or all three
blaxk-sounds list                   show what is configured and what is missing
blaxk-sounds enable | disable       mute or unmute without uninstalling
blaxk-sounds doctor                 check the whole chain, link by link
blaxk-sounds uninstall [--purge]    remove the shim; --purge also drops your sounds
```

## Muting

```bash
blaxk-sounds disable        # until you turn it back on
BLAXK_SOUNDS_DISABLED=1 git push   # for one command
```

## When sound stops working

```bash
blaxk-sounds doctor
```

It checks ten links in the chain: the shim is installed and executable, it wins
`PATH`, the real git it points at still exists, the shim is not pointing at
itself, the shim's baked-in paths match your config, the config parses, all three
sounds are present and readable as audio, an audio backend exists, there is a
live audio session, and `ffmpeg` is available. It prints a line per check and
exits non-zero on a real failure. This system is silent when it works and silent
when it breaks, so doctor is the difference between "I guess I'm not hearing
sounds" and the actual cause.

## Uninstall

```bash
blaxk-sounds uninstall          # removes the shim and the package, keeps your sounds
blaxk-sounds uninstall --purge  # also removes your sounds and config
```

It refuses to delete a `~/.local/bin/git` that is not its own unless you pass
`--purge`.

## Known limitations

These are accepted, not bugs:

- **No IDE or GUI coverage.** VS Code's git panel, IDE plugins, and pushes made
  from a terminal inside an IDE are silent. The shim is found through `~/.zshrc`,
  which only interactive shells source.
- **Non-interactive scripts are silent.** Same cause. This is also the safer
  behavior: a loop doing ten pushes does not fire ten sounds.
- **Git aliases do not trigger.** If `pp` is an alias for `push`, the shim sees
  `pp` and treats it as an ordinary command. Resolving aliases would cost a `git
  config` call on every push.
- **`/usr/bin/git push` bypasses it entirely.** Inherent to `PATH`
  interception. Use `git push`.
- **Interactive prompts still work.** `git push` asking for a password or
  prompting for credentials behaves exactly as before; stdin is passed straight
  through and never consumed.

Covering GUI applications would mean installing the same shim to
`/usr/local/bin/git` with one `sudo` at install time. Nothing runs as root
either way.
