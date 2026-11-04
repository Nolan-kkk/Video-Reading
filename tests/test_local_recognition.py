import asyncio
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from videomind.cli import main
from videomind.config import OCRConfig, Settings, SpeechConfig
from videomind.errors import ConfigurationError, MediaError
from videomind.models.schemas import Evidence
from videomind.pipeline import analyze
from videomind.processors import speech
from videomind.processors.ocr import FrameOCR
from videomind.processors.speech import SpeechResult, transcribe
from videomind.providers.deepseek import DeepSeekProvider


@pytest.fixture
def model_directory(tmp_path):
    model = tmp_path / "local model"
    model.mkdir()
    for name in (*speech.MODEL_FILES, "vocabulary.txt"):
        (model / name).write_text("fake model", encoding="utf-8")
    return model


@pytest.fixture
def local_settings(model_directory):
    return Settings(speech=SpeechConfig(enabled=True, model_directory=model_directory))


def mock_whisper(monkeypatch, segments):
    calls = []

    class Model:
        def __init__(self, directory, **kwargs):
            calls.append((directory, kwargs))

        def transcribe(self, audio, **kwargs):
            calls.append((audio, kwargs))
            return iter(segments), SimpleNamespace(language="zh")

    monkeypatch.setattr(speech.importlib.util, "find_spec", lambda _: True)
    monkeypatch.setattr(
        speech.importlib, "import_module", lambda _: SimpleNamespace(WhisperModel=Model)
    )
    return calls


def test_asr_only_loads_local_model_and_keeps_timestamps(model_directory, monkeypatch):
    calls = mock_whisper(monkeypatch, [SimpleNamespace(start=0.25, end=1.7, text="  真实语音  ")])
    result = transcribe(Path("audio.wav"), SpeechConfig(model_directory=model_directory), 2)
    assert result.evidence[0].source == "transcription"
    assert result.evidence[0].text == "真实语音"
    assert result.evidence[0].start_seconds == 0.25
    assert result.evidence[0].end_seconds == 1.7
    assert calls[0][1]["local_files_only"] is True
    assert calls[0][1]["device"] == "cpu" and calls[0][1]["compute_type"] == "int8"
    assert calls[1][1]["vad_filter"] is True


def test_low_asr_score_flags_review_without_changing_words(model_directory, monkeypatch):
    mock_whisper(
        monkeypatch,
        [
            SimpleNamespace(start=0.1, end=0.7, text="原文", avg_logprob=-1.25),
            SimpleNamespace(start=0.8, end=1.2, text="另一句", avg_logprob=-0.2),
        ],
    )
    result = transcribe(Path("audio.wav"), SpeechConfig(model_directory=model_directory), 2)
    assert result.evidence[0].text == "原文"
    assert "建议优先回听" in result.evidence[0].uncertainty
    assert "-1.25" in result.evidence[0].uncertainty
    assert "建议优先回听" not in result.evidence[1].uncertainty


