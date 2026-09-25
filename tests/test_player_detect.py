import pytest

from blaxk_sounds import player


def test_probe_order_is_pw_play_then_paplay_then_ffplay_then_aplay():
    names = [name for name, _ in player.backend_candidates()]
    assert names == ["pw-play", "paplay", "ffplay", "aplay"]


def test_detects_pw_play_first(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("pw-play", "aplay"):
        (bindir / name).write_text("#!/bin/sh\n")
        (bindir / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert player.detect_backend()[0] == "pw-play"


def test_falls_through_to_aplay_when_others_absent(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aplay").write_text("#!/bin/sh\n")
    (bindir / "aplay").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert player.detect_backend()[0] == "aplay"


def test_returns_none_when_nothing_available(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert player.detect_backend() is None


def test_argv_prefix_matches_backend(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ffplay").write_text("#!/bin/sh\n")
    (bindir / "ffplay").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    name, prefix = player.detect_backend()
    assert name == "ffplay"
    assert prefix == ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
