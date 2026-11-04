"""Single local-video workflow; cloud calls require explicit BYOK and cost approval."""

import hashlib
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from videomind import __version__
from videomind.billing import (
    PRICE_CHECKED_ON,
    PRICE_SOURCE,
    PRICE_VALID_THROUGH,
    Budget,
    deepseek_rate,
)
from videomind.config import Role, Settings
from videomind.errors import (
    BudgetError,
    ConfigurationError,
    MediaError,
    ProviderError,
    VideoMindError,
)
from videomind.exporters.markdown import export
from videomind.extractors.base import AcquiredVideo
from videomind.models.schemas import Evidence
from videomind.processors.media import extract_audio, extract_frames, probe
from videomind.processors.ocr import FrameOCR, bundled_models
from videomind.processors.speech import check_speech, transcribe
from videomind.processors.subtitles import read_subtitles
from videomind.providers.deepseek import DeepSeekProvider
from videomind.security import resolve_credentials


@dataclass(frozen=True)
class AnalysisResult:
    directory: Path
    status: str
    error: str | None


def _requirements(settings: Settings, *, cloud: bool) -> list[tuple[Role, int]]:
    if not cloud:
        return []
    requests: list[tuple[Role, int]] = []
    if settings.output.depth != "fast":
        requests.append(("vision", settings.vision.max_frames_per_video))
    if settings.output.mode != "raw":
        requests.append(("text", 1))
    return requests


def _planned_cost(settings: Settings, requests: list[tuple[Role, int]]) -> Decimal:
    configured = settings.providers.configured()
    total = Decimal("0")
    for role, count in requests:
        spec = configured.get(role)
        if spec is None or spec.provider != "deepseek":
            raise ConfigurationError(f"{role}: V1 云端路径需要明确配置 DeepSeek Provider。")
        rate = deepseek_rate(spec.model)
        if role == "vision" and not rate.vision:
            raise ProviderError("所选 DeepSeek 模型不支持图像，尚未发起任何请求。")
        total += rate.upper_cost(settings.billing.max_output_tokens_per_request) * count
    return total


def preview(settings: Settings, *, cloud: bool) -> dict[str, object]:
    if settings.ocr.enabled and settings.output.depth == "fast":
        raise ConfigurationError("OCR 需要关键帧；请使用 standard/deep 深度。")
    requests = _requirements(settings, cloud=cloud)
    cost = _planned_cost(settings, requests)
    Budget(settings.billing.max_budget_usd_per_batch).check_total(cost)
    return {
        "cloud": cloud,
        "provider": "deepseek" if cloud else None,
        "destination": "https://api.deepseek.com" if cloud else None,
        "requests_at_most": sum(count for _, count in requests),
        "reserved_upper_usd": str(cost),
        "budget_usd": str(settings.billing.max_budget_usd_per_batch),
        "pricing_source": PRICE_SOURCE if cloud else None,
        "pricing_checked_on": str(PRICE_CHECKED_ON) if cloud else None,
        "pricing_method": "按每次完整上下文及最大输出、峰时非缓存价格预留；非精确账单。",
        "paid_requests_sent": 0,
    }


def check_cloud_access(settings: Settings, *, approve_paid: bool) -> None:
    """Fail before a URL download if cloud configuration/authorization is missing."""
    requests = _requirements(settings, cloud=True)
    Budget(settings.billing.max_budget_usd_per_batch).check_total(_planned_cost(settings, requests))
    if requests:
        resolve_credentials(settings, roles=[role for role, _ in requests])
    if requests and settings.billing.confirm_before_paid_requests and not approve_paid:
        raise BudgetError("云端分析需要费用确认；先用 --dry-run 查看预留，再添加 --yes-paid。")


