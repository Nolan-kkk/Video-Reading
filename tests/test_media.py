import wave

import pytest

from videomind.errors import MediaError
from videomind.processors.media import extract_audio, extract_frames, probe, run_tool


def test_real_video_probe_scene_frames_and_audio(sample_video, tmp_path):
    info = probe(sample_video, 1)
    assert info.duration_seconds == pytest.approx(2, abs=0.1)
    assert info.has_audio
    frames = extract_frames(
        sample_video,
        tmp_path / "images",
        limit=3,
        threshold=0.3,
        max_width=640,
        duration=info.duration_seconds,
    )
    assert len(frames) == 2
    assert frames[0].at_seconds == pytest.approx(0)
    assert frames[1].at_seconds == pytest.approx(1, abs=0.1)
    assert all(f.path.is_file() for f in frames)
    audio = tmp_path / "audio.wav"
    extract_audio(sample_video, audio, info.duration_seconds)
    with wave.open(str(audio)) as reader:
        assert reader.getframerate() == 16000
        assert reader.getnchannels() == 1


def test_duration_limit_prevents_processing(sample_video):
    with pytest.raises(MediaError, match="时长超过"):
        probe(sample_video, 0.001)


def test_invalid_media_is_sanitized(tmp_path, media_tools):
    media = tmp_path / "test-only-private-name.mp4"
    media.write_bytes(b"not a video")
    with pytest.raises(MediaError) as error:
        probe(media, 1)
    assert media.name not in str(error.value)


def test_frame_cap_is_enforced(sample_video, tmp_path):
    frames = extract_frames(
        sample_video, tmp_path / "frames", limit=1, threshold=0.3, max_width=640, duration=2
    )
    assert len(frames) == 1


def test_static_later_content_is_sampled_without_exhausting_cap_early(tmp_path, media_tools):
    video = tmp_path / "mostly-static.mp4"
    run_tool(
        "ffmpeg",
        [
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=5:duration=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=5:d=5",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "mpeg4",
            str(video),
        ],
    )
    frames = extract_frames(
        video, tmp_path / "spanning-frames", limit=3, threshold=0.01, max_width=640, duration=6
    )
    assert 2 <= len(frames) <= 3
    assert frames[-1].at_seconds >= 4
    assert all(
        right.at_seconds - left.at_seconds >= 1.99
        for left, right in zip(frames, frames[1:], strict=False)
    )
