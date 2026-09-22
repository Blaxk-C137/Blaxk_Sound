# CLAUDE.md

```markdown
# CLAUDE.md - Git Sound Feedback System

## Project Overview

A cross-platform daemon that intercepts `git push` commands and plays
custom sounds based on the result. Works transparently - the user types
normal git commands and sounds play automatically.

**Supported Platforms:**
- Fedora Linux (primary)
- Windows 10/11
- Other Linux distros (Ubuntu, Debian, Arch) with minor adjustments

---

## Project Structure

```
git-sound-feedback/
├── CLAUDE.md                        # This file
├── README.md
├── requirements.txt
│
├── daemon/
│   ├── main.py                      # Entry point, argument parsing
│   ├── config.py                    # Settings load/save, path resolution
│   ├── sound_player.py              # Cross-platform audio playback
│   ├── monitor.py                   # Git output monitoring logic
│   ├── git_wrapper.sh               # Linux bash wrapper (replaces /usr/local/bin/git)
│   └── git_wrapper.bat              # Windows batch wrapper
│
├── sounds/
│   └── default/
│       ├── push_success.wav         # Played on exit code 0
│       ├── push_fail.wav            # Played on non-zero exit code
│       └── push_start.wav           # Played immediately when push begins
│
├── config/
│   └── settings.json                # User config (auto-generated on first run)
│
└── install/
    ├── install_linux.sh             # Fedora/Linux installer
    └── install_windows.bat          # Windows installer
```

---

## Architecture

### How Interception Works

```
User types: git push -u origin main
                  │
                  ▼
    /usr/local/bin/git          ← our bash wrapper (found first in PATH)
                  │
                  ├─ is "push" in args?
                  │
                  │   NO  ──► exec /usr/bin/git "$@"   (real git, zero overhead)
                  │
                  └─ YES ──► python3 /opt/git-sound-feedback/daemon/main.py push \
                                     /usr/bin/git "$@"
                                          │
                                          ├─ play push_start.wav
                                          │
                                          ├─ subprocess.run([real_git] + all_args)
                                          │   (output streams directly to terminal)
                                          │
                                          ├─ exit 0  ──► play push_success.wav
                                          └─ exit 1+ ──► play push_fail.wav
```

### Why `/usr/local/bin` Works

Linux PATH order is typically:
```
/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin
```
Our wrapper at `/usr/local/bin/git` is found **before** the real git
at `/usr/bin/git`. The real git binary is **never modified or moved**.

### Windows Equivalent

The wrapper `.bat` file is placed in a directory that appears before
the real Git for Windows location in the system `PATH` environment variable.

---

## Core Components

### `daemon/main.py`
- Entry point for all operations
- Parses subcommands: `push`, `config`, `test`
- Called by the shell wrapper with: `main.py push <real_git_path> <all_original_args>`
- Loads settings and initializes `SoundPlayer` on every invocation
- Routes to correct handler function
- Exits with the same exit code as the real git process

### `daemon/config.py`
- Resolves config directory based on OS:
  - Linux:   `~/.config/git-sound-feedback/settings.json`
  - Windows: `%APPDATA%\git-sound-feedback\settings.json`
- Creates default config on first run
- Exposes `load_settings()` and `save_settings()`
- Default settings structure:
  ```json
  {
      "sounds": {
          "push_success": "sounds/default/push_success.wav",
          "push_fail":    "sounds/default/push_fail.wav",
          "push_start":   "sounds/default/push_start.wav"
      },
      "volume": 1.0,
      "enabled": true,
      "log_level": "INFO"
  }
  ```

### `daemon/sound_player.py`
- Detects OS and available audio backends at init time
- Linux backend priority order:
  1. `paplay`  (PulseAudio - default on Fedora)
  2. `aplay`   (ALSA)
  3. `mpg123`  (MP3 support)
  4. `ffplay`  (ffmpeg, broadest format support)
- Windows backend: `winsound` (stdlib, no extra install)
- All playback is **non-blocking** (does not delay git output)
- Logs a warning if no backend is found, does not crash

### `daemon/monitor.py`
- `GitOutputMonitor` class wraps git push execution
- Passes **all original arguments** through to real git untouched
- Streams stdout/stderr directly to terminal in real time
- Checks `returncode` for success/fail determination
- Does NOT parse git output text (returncode is more reliable)

### `daemon/git_wrapper.sh`
- Bash script installed at `/usr/local/bin/git`
- Locates real git by finding first `git` binary NOT in `/usr/local/bin`
- For non-push commands uses `exec` (replaces shell process, no overhead)
- For push commands delegates to Python with full arg passthrough

---

## Data Flow

### Push Command (happy path)
```
1. User runs:     git push -u origin main
2. Wrapper runs:  python3 main.py push /usr/bin/git push -u origin main
3. main.py:       loads settings.json
4. main.py:       initializes SoundPlayer (detects paplay)
5. main.py:       calls run_push("/usr/bin/git", ["push", "-u", "origin", "main"])
6. run_push:      plays push_start.wav (non-blocking)
7. run_push:      subprocess.run(["/usr/bin/git", "push", "-u", "origin", "main"])
8. terminal:      shows real git output as it happens
9. run_push:      returncode == 0
10. run_push:     plays push_success.wav (non-blocking)
11. main.py:      sys.exit(0)
12. wrapper:      exits with code 0
```

### Non-Push Command (zero overhead path)
```
1. User runs:  git status
2. Wrapper:    "push" not in args
3. Wrapper:    exec /usr/bin/git status
4. Shell:      wrapper process IS REPLACED by real git (exec)
               no Python ever starts
               no overhead whatsoever
