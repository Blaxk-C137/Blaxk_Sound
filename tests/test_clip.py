import subprocess
from pathlib import Path

import pytest

from blaxk_sounds import clip, config


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLAXK_SOUNDS_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


@pytest.fixture
def tone(tmp_path):
    """A 3-second 440Hz mono tone, courtesy of ffmpeg itself."""
    path = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", "-y", str(path)],
        check=True,
    )
    return path


@pytest.mark.parametrize(
    "text,expected",
    [("5", 5.0), ("1:30", 90.0), ("0:07.5", 7.5), ("1:02:03", 3723.0)],
)
def test_parse_time(text, expected):
    assert clip.parse_time(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "abc", "1:2:3:4", "-5", "1:-2"])
def test_parse_time_rejects_bad_input(text):
    with pytest.raises(ValueError):
        clip.parse_time(text)


def test_probe_duration_reads_the_real_length(tone):
    assert clip.probe_duration(str(tone)) == pytest.approx(3.0, abs=0.1)


def test_extract_writes_a_normalized_wav(tone):
    out = clip.extract(str(tone), from_s=0.5, length_s=1.0, event="success")
    assert out.exists()
    assert out == config.sounds_dir() / "success.wav"

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,sample_rate,channels", "-of", "default=nw=1", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "codec_name=pcm_s16le" in probe
    assert "sample_rate=44100" in probe
    assert "channels=1" in probe
    assert clip.probe_duration(str(out)) == pytest.approx(1.0, abs=0.15)


def test_extract_updates_the_config(tone):
    clip.extract(str(tone), from_s=0.0, length_s=0.5, event="fail")
    assert config.load_settings()["sounds"]["fail"] == str(
        config.sounds_dir() / "fail.wav"
    )


def test_extract_rejects_clips_over_the_limit(tone):
    with pytest.raises(ValueError, match="10"):
        clip.extract(str(tone), from_s=0.0, length_s=11.0, event="start")


def test_extract_rejects_start_past_the_end(tone):
    with pytest.raises(ValueError, match="3.0"):
        clip.extract(str(tone), from_s=5.0, length_s=1.0, event="start")


def test_extract_rejects_length_running_past_the_end(tone):
    with pytest.raises(ValueError, match="3.0"):
        clip.extract(str(tone), from_s=2.5, length_s=2.0, event="start")


def test_extract_does_not_modify_the_source(tone):
    before = tone.stat().st_size
    clip.extract(str(tone), from_s=0.0, length_s=0.5, event="start")
    assert tone.stat().st_size == before


@pytest.mark.parametrize("volume", [0.0, 0.5, 1.0, 2.0])
def test_extract_accepts_valid_volume(tone, volume):
    assert clip.extract(
        str(tone), from_s=0.0, length_s=0.5, event="start", volume=volume
    ).exists()


@pytest.mark.parametrize("volume", [-0.1, 2.1])
def test_extract_rejects_invalid_volume(tone, volume):
    with pytest.raises(ValueError):
        clip.extract(str(tone), from_s=0.0, length_s=0.5, event="start", volume=volume)


def test_extract_rejects_unknown_event(tone):
    with pytest.raises(ValueError, match="event"):
        clip.extract(str(tone), from_s=0.0, length_s=0.5, event="banana")


@pytest.mark.parametrize(
    "text,expected",
    [("0.5", "0.5"), ("0:02", "2.0"), ("0:00:01", "1.0")],
)
def test_extract_passes_parsed_seconds_to_ffmpeg(tone, monkeypatch, text, expected):
    """Spec 11.3: ffmpeg argv correct for each --from format."""
    captured = {}
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "ffmpeg":
            captured["cmd"] = list(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, *args, **kwargs)  # ffprobe must stay real

    monkeypatch.setattr(clip.subprocess, "run", fake_run)
    clip.extract(
        str(tone), from_s=clip.parse_time(text), length_s=0.5, event="start"
    )

    cmd = captured["cmd"]
    assert cmd[cmd.index("-ss") + 1] == expected
    assert cmd[cmd.index("-t") + 1] == "0.5"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-ar") + 1] == "44100"
    assert cmd[cmd.index("-c:a") + 1] == "pcm_s16le"
    assert cmd[-1].endswith("start.wav")
