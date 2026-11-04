"""Strict, secret-free configuration; API keys are resolved separately at runtime."""

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from videomind.errors import ConfigurationError

Role = Literal["transcription", "vision", "text"]
ProviderName = Literal["openai", "gemini", "anthropic", "deepseek"]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, allow_inf_nan=False
    )


class ProviderConfig(StrictModel):
    provider: ProviderName
    model: Annotated[str, Field(min_length=1, max_length=200)]
    api_key_env: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")]

    @field_validator("model")
    @classmethod
    def concrete_model(cls, value: str) -> str:
        value = value.strip()
        if not value or value.casefold().startswith(("your_", "placeholder", "change_me")):
            raise ValueError("A concrete, user-selected model is required")
        return value


class ProviderSlots(StrictModel):
    transcription: ProviderConfig | None = None
    vision: ProviderConfig | None = None
    text: ProviderConfig | None = None

    def configured(self) -> dict[Role, ProviderConfig]:
        result: dict[Role, ProviderConfig] = {}
        for role in ("transcription", "vision", "text"):
            spec = getattr(self, role)
            if spec is not None:
                result[role] = spec
        return result


class VideoLimits(StrictModel):
    max_concurrent_tasks: Annotated[int, Field(ge=1, le=32, strict=True)] = 3
    max_duration_minutes: Annotated[float, Field(gt=0)] = 120
    max_retries: NonNegativeInt = 2


class VisionLimits(StrictModel):
    max_frames_per_video: PositiveInt = 12
    scene_threshold: Annotated[float, Field(gt=0, le=1)] = 0.3
    max_width: Annotated[int, Field(ge=320, le=1920, strict=True)] = 1280


class BillingConfig(StrictModel):
    mode: Literal["user_provided_api_key"] = "user_provided_api_key"
    max_budget_usd_per_batch: Annotated[Decimal, Field(gt=0)] = Decimal("5.00")
    confirm_before_paid_requests: Annotated[bool, Field(strict=True)] = True
    max_output_tokens_per_request: Annotated[int, Field(gt=0, le=8192, strict=True)] = 2048


class SpeechConfig(StrictModel):
    enabled: Annotated[bool, Field(strict=True)] = False
    prefer_subtitles: Annotated[bool, Field(strict=True)] = True
    model_directory: Path = Path(".cache/models/faster-whisper-small")
    language: Annotated[str, Field(pattern=r"^[a-z]{2,3}$")] | None = None
    cpu_threads: Annotated[int, Field(ge=1, le=32, strict=True)] = 4


class OCRConfig(StrictModel):
    enabled: Annotated[bool, Field(strict=True)] = False
    min_confidence: Annotated[float, Field(ge=0, le=1)] = 0.5


class OutputConfig(StrictModel):
    directory: Path = Path("output")
    mode: Literal["raw", "notes", "full"] = "full"
    depth: Literal["fast", "standard", "deep"] = "standard"


class DownloadConfig(StrictModel):
    directory: Path = Path(".cache/downloads")
    max_height: Annotated[int, Field(ge=144, le=1080, strict=True)] = 720
    max_download_mb: Annotated[int, Field(gt=0, le=10240, strict=True)] = 1024
    timeout_seconds: Annotated[int, Field(ge=10, le=3600, strict=True)] = 600


class Settings(StrictModel):
    providers: ProviderSlots = Field(default_factory=ProviderSlots)
    video: VideoLimits = Field(default_factory=VideoLimits)
    vision: VisionLimits = Field(default_factory=VisionLimits)
    billing: BillingConfig = Field(default_factory=BillingConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate keys instead of silently overriding safety limits."""


def _mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            if key in result:
                raise ConfigurationError("配置包含重复字段，请删除重复项。")
            result[key] = loader.construct_object(value_node, deep=True)
        except TypeError:
            raise ConfigurationError("配置字段必须使用简单名称。") from None
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_config(path: Path) -> Settings:
    """Read YAML without ever including file contents or paths in diagnostics."""
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ConfigurationError("无法读取配置文件，请检查文件位置、权限和 UTF-8 编码。") from None
    try:
        data = yaml.load(content, Loader=_UniqueKeyLoader)
        settings = Settings.model_validate(data)
    except (yaml.YAMLError, ValidationError, RecursionError):
        raise ConfigurationError(
            "配置不合法；请检查字段、类型、范围和模型占位符。禁止在 YAML 中填写 API Key。"
        ) from None
    # Relative output paths are always relative to the configuration, not the caller's CWD.
    directory = settings.output.directory
    if not directory.is_absolute():
        directory = path.resolve().parent / directory
    download_dir = settings.download.directory
    if not download_dir.is_absolute():
        download_dir = path.resolve().parent / download_dir
    speech_dir = settings.speech.model_directory
    if not speech_dir.is_absolute():
        speech_dir = path.resolve().parent / speech_dir
    return settings.model_copy(
        update={
            "output": settings.output.model_copy(update={"directory": directory}),
            "download": settings.download.model_copy(update={"directory": download_dir}),
            "speech": settings.speech.model_copy(update={"model_directory": speech_dir}),
        }
    )