```

---

## Configuration System

### Settings File Location
| OS      | Path |
|---------|------|
| Linux   | `~/.config/git-sound-feedback/settings.json` |
| Windows | `%APPDATA%\git-sound-feedback\settings.json` |

### Sound Event Names
| Event           | When It Fires |
|-----------------|---------------|
| `push_start`    | Immediately when push begins, before git runs |
| `push_success`  | After git exits with code 0 |
| `push_fail`     | After git exits with any non-zero code |

### Config Commands
```bash
# View full config
git-sound-config config --list

# Set a custom sound
git-sound-config config --sound push_success --path /home/user/sounds/win.wav
git-sound-config config --sound push_fail    --path /home/user/sounds/fail.wav
git-sound-config config --sound push_start   --path /home/user/sounds/start.wav

# Adjust volume (0.0 = silent, 1.0 = full)
git-sound-config config --volume 0.7

# Toggle sounds without uninstalling
git-sound-config config --disable
git-sound-config config --enable

# Test a sound plays correctly
git-sound-config test push_success
git-sound-config test push_fail
git-sound-config test push_start
```

---

## Installation

### Linux / Fedora
```bash
git clone <repo>
cd git-sound-feedback/install
chmod +x install_linux.sh
sudo ./install_linux.sh
```

**What the installer does:**
1. Installs system packages: `python3`, `python3-pip`, `pulseaudio-utils`
2. Installs Python packages: `watchdog`
3. Copies app to `/opt/git-sound-feedback/`
4. Installs wrapper to `/usr/local/bin/git`
5. Makes wrapper executable
6. Installs `git-sound-config` helper to `/usr/local/bin/`

### Windows
```batch
cd install
install_windows.bat
```

**What the installer does:**
1. Verifies Python is installed
2. Installs Python packages: `watchdog`
3. Copies app to `%PROGRAMFILES%\git-sound-feedback\`
4. Places `git.bat` wrapper in a PATH-priority directory
5. Installs `git-sound-config.bat` helper

### Verify Installation
```bash
# Linux
which git                    # should show /usr/local/bin/git
git push --help              # should work normally
git-sound-config test        # should play a sound

# Windows
where git                    # should show wrapper location first
git-sound-config test
```

---

## Dependencies

### Python (all platforms)
| Package    | Version  | Purpose |
|------------|----------|---------|
| `watchdog` | >=3.0.0  | Filesystem monitoring (future features) |

### System - Linux
| Package            | Purpose |
|--------------------|---------|
| `python3`          | Runtime |
| `pulseaudio-utils` | `paplay` command for audio |
| `alsa-utils`       | `aplay` fallback |

### System - Windows
| Package   | Purpose |
|-----------|---------|
| `Python`  | Runtime (from python.org) |
| `winsound`| Audio playback (Python stdlib, no install needed) |

### Audio File Format
- **Required:** `.wav` format for maximum compatibility
- `winsound` (Windows) only supports `.wav`
- `aplay` (Linux ALSA) only supports `.wav`
- `paplay` and `ffplay` support broader formats but `.wav` is safest
- Recommended: 16-bit PCM, 44100Hz, stereo or mono

---

## Sound Files

### Default Sounds Location
```
/opt/git-sound-feedback/sounds/default/   (Linux)
%PROGRAMFILES%\git-sound-feedback\sounds\default\   (Windows)
```

### Adding Custom Sounds
1. Place your `.wav` file anywhere accessible
2. Run config command:
   ```bash
   git-sound-config config --sound push_success --path /path/to/mysound.wav
   ```
3. Test it:
   ```bash
   git-sound-config test push_success
   ```

### Recommended Sound Sources
- freesound.org (Creative Commons)
- Your own recordings
- Any `.wav` converter from `.mp3`/`.ogg` etc.

---

## Troubleshooting

### No Sound Playing
```bash
# 1. Check if sounds are enabled
git-sound-config config --list

# 2. Test direct playback
paplay /opt/git-sound-feedback/sounds/default/push_success.wav

# 3. Check backend detection
python3 -c "from daemon.sound_player import SoundPlayer; SoundPlayer()"

# 4. Check sound file exists
ls -la /opt/git-sound-feedback/sounds/default/

