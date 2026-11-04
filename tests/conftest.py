import os
import socket
import threading
from datetime import date
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def fixed_price_date(monkeypatch):
    # Offline tests remain repeatable after the runtime price snapshot expires.
    monkeypatch.setattr("videomind.billing.utc_today", lambda: date(2026, 11, 4))


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair
    pair_lock = threading.Lock()

    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not use the network or paid APIs")

    def local_socketpair(*args, **kwargs):
        # Windows implements asyncio's internal wake-up socketpair via loopback.
        # Restore connect only inside the stdlib socketpair constructor, never
        # for arbitrary localhost requests or while the event loop is running.
        with pair_lock, monkeypatch.context() as context:
            context.setattr(socket.socket, "connect", original_connect)
            return original_socketpair(*args, **kwargs)

    monkeypatch.setattr(socket, "socketpair", local_socketpair)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def config_data():
    return {
        "providers": {
            "vision": {
                "provider": "openai",
                "model": "unit-test-vision-model",
                "api_key_env": "VIDEOMIND_TEST_KEY",
            }
        }
    }


@pytest.fixture
def config_file(tmp_path, config_data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    return path


@pytest.fixture
def media_tools(monkeypatch):
    from videomind.processors.media import find_tool

    for name in ("ffmpeg", "ffprobe"):
        local = Path(__file__).resolve().parents[1] / ".cache" / "tools" / f"{name}.exe"
        if local.is_file() and not os.environ.get(f"VIDEOMIND_{name.upper()}"):
            monkeypatch.setenv(f"VIDEOMIND_{name.upper()}", str(local))
        if find_tool(name) is None:
            pytest.skip("FFmpeg/ffprobe required for media integration tests")


@pytest.fixture
def sample_video(tmp_path, media_tools):
    from videomind.processors.media import run_tool

    video = tmp_path / "demo with spaces.mp4"
    run_tool(
        "ffmpeg",
        [
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=320x240:r=4:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=4:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ],
    )
    video.with_suffix(".srt").write_text(
        "1\n00:00:00,000 --> 00:00:00,900\nIntro\n\n"
        "2\n00:00:01,000 --> 00:00:01,900\nCode explanation\n",
        encoding="utf-8",
    )
    return video


@pytest.fixture
def deepseek_settings():
    from videomind.config import Settings

    return Settings.model_validate(
        {
            "providers": {
                role: {
                    "provider": "deepseek",
                    "model": "deepseek-flash",
                    "api_key_env": "VIDEOMIND_TEST_KEY",
                }
                for role in ("vision", "text")
            },
            "vision": {"max_frames_per_video": 3},
        }
    )
