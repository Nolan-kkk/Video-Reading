import json
import shutil
from decimal import Decimal

import httpx
import pytest
import yaml

from videomind import batch, synthesis
from videomind.cli import main
from videomind.config import Settings
from videomind.errors import BudgetError, ConfigurationError, ProviderError
from videomind.providers.deepseek import DeepSeekProvider


@pytest.fixture
def completed_batch(sample_video, tmp_path):
    second = tmp_path / "second.mp4"
    shutil.copyfile(sample_video, second)
    shutil.copyfile(sample_video.with_suffix(".srt"), second.with_suffix(".srt"))
    listing = tmp_path / "list.txt"
    listing.write_text(f"{sample_video}\n{second}\nmissing.mp4\n", encoding="utf-8")
    return batch.run_batch(listing, Settings(), output=tmp_path / "out").directory


def mock_provider(monkeypatch, calls, response_data):
    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(response_data)}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    monkeypatch.setattr(
        synthesis,
        "DeepSeekProvider",
        lambda *a, **k: DeepSeekProvider(*a, **k, transport=httpx.MockTransport(handler)),
    )


def test_preview_without_credentials_and_fusion_with_citations(
    completed_batch, deepseek_settings, monkeypatch
):
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    plan = synthesis.preview_synthesis(completed_batch, deepseek_settings)
    assert plan["video_count"] == 2 and plan["paid_requests_sent"] == 0
    assert "J0003: failed" in plan["excluded_jobs"]
    assert plan["credentials"] == "not_checked"
    with pytest.raises(ConfigurationError, match="yes-paid"):
        synthesis.synthesize(completed_batch, deepseek_settings, yes_paid=False, new_attempt=False)
    assert not (completed_batch / "synthesis_status.json").exists()
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-key")
    calls = []
    mock_provider(
        monkeypatch,
        calls,
        {
            "sections": [
                {
                    "title": "共同主题",
                    "summary": "两段均有介绍。",
                    "evidence_ids": ["J0001-E0002", "J0002-E0002"],
                }
            ]
        },
    )
    report = synthesis.synthesize(
        completed_batch, deepseek_settings, yes_paid=True, new_attempt=False
    )
    text = report.read_text(encoding="utf-8")
    assert "共同主题" in text and "J0003: failed" in text
    assert "输入 100；输出 50 Token" in text
    assert text.count("transcript.md#e0002") == 2 and "00:00:00.000" in text
    assert text.count("uncertainties.md") == 2
    for link in [part.split(")", 1)[0] for part in text.split("](")[1:]]:
        assert (completed_batch / link.split("#")[0]).is_file()
    assert len(calls) == 1
    payload = json.loads(calls[0].content)
    rows = json.loads(payload["messages"][1]["content"])
    assert {r["video_id"] for r in rows} == {"J0001", "J0002"}
    assert sum("video_limitations" in row for row in rows) == 2
    assert "处理限制" in text
    assert "data:image" not in json.dumps(payload)
    journal = json.loads((completed_batch / "synthesis_status.json").read_text(encoding="utf-8"))
    assert journal["attempts"][0]["status"] == "completed"
    assert Decimal(journal["attempts"][0]["reserved_usd"]) > 0
    with pytest.raises(ConfigurationError, match="new-attempt"):
        synthesis.synthesize(completed_batch, deepseek_settings, yes_paid=True, new_attempt=False)
    assert len(calls) == 1


@pytest.mark.parametrize("refs", [["J0001-E0002"], ["J0001-E0002", "J0009-E0001"]])
def test_invalid_citations_fail_and_keep_reservation(
    completed_batch, deepseek_settings, monkeypatch, refs
):
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-key")
    calls = []
    mock_provider(
        monkeypatch, calls, {"sections": [{"title": "x", "summary": "y", "evidence_ids": refs}]}
    )
    with pytest.raises(ProviderError):
        synthesis.synthesize(completed_batch, deepseek_settings, yes_paid=True, new_attempt=False)
    journal = json.loads((completed_batch / "synthesis_status.json").read_text(encoding="utf-8"))
    assert journal["attempts"][0]["status"] == "failed" and len(calls) == 1
    assert not list(completed_batch.glob("fusion_*.md"))
    with pytest.raises(ConfigurationError, match="new-attempt"):
        synthesis.synthesize(completed_batch, deepseek_settings, yes_paid=True, new_attempt=False)


def test_tampered_evidence_and_low_budget_block(completed_batch, deepseek_settings):
    low = deepseek_settings.model_copy(
        update={
            "billing": deepseek_settings.billing.model_copy(
                update={"max_budget_usd_per_batch": Decimal("0.0001")}
            )
        }
    )
    with pytest.raises(BudgetError):
        synthesis.preview_synthesis(completed_batch, low)
    state = json.loads((completed_batch / "batch_status.json").read_text(encoding="utf-8"))
    folder = completed_batch / state["jobs"][0]["output"]
    (folder / "evidence.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="产物"):
        synthesis.preview_synthesis(completed_batch, deepseek_settings)


def test_timeout_keeps_reservation_and_explicit_retry_accumulates(
    completed_batch, deepseek_settings, monkeypatch
):
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-key")
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("private detail", request=request)

    monkeypatch.setattr(
        synthesis,
        "DeepSeekProvider",
        lambda *a, **k: DeepSeekProvider(*a, **k, transport=httpx.MockTransport(timeout)),
    )
    for retry in (False, True):
        with pytest.raises(ProviderError, match="可能已计费"):
            synthesis.synthesize(
                completed_batch, deepseek_settings, yes_paid=True, new_attempt=retry
            )
    journal = json.loads((completed_batch / "synthesis_status.json").read_text(encoding="utf-8"))
    assert len(journal["attempts"]) == len(calls) == 2
    assert all(attempt["status"] == "failed" for attempt in journal["attempts"])
    assert synthesis.preview_synthesis(completed_batch, deepseek_settings)[
        "previous_synthesis_reserved_usd"
    ] == str(sum(Decimal(attempt["reserved_usd"]) for attempt in journal["attempts"]))


def test_cli_preview_is_offline_and_does_not_create_journal(
    completed_batch, deepseek_settings, tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(deepseek_settings.model_dump(mode="json")), encoding="utf-8")
    assert main(["synthesize", str(completed_batch), "--config", str(config), "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["video_count"] == 2
    assert not (completed_batch / "synthesis_status.json").exists()
