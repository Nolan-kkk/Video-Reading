import json
import subprocess
from pathlib import Path

import pytest

from videomind.cli import main
from videomind.config import Settings
from videomind.errors import SourceError
from videomind.extractors import bilibili
from videomind.extractors.base import AcquiredVideo, SourceInfo
from videomind.extractors.bilibili import WorkerResponse, fetch_url, normalize_url

URL = "https://www.bilibili.com/video/BV1NNNqzVEi4/"


def source_info(**updates):
    return SourceInfo(
        url=URL, video_id="BV1NNNqzVEi4", title="Test video", duration_seconds=2, **updates
    )


def test_normalization_preserves_part_and_removes_tracking():
    assert normalize_url(URL + "?vd_source=private-tracking#secret") == URL
    assert (
        normalize_url("https://m.bilibili.com/video/BV1NNNqzVEi4?p=2&key=private") == URL + "?p=2"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://b23.tv/test",
        "https://example.com/video/BV1NNNqzVEi4",
        "https://www.bilibili.com.evil.invalid/video/BV1NNNqzVEi4",
        "https://www.bilibili.com@127.0.0.1/video/BV1NNNqzVEi4",
        "https://secret@www.bilibili.com/video/BV1NNNqzVEi4",
        "file:///video/BV1NNNqzVEi4",
        "https://www.bilibili.com/playlist/1",
        URL + "?p=0",
        URL + "?p=1&p=2",
        URL + "?p=",
        URL + "?p=not-a-number",
        "https://www.bilibili.com:9000/video/BV1NNNqzVEi4",
    ],
)
def test_unsupported_or_ambiguous_urls_fail_before_network(url):
    with pytest.raises(SourceError) as error:
        normalize_url(url)
    assert "secret" not in str(error.value)


def test_missing_dependency_is_safe(monkeypatch):
    monkeypatch.setattr(bilibili.importlib.util, "find_spec", lambda _: None)
    with pytest.raises(SourceError, match="download"):
        bilibili.inspect_url(URL, Settings())


def test_worker_process_does_not_inherit_ai_keys_or_proxy_credentials(monkeypatch):
    captured = {}
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-secret")
    monkeypatch.setenv("HTTPS_PROXY", "https://secret:password@proxy.invalid")
    monkeypatch.setenv("PYTHONPATH", "untrusted-path")
    monkeypatch.setenv("SystemDrive", "C:")
    monkeypatch.setenv("ProgramData", "C:\\ProgramData")
    monkeypatch.setattr(bilibili.importlib.util, "find_spec", lambda _: object())

    class Process:
        returncode = 0

        def __init__(self, command, **kwargs):
            captured.update(kwargs)
            assert "-I" in command

        def communicate(self, data, timeout):
            assert "test-only-secret" not in data
            return WorkerResponse(status="ok", info=source_info()).model_dump_json(), None

    monkeypatch.setattr(bilibili.subprocess, "Popen", Process)
    info = bilibili.inspect_url(URL, Settings())
    assert info.video_id == "BV1NNNqzVEi4"
    environment = captured["env"]
    assert "DEEPSEEK_API_KEY" not in environment
    assert "HTTPS_PROXY" not in environment
    assert "PYTHONPATH" not in environment
    normalized = {key.upper(): value for key, value in environment.items()}
    assert normalized["SYSTEMDRIVE"] == "C:"
    assert normalized["PROGRAMDATA"] == "C:\\ProgramData"


def test_worker_timeout_stops_its_process_tree_without_echoing_input(monkeypatch):
    stopped = []
    monkeypatch.setattr(bilibili.importlib.util, "find_spec", lambda _: object())

    class Process:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, data=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("test-only-private-command", timeout)
            return "", None

    monkeypatch.setattr(bilibili.subprocess, "Popen", Process)
    monkeypatch.setattr(bilibili, "_stop_process", lambda process: stopped.append(process))
    with pytest.raises(SourceError) as error:
        bilibili.inspect_url(URL, Settings())
    assert len(stopped) == 1
    assert "test-only-private-command" not in str(error.value)