def test_doctor_reports_missing_local_speech_model_without_reading_key(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    assert main(["doctor"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["speech_model_files_available"] is False
    assert any("prepare-speech" in item for item in result["recommended_actions"])
    assert result["paid_requests_enabled"] is False


def test_doctor_warns_when_pricing_snapshot_expires(monkeypatch, capsys):
    from datetime import date

    monkeypatch.setattr("videomind.cli.utc_today", lambda: date(2030, 1, 1))
    assert main(["doctor"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["pricing_snapshot_current"] is False
    assert any("价格快照已过期" in action for action in result["recommended_actions"])


@pytest.mark.parametrize("start,end", [(-1, 1), (1, 0), (0, 99), (0, float("nan"))])
def test_invalid_asr_timestamps_are_rejected(model_directory, monkeypatch, start, end):
    mock_whisper(monkeypatch, [SimpleNamespace(start=start, end=end, text="bad")])
    with pytest.raises(MediaError):
        transcribe(Path("audio.wav"), SpeechConfig(model_directory=model_directory), 2)


def test_lazy_asr_failure_is_sanitized(model_directory, monkeypatch):
    def broken():
        raise RuntimeError("test-only-secret-sdk-error")
        yield

    mock_whisper(monkeypatch, broken())
    with pytest.raises(MediaError) as error:
        transcribe(Path("audio.wav"), SpeechConfig(model_directory=model_directory), 2)
    assert "test-only-secret" not in str(error.value)
    assert error.value.__cause__ is None


def test_missing_model_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(speech.importlib.util, "find_spec", lambda _: True)
    monkeypatch.setattr(speech.importlib, "import_module", lambda _: pytest.fail("no SDK calls"))
    with pytest.raises(ConfigurationError, match="prepare-speech"):
        transcribe(Path("audio.wav"), SpeechConfig(model_directory=tmp_path), 2)


@pytest.mark.parametrize("size", ["base", "medium"])
def test_prepare_is_anonymous_pinned_and_records_hashes(tmp_path, monkeypatch, size):
    calls = []

    class API:
        def model_info(self, repo, **kwargs):
            calls.append((repo, kwargs))
            return SimpleNamespace(sha="a" * 40)

    def snapshot(repo, **kwargs):
        calls.append((repo, kwargs))
        root = Path(kwargs["local_dir"])
        for name in (*speech.MODEL_FILES, "vocabulary.txt"):
            (root / name).write_text("public model", encoding="utf-8")

    monkeypatch.setattr(speech.importlib.util, "find_spec", lambda _: True)
    monkeypatch.setattr(
        speech.importlib,
        "import_module",
        lambda _: SimpleNamespace(HfApi=API, snapshot_download=snapshot),
    )
    speech.prepare_speech(tmp_path, size)
    manifest = json.loads((tmp_path / "videomind-model.json").read_text(encoding="utf-8"))
    assert all(call[1]["token"] is False for call in calls)
    assert calls[1][1]["revision"] == "a" * 40
    assert "*.py" not in calls[1][1]["allow_patterns"]
    assert manifest["repository"] == f"Systran/faster-whisper-{size}"
    assert len(manifest["sha256"]["model.bin"]) == 64


def test_subtitles_preferred_without_loading_asr(sample_video, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "videomind.pipeline.check_speech", lambda _: pytest.fail("prefer subtitles")
    )
    settings = Settings(speech=SpeechConfig(enabled=True, model_directory=tmp_path / "missing"))
    result = asyncio.run(analyze(sample_video, settings, output=tmp_path / "output"))
    meta = json.loads((result.directory / "metadata.json").read_text(encoding="utf-8"))
    assert meta["local_recognition"]["speech"] == "subtitles_preferred"
    assert not (result.directory / "audio.wav").exists()


def test_local_audio_reaches_markdown_without_api(
    sample_video, tmp_path, monkeypatch, local_settings
):
    sample_video.with_suffix(".srt").unlink()
    monkeypatch.setattr("videomind.pipeline.check_speech", lambda _: None)
    monkeypatch.setattr(
        "videomind.pipeline.transcribe",
        lambda *args: SpeechResult(
            (
                Evidence(
                    start_seconds=0, end_seconds=1, source="transcription", text="spoken evidence"
                ),
            ),
            "en",
        ),
    )
    result = asyncio.run(analyze(sample_video, local_settings, output=tmp_path / "output"))
    assert "spoken evidence" in (result.directory / "transcript.md").read_text(encoding="utf-8")
    assert (result.directory / "audio.wav").exists()
    meta = json.loads((result.directory / "metadata.json").read_text(encoding="utf-8"))
    assert meta["local_recognition"]["speech_segments"] == 1
    assert meta["billing"]["reserved_upper_usd"] == "0"


def test_empty_transcription_blocks_all_cloud_calls(
    sample_video, tmp_path, monkeypatch, deepseek_settings, model_directory
):
    sample_video.with_suffix(".srt").unlink()
    settings = deepseek_settings.model_copy(
        update={
            "speech": SpeechConfig(enabled=True, model_directory=model_directory),
        }
    )
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-user-key")
    monkeypatch.setattr("videomind.pipeline.check_speech", lambda _: None)
    monkeypatch.setattr("videomind.pipeline.transcribe", lambda *args: SpeechResult((), "en"))
    monkeypatch.setattr(
        "videomind.pipeline.DeepSeekProvider", lambda *a, **k: pytest.fail("no cloud")
    )
    result = asyncio.run(
        analyze(sample_video, settings, output=tmp_path / "output", cloud=True, approve_paid=True)
    )
    assert result.status == "failed" and "无文本" in result.error
    assert (result.directory / "transcript.md").exists()
    meta = json.loads((result.directory / "metadata.json").read_text(encoding="utf-8"))
    assert meta["billing"]["reserved_upper_usd"] == "0"


def test_recognition_failure_preserves_raw_frames(
    sample_video, tmp_path, monkeypatch, local_settings
):
    sample_video.with_suffix(".srt").unlink()
    monkeypatch.setattr("videomind.pipeline.check_speech", lambda _: None)

    def failed(*args):
        raise MediaError("本地语音识别失败")

    monkeypatch.setattr("videomind.pipeline.transcribe", failed)
    result = asyncio.run(analyze(sample_video, local_settings, output=tmp_path / "output"))
    meta = json.loads((result.directory / "metadata.json").read_text(encoding="utf-8"))
    assert meta["local_recognition"]["speech"] == "failed"
    assert len(list((result.directory / "images").glob("*.png"))) == 2


def test_ocr_fast_is_rejected_even_in_preview(sample_video, capsys):
    assert main(["analyze", str(sample_video), "--ocr", "--depth", "fast", "--dry-run"]) == 2
    assert "OCR" in capsys.readouterr().err


def test_audio_and_ocr_are_in_cloud_evidence_payload(
    sample_video, tmp_path, monkeypatch, deepseek_settings, model_directory
):
    sample_video.with_suffix(".srt").unlink()
    settings = deepseek_settings.model_copy(
        update={
            "speech": SpeechConfig(enabled=True, model_directory=model_directory),
            "ocr": OCRConfig(enabled=True),
        }
    )
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-user-key")
    monkeypatch.setattr("videomind.pipeline.check_speech", lambda _: None)
    monkeypatch.setattr("videomind.pipeline.bundled_models", lambda: {})
    monkeypatch.setattr(
        "videomind.pipeline.transcribe",
        lambda *args: SpeechResult(
            (Evidence(start_seconds=0, end_seconds=1, source="transcription", text="spoken text"),),
            "en",
        ),
    )

    class OCR:
        def __init__(self, config):
            pass

        def recognize(self, path, seconds):
            return (
                Evidence(
                    start_seconds=seconds, end_seconds=seconds, source="ocr", text="slide text"
                ),
            )

    monkeypatch.setattr("videomind.pipeline.FrameOCR", OCR)
    received = []

    def handler(request):
        content = json.loads(request.content)["messages"][1]["content"]
        if isinstance(content, list):
            result = {"description": "a frame"}
        else:
            received.extend(json.loads(content))
            result = {
                "sections": [
                    {"title": "Combined", "summary": "audio and slide", "evidence_ids": ["E0001"]}
                ]
            }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(result)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "videomind.pipeline.DeepSeekProvider",
        lambda *a, **k: DeepSeekProvider(
            *a,
            **k,
            transport=httpx.MockTransport(handler),
        ),
    )
    result = asyncio.run(
        analyze(sample_video, settings, output=tmp_path / "output", cloud=True, approve_paid=True)
    )
    assert result.error is None
    assert any(
        row["source"] == "transcription" and row["text"] == "spoken text" for row in received
    )
    assert any(row["source"] == "ocr" and row["text"] == "slide text" for row in received)


def test_partial_ocr_failure_preserves_speech_and_first_frame(
    sample_video, tmp_path, monkeypatch, local_settings
):
    sample_video.with_suffix(".srt").unlink()
    settings = local_settings.model_copy(update={"ocr": OCRConfig(enabled=True)})
    monkeypatch.setattr("videomind.pipeline.check_speech", lambda _: None)
    monkeypatch.setattr("videomind.pipeline.bundled_models", lambda: {})
    monkeypatch.setattr(
        "videomind.pipeline.transcribe",
        lambda *args: SpeechResult(
            (Evidence(start_seconds=0, end_seconds=1, source="transcription", text="audio kept"),),
            "en",
        ),
    )

    class OCR:
        def __init__(self, config):
            self.calls = 0

        def recognize(self, path, seconds):
            self.calls += 1
            if self.calls > 1:
                raise MediaError("画面文字识别失败")
            return (
                Evidence(
                    start_seconds=seconds,
                    end_seconds=seconds,
                    source="ocr",
                    text="first frame kept",
                ),
            )

    monkeypatch.setattr("videomind.pipeline.FrameOCR", OCR)
    result = asyncio.run(analyze(sample_video, settings, output=tmp_path / "output"))
    assert result.status == "failed"
    transcript = (result.directory / "transcript.md").read_text(encoding="utf-8")
    assert "audio kept" in transcript and "first frame kept" in transcript
    meta = json.loads((result.directory / "metadata.json").read_text(encoding="utf-8"))
    assert meta["local_recognition"]["speech"] == "completed"
    assert meta["local_recognition"]["ocr"] == "failed"


def test_real_bundled_ocr_has_no_network_and_keeps_geometry(tmp_path):
    pytest.importorskip("rapidocr")
    pytest.importorskip("onnxruntime")
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (640, 160), "white")
    draw = ImageDraw.Draw(image)
    # Pillow includes DejaVuSans on many platforms; Windows has Arial.
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path) if font_path.exists() else "DejaVuSans.ttf", 42)
    draw.text((25, 40), "Hello VideoMind 123", fill="black", font=font)
    frame = tmp_path / "text.png"
    image.save(frame)
    result = FrameOCR(OCRConfig()).recognize(frame, 1.5)
    assert "VideoMind" in result[0].text
    assert result[0].source == "ocr" and result[0].start_seconds == 1.5
    assert all(len(line.box) == 4 and 0 <= line.confidence <= 1 for line in result[0].ocr_lines)


@pytest.mark.parametrize(
    "lines,expected",
    [
        (["PROJECT PLAN", "Milestone Alpha", "Next steps"], "PROJECT"),
        (["def calculate_total(items):", "    return sum(items)"], "calculate"),
        (["SALES CHART", "Revenue USD", "2024  2025"], "SALES"),
    ],
)
def test_real_ocr_on_slide_code_and_chart_labels(tmp_path, lines, expected):
    pytest.importorskip("rapidocr")
    pytest.importorskip("onnxruntime")
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1000, 300), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path) if font_path.exists() else "DejaVuSans.ttf", 42)
    for index, line in enumerate(lines):
        draw.text((30, 25 + index * 75), line, fill="black", font=font)
    if expected == "SALES":
        draw.line((620, 220, 940, 220), fill="black", width=3)
        draw.line((620, 50, 620, 220), fill="black", width=3)
        draw.rectangle((680, 140, 750, 219), fill="blue")
        draw.rectangle((800, 90, 870, 219), fill="blue")
    frame = tmp_path / "sample.png"
    image.save(frame)
    result = FrameOCR(OCRConfig()).recognize(frame, 4.0)
    assert result and expected.lower() in result[0].text.lower()
    assert result[0].start_seconds == 4.0 and result[0].source == "ocr"


def test_real_local_asr_does_not_hallucinate_test_tone(sample_video, tmp_path):
    if importlib.util.find_spec("faster_whisper") is None:
        pytest.skip("Optional speech dependency not installed")
    model = Path(
        os.environ.get(
            "VIDEOMIND_TEST_SPEECH_MODEL",
            str(Path(__file__).resolve().parents[1] / ".cache/models/faster-whisper-small"),
        )
    )
    if not (model / "model.bin").is_file():
        pytest.skip("Explicitly prepared local speech model required; tests never download")
    from videomind.processors.media import extract_audio

    audio = tmp_path / "tone.wav"
    extract_audio(sample_video, audio, 2)
    assert transcribe(audio, SpeechConfig(model_directory=model), 2).evidence == ()
