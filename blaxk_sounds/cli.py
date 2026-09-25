"""User-facing commands."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from . import clip, config, doctor, player


def _is_audio(path: str) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _cmd_set(args) -> int:
    if args.event not in config.EVENTS:
        print(
            f"unknown event {args.event!r}: expected one of {', '.join(config.EVENTS)}",
            file=sys.stderr,
        )
        return 1

    path = Path(args.path).expanduser()
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 1
    if not _is_audio(str(path)):
        print(f"not readable as audio: {path}", file=sys.stderr)
        return 1

    settings = config.load_settings()
    settings.setdefault("sounds", {})[args.event] = str(path.resolve())
    if not config.save_settings(settings):
        print(f"could not write config at {config.config_path()}", file=sys.stderr)
        return 1
    print(f"{args.event} -> {path.resolve()}")
    return 0


def _cmd_clip(args) -> int:
    try:
        from_s = clip.parse_time(args.from_)
        length_s = float(args.len)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        out = clip.extract(args.source, from_s, length_s, args.event, args.volume)
    except Exception as exc:
        print(f"clip failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.event} -> {out}")
    return 0


def _cmd_test(args) -> int:
    settings = config.load_settings()
    events = [args.event] if args.event else list(config.EVENTS)
    for index, event in enumerate(events):
        path = (settings.get("sounds") or {}).get(event)
        if not path:
            print(f"{event}: no sound configured", file=sys.stderr)
            continue
        player.play(path)
        print(f"{event}: {path}")
        if index < len(events) - 1:
            time.sleep(1.0)
    return 0


def _cmd_list(args) -> int:
    settings = config.load_settings()
    sounds = settings.get("sounds") or {}
    print(f"enabled: {settings.get('enabled', True)}")
    print(f"real git: {settings.get('real_git')}")
    print(f"config: {config.config_path()}")
    print()
    for event in config.EVENTS:
        path = sounds.get(event)
        if not path:
            state = "missing (not configured)"
        elif os.path.isfile(path):
            state = "ok"
        else:
            state = "missing"
        print(f"{event:8} {state:22} {path}")
    return 0


def _cmd_enable(args) -> int:
    settings = config.load_settings()
    settings["enabled"] = bool(args.enabled)
    if not config.save_settings(settings):
        print("could not write config", file=sys.stderr)
        return 1
    print("sounds enabled" if args.enabled else "sounds disabled")
    return 0


def _is_ours(path: Path, marker: str) -> bool:
    try:
        return marker in path.read_text(encoding="utf-8")
    except Exception:
        return False


def _cmd_uninstall(args) -> int:
    # Every path we might delete, with the marker that proves it is ours. The
    # ownership check does not depend on --purge: --purge drops sounds and
    # config, and must never double as an override of the guard protecting a
    # git or a command somebody else put at these paths.
    targets = (
        (doctor.shim_path(), "blaxk-sounds git shim"),
        (doctor.cli_path(), "blaxk-sounds CLI wrapper"),
    )

    # Check all of them before removing any, so a refusal leaves nothing
    # half-removed.
    for path, marker in targets:
        if path.exists() and not _is_ours(path, marker):
            print(
                f"{path} does not look like ours; refusing to remove anything",
                file=sys.stderr,
            )
            return 1

    for path, _ in targets:
        if path.exists():
            path.unlink()
            print(f"removed {path}")

    package = config.data_dir() / "blaxk_sounds"
    if package.exists():
        import shutil as _shutil

        _shutil.rmtree(package)
        print(f"removed {package}")

    if args.purge:
        import shutil as _shutil

        for target in (config.sounds_dir(), config.config_path().parent):
            if target.exists():
                _shutil.rmtree(target)
                print(f"removed {target}")
        print("purged sounds and config")
    else:
        print("kept your sounds and config; pass --purge to remove them")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blaxk-sounds", description="Sound feedback for git push."
    )
    sub = parser.add_subparsers(dest="command")

    set_p = sub.add_parser("set", help="point an event at a sound file")
    # No choices= here: argparse would sys.exit(2) on an unknown event, escaping
    # cli.main's int contract and short-circuiting _cmd_set's own check.
    set_p.add_argument("event", metavar="{" + ",".join(config.EVENTS) + "}")
    set_p.add_argument("path")
    set_p.set_defaults(func=_cmd_set)

    clip_p = sub.add_parser("clip", help="extract a clip from an audio file")
    clip_p.add_argument("source")
    clip_p.add_argument("--from", dest="from_", required=True, help="SS, MM:SS, or HH:MM:SS")
    clip_p.add_argument("--len", required=True, help="length in seconds")
    clip_p.add_argument("--as", dest="event", required=True, choices=config.EVENTS)
    clip_p.add_argument("--volume", type=float, default=1.0)
    clip_p.set_defaults(func=_cmd_clip)

    test_p = sub.add_parser("test", help="play a sound now")
    test_p.add_argument("event", nargs="?", choices=config.EVENTS)
    test_p.set_defaults(func=_cmd_test)

    list_p = sub.add_parser("list", help="show current sounds")
    list_p.set_defaults(func=_cmd_list)

    for name, value, help_text in (
        ("enable", True, "turn sounds on"),
        ("disable", False, "turn sounds off"),
    ):
        toggle = sub.add_parser(name, help=help_text)
        toggle.set_defaults(func=_cmd_enable, enabled=value)

    uninstall_p = sub.add_parser("uninstall", help="remove the shim")
    uninstall_p.add_argument("--purge", action="store_true")
    uninstall_p.set_defaults(func=_cmd_uninstall)

    doctor_p = sub.add_parser("doctor", help="verify the whole chain")
    doctor_p.set_defaults(func=lambda args: doctor.main([]))

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
