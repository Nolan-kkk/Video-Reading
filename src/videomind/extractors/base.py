"""Public acquisition metadata; excludes cookies, headers and signed media URLs."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from videomind.config import StrictModel


class SourceInfo(StrictModel):
    platform: Literal["bilibili", "douyin"] = "bilibili"
    url: str
    video_id: Annotated[str, Field(pattern=r"^(BV[A-Za-z0-9]{10}|av[0-9]+|[0-9]{1,25})$")]
    part: Annotated[int, Field(gt=0)] = 1
    title: Annotated[str, Field(min_length=1, max_length=500)]
    author: Annotated[str, Field(max_length=500)] | None = None
    duration_seconds: Annotated[float, Field(gt=0)]
    subtitle_languages: tuple[str, ...] = ()
    selected_subtitle: str | None = None

    @model_validator(mode="after")
    def platform_matches_id(self) -> "SourceInfo":
        if self.platform == "douyin" and not self.video_id.isdigit():
            raise ValueError("Invalid Douyin video ID")
        if self.platform == "bilibili" and self.video_id.isdigit():
            raise ValueError("Invalid Bilibili video ID")
        if self.platform == "douyin" and self.part != 1:
            raise ValueError("Douyin does not support parts")
        return self


@dataclass(frozen=True)
class AcquiredVideo:
    video: Path
    subtitles: Path | None
    info: SourceInfo
    manifest: Path