# 5. Check volume is not zero
git-sound-config config --volume 1.0
```

### Git Commands Broken After Install
```bash
# Verify wrapper can find real git
bash -x /usr/local/bin/git status

# Check real git location
which -a git

# Emergency - remove wrapper to restore normal git
sudo rm /usr/local/bin/git

# Then reinstall after fixing the issue
```

### Python Not Found
```bash
# Fedora
sudo dnf install python3

# Check path in wrapper matches your python
which python3
# Update INSTALL_DIR/daemon/git_wrapper.sh first line if needed
```

### Sounds Play But Git Output Is Delayed
- This should not happen - output is streamed directly
- If it does, check that `subprocess.run()` is NOT using `capture_output=True`
- The `run_push()` function must not capture stdout/stderr

### PulseAudio Not Running (Fedora/Linux)
```bash
# Start PulseAudio
pulseaudio --start

# Or use PipeWire (modern Fedora)
systemctl --user start pipewire pipewire-pulse

# Switch backend to aplay instead
git-sound-config config --backend aplay   # (if backend switching added)
```

### Windows: Wrong Git Being Called
```batch
:: Check PATH order
where git

:: The wrapper directory must appear BEFORE Git for Windows
:: Check system PATH in:
:: Control Panel > System > Advanced > Environment Variables
```

---

## Development

### Running Without Installing
```bash
# From project root
python3 daemon/main.py test push_success
python3 daemon/main.py config --list
python3 daemon/main.py push /usr/bin/git push origin main
```

### Running Tests
```bash
# No test framework yet - use manual tests
python3 daemon/main.py test push_success
python3 daemon/main.py test push_fail
python3 daemon/main.py test push_start
```

### Adding a New Sound Event
1. Add event name to `DEFAULT_SETTINGS["sounds"]` in `config.py`
2. Add the `.wav` file to `sounds/default/`
3. Call `play_event("your_event", player, settings)` in `main.py`
4. Update this documentation

### Adding a New Git Command (e.g., git commit sounds)
1. Add patterns to `git_wrapper.sh`:
   ```bash
   IS_COMMIT=false
   for arg in "$@"; do
       if [ "$arg" = "commit" ]; then IS_COMMIT=true; break; fi
   done
   ```
2. Add handling in `main.py`
3. Add new sound events to config
4. Add new `.wav` files

### Modifying the Wrapper
After editing `git_wrapper.sh`, reinstall it:
```bash
sudo cp daemon/git_wrapper.sh /usr/local/bin/git
sudo chmod +x /usr/local/bin/git
```

---

## Uninstall

### Linux
```bash
# Remove wrapper (restores normal git behavior immediately)
sudo rm /usr/local/bin/git

# Remove app files
sudo rm -rf /opt/git-sound-feedback

# Remove config (optional - keeps your sound customizations)
rm -rf ~/.config/git-sound-feedback

# Remove helper command
sudo rm /usr/local/bin/git-sound-config
```

### Windows
```batch
:: Run uninstaller or manually:
del "%INSTALL_DIR%\git.bat"
rmdir /S /Q "%PROGRAMFILES%\git-sound-feedback"
```

---

## Known Limitations

| Limitation | Detail |
|------------|--------|
| `.wav` only on Windows | `winsound` does not support mp3/ogg |
| Sound timing | `push_fail` plays after git finishes, not during |
| No per-repo sounds | Same sounds for all repos (planned feature) |
| No network detection | Does not distinguish timeout vs auth failure |
| Root process | Wrapper runs as calling user, not true root daemon |
| WSL | Not tested in Windows Subsystem for Linux |

---

## Planned Features

- [ ] Per-repository sound profiles
- [ ] Additional git events: `commit`, `merge`, `pull`, `clone`
- [ ] GUI configuration tool (tkinter)
- [ ] Sound themes (sets of sounds that go together)
- [ ] GitHub Actions status monitoring (poll after push)
- [ ] Notification popup alongside sound
- [ ] Volume fade in/out
- [ ] `.mp3` / `.ogg` support via ffplay backend
- [ ] Shell completion for `git-sound-config`

---

## Security Notes

- The wrapper runs as the **calling user**, not root
- The wrapper only delegates to the real git binary
- No network access by the sound system itself
- Config file is user-owned and user-readable only
- The real git binary path is resolved at install time and hardcoded
  in the wrapper to prevent PATH hijacking of the real git
- Sound files are never executed, only passed to audio player

---

## Environment Variables

| Variable              | Purpose |
|-----------------------|---------|
| `GIT_SOUND_DISABLED`  | Set to `1` to skip sounds for one command |
| `GIT_SOUND_CONFIG`    | Override config file path |
| `GIT_SOUND_LOG`       | Set log level: DEBUG, INFO, WARNING, ERROR |

Usage:
```bash
GIT_SOUND_DISABLED=1 git push origin main   # no sounds this time
GIT_SOUND_LOG=DEBUG git push origin main    # verbose output
```
```
