"""Isolated yt-dlp worker: public Bilibili/Douyin, no user cookies or AI keys."""

import contextlib
import importlib
import io
import math
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from videomind.extractors.base import SourceInfo
from videomind.extractors.bilibili import WorkerRequest, WorkerResponse
from videomind.extractors.sources import is_short_url, normalize_source_url, source_platform

ErrorCode = Literal[
    "dependency", "unavailable", "restricted", "duration", "size", "subtitle", "invalid"
]


class _Failure(Exception):
    def __init__(self, code: ErrorCode) -> None:
        self.code = code


class _QuietLogger:
    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


def _tracks(info: dict[str, Any]) -> list[str]:
    languages: set[str] = set()
    for group in ("subtitles", "automatic_captions"):
        for language, tracks in (info.get(group) or {}).items():
            if (
                language != "danmaku"
                and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", language)
                and any(track.get("ext") in {"srt", "vtt"} for track in tracks)
            ):
                languages.add(language)
    return sorted(languages)


def _public_info(info: dict[str, Any], request: WorkerRequest) -> SourceInfo:
    try:
        duration = float(info.get("duration", 0))
    except (ValueError, TypeError):
        raise _Failure("duration") from None
    if (
        not math.isfinite(duration)
        or duration <= 0
        or duration > request.max_minutes * 60
        or info.get("is_live")
        or info.get("live_status") in {"is_live", "is_upcoming"}
        or info.get("_type") in {"playlist", "multi_video"}
    ):
        raise _Failure("duration")
    languages = _tracks(info)
    selected: str | None
    if request.subtitle_language is not None:
        if request.subtitle_language not in languages:
            raise _Failure("subtitle")
        selected = request.subtitle_language
    else:
        preferred = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "ai-zh", "en", "ai-en")
        selected = next(
            (lang for lang in preferred if lang in languages), languages[0] if languages else None
        )
    parsed = urlsplit(request.url)
    platform = source_platform(request.url)
    video_id = parsed.path.strip("/").split("/")[-1]
    if platform == "douyin" and str(info.get("id")) != video_id:
        raise _Failure("invalid")
    return SourceInfo(
        platform=platform,
        url=request.url,
        video_id=video_id,
        part=int(parse_qs(parsed.query).get("p", ["1"])[0]),
        title=info.get("title") or "未提供标题",
        author=info.get("uploader"),
        duration_seconds=duration,
        subtitle_languages=tuple(languages),
        selected_subtitle=selected,
    )


def execute(
    request: WorkerRequest, *, factory: Callable[[dict[str, Any]], Any] | None = None
) -> WorkerResponse:
    if normalize_source_url(request.url) != request.url or is_short_url(request.url):
        raise _Failure("invalid")
    if factory is None:
        # Explicitly disable upstream's plugin auto-discovery before constructing YoutubeDL.
        module = importlib.import_module("yt_dlp")
        importlib.import_module("yt_dlp.globals").plugin_dirs.value = []
        factory = module.YoutubeDL
    sizes: dict[str, int] = {}

    def guard(progress: dict[str, Any]) -> None:
        sizes[str(progress.get("filename", "media"))] = int(progress.get("downloaded_bytes") or 0)
        if sum(sizes.values()) > request.max_bytes:
            raise _Failure("size")

    def match_filter(info: dict[str, Any], *, incomplete: bool = False) -> None:
        if not incomplete:
            _public_info(info, request)

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "noplaylist": True,
        "allowed_extractors": [
            "Douyin" if source_platform(request.url) == "douyin" else "BiliBili"
        ],
        "cachedir": False,
        "socket_timeout": 20,
        "retries": 0,
        "extractor_retries": 0,
        "fragment_retries": 0,
        "file_access_retries": 0,
        "skip_unavailable_fragments": False,
        "cookiefile": None,
        "cookiesfrombrowser": None,
        "usenetrc": False,
        "proxy": "",
        "ignoreerrors": False,
        "match_filter": match_filter,
        "skip_download": request.action == "inspect",
        "writesubtitles": request.action == "download" and request.subtitle_language is not None,
        "writeautomaticsub": request.action == "download" and request.subtitle_language is not None,
        "subtitleslangs": [re.escape(request.subtitle_language)]
        if request.subtitle_language
        else [],
        "subtitlesformat": "srt/vtt",
    }
    if request.action == "download":
        if request.directory is None or request.ffmpeg is None:
            raise _Failure("invalid")
        folder = Path(request.directory).resolve()
        if not folder.is_dir() or (folder / "source.mkv").exists():
            raise _Failure("invalid")
        options.update(
            {
                "outtmpl": str(folder / "source.%(ext)s"),
                "format": f"bv[height<={request.max_height}]+ba/b[height<={request.max_height}]",
                "ffmpeg_location": request.ffmpeg,
                "merge_output_format": "mkv",
                "max_filesize": request.max_bytes,
                "progress_hooks": [guard],
                "buffersize": 65536,
                "http_chunk_size": 1024 * 1024,
                "concurrent_fragment_downloads": 1,
                "postprocessors": [
                    {"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"},
                    {"key": "FFmpegSubtitlesConvertor", "format": "srt"},
                ],
            }
        )
    with factory(options) as client:
        info = client.extract_info(request.url, download=request.action == "download")
    if not isinstance(info, dict):
        raise _Failure("unavailable")
    public = _public_info(info, request)
    if request.action == "inspect":
        return WorkerResponse(status="ok", info=public)
    folder = Path(request.directory or "").resolve()
    media = folder / "source.mkv"
    if not media.is_file():
        raise _Failure("unavailable")
    if media.stat().st_size > request.max_bytes:
        raise _Failure("size")
    caption_file: str | None = None
    if request.subtitle_language:
        subtitle = folder / f"source.{request.subtitle_language}.srt"
        if not subtitle.is_file():
            raise _Failure("subtitle")
        if subtitle.stat().st_size > 10 * 1024 * 1024:
            raise _Failure("size")
        subtitle.rename(folder / "captions.srt")
        caption_file = "captions.srt"
    return WorkerResponse(
        status="ok",
        info=public.model_copy(update={"selected_subtitle": request.subtitle_language}),
        video_file="source.mkv",
        subtitle_file=caption_file,
    )


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        request = WorkerRequest.model_validate_json(sys.stdin.read(65537))
        with (
            open(os.devnull, "w", encoding="utf-8") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            result = execute(request)
    except (ValidationError, ValueError):
        result = WorkerResponse(status="error", error="invalid")
    except ModuleNotFoundError:
        result = WorkerResponse(status="error", error="dependency")
    except _Failure as failure:
        result = WorkerResponse(status="error", error=failure.code)
    except Exception as exc:
        # Raw upstream errors may include cookies or signed URLs. Never serialize them.
        code: ErrorCode = "restricted" if "fresh cookies" in str(exc).lower() else "unavailable"
        result = WorkerResponse(status="error", error=code)
    print(result.model_dump_json())
    return 0 if result.status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
