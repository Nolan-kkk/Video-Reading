"""Separate modality interfaces; a provider must explicitly declare capabilities."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from videomind.config import Role
from videomind.models.schemas import Evidence


@dataclass(frozen=True)
class ProviderCapabilities:
    roles: frozenset[Role]
    timestamped_transcription: bool = False


@dataclass(frozen=True)
class Usage:
    """Provider-reported usage; unknown quantities must remain unknown, not zero."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    audio_seconds: float | None = None
    images: int | None = None
    billed_usd: Decimal | None = None


@dataclass(frozen=True)
class EvidenceResult:
    evidence: tuple[Evidence, ...]
    usage: Usage
    model: str


@dataclass(frozen=True)
class TextResult:
    markdown: str
    usage: Usage
    model: str


class TranscriptionProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def transcribe(self, audio: Path) -> EvidenceResult: ...


class VisionProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def describe_frame(self, image: Path, at_seconds: float) -> EvidenceResult: ...


class TextProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def organize(self, evidence: Sequence[Evidence]) -> TextResult: ...
