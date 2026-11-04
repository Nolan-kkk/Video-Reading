"""SRT/WebVTT sidecars with explicit timestamps; not an ASR substitute."""

import re
from pathlib import Path

from videomind.errors import MediaError
from videomind.models.schemas import Evidence

_TIME = r"(?:\d{2,}:)?\d{2}:\d{2}[.,]\d{3}"
_CUE = re.compile(rf"^({_TIME})\s+-->\s+({_TIME})(?:\s+.*)?$")


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if any(float(part) >= 60 for part in parts[-2:]):
        raise MediaError("字幕分钟或秒数超出合法范围。")
    return float(sum(float(part) * 60**i for i, part in enumerate(reversed(parts))))


def read_subtitles(path: Path, duration: float) -> list[Evidence]:
    if path.suffix.lower() not in {".srt", ".vtt"}:
        raise MediaError("字幕仅支持 UTF-8 SRT 或 WebVTT。")
    try:
        if path.stat().st_size > 10 * 1024 * 1024:
            raise MediaError("字幕超过 10 MiB 上限。")
        content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeError):
        raise MediaError("无法读取 UTF-8 字幕文件。") from None
    result: list[Evidence] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.splitlines()
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            raise MediaError("字幕块缺少有效时间戳。")
        match = _CUE.fullmatch(lines[timing].strip())
        if match is None:
            raise MediaError("字幕时间戳格式无效。")
        start, end = (_seconds(value) for value in match.groups())
        text = "\n".join(lines[timing + 1 :]).strip()
        if end < start or start >= duration or end > duration + 1 or not text:
            raise MediaError("字幕时间超出视频范围、顺序错误或内容为空。")
        result.append(
            Evidence(
                start_seconds=start, end_seconds=min(end, duration), source="subtitle", text=text
            )
        )
    if not result:
        raise MediaError("字幕不包含可用内容。")
    return sorted(result, key=lambda e: e.start_seconds)
