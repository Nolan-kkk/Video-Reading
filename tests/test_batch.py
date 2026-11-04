import json
import shutil
import threading
from datetime import date
from decimal import Decimal

import httpx
import pytest

from videomind import batch
from videomind.cli import main
from videomind.config import Settings
from videomind.errors import BudgetError, ConfigurationError, CredentialsError, SourceError
from videomind.extractors.base import AcquiredVideo, SourceInfo
from videomind.persistence import atomic_json, directory_lock
from videomind.pipeline import AnalysisResult
from videomind.providers.deepseek import DeepSeekProvider

URL = "https://www.bilibili.com/video/BV1NNNqzVEi4/"


def test_summary_preview_covers_beginning_middle_and_end():
    evidence = [
        {"id": f"E{index:04d}", "source": "frame" if index == 10 else "ocr"} for index in range(21)
    ]
    selected = batch._preview_evidence(evidence)
    assert len(selected) == 5
    assert selected[0]["id"] == "E0000" and selected[-1]["id"] == "E0020"
    assert any(8 <= int(str(item["id"])[1:]) <= 12 for item in selected)
    assert all(item["source"] != "frame" for item in selected)


def manifest(result):
    return json.loads((result.directory / "batch_status.json").read_text(encoding="utf-8"))


def sources(tmp_path, *values):
    path = tmp_path / "inputs.txt"
    path.write_text("\n".join(str(value) for value in values), encoding="utf-8-sig")
    return path


def test_parser_paths_relative_to_list_and_normalized_dedup(tmp_path, monkeypatch):
    path = sources(
        tmp_path,
        "# comment",
        "",
        "a video.mp4",
        "./a video.mp4",
        URL + "?vd_source=tracking",
        URL,
        "https://example.com/?api_key=test-only-secret",
    )
    monkeypatch.chdir(tmp_path.parent)
    jobs = batch.read_sources(path)
    assert len(jobs) == 5
    assert jobs[0].source == str(tmp_path / "a video.mp4")
    assert jobs[1].duplicate_of == "J0001" and jobs[1].status == "skipped"
    assert jobs[2].source == URL and jobs[3].duplicate_of == "J0003"
    assert jobs[4].status == "failed" and jobs[4].source is None
    assert "test-only-secret" not in jobs[4].model_dump_json()


