import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from videomind.cli import main
from videomind.config import Settings
from videomind.errors import BudgetError, CredentialsError, ProviderError
from videomind.pipeline import analyze
from videomind.providers.deepseek import DeepSeekProvider


def test_offline_real_video_to_traceable_markdown(sample_video, tmp_path):
    result = asyncio.run(
        analyze(sample_video, Settings(), output=tmp_path / "output", save_audio=True)
    )
    assert result.status == "completed_with_limitations"
    for name in (
        "metadata.json",
        "transcript.md",
        "notes.md",
        "code.md",
        "uncertainties.md",
        "usage.md",
        "evidence.json",
        "audio.wav",
    ):
        assert (result.directory / name).is_file()
    metadata = json.loads((result.directory / "metadata.json").read_text(encoding="utf-8"))
    evidence = json.loads((result.directory / "evidence.json").read_text(encoding="utf-8"))[
        "evidence"
    ]
    assert metadata["frame_count"] == 2
    assert metadata["billing"]["reserved_upper_usd"] == "0"
    assert metadata["billing"]["actual_invoice_usd"] is None
    assert sum(e["source"] == "subtitle" for e in evidence) == 2
    assert sum(e["source"] == "frame" for e in evidence) == 2
    assert all((result.directory / e["frame"]).exists() for e in evidence if e["frame"])
    assert "尚无 AI 整理结果" in (result.directory / "notes.md").read_text(encoding="utf-8")
    assert "这不表示视频中没有代码" in (result.directory / "code.md").read_text(encoding="utf-8")


def test_cloud_missing_key_has_no_artifacts(sample_video, tmp_path, deepseek_settings, monkeypatch):
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    output = tmp_path / "output"
    with pytest.raises(CredentialsError):
        asyncio.run(
            analyze(sample_video, deepseek_settings, output=output, cloud=True, approve_paid=True)
        )
    assert not output.exists()


def test_no_approval_or_budget_means_no_request(
    sample_video, tmp_path, deepseek_settings, monkeypatch
):
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-user-key")
    with pytest.raises(BudgetError):
        asyncio.run(
            analyze(sample_video, deepseek_settings, output=tmp_path / "output", cloud=True)
        )
    small = deepseek_settings.model_copy(
        update={
            "billing": deepseek_settings.billing.model_copy(
                update={"max_budget_usd_per_batch": Decimal("0.001")}
            )
        }
    )
    with pytest.raises(BudgetError):
        asyncio.run(
            analyze(sample_video, small, output=tmp_path / "output", cloud=True, approve_paid=True)
        )
    assert not (tmp_path / "output").exists()


def test_no_subtitles_does_not_silently_claim_speech_understanding(
    sample_video, tmp_path, deepseek_settings
):
    sample_video.with_suffix(".srt").unlink()
    with pytest.raises(ProviderError, match="语音转录"):
        asyncio.run(
            analyze(sample_video, deepseek_settings, output=tmp_path / "output", cloud=True)
        )


def test_dry_run_is_offline_and_creates_nothing(sample_video, tmp_path, media_tools, capsys):
    output = tmp_path / "output"
    assert main(["analyze", str(sample_video), "--dry-run", "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["paid_requests_sent"] == 0
    assert not output.exists()


def test_mocked_cloud_pipeline_keeps_code_sources_and_citations(
    sample_video, tmp_path, deepseek_settings, monkeypatch
):
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-user-key")
    calls = []

    def handler(request):
        calls.append(request)
        content = json.loads(request.content)["messages"][1]["content"]
        result = (
            {
                "description": "Code slide",
                "code": [{"language": "python", "text": "print(", "uncertainty": "cropped"}],
            }
            if isinstance(content, list)
            else {
                "sections": [
                    {"title": "Code", "summary": "partial code", "evidence_ids": ["E0001"]}
                ]
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(result)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    monkeypatch.setattr(
        "videomind.pipeline.DeepSeekProvider",
        lambda *args, **kwargs: DeepSeekProvider(
            *args, **kwargs, transport=httpx.MockTransport(handler)
        ),
    )
    result = asyncio.run(
        analyze(
            sample_video,
            deepseek_settings,
            output=tmp_path / "output",
            cloud=True,
            approve_paid=True,
        )
    )
    assert result.status == "completed"
    assert len(calls) == 3
    code = (result.directory / "code.md").read_text(encoding="utf-8")
    assert "print(" in code and "cropped" in code
    usage = (result.directory / "usage.md").read_text(encoding="utf-8")
    assert "输入 300；输出 150 Token" in usage
    report = (result.directory / "uncertainties.md").read_text(encoding="utf-8")
    assert "cropped" in report and "transcript.md#e" in report
    assert "transcript.md#e0001" in (result.directory / "notes.md").read_text(encoding="utf-8")
    for path in result.directory.glob("*.*"):
        if path.suffix in {".md", ".json"}:
            assert "test-only-user-key" not in path.read_text(encoding="utf-8")


def test_remote_failure_preserves_raw_evidence_and_reserved_cost(
    sample_video, tmp_path, deepseek_settings, monkeypatch
):
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-user-key")
    transport = httpx.MockTransport(lambda _: httpx.Response(401, text="test-only-user-key"))
    monkeypatch.setattr(
        "videomind.pipeline.DeepSeekProvider",
        lambda *args, **kwargs: DeepSeekProvider(*args, **kwargs, transport=transport),
    )
    result = asyncio.run(
        analyze(
            sample_video,
            deepseek_settings,
            output=tmp_path / "output",
            cloud=True,
            approve_paid=True,
        )
    )
    assert result.status == "failed"
    metadata = json.loads((result.directory / "metadata.json").read_text(encoding="utf-8"))
    assert Decimal(metadata["billing"]["reserved_upper_usd"]) > 0
    assert "test-only-user-key" not in json.dumps(metadata)
    assert "Intro" in (result.directory / "transcript.md").read_text(encoding="utf-8")
    assert "处理失败" in (result.directory / "uncertainties.md").read_text(encoding="utf-8")
    usage = (result.directory / "usage.md").read_text(encoding="utf-8")
    assert "没有收到服务商 Token 用量" in usage
    assert len(list((result.directory / "images").glob("*.png"))) == 2
