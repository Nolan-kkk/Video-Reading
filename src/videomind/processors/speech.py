"""Optional CPU/int8 ASR. Recognition only loads explicitly prepared local models."""

import hashlib
import importlib
import importlib.util
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from videomind.config import SpeechConfig
from videomind.errors import ConfigurationError, MediaError
from videomind.models.schemas import Evidence

MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")
VOCAB_FILES = ("vocabulary.json", "vocabulary.txt")


def _model_files(directory: Path) -> list[Path]:
    files = [directory / name for name in MODEL_FILES]
    vocab = [directory / name for name in VOCAB_FILES if (directory / name).is_file()]
    if not all(path.is_file() for path in files) or not vocab:
        return []
    return [*files, *vocab]


def check_speech(config: SpeechConfig) -> None:
    if importlib.util.find_spec("faster_whisper") is None:
        raise ConfigurationError('本地转录需要可选依赖：pip install "videomind[speech]"。')
    if not _model_files(config.model_directory):
        raise ConfigurationError(
            "缺少本地语音模型；先运行 prepare-speech 下载，或配置 speech.model_directory。"
            "analyze 不会自动下载模型。"
        )


def speech_model_ready(config: SpeechConfig) -> bool:
    """Check required files only, without loading models or accessing the network."""
    return bool(_model_files(config.model_directory))


def prepare_speech(
    directory: Path, size: Literal["tiny", "base", "small", "medium"] = "small"
) -> Path:
    """Explicit anonymous public download; never use cached Hugging Face credentials."""
    if size not in {"tiny", "base", "small", "medium"}:
        raise ConfigurationError("只支持 tiny/base/small/medium 多语言语音模型。")
    if importlib.util.find_spec("huggingface_hub") is None:
        raise ConfigurationError('下载语音模型需要：pip install "videomind[speech]"。')
    repo = f"Systran/faster-whisper-{size}"
    directory = directory.resolve()
    try:
        hub = importlib.import_module("huggingface_hub")
        # Pin the observed revision so files cannot come from different revisions.
        revision = hub.HfApi().model_info(repo, token=False).sha
        if not isinstance(revision, str) or len(revision) != 40:
            raise ValueError("Invalid revision")
        hub.snapshot_download(
            repo,
            revision=revision,
            local_dir=str(directory),
            allow_patterns=[*MODEL_FILES, *VOCAB_FILES, "preprocessor_config.json", "README.md"],
            token=False,
            max_workers=2,
        )
        hashes = {}
        files = _model_files(directory)
        if not files:
            raise ValueError("Incomplete model")
        for path in files:
            with path.open("rb") as handle:
                hashes[path.name] = hashlib.file_digest(handle, "sha256").hexdigest()
        (directory / "videomind-model.json").write_text(
            json.dumps({"repository": repo, "revision": revision, "sha256": hashes}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        raise MediaError(
            "语音模型下载失败；请检查公共 Hugging Face 连接及磁盘空间。"
            "可再次运行下载命令，或自行准备兼容的本地模型；未调用付费 API。"
        ) from None
    return directory


@dataclass(frozen=True)
class SpeechResult:
    evidence: tuple[Evidence, ...]
    language: str


def transcribe(audio: Path, config: SpeechConfig, duration: float) -> SpeechResult:
    check_speech(config)
    try:
        whisper = importlib.import_module("faster_whisper")
        model = whisper.WhisperModel(
            str(config.model_directory.resolve()),
            device="cpu",
            compute_type="int8",
            cpu_threads=config.cpu_threads,
            local_files_only=True,
        )
        segments, info = model.transcribe(
            str(audio.resolve()),
            language=config.language,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        records = []
        # faster-whisper executes lazily: iteration must remain in the error boundary.
        for segment in segments:
            text = segment.text.strip()
            start, end = float(segment.start), float(segment.end)
            if not text:
                continue
            if not math.isfinite(start + end) or start < 0 or end < start or end > duration + 1:
                raise ValueError("Invalid ASR timestamps")
            if start >= duration:
                continue
            uncertainty = "本地 faster-whisper 自动转录，未经人工核验；可能误听或漏词。"
            # Model scores are review hints, not calibrated correctness probabilities.
            score = getattr(segment, "avg_logprob", None)
            if isinstance(score, (float, int)) and math.isfinite(score) and score < -1.0:
                uncertainty += f" 该片段平均对数概率较低（{score:.2f}），建议优先回听。"
            records.append(
                Evidence(
                    start_seconds=start,
                    end_seconds=min(end, duration),
                    source="transcription",
                    text=text,
                    uncertainty=uncertainty,
                )
            )
        return SpeechResult(tuple(records), str(info.language))
    except Exception:
        raise MediaError(
            "本地语音识别失败；请检查模型文件、音轨及 speech 依赖。原始证据会保留。"
        ) from None