def test_empty_or_oversized_input_fails_without_output(tmp_path):
    path = sources(tmp_path, "# empty")
    with pytest.raises(ConfigurationError):
        batch.read_sources(path)
    path.write_text("a" * (1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        batch.read_sources(path)


def test_accidentally_pasted_key_is_not_persisted(tmp_path):
    secret = "test-only-accidental-private-key"
    result = batch.run_batch(sources(tmp_path, secret), Settings(), output=tmp_path / "out")
    assert result.counts["failed"] == 1
    assert secret not in (result.directory / "batch_status.json").read_text(encoding="utf-8")
    assert secret not in (result.directory / "batch_summary.md").read_text(encoding="utf-8")


def test_real_mixed_batch_failure_isolated_and_summary_has_timestamps(sample_video, tmp_path):
    path = sources(tmp_path, sample_video, sample_video, "missing.mp4", "https://example.com/video")
    result = batch.run_batch(path, Settings(), output=tmp_path / "out")
    assert result.counts["completed_with_limitations"] == 1
    assert result.counts["failed"] == 2 and result.counts["skipped"] == 1
    assert result.status == "completed_with_errors"
    state = manifest(result)
    assert state["id"] == result.directory.name
    assert state["reserved_upper_usd"] == "0"
    summary = (result.directory / "batch_summary.md").read_text(encoding="utf-8")
    assert "00:00:00.000 / E000" in summary
    assert "transcript.md#e000" in summary and "综合结论" in summary
    assert "uncertainties.md" in summary


def test_completed_resume_verifies_artifacts_and_does_not_recompute(
    sample_video, tmp_path, monkeypatch
):
    path = sources(tmp_path, sample_video)
    first = batch.run_batch(path, Settings(), output=tmp_path / "out")
    output = manifest(first)["jobs"][0]["output"]
    monkeypatch.setattr(batch, "_execute", lambda *a, **k: pytest.fail("reuse completed output"))
    second = batch.run_batch(path, Settings(), resume=first.directory)
    assert manifest(second)["jobs"][0]["output"] == output
    assert manifest(second)["jobs"][0]["attempts"] == 1


@pytest.mark.parametrize("change", ["subtitles", "artifact", "uncertainties"])
def test_changed_input_or_deleted_output_invalidates_cache(sample_video, tmp_path, change):
    path = sources(tmp_path, sample_video)
    first = batch.run_batch(path, Settings(), output=tmp_path / "out")
    old = manifest(first)["jobs"][0]["output"]
    if change == "subtitles":
        with sample_video.with_suffix(".srt").open("a", encoding="utf-8") as handle:
            handle.write("\n3\n00:00:01,900 --> 00:00:02,000\nNew text\n")
    elif change == "artifact":
        (first.directory / old / "transcript.md").unlink()
    else:
        (first.directory / old / "uncertainties.md").unlink()
    second = batch.run_batch(path, Settings(), resume=first.directory)
    job = manifest(second)["jobs"][0]
    assert job["attempts"] == 2 and job["output"] != old
    assert (first.directory / old).is_dir()  # Never overwrite earlier work.


def test_config_changes_refuse_stale_cache(sample_video, tmp_path):
    path = sources(tmp_path, sample_video)
    result = batch.run_batch(path, Settings(), output=tmp_path / "out")
    settings = Settings.model_validate({"vision": {"max_frames_per_video": 2}})
    with pytest.raises(ConfigurationError, match="配置已变化"):
        batch.run_batch(path, settings, resume=result.directory)


def test_budget_and_missing_key_block_before_download_or_output(
    tmp_path, deepseek_settings, monkeypatch
):
    path = sources(tmp_path, URL, URL.replace("BV1NNNqzVEi4", "BV1xx411c7mD"))
    settings = deepseek_settings.model_copy(
        update={
            "billing": deepseek_settings.billing.model_copy(
                update={"max_budget_usd_per_batch": Decimal("2")}
            )
        }
    )
    monkeypatch.setattr(batch, "fetch_url", lambda *a, **k: pytest.fail("no download"))
    with pytest.raises(BudgetError):
        batch.run_batch(path, settings, cloud=True, approve_paid=True, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    with pytest.raises(CredentialsError):
        batch.run_batch(
            path, deepseek_settings, cloud=True, approve_paid=True, output=tmp_path / "out"
        )
    assert not (tmp_path / "out").exists()


def test_batch_dry_run_is_offline_and_never_reads_keys(
    tmp_path, deepseek_settings, monkeypatch, capsys
):
    path = sources(tmp_path, URL, URL + "?vd_source=x")
    monkeypatch.setattr("videomind.cli.load_config", lambda _: deepseek_settings)
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    assert main(["batch", str(path), "--config", "unused", "--cloud", "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["pending_tasks"] == 1 and result["duplicate_rows"] == 1
    assert result["network_requests_sent"] == 0 and result["requests_at_most"] == 4


def test_download_failure_does_not_stop_later_local_item(sample_video, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise SourceError("safe platform error")

    monkeypatch.setattr(batch, "fetch_url", fail)
    result = batch.run_batch(
        sources(tmp_path, URL, sample_video), Settings(), output=tmp_path / "out"
    )
    assert result.counts["failed"] == 1 and result.counts["completed_with_limitations"] == 1


def test_bilibili_batch_reuses_real_local_pipeline(sample_video, tmp_path, monkeypatch):
    origin = AcquiredVideo(
        sample_video,
        sample_video.with_suffix(".srt"),
        SourceInfo(
            url=URL,
            video_id="BV1NNNqzVEi4",
            title="A title",
            duration_seconds=2,
            subtitle_languages=("zh-Hans",),
            selected_subtitle="zh-Hans",
        ),
        tmp_path / "source.json",
    )
    monkeypatch.setattr(batch, "fetch_url", lambda *a, **k: origin)
    result = batch.run_batch(sources(tmp_path, URL), Settings(), output=tmp_path / "out")
    job = manifest(result)["jobs"][0]
    assert URL in (result.directory / job["output"] / "transcript.md").read_text(encoding="utf-8")


def test_interrupt_journal_and_explicit_failed_retry(sample_video, tmp_path, monkeypatch):
    path = sources(tmp_path, sample_video)
    real = batch._execute
    monkeypatch.setattr(
        batch, "_execute", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    with pytest.raises(KeyboardInterrupt):
        batch.run_batch(path, Settings(), output=tmp_path / "out")
    directory = next((tmp_path / "out").glob("batch_*"))
    state = json.loads((directory / "batch_status.json").read_text(encoding="utf-8"))
    assert state["status"] == "interrupted" and state["jobs"][0]["status"] == "running"
    monkeypatch.setattr(batch, "_execute", real)
    resumed = batch.run_batch(path, Settings(), resume=directory)
    assert manifest(resumed)["jobs"][0]["attempts"] == 2
    assert resumed.counts["completed_with_limitations"] == 1


def test_paid_interruption_never_automatically_resends_and_reserves_before_start(
    sample_video, tmp_path, monkeypatch, deepseek_settings
):
    path = sources(tmp_path, sample_video)
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-user-key")

    def crash(job, settings, directory, **kwargs):
        state = json.loads((directory / "batch_status.json").read_text(encoding="utf-8"))
        assert Decimal(state["reserved_upper_usd"]) > 1
        assert state["jobs"][0]["status"] == "running"
        raise KeyboardInterrupt

    monkeypatch.setattr(batch, "_execute", crash)
    with pytest.raises(KeyboardInterrupt):
        batch.run_batch(
            path, deepseek_settings, cloud=True, approve_paid=True, output=tmp_path / "out"
        )
    directory = next((tmp_path / "out").glob("batch_*"))
    monkeypatch.delenv("VIDEOMIND_TEST_KEY")
    monkeypatch.setattr(batch, "_execute", lambda *a, **k: pytest.fail("never silently resend"))
    resumed = batch.run_batch(path, deepseek_settings, cloud=True, resume=directory)
    assert resumed.counts["failed"] == 1
    assert "--retry-failed" in manifest(resumed)["jobs"][0]["error"]
    assert resumed.reserved_upper_usd > 1


def test_resume_rejects_corrupted_source_and_config(sample_video, tmp_path):
    path = sources(tmp_path, sample_video)
    result = batch.run_batch(path, Settings(), output=tmp_path / "out")
    state = manifest(result)
    state["jobs"][0]["source"] = str(tmp_path / "unrelated-private-file")
    atomic_json(result.directory / "batch_status.json", state)
    with pytest.raises(ConfigurationError):
        batch.run_batch(path, Settings(), resume=result.directory)


def test_lock_prevents_simultaneous_resume_and_releases_after_failure(tmp_path):
    with directory_lock(tmp_path):
        with pytest.raises(ConfigurationError):
            with directory_lock(tmp_path):
                pytest.fail("must not acquire twice")
    with directory_lock(tmp_path):
        pass


def test_atomic_write_failure_preserves_previous_record(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    atomic_json(path, {"status": "old"})
    monkeypatch.setattr(
        "videomind.persistence.os.replace", lambda *a: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(OSError):
        atomic_json(path, {"status": "new"})
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "old"
    assert len(list(tmp_path.iterdir())) == 1


def test_actual_parallel_workers_respect_configured_limit(sample_video, tmp_path, monkeypatch):
    videos = []
    for i in range(4):
        video = tmp_path / f"copy{i}.mp4"
        shutil.copyfile(sample_video, video)
        shutil.copyfile(sample_video.with_suffix(".srt"), video.with_suffix(".srt"))
        videos.append(video)
    gate = threading.Barrier(2)
    lock = threading.Lock()
    counts = {"active": 0, "peak": 0}
    real = batch._execute

    def tracked(*args, **kwargs):
        with lock:
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        try:
            gate.wait(timeout=10)
            return real(*args, **kwargs)
        finally:
            with lock:
                counts["active"] -= 1

    monkeypatch.setattr(batch, "_execute", tracked)
    settings = Settings.model_validate({"video": {"max_concurrent_tasks": 2}})
    result = batch.run_batch(sources(tmp_path, *videos), settings, output=tmp_path / "out")
    assert result.counts["completed_with_limitations"] == 4
    assert counts["peak"] == 2


def test_explicit_retry_keeps_cumulative_paid_reservation(tmp_path, monkeypatch, deepseek_settings):
    path = sources(tmp_path, URL)
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-user-key")
    seen_limits = []

    def fail(job, settings, directory, **kwargs):
        seen_limits.append(settings.billing.max_budget_usd_per_batch)
        raise SourceError("safe failure")

    monkeypatch.setattr(batch, "_execute", fail)
    first = batch.run_batch(
        path, deepseek_settings, cloud=True, approve_paid=True, output=tmp_path / "out"
    )
    second = batch.run_batch(
        path,
        deepseek_settings,
        cloud=True,
        approve_paid=True,
        resume=first.directory,
        retry_failed=True,
    )
    assert second.reserved_upper_usd == first.reserved_upper_usd * 2
    assert seen_limits == [first.reserved_upper_usd, first.reserved_upper_usd]
    assert manifest(second)["jobs"][0]["attempts"] == 2
    reduced = deepseek_settings.model_copy(
        update={
            "billing": deepseek_settings.billing.model_copy(
                update={"max_budget_usd_per_batch": second.reserved_upper_usd}
            )
        }
    )
    with pytest.raises(BudgetError):
        batch.run_batch(
            path, reduced, cloud=True, approve_paid=True, resume=first.directory, retry_failed=True
        )
    assert len(seen_limits) == 2


def test_source_changed_during_work_is_never_cached(sample_video, tmp_path, monkeypatch):
    real = batch._execute

    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        with sample_video.with_suffix(".srt").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        return result

    monkeypatch.setattr(batch, "_execute", changed)
    result = batch.run_batch(sources(tmp_path, sample_video), Settings(), output=tmp_path / "out")
    job = manifest(result)["jobs"][0]
    assert job["status"] == "failed" and job["artifacts"] == {}
    assert "处理期间" in job["error"]


def test_core_result_cannot_redirect_batch_to_external_directory(
    sample_video, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        batch, "_execute", lambda *a, **k: AnalysisResult(tmp_path.parent, "completed", None)
    )
    result = batch.run_batch(sources(tmp_path, sample_video), Settings(), output=tmp_path / "out")
    assert result.counts["failed"] == 1
    assert manifest(result)["jobs"][0]["output"] is None


def test_mocked_paid_parallel_batch_obeys_total_budget_and_reuses_offline(
    sample_video, tmp_path, monkeypatch, deepseek_settings
):
    videos = []
    for i in range(3):
        target = tmp_path / f"cloud{i}.mp4"
        shutil.copyfile(sample_video, target)
        shutil.copyfile(sample_video.with_suffix(".srt"), target.with_suffix(".srt"))
        videos.append(target)
    settings = deepseek_settings.model_copy(
        update={
            "vision": deepseek_settings.vision.model_copy(update={"max_frames_per_video": 1}),
            "billing": deepseek_settings.billing.model_copy(
                update={"max_budget_usd_per_batch": Decimal("2")}
            ),
        }
    )
    monkeypatch.setenv("VIDEOMIND_TEST_KEY", "test-only-user-key")
    calls = []

    def handler(request):
        calls.append(request)
        content = json.loads(request.content)["messages"][1]["content"]
        result = (
            {"description": "visible slide"}
            if isinstance(content, list)
            else {
                "sections": [
                    {"title": "A section", "summary": "Source summary", "evidence_ids": ["E0001"]}
                ],
            }
        )
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
    path = sources(tmp_path, *videos)
    first = batch.run_batch(path, settings, cloud=True, approve_paid=True, output=tmp_path / "out")
    assert first.counts["completed"] == 3 and len(calls) == 6
    assert 0 < first.reserved_upper_usd <= Decimal("2")
    assert len({job["output"] for job in manifest(first)["jobs"]}) == 3
    monkeypatch.delenv("VIDEOMIND_TEST_KEY")
    monkeypatch.setattr("videomind.billing.utc_today", lambda: date(2030, 1, 1))
    monkeypatch.setattr(batch, "_execute", lambda *a, **k: pytest.fail("offline reuse only"))
    resumed = batch.run_batch(path, settings, cloud=True, resume=first.directory)
    assert resumed.counts["completed"] == 3 and len(calls) == 6
    assert resumed.reserved_upper_usd == first.reserved_upper_usd
    output = manifest(resumed)["jobs"][0]["output"]
    (first.directory / output / "uncertainties.md").unlink()
    invalidated = batch.run_batch(path, settings, cloud=True, resume=first.directory)
    assert invalidated.counts["failed"] == 1 and len(calls) == 6
    assert "--retry-failed" in manifest(invalidated)["jobs"][0]["error"]
