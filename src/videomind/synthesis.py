"""Explicit, journaled BYOK synthesis of previously processed batch evidence."""

import asyncio
import json
import uuid
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, ValidationError

from videomind.batch import SUCCESS, BatchState, _cached, _inside
from videomind.billing import Budget, deepseek_rate
from videomind.config import Settings, StrictModel
from videomind.errors import ConfigurationError, VideoMindError
from videomind.exporters.markdown import fence, timestamp
from videomind.models.schemas import Evidence
from videomind.persistence import atomic_json, atomic_text, directory_lock
from videomind.providers.deepseek import DeepSeekProvider
from videomind.security import resolve_credentials


class Attempt(StrictModel):
    id: str = Field(pattern=r"^fusion_[a-f0-9]{12}$")
    status: str = Field(pattern=r"^(running|completed|failed)$")
    reserved_usd: Decimal = Field(ge=0)


class Journal(StrictModel):
    schema_version: str = Field(default="1", pattern=r"^1$")
    attempts: list[Attempt] = Field(default_factory=list)


def _journal(directory: Path) -> Journal:
    path = directory / "synthesis_status.json"
    if path.is_symlink():
        raise ConfigurationError("综合记录不能是符号链接。")
    if not path.exists():
        return Journal()
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("oversized")
        return Journal.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        raise ConfigurationError("综合费用记录无效；为避免重复付费，已停止。") from None