def test_fetch_contract_records_metadata_without_upstream_secrets(
    tmp_path, monkeypatch, media_tools
):
    calls = []

    def worker(request, timeout):
        calls.append(request.action)
        if request.action == "download":
            directory = Path(request.directory)
            (directory / "source.mkv").write_bytes(b"fixture media")
            (directory / "captions.srt").write_text("fixture subtitles", encoding="utf-8")
        return WorkerResponse(
            status="ok",
            info=source_info(selected_subtitle="zh-Hans"),
            video_file="source.mkv" if request.action == "download" else None,
            subtitle_file="captions.srt" if request.action == "download" else None,
        )

    monkeypatch.setattr(bilibili, "_run_worker", worker)
    acquired = fetch_url(URL + "?vd_source=tracking", Settings(), directory=tmp_path)
    assert calls == ["inspect", "download"]
    assert acquired.video.exists() and acquired.subtitles.exists()
    manifest = acquired.manifest.read_text(encoding="utf-8")
    assert "tracking" not in manifest
    assert json.loads(manifest)["status"] == "completed"


def test_failed_download_keeps_failure_manifest(tmp_path, monkeypatch, media_tools):
    def worker(request, timeout):
        if request.action == "download":
            raise SourceError("safe failure")
        return WorkerResponse(status="ok", info=source_info())

    monkeypatch.setattr(bilibili, "_run_worker", worker)
    with pytest.raises(SourceError):
        fetch_url(URL, Settings(), directory=tmp_path)
    manifest = next(tmp_path.glob("bilibili_*/source.json"))
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "failed"


def test_worker_cannot_return_arbitrary_output_paths(tmp_path, monkeypatch, media_tools):
    monkeypatch.setattr(
        bilibili,
        "_run_worker",
        lambda request, timeout: WorkerResponse(
            status="ok", info=source_info(), video_file="../private.mkv"
        ),
    )
    with pytest.raises(SourceError):
        fetch_url(URL, Settings(), directory=tmp_path)


def test_remote_dry_run_queries_metadata_without_downloading(monkeypatch, capsys):
    monkeypatch.setattr("videomind.cli.inspect_url", lambda *args, **kwargs: source_info())
    monkeypatch.setattr(
        "videomind.cli.fetch_url", lambda *args, **kwargs: pytest.fail("no download")
    )
    assert main(["analyze", URL, "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source"]["url"] == URL
    assert result["video_downloaded"] is False and result["paid_requests_sent"] == 0


def test_remote_cloud_missing_key_blocks_download(deepseek_settings, monkeypatch):
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    monkeypatch.setattr("videomind.cli.load_config", lambda _: deepseek_settings)
    monkeypatch.setattr(
        "videomind.cli.fetch_url", lambda *args, **kwargs: pytest.fail("no download")
    )
    assert main(["analyze", URL, "--config", "unused.yaml", "--cloud", "--yes-paid"]) == 2


def test_downloaded_video_uses_existing_real_pipeline(sample_video, tmp_path, monkeypatch):
    info = source_info(subtitle_languages=("zh-Hans",), selected_subtitle="zh-Hans")
    acquired = AcquiredVideo(
        sample_video, sample_video.with_suffix(".srt"), info, tmp_path / "source.json"
    )
    monkeypatch.setattr("videomind.cli.fetch_url", lambda *args, **kwargs: acquired)
    assert main(["analyze", URL, "--output", str(tmp_path / "output")]) == 0
    metadata_file = next((tmp_path / "output").glob("video_*/metadata.json"))
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["source_type"] == "bilibili"
    assert metadata["source_url"] == URL
    assert metadata["subtitle_origin"] == "platform"
    transcript = metadata_file.with_name("transcript.md").read_text(encoding="utf-8")
    assert URL in transcript and "Test video" in transcript
    evidence = json.loads(metadata_file.with_name("evidence.json").read_text(encoding="utf-8"))[
        "evidence"
    ]
    assert any(
        item["source"] == "subtitle" and "平台字幕" in item["uncertainty"] for item in evidence
    )
