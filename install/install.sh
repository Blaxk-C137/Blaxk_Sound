#!/usr/bin/env bash
# install/install.sh - no sudo, idempotent, safe to re-run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHIM_DEST="$HOME/.local/bin/git"
CLI_DEST="$HOME/.local/bin/blaxk-sounds"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/blaxk-sounds"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/blaxk-sounds"
SOUNDS_DIR="$INSTALL_DIR/sounds"

warn() { printf 'warning: %s\n' "$*" >&2; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- 1. Preconditions -------------------------------------------------------
command -v python3 >/dev/null 2>&1 || fail "python3 not found on PATH"

REAL_GIT=""
for candidate in /usr/bin/git /usr/local/bin/git /bin/git; do
    if [ -x "$candidate" ] && [ "$candidate" != "$SHIM_DEST" ]; then
        REAL_GIT="$candidate"
        break
    fi
done
[ -n "$REAL_GIT" ] || fail "could not find a real git binary"

# --- 2. Refuse to clobber something that is not ours ------------------------
if [ -e "$SHIM_DEST" ] && ! grep -q "blaxk-sounds git shim" "$SHIM_DEST" 2>/dev/null; then
    fail "$SHIM_DEST exists and is not ours; refusing to overwrite it"
fi

# --- 3. Install the package -------------------------------------------------
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/blaxk_sounds"
cp -r "$REPO_ROOT/blaxk_sounds" "$INSTALL_DIR/blaxk_sounds"

# --- 4. Generate the shim ---------------------------------------------------
mkdir -p "$(dirname "$SHIM_DEST")"
sed -e "s|__REAL_GIT__|$REAL_GIT|g" \
    -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    "$REPO_ROOT/shim/git.sh.template" > "$SHIM_DEST"
chmod 0755 "$SHIM_DEST"

# --- 4b. Generate the CLI wrapper -------------------------------------------
sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    "$REPO_ROOT/install/blaxk-sounds.template" > "$CLI_DEST"
chmod 0755 "$CLI_DEST"

# --- 5. Default config ------------------------------------------------------
mkdir -p "$CONFIG_DIR"
if [ ! -e "$CONFIG_DIR/settings.json" ]; then
    mkdir -p "$SOUNDS_DIR"
    cat > "$CONFIG_DIR/settings.json" <<JSON
{
  "enabled": true,
  "real_git": "$REAL_GIT",
  "sounds": {
    "start": "$SOUNDS_DIR/start.wav",
    "success": "$SOUNDS_DIR/success.wav",
    "fail": "$SOUNDS_DIR/fail.wav"
  }
}
JSON
else
    # Spec 4.5: re-running install is the remedy when git moves. doctor prints
    # "re-run install" when the shim's REAL_GIT and config.real_git disagree, so
    # re-running has to reconcile them, not rewrite only the shim and leave the
    # printed remedy permanently broken.
    PYTHONPATH="$INSTALL_DIR" python3 - "$REAL_GIT" <<'PY'
import sys

from blaxk_sounds import config

settings = config.load_settings()
if settings.get("real_git") != sys.argv[1]:
    settings["real_git"] = sys.argv[1]
    config.save_settings(settings)
PY
fi

# --- 6. Placeholder tones, so it works immediately --------------------------
# Spec 7.4: a short soft blip, a rising two-note chime, and a low dull thud.
if command -v ffmpeg >/dev/null 2>&1; then
    mkdir -p "$SOUNDS_DIR"
    normalize() { # $1 dest, $2 lavfi source, $3 audio filter
        ffmpeg -hide_banner -loglevel error -f lavfi -i "$2" \
            -af "$3" -ac 1 -ar 44100 -c:a pcm_s16le -y "$1"
    }
    [ -e "$SOUNDS_DIR/start.wav" ] || normalize "$SOUNDS_DIR/start.wav" \
        "sine=frequency=700:duration=0.08" "volume=0.30"
    if [ ! -e "$SOUNDS_DIR/success.wav" ]; then
        # Two rising notes (660Hz then 990Hz) concatenated into one chime.
        ffmpeg -hide_banner -loglevel error \
            -f lavfi -i "sine=frequency=660:duration=0.09" \
            -f lavfi -i "sine=frequency=990:duration=0.16" \
            -filter_complex "[0:a][1:a]concat=n=2:v=0:a=1,volume=0.40" \
            -ac 1 -ar 44100 -c:a pcm_s16le -y "$SOUNDS_DIR/success.wav"
    fi
    [ -e "$SOUNDS_DIR/fail.wav" ] || normalize "$SOUNDS_DIR/fail.wav" \
        "sine=frequency=150:duration=0.32" "volume=0.45"
else
    warn "ffmpeg not found: placeholder tones not generated and 'clip' unavailable"
fi

# --- 7. Verify --------------------------------------------------------------
# No PATH prepend here on purpose. doctor is run as a module, so it needs
# nothing from PATH, and prepending the shim's own directory would guarantee
# "shim wins PATH" passes by construction - the one check that catches a PATH
# without ~/.local/bin ahead of /usr/bin, which is the whole install.
PYTHONPATH="$INSTALL_DIR" \
    python3 -m blaxk_sounds.doctor || warn "doctor reported problems (see above)"

echo
echo "installed. Try:  blaxk-sounds test"