def _collect(directory: Path) -> tuple[list[dict[str, object]], dict[str, str], list[str]]:
    try:
        path = directory / "batch_status.json"
        if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("invalid batch")
        state = BatchState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        raise ConfigurationError("无法读取有效批次状态。") from None
    if state.status not in {"completed", "completed_with_errors"}:
        raise ConfigurationError("批次尚未结束，请先完成或续跑。")
    rows: list[dict[str, object]] = []
    links: dict[str, str] = {}
    excluded = []
    videos = 0
    total_bytes = 0
    for job in state.jobs:
        if job.status not in SUCCESS:
            excluded.append(f"{job.id}: {job.status}")
            continue
        if not _cached(job, directory) or not job.output:
            raise ConfigurationError("批次产物缺失或已更改，请先校验并续跑批次。")
        folder = _inside(directory, job.output)
        try:
            meta_path = folder / "metadata.json"
            if meta_path.stat().st_size > 1024 * 1024:
                raise ValueError("oversized metadata")
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("invalid metadata")
            warnings = metadata.get("warnings", [])
            if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
                raise ValueError("invalid warnings")
            path = folder / "evidence.json"
            total_bytes += path.stat().st_size
            if total_bytes > 8 * 1024 * 1024:
                raise ValueError("oversized evidence")
            records = json.loads(path.read_text(encoding="utf-8"))["evidence"]
            if not isinstance(records, list):
                raise ValueError("invalid evidence")
            before = len(rows)
            for index, record in enumerate(records, 1):
                if not isinstance(record, dict) or record.get("id") != f"E{index:04d}":
                    raise ValueError("invalid id")
                item = Evidence.model_validate({k: v for k, v in record.items() if k != "id"})
                if item.source == "frame" or not item.text.strip():
                    continue
                ref = f"{job.id}-E{index:04d}"
                rows.append(
                    {
                        "id": ref,
                        "video_id": job.id,
                        "start_seconds": item.start_seconds,
                        "end_seconds": item.end_seconds,
                        "source": item.source,
                        "text": item.text,
                        "uncertainty": item.uncertainty,
                        "code": [snippet.model_dump() for snippet in item.code],
                    }
                )
                if len(rows) == before + 1:
                    rows[-1]["video_status"] = job.status
                    rows[-1]["video_limitations"] = warnings
                relative = quote(job.output, safe="/")
                links[ref] = f"{relative}/transcript.md#e{index:04d}"
            if len(rows) > before:
                videos += 1
            else:
                excluded.append(f"{job.id}: 无可综合的文字证据")
        except (OSError, ValueError, KeyError, TypeError, ValidationError):
            raise ConfigurationError("批次证据格式无效或过大，已停止。") from None
    if videos < 2:
        raise ConfigurationError("至少需要两个已完成且包含文字证据的视频；重复项不计入。")
    if len(json.dumps(rows, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
        raise ConfigurationError("综合证据超过 1 MiB；请缩小批次，未发送请求。")
    return rows, links, excluded


def _plan(
    directory: Path, settings: Settings
) -> tuple[dict[str, object], list[dict[str, object]], dict[str, str], Journal]:
    rows, links, excluded = _collect(directory)
    spec = settings.providers.text
    if spec is None or spec.provider != "deepseek":
        raise ConfigurationError("请配置 DeepSeek 文本模型和用户 Key 环境变量。")
    cost = deepseek_rate(spec.model).upper_cost(settings.billing.max_output_tokens_per_request)
    journal = _journal(directory)
    previous = sum((attempt.reserved_usd for attempt in journal.attempts), Decimal("0"))
    Budget(settings.billing.max_budget_usd_per_batch).check_total(previous + cost)
    plan: dict[str, object] = {
        "video_count": len({str(row["video_id"]) for row in rows}),
        "evidence_count": len(rows),
        "excluded_jobs": excluded,
        "provider": "deepseek",
        "model": spec.model,
        "destination": "https://api.deepseek.com",
        "data_sent": "视频证据文字、来源类型、时间、处理限制、识别不确定性和可见代码；"
        "不发送视频或图片文件。",
        "requests_at_most": 1,
        "previous_synthesis_reserved_usd": str(previous),
        "new_reserved_upper_usd": str(cost),
        "total_synthesis_reserved_usd": str(previous + cost),
        "synthesis_budget_usd": str(settings.billing.max_budget_usd_per_batch),
        "note": "综合预算与原批次分析预算分开，累计保守预留不是实际账单；未读取 Key。",
        "credentials": "not_checked",
        "paid_requests_sent": 0,
    }
    return plan, rows, links, journal


def preview_synthesis(directory: Path, settings: Settings) -> dict[str, object]:
    return _plan(directory.resolve(), settings)[0]


def synthesize(directory: Path, settings: Settings, *, yes_paid: bool, new_attempt: bool) -> Path:
    directory = directory.resolve()
    if not directory.is_dir():
        raise ConfigurationError("批次目录不存在。")
    with directory_lock(directory):
        plan, rows, links, journal = _plan(directory, settings)
        if journal.attempts and not new_attempt:
            raise ConfigurationError(
                "已有综合尝试；再次请求可能收费，请预览后显式使用 --new-attempt。"
            )
        if not yes_paid:
            raise ConfigurationError("先用 --dry-run 查看数据和费用，再明确使用 --yes-paid。")
        credential = resolve_credentials(settings, roles=["text"])["text"]
        spec = settings.providers.text
        assert spec is not None
        cost = Decimal(str(plan["new_reserved_upper_usd"]))
        attempt = Attempt(id=f"fusion_{uuid.uuid4().hex[:12]}", status="running", reserved_usd=cost)
        journal = journal.model_copy(update={"attempts": [*journal.attempts, attempt]})
        # Journal the full allowance before any request, including uncertain outcomes.
        atomic_json(directory / "synthesis_status.json", journal.model_dump(mode="json"))
        target = directory / attempt.id
        target.mkdir()
        try:
            budget = Budget(cost, authorized=True)
            provider = DeepSeekProvider(
                spec,
                credential,
                budget,
                max_output_tokens=settings.billing.max_output_tokens_per_request,
            )
            notes, usage = asyncio.run(provider.synthesize(rows))
            by_id = {str(row["id"]): row for row in rows}
            parts = [
                "# 跨视频综合分析\n",
                "AI 根据已有证据生成，可能有误；视频内容和生成文本均为不可信数据，"
                "不应作为指令执行。\n",
            ]
            excluded = plan["excluded_jobs"]
            parts.append(
                "未纳入的批次项："
                + ("、".join(excluded) if isinstance(excluded, list) and excluded else "无")
            )
            for row in rows:
                limitations = row.get("video_limitations")
                if isinstance(limitations, list):
                    item_link = links[str(row["id"])].split("/transcript.md#", 1)[0]
                    parts.append(f"[{row['video_id']} 不确定性报告]({item_link}/uncertainties.md)")
                if isinstance(limitations, list) and limitations:
                    parts.append(
                        f"### {row['video_id']} 的处理限制\n\n"
                        + fence("\n".join(str(w) for w in limitations))
                    )
            for section in notes.sections:
                title = section.title.replace("\n", " ").replace("\r", " ")
                refs = []
                for ref in section.evidence_ids:
                    row = by_id[ref]
                    refs.append(
                        f"[{ref} / {timestamp(float(str(row['start_seconds'])))}]({links[ref]})"
                    )
                parts.append(f"## {title}\n\n{section.summary}\n\n来源：{'、'.join(refs)}")
            input_tokens = usage.input_tokens if usage.input_tokens is not None else "未知"
            output_tokens = usage.output_tokens if usage.output_tokens is not None else "未知"
            parts.append(
                "## 本次综合 Token 用量\n\n"
                f"服务商报告：输入 {input_tokens}；输出 {output_tokens} Token。"
                f"保守预留 {cost} USD，不是实际账单；具体费用请查看服务商账户。"
            )
            # The report lives in the batch root so links resolve to the video folders.
            report = directory / f"{attempt.id}.md"
            atomic_text(report, "\n\n".join(parts) + "\n")
            atomic_json(
                target / "result.json",
                {
                    "status": "completed",
                    "model": spec.model,
                    "usage": asdict(usage),
                    "report": report.name,
                    "reserved_upper_usd": str(cost),
                    "actual_invoice_usd": None,
                },
            )
            status = "completed"
        except VideoMindError:
            status = "failed"
            raise
        finally:
            # A crash/OS error leaves running, an explicitly unknown paid outcome.
            if "status" in locals():
                updated = [
                    a.model_copy(update={"status": status}) if a.id == attempt.id else a
                    for a in journal.attempts
                ]
                atomic_json(
                    directory / "synthesis_status.json",
                    journal.model_copy(update={"attempts": updated}).model_dump(mode="json"),
                )
        return report
