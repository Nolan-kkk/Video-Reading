"""Timestamped evidence and uncertain visible-code recognition contracts."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from videomind.config import StrictModel


class RecognizedCode(StrictModel):
    language: str = "text"
    text: Annotated[str, Field(min_length=1)]
    uncertainty: str = "模型识别，未人工核验；可能存在缺失或误识别。"


class OCRLine(StrictModel):
    text: Annotated[str, Field(min_length=1)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    box: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]


class Evidence(StrictModel):
    start_seconds: Annotated[float, Field(ge=0)]
    end_seconds: Annotated[float, Field(ge=0)]
    source: Literal["subtitle", "transcription", "ocr", "vision", "frame"]
    text: str
    uncertainty: str | None = None
    frame: Path | None = None
    code: tuple[RecognizedCode, ...] = ()
    ocr_lines: tuple[OCRLine, ...] = ()

    @model_validator(mode="after")
    def ordered_timestamps(self) -> "Evidence":
        if self.end_seconds < self.start_seconds:
            raise ValueError("Evidence end must not precede start")
        return self
