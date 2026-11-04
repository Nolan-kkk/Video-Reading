"""Bilibili normalization and isolated, bounded public-video acquisition."""

import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

from videomind.config import Settings, StrictModel
from videomind.errors import SourceError
from videomind.extractors.base import AcquiredVideo, SourceInfo
from videomind.extractors.sources import resolve_source_url, source_platform
from videomind.processors.media import find_tool

_PATH = re.compile(r"/video/(BV[A-Za-z0-9]{10}|av[0-9]+)/?")
_LANG = re.compile(r"[A-Za-z0-9_-]{1,32}")


def normalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        match = _PATH.fullmatch(parsed.path)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or match is None
        ):
            raise ValueError
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=100)
        page = query.get("p", ["1"])
        if len(page) != 1 or not page[0].isdigit() or not 1 <= int(page[0]) <= 10000:
            raise ValueError
    except ValueError:
        raise SourceError(
            "仅支持标准 B站 BV/av 视频地址；不接受短链、合集、其他平台或带账号的 URL。"
        ) from None
    suffix = urlencode({"p": int(page[0])}) if int(page[0]) != 1 else ""
    return urlunsplit(("https", "www.bilibili.com", f"/video/{match[1]}/", suffix, ""))


class WorkerRequest(StrictModel):
    action: Literal["inspect", "download"]
    url: str
    directory: str | None = None
    max_minutes: float
    max_height: int = 720
    max_bytes: int = 1024 * 1024 * 1024
    subtitle_language: str | None = None
    ffmpeg: str | None = None


class WorkerResponse(StrictModel):
    status: Literal["ok", "error"]
    info: SourceInfo | None = None
    video_file: str | None = None
    subtitle_file: str | None = None
    error: (
        Literal[
            "dependency", "unavailable", "restricted", "duration", "size", "subtitle", "invalid"
        ]
        | None
    ) = None


_ERRORS = {
    "dependency": "缺少下载依赖；请安装 videomind[download] 和 FFmpeg/ffprobe。",
    "unavailable": "无法公开获取该视频；可能需要登录、受访问限制或接口变化。可提供本地文件。",
    "restricted": "平台要求额外验证或 Cookie，当前未读取浏览器登录；请提供有权处理的本地文件。",
    "duration": "平台未提供有效时长、视频为直播或时长超限，未下载视频。",
    "size": "下载体积超过上限，已停止；可能保留部分文件。",
    "subtitle": "没有找到指定语言的可用字幕；弹幕不是字幕。",
    "invalid": "平台获取结果无效，未保留原始响应或敏感请求信息。",
}


def _stop_process(process: subprocess.Popen[str]) -> None:
    if sys.platform == "win32":
        # Limit termination to this worker and descendants (e.g. its FFmpeg merge).
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


def _run_worker(request: WorkerRequest, timeout: float) -> WorkerResponse:
    if importlib.util.find_spec("yt_dlp") is None:
        raise SourceError(_ERRORS["dependency"])
    # Do not pass AI keys, proxy credentials, PYTHONPATH or login environment to yt-dlp.
    allowed = {
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "PROGRAMDATA",
        "WINDIR",
        "TEMP",
        "TMP",
        "PATH",
        "LANG",
        "LC_ALL",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment["PYTHONIOENCODING"] = "utf-8"
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-m", "videomind.extractors.worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            env=environment,
            start_new_session=os.name != "nt",
            creationflags=creation_flags,
        )
        try:
            stdout, _ = process.communicate(request.model_dump_json(), timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_process(process)
            process.communicate(timeout=10)
            raise SourceError("平台获取超时，已停止下载进程；可稍后重试或提供本地文件。") from None
        response = WorkerResponse.model_validate_json(stdout)
    except (OSError, ValidationError, subprocess.SubprocessError):
        raise SourceError("平台下载进程失败；底层日志已隐藏，未进行自动重试。") from None
    if response.status != "ok" or process.returncode != 0 or response.info is None:
        raise SourceError(_ERRORS.get(response.error or "invalid", _ERRORS["invalid"]))
    expected_id = urlsplit(request.url).path.strip("/").split("/")[-1]
    expected_part = int(parse_qs(urlsplit(request.url).query).get("p", ["1"])[0])
    if (
        response.info.url != request.url
        or response.info.platform != source_platform(request.url)
        or response.info.video_id != expected_id
        or response.info.part != expected_part
    ):
        raise SourceError(_ERRORS["invalid"])
    return response


def inspect_url(url: str, settings: Settings, *, language: str | None = None) -> SourceInfo:
    canonical = resolve_source_url(url)
    if language is not None and _LANG.fullmatch(language) is None:
        raise SourceError("字幕语言代码无效。")
    response = _run_worker(
        WorkerRequest(
            action="inspect",
            url=canonical,
            max_minutes=settings.video.max_duration_minutes,
            subtitle_language=language,
        ),
        min(settings.download.timeout_seconds, 90),
    )
    assert response.info is not None
    return response.info


def fetch_url(
    url: str, settings: Settings, *, directory: Path | None = None, language: str | None = None
) -> AcquiredVideo:
    info = inspect_url(url, settings, language=language)
    ffmpeg = find_tool("ffmpeg")
    if ffmpeg is None or find_tool("ffprobe") is None:
        raise SourceError(_ERRORS["dependency"])
    root = (directory or settings.download.directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{info.platform}_{uuid.uuid4().hex[:12]}"
    folder.mkdir()
    manifest = folder / "source.json"
    record: dict[str, object] = {"status": "running", "source": info.model_dump(mode="json")}
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        response = _run_worker(
            WorkerRequest(
                action="download",
                url=info.url,
                directory=str(folder),
                max_minutes=settings.video.max_duration_minutes,
                max_height=settings.download.max_height,
                max_bytes=settings.download.max_download_mb * 1024 * 1024,
                subtitle_language=info.selected_subtitle,
                ffmpeg=ffmpeg,
            ),
            settings.download.timeout_seconds,
        )
        if response.video_file != "source.mkv" or response.subtitle_file not in {
            None,
            "captions.srt",
        }:
            raise SourceError(_ERRORS["invalid"])
        video = folder / "source.mkv"
        captions = folder / "captions.srt" if response.subtitle_file else None
        if (
            not video.is_file()
            or video.is_symlink()
            or (captions is not None and (not captions.is_file() or captions.is_symlink()))
        ):
            raise SourceError(_ERRORS["invalid"])
        assert response.info is not None
        info = response.info
    except SourceError as exc:
        record.update({"status": "failed", "error": str(exc)})
        manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    record.update(
        {
            "status": "completed",
            "source": info.model_dump(mode="json"),
            "video_file": "source.mkv",
            "subtitle_file": "captions.srt" if captions else None,
        }
    )
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return AcquiredVideo(video, captions, info, manifest)
