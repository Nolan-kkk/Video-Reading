"""Bounded local FFmpeg operations. No shell, network protocols or raw tool errors."""

import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videomind.errors import MediaError

VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts"})


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    has_audio: bool
    width: int
    height: int


@dataclass(frozen=True)
class Frame:
    at_seconds: float
    path: Path


def find_tool(name: str) -> str | None:
    explicit = os.environ.get(f"VIDEOMIND_{name.upper()}")
    if explicit:
        return str(Path(explicit).resolve()) if Path(explicit).is_file() else None
    return shutil.which(name)


def run_tool(
    name: str, arguments: list[str], *, timeout: float = 120
) -> subprocess.CompletedProcess[str]:
    executable = find_tool(name)
    if executable is None:
        raise MediaError(f"缺少 {name}；请安装并加入 PATH，或配置对应 VIDEOMIND 环境变量。")
    try:
        result = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise MediaError(f"{name} 启动失败或处理超时。") from None
    if result.returncode:
        raise MediaError(f"{name} 无法处理该本地媒体；请检查格式或文件完整性。")
    return result


def probe(path: Path, max_minutes: float) -> MediaInfo:
    if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise MediaError("V1 本地入口需要存在的视频文件（mp4/mkv/mov/webm/avi/m4v/ts）。")
    result = run_tool(
        "ffprobe",
        [
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path.resolve()),
        ],
        timeout=30,
    )
    try:
        data = json.loads(result.stdout)
        video = next(s for s in data["streams"] if s.get("codec_type") == "video")
        duration = float(data["format"]["duration"])
        width, height = int(video["width"]), int(video["height"])
        if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0:
            raise ValueError
    except (ValueError, TypeError, KeyError, StopIteration):
        raise MediaError("媒体缺少有效视频轨或有限时长，无法安全处理。") from None
    if duration > max_minutes * 60:
        raise MediaError("视频时长超过配置上限，尚未进行抽帧或 API 调用。")
    return MediaInfo(
        duration, any(s.get("codec_type") == "audio" for s in data["streams"]), width, height
    )


def extract_frames(
    path: Path, directory: Path, *, limit: int, threshold: float, max_width: int, duration: float
) -> list[Frame]:
    directory.mkdir()
    # Bound scene-triggered bursts, leaving time for later parts of the video.
    # Sparse coverage also samples static slides whose text changes too little
    # to exceed the scene threshold. Neither rule guarantees exhaustive recall.
    gap = max(duration / limit, 0.5)
    coverage = max(gap * 2, 2)
    tail = f"+gte(t,{max(0, duration - gap):.9f})" if duration >= 4 and limit > 1 else ""
    selection = (
        "if(isnan(prev_selected_t),1,"
        f"gte(t-prev_selected_t,{gap:.9f})*"
        f"(gt(scene,{threshold})+gte(t-prev_selected_t,{coverage:.9f}){tail}))"
    )
    filters = f"setpts=PTS-STARTPTS,select='{selection}',scale='min({max_width},iw)':-2,showinfo"
    result = run_tool(
        "ffmpeg",
        [
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(path.resolve()),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-vf",
            filters,
            "-fps_mode",
            "vfr",
            "-frames:v",
            str(limit),
            str(directory / "frame_%04d.png"),
        ],
        timeout=max(120, duration * 2),
    )
    timestamps = [float(t) for t in re.findall(r"pts_time:\s*([\d.eE+\-]+)", result.stderr)]
    files = sorted(directory.glob("frame_*.png"))
    if not files or len(files) > limit or len(timestamps) < len(files):
        raise MediaError("关键帧提取失败或无法对齐时间戳。")
    return [Frame(max(0, t), image) for t, image in zip(timestamps, files, strict=False)]


def extract_audio(path: Path, output: Path, duration: float) -> None:
    run_tool(
        "ffmpeg",
        [
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(path.resolve()),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        timeout=max(120, duration * 2),
    )