def _sidecar(source: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    choices = [
        path for suffix in (".srt", ".vtt") if (path := source.with_suffix(suffix)).is_file()
    ]
    if len(choices) > 1:
        raise MediaError("同名 SRT/VTT 同时存在；请用 --subtitles 明确选择。")
    return choices[0] if choices else None


async def analyze(
    source: Path,
    settings: Settings,
    *,
    output: Path | None = None,
    subtitles: Path | None = None,
    cloud: bool = False,
    approve_paid: bool = False,
    visual_only: bool = False,
    save_audio: bool = False,
    origin: AcquiredVideo | None = None,
) -> AnalysisResult:
    source = source.resolve()
    info = probe(source, settings.video.max_duration_minutes)
    subtitle_path = _sidecar(source, subtitles)
    evidence = read_subtitles(subtitle_path, info.duration_seconds) if subtitle_path else []
    has_subtitles = bool(evidence)
    platform_captions = (
        origin is not None and subtitle_path == origin.subtitles and subtitle_path is not None
    )
    if platform_captions:
        evidence = [
            item.model_copy(
                update={
                    "uncertainty": "平台字幕未经人工核验，可能为自动生成。",
                }
            )
            for item in evidence
        ]
    needs_speech = (
        settings.speech.enabled
        and info.has_audio
        and (not evidence or not settings.speech.prefer_subtitles)
    )
    if settings.ocr.enabled and settings.output.depth == "fast":
        raise ConfigurationError("OCR 需要关键帧；请使用 standard/deep 深度。")
    if needs_speech:
        check_speech(settings.speech)
    if settings.ocr.enabled:
        bundled_models()
    if cloud and info.has_audio and not evidence and not visual_only and not needs_speech:
        raise ProviderError(
            "未找到字幕；请启用 --transcribe 本地语音转录，或提供 SRT/VTT，"
            "或用 --visual-only 明确接受缺失语音。"
        )
    requests = _requirements(settings, cloud=cloud)
    planned = _planned_cost(settings, requests)
    credentials = resolve_credentials(settings, roles=[r for r, _ in requests]) if requests else {}
    authorized = cloud and (approve_paid or not settings.billing.confirm_before_paid_requests)
    budget = Budget(settings.billing.max_budget_usd_per_batch, authorized=authorized)
    budget.check_total(planned)
    if requests and not authorized:
        raise BudgetError("云端分析需要费用确认；先用 --dry-run 查看预留，再添加 --yes-paid。")
    root = (output or settings.output.directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    identity = f"video_{uuid.uuid4().hex[:12]}"
    stage, destination = root / f".{identity}.partial", root / identity
    stage.mkdir()
    warnings: list[str] = []
    if info.has_audio and not evidence and not needs_speech:
        warnings.append("没有字幕/语音转录，语音内容未被理解。")
    if platform_captions:
        warnings.append("所用平台字幕未经人工核验，可能含自动识别错误。")
    if not cloud:
        warnings.append("未调用云端语义模型；笔记仅为证据索引，画面语义与代码结构未经模型整理。")
    if needs_speech:
        warnings.append("语音为本地自动转录，未经人工核验；可能误听或漏词。")
    if settings.ocr.enabled:
        warnings.append("OCR 只识别所采样帧的文字；可能漏字、误识或遗漏帧间内容。")
    if settings.speech.enabled and not info.has_audio:
        warnings.append("视频没有音轨，已跳过语音识别。")
    if settings.output.depth == "fast":
        warnings.append("fast 深度跳过关键帧，不包含视觉理解。")
    metadata: dict[str, object] = {
        "schema_version": "1",
        "version": __version__,
        "task_id": identity,
        "source_type": "local",
        "source_filename": source.name,
        "duration_seconds": info.duration_seconds,
        "has_audio": info.has_audio,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "cloud": cloud,
        "mode": settings.output.mode,
        "depth": settings.output.depth,
        "warnings": warnings,
        "models": {r: settings.providers.configured()[r].model for r, _ in requests},
        "local_recognition": {
            "speech": "pending"
            if needs_speech
            else ("subtitles_preferred" if settings.speech.enabled and evidence else "not_run"),
            "ocr": "pending" if settings.ocr.enabled else "not_run",
        },
    }
    if origin is not None:
        metadata.update(
            {
                "source_type": origin.info.platform,
                "source_url": origin.info.url,
                "source_video_id": origin.info.video_id,
                "source_part": origin.info.part,
                "title": origin.info.title,
                "author": origin.info.author,
                "available_subtitle_languages": list(origin.info.subtitle_languages),
                "subtitle_language": origin.info.selected_subtitle if platform_captions else None,
                "subtitle_origin": "platform"
                if platform_captions
                else ("external" if evidence else None),
            }
        )
    notes: str | None = None
    failure: str | None = None
    try:
        with source.open("rb") as handle:
            metadata["source_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
        frames = (
            []
            if settings.output.depth == "fast"
            else extract_frames(
                source,
                stage / "images",
                limit=settings.vision.max_frames_per_video,
                threshold=settings.vision.scene_threshold
                / (2 if settings.output.depth == "deep" else 1),
                max_width=settings.vision.max_width,
                duration=info.duration_seconds,
            )
        )
        if settings.output.depth == "fast":
            (stage / "images").mkdir()
        metadata["frame_count"] = len(frames)
        metadata["frame_sampling"] = "scene_change_with_sparse_coverage"
        if (save_audio or needs_speech) and info.has_audio:
            extract_audio(source, stage / "audio.wav", info.duration_seconds)
            metadata["audio_file"] = "audio.wav"
        for frame in frames:
            evidence.append(
                Evidence(
                    start_seconds=frame.at_seconds,
                    end_seconds=frame.at_seconds,
                    source="frame",
                    text="本地关键帧；此条仅记录图片，模型理解见独立 vision 证据（如有）。",
                    frame=Path("images") / frame.path.name,
                )
            )
        # Persist raw source evidence before any paid API call. Failure preserves it.
        evidence.sort(key=lambda item: (item.start_seconds, item.source))
        export(stage, evidence, metadata, notes=None, mode=settings.output.mode)
        recognition = metadata["local_recognition"]
        assert isinstance(recognition, dict)
        if needs_speech:
            recognition["speech"] = "running"
            speech_result = transcribe(stage / "audio.wav", settings.speech, info.duration_seconds)
            evidence.extend(speech_result.evidence)
            recognition.update(
                {
                    "speech": "completed",
                    "speech_engine": "faster-whisper",
                    "speech_device": "cpu/int8",
                    "speech_language": speech_result.language,
                    "speech_segments": len(speech_result.evidence),
                    "speech_cpu_threads": settings.speech.cpu_threads,
                    "speech_requested_language": settings.speech.language,
                    "speech_prefer_subtitles": settings.speech.prefer_subtitles,
                }
            )
            with (settings.speech.model_directory / "model.bin").open("rb") as handle:
                recognition["speech_model_sha256"] = hashlib.file_digest(
                    handle, "sha256"
                ).hexdigest()
            if not speech_result.evidence:
                warnings.append("本地语音识别没有返回文本；不能据此断言视频没有语音。")
                if cloud and not has_subtitles and not visual_only:
                    raise ProviderError("语音转录无文本；已停止云端请求，避免缺语音的完整性误判。")
        if settings.ocr.enabled:
            recognition["ocr"] = "running"
            ocr = FrameOCR(settings.ocr)
            ocr_count = 0
            for frame in frames:
                recognized = ocr.recognize(frame.path, frame.at_seconds)
                evidence.extend(
                    item.model_copy(update={"frame": Path("images") / frame.path.name})
                    for item in recognized
                )
                ocr_count += len(recognized)
            recognition.update(
                {
                    "ocr": "completed",
                    "ocr_engine": "RapidOCR/PP-OCRv6",
                    "ocr_frames_with_text": ocr_count,
                    "ocr_min_confidence": settings.ocr.min_confidence,
                }
            )
            if not ocr_count:
                warnings.append("所采样关键帧没有返回 OCR 文字；不表示视频中没有文字。")
        evidence.sort(key=lambda item: (item.start_seconds, item.source))
        export(stage, evidence, metadata, notes=None, mode=settings.output.mode)
        if cloud and frames:
            spec = settings.providers.configured()["vision"]
            vision = DeepSeekProvider(
                spec,
                credentials["vision"],
                budget,
                max_output_tokens=settings.billing.max_output_tokens_per_request,
            )
            for frame in frames:
                result = await vision.describe_frame(frame.path, frame.at_seconds)
                evidence.extend(
                    item.model_copy(update={"frame": Path("images") / frame.path.name})
                    for item in result.evidence
                )
        evidence.sort(key=lambda item: (item.start_seconds, item.source))
        if cloud and settings.output.mode != "raw":
            spec = settings.providers.configured()["text"]
            text_provider = DeepSeekProvider(
                spec,
                credentials["text"],
                budget,
                max_output_tokens=settings.billing.max_output_tokens_per_request,
            )
            notes = (await text_provider.organize(evidence)).markdown
    except VideoMindError as exc:
        failure = str(exc)
    except OSError:
        failure = "本地文件读写失败；请检查空间和权限。"
    recognition = metadata["local_recognition"]
    assert isinstance(recognition, dict)
    for role in ("speech", "ocr"):
        if recognition[role] == "running":
            recognition[role] = "failed"
        elif recognition[role] == "pending":
            recognition[role] = "not_run"
    metadata.update(
        {
            "status": "failed"
            if failure
            else ("completed_with_limitations" if warnings else "completed"),
            "error": failure,
            "finished_at": datetime.now(UTC).isoformat(),
            "billing": {
                "limit_usd": str(budget.limit_usd),
                "reserved_upper_usd": str(budget.reserved_usd),
                "planned_upper_usd": str(planned),
                "actual_invoice_usd": None,
                "pricing_source": PRICE_SOURCE if cloud else None,
                "pricing_checked_on": str(PRICE_CHECKED_ON) if cloud else None,
                "pricing_valid_through": str(PRICE_VALID_THROUGH) if cloud else None,
                "usage": [asdict(item) for item in budget.usage],
            },
        }
    )
    evidence.sort(key=lambda item: (item.start_seconds, item.source))
    # Exported models/usage contain no credentials; frames use relative paths after rename.
    export(stage, evidence, metadata, notes=notes, mode=settings.output.mode)
    stage.rename(destination)
    return AnalysisResult(destination, str(metadata["status"]), failure)
