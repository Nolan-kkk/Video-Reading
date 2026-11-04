import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from videomind.billing import Budget
from videomind.config import ProviderConfig
from videomind.errors import BudgetError, ProviderError
from videomind.exporters.markdown import export
from videomind.models.schemas import Evidence
from videomind.providers.deepseek import ENDPOINT, DeepSeekProvider
from videomind.security import Credential


def response(content, *, finish="stop", usage=True):
    result = {"choices": [{"message": {"content": json.dumps(content)}, "finish_reason": finish}]}
    if usage:
        result["usage"] = {"prompt_tokens": 20, "completion_tokens": 30}
    return httpx.Response(200, json=result)


def provider(handler, *, model="deepseek-flash", authorized=True):
    budget = Budget(Decimal("5"), authorized=authorized)
    adapter = DeepSeekProvider(
        ProviderConfig(provider="deepseek", model=model, api_key_env="VIDEOMIND_TEST_KEY"),
        Credential(api_key=SecretStr("test-only-deepseek-key")),
        budget,
        transport=httpx.MockTransport(handler),
    )
    return adapter, budget


def sample_evidence():
    return [Evidence(start_seconds=0, end_seconds=1, source="subtitle", text="intro")]


def test_text_request_uses_only_official_endpoint_and_explicit_key():
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert str(request.url) == ENDPOINT
        assert request.headers["authorization"] == "Bearer test-only-deepseek-key"
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["max_tokens"] == 2048
        return response(
            {"sections": [{"title": "Intro", "summary": "Summary", "evidence_ids": ["E0001"]}]}
        )

    adapter, budget = provider(handler)
    result = asyncio.run(adapter.organize(sample_evidence()))
    assert "transcript.md#e0001" in result.markdown
    assert len(calls) == 1
    assert budget.reserved_usd > 0
    assert result.usage.input_tokens == 20
    assert result.usage.billed_usd is None


def test_no_authorization_means_no_http_call():
    adapter, budget = provider(lambda _: pytest.fail("must not call"), authorized=False)
    with pytest.raises(BudgetError):
        asyncio.run(adapter.organize(sample_evidence()))
    assert budget.reserved_usd == 0


def test_visual_json_keeps_partial_code_and_uncertainty(tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"fake-png-only-for-mock")

    def handler(request):
        payload = json.loads(request.content)
        assert payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png")
        return response(
            {
                "description": "Code slide",
                "code": [
                    {"language": "python", "text": "print(", "uncertainty": "last part missing"}
                ],
            }
        )

    adapter, _ = provider(handler)
    result = asyncio.run(adapter.describe_frame(image, 3.5))
    assert result.evidence[0].start_seconds == 3.5
    assert result.evidence[0].code[0].text == "print("
    assert result.evidence[0].code[0].uncertainty == "last part missing"


@pytest.mark.parametrize(
    "visual,expected",
    [
        (
            {"description": "PPT 标题：项目计划；正文部分模糊", "uncertainty": "正文不可辨"},
            "项目计划",
        ),
        (
            {"description": "柱状图；横轴为季度，纵轴单位不可辨", "uncertainty": "具体数值不可辨"},
            "柱状图",
        ),
        (
            {
                "description": "代码画面",
                "uncertainty": "右侧被遮挡",
                "code": [
                    {"language": "python", "text": "if x:\n    print(", "uncertainty": "缺失右侧"}
                ],
            },
            "print(",
        ),
    ],
)
def test_visual_evidence_survives_export_with_uncertainty(tmp_path, visual, expected):
    image = tmp_path / "frame.png"
    image.write_bytes(b"mock-image")

    def handler(request):
        payload = json.loads(request.content)
        instruction = payload["messages"][0]["content"]
        assert all(word in instruction for word in ("axes", "units", "indentation", "unreadable"))
        return response(visual)

    adapter, _ = provider(handler)
    evidence = asyncio.run(adapter.describe_frame(image, 12.5)).evidence
    export(tmp_path, evidence, {"status": "completed"}, notes=None, mode="raw")
    transcript = (tmp_path / "transcript.md").read_text(encoding="utf-8")
    records = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))["evidence"]
    assert "00:00:12.500" in transcript
    assert visual["uncertainty"] in transcript
    assert records[0]["source"] == "vision"
    output = (tmp_path / ("code.md" if "code" in visual else "transcript.md")).read_text(
        encoding="utf-8"
    )
    assert expected in output
    if "code" in visual:
        assert "if x:\n    print(" in output


def test_text_only_model_rejects_images_before_http(tmp_path):
    adapter, budget = provider(lambda _: pytest.fail("must not call"), model="deepseek-v4-pro")
    with pytest.raises(ProviderError, match="不支持图像"):
        asyncio.run(adapter.describe_frame(tmp_path / "not-needed.png", 0))
    assert budget.reserved_usd == 0


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_http_errors_never_echo_body_or_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="test-only-deepseek-key", headers={"Location": "https://elsewhere.invalid"}
        )

    adapter, budget = provider(handler)
    with pytest.raises(ProviderError) as error:
        asyncio.run(adapter.organize(sample_evidence()))
    assert "test-only-deepseek-key" not in str(error.value)
    assert len(calls) == 1
    assert budget.reserved_usd > 0


def test_timeout_keeps_reservation_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("test-only-deepseek-key", request=request)

    adapter, budget = provider(handler)
    with pytest.raises(ProviderError) as error:
        asyncio.run(adapter.organize(sample_evidence()))
    assert "test-only-deepseek-key" not in str(error.value)
    assert len(calls) == 1
    assert budget.reserved_usd > 0


@pytest.mark.parametrize(
    "content,finish",
    [
        ({"sections": [{"title": "x", "summary": "y", "evidence_ids": ["E9999"]}]}, "stop"),
        ({"sections": []}, "stop"),
        ({"sections": [{"title": "x", "summary": "y", "evidence_ids": ["E0001"]}]}, "length"),
    ],
)
def test_invalid_or_truncated_notes_are_rejected(content, finish):
    adapter, _ = provider(lambda _: response(content, finish=finish))
    with pytest.raises(ProviderError):
        asyncio.run(adapter.organize(sample_evidence()))


def test_unknown_usage_is_null_and_echoed_secret_is_redacted():
    adapter, _ = provider(
        lambda _: response(
            {
                "sections": [
                    {"title": "x", "summary": "test-only-deepseek-key", "evidence_ids": ["E0001"]}
                ]
            },
            usage=False,
        )
    )
    result = asyncio.run(adapter.organize(sample_evidence()))
    assert "test-only-deepseek-key" not in result.markdown
    assert "[REDACTED]" in result.markdown
    assert result.usage.input_tokens is None
