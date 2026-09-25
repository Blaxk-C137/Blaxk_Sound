"""Verify the whole chain.

This system is invisible when it works and invisible when it breaks, so without
a doctor a failure presents as "I guess I'm not hearing sounds" with ten
possible causes (spec section 9.1).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from . import config, player


class Check(NamedTuple):
    name: str
    ok: bool
    detail: str
    fatal: bool = True


def shim_path() -> Path:
    return Path.home() / ".local" / "bin" / "git"


def cli_path() -> Path:
    return Path.home() / ".local" / "bin" / "blaxk-sounds"


def install_dir() -> Path:
    return config.data_dir()


def check_shim_installed(shim: Path) -> Check:
    if not shim.exists():
        return Check("shim installed", False, f"not found at {shim}")
    if not os.access(shim, os.X_OK):
        return Check("shim installed", False, f"{shim} is not executable")
    return Check("shim installed", True, str(shim))


def check_shim_wins_path(shim: Path) -> Check:
    resolved = shutil.which("git")
    if resolved is None:
        return Check("shim wins PATH", False, "no git found on PATH")
    if Path(resolved).resolve() != shim.resolve():
        return Check(
            "shim wins PATH",
            False,
            f"PATH resolves git to {resolved}, not {shim}",
        )
    return Check("shim wins PATH", True, f"{shim} is first")


def check_real_git(path: str) -> Check:
    if not path or not os.path.isfile(path):
        return Check("real git", False, f"{path} does not exist")
    if not os.access(path, os.X_OK):
        return Check("real git", False, f"{path} is not executable")
    return Check("real git", True, path)


def check_not_recursive(real_git: str, shim: Path) -> Check:
    try:
        same = Path(real_git).resolve() == shim.resolve()
    except Exception:
        same = False
    if same:
        return Check(
            "recursion guard",
            False,
            f"real git IS the shim ({real_git}) - every git call would recurse",
        )
    return Check("recursion guard", True, "real git differs from the shim")


def _read_literal(text: str, name: str) -> str | None:
    match = re.search(rf'^{name}="([^"]*)"', text, re.MULTILINE)
    return match.group(1) if match else None


def check_shim_literals(shim: Path, settings: dict, expected_install_dir: Path) -> Check:
    try:
        text = shim.read_text(encoding="utf-8")
    except Exception as exc:
        return Check("shim literals", False, f"cannot read shim: {exc}")

    baked_git = _read_literal(text, "REAL_GIT")
    baked_dir = _read_literal(text, "INSTALL_DIR")
    if baked_git is None or baked_dir is None:
        return Check("shim literals", False, "shim is missing REAL_GIT or INSTALL_DIR")

    configured = settings.get("real_git")
    if baked_git != configured:
        return Check(
            "shim literals",
            False,
            f"shim has REAL_GIT={baked_git} but config says {configured}; re-run install",
        )
    if Path(baked_dir) != Path(expected_install_dir):
        return Check(
            "shim literals",
            False,
            f"shim has INSTALL_DIR={baked_dir}, expected {expected_install_dir}",
        )
    return Check("shim literals", True, f"{baked_git} / {baked_dir}")


def check_sounds(settings: dict) -> list[Check]:
    checks = []
    sounds = settings.get("sounds") or {}
    for event in config.EVENTS:
        name = f"sound: {event}"
        path = sounds.get(event)
        if not path:
            checks.append(Check(name, False, "no file configured"))
            continue
        if not os.path.isfile(path):
            checks.append(Check(name, False, f"{path} does not exist"))
            continue
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as exc:
            checks.append(Check(name, False, f"ffprobe failed: {exc}", fatal=False))
            continue
        if probe.returncode != 0 or not probe.stdout.strip():
            checks.append(Check(name, False, f"{path} is not readable as audio"))
        else:
            checks.append(Check(name, True, f"{path} ({probe.stdout.strip()})"))
    return checks


def check_backend() -> Check:
    found = player.detect_backend()
    if found is None:
        return Check("audio backend", False, "none of pw-play, paplay, ffplay, aplay found")
    return Check("audio backend", True, found[0])


def check_audio_session() -> Check:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        return Check("audio session", False, "XDG_RUNTIME_DIR is not set")
    root = Path(runtime)
    for candidate in ("pipewire-0", "pulse/native"):
        if (root / candidate).exists():
            return Check("audio session", True, str(root / candidate))
    return Check("audio session", False, f"no socket under {root}")


def check_config_parses() -> Check:
    path = config.config_path()
    if not path.exists():
        return Check("config parses", True, f"{path} absent, defaults will be used", fatal=False)
    try:
        config.load_settings()
    except Exception as exc:  # load_settings never raises, but be explicit
        return Check("config parses", False, str(exc))
    return Check("config parses", True, str(path))


def check_ffmpeg() -> Check:
    if shutil.which("ffmpeg") is None:
        return Check("ffmpeg present", False, "clip extraction unavailable", fatal=False)
    return Check("ffmpeg present", True, shutil.which("ffmpeg"))


def run_checks() -> list[Check]:
    settings = config.load_settings()
    shim = shim_path()
    checks = [
        check_shim_installed(shim),
        check_shim_wins_path(shim),
        check_real_git(settings.get("real_git", "")),
        check_not_recursive(settings.get("real_git", ""), shim),
        check_shim_literals(shim, settings, install_dir()),
        check_config_parses(),
        check_backend(),
        check_audio_session(),
        check_ffmpeg(),
    ]
    checks.extend(check_sounds(settings))
    return checks


def main(argv: list[str]) -> int:
    checks = run_checks()
    failed = 0
    for check in checks:
        mark = "ok  " if check.ok else ("FAIL" if check.fatal else "warn")
        print(f"[{mark}] {check.name}: {check.detail}")
        if not check.ok and check.fatal:
            failed += 1
    print()
    if failed:
        print(f"{failed} check(s) failed.")
    else:
        print("All checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
