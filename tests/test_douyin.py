import json
from pathlib import Path

import httpx
import pytest

from videomind import batch
from videomind.cli import main
from videomind.config import Settings
from videomind.errors import SourceError
from videomind.extractors import bilibili
from videomind.extractors.base import AcquiredVideo, SourceInfo
from videomind.extractors.bilibili import WorkerRequest, WorkerResponse
from videomind.extractors.sources import normalize_source_url, resolve_source_url
from videomind.extractors.worker import _Failure, execute

URL = "https://www.douyin.com/video/7274114540818681099"


@pytest.mark.parametrize(
    "source",
    [
        URL,
        URL + "/?from=share&secret=tracking#fragment",
        "http://douyin.com/video/7274114540818681099",
    ],
)
def test_normalize_douyin_strips_tracking(source):
    assert normalize_source_url(source) == URL


@pytest.mark.parametrize(
    "source",
    [
        "https://www.douyin.com.evil.example/video/7274114540818681099",
        "https://user:secret@www.douyin.com/video/7274114540818681099",
        "https://www.douyin.com:9000/video/7274114540818681099",
        "https://www.douyin.com/video/not-an-id",
        "https://www.douyin.com/video/" + "1" * 26,
        "https://www.douyin.com/user/7274114540818681099",
        "https://www.youtube.com/watch?v=abcdefghijk",
    ],
)
def test_reject_unsupported_addresses_before_network(source):
    with pytest.raises(SourceError) as exc:
        normalize_source_url(source)
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize(
    "short,location,expected",
    [
        ("https://v.douyin.com/abcd/?tracking=secret", URL + "?tracking=secret", URL),
        (
            "https://v.douyin.com/abcd",
            "https://www.iesdouyin.com/share/video/7274114540818681099/?x=y",
            URL,
        ),
        (
            "https://b23.tv/abcd",
            "https://m.bilibili.com/video/BV1NNNqzVEi4?p=2&x=y",
            "https://www.bilibili.com/video/BV1NNNqzVEi4/?p=2",
        ),
    ],
)
def test_short_links_resolve_only_official_locations(short, location, expected):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": location})

    assert resolve_source_url(short, transport=httpx.MockTransport(handler)) == expected
    assert len(requests) == 1 and "secret" not in str(requests[0].url)
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/private",
        "https://example.com/video/123",
        "https://user:secret@www.douyin.com/video/123",
        "https://www.bilibili.com/video/BV1NNNqzVEi4/",
        "https://www.iesdouyin.com/other/123",
    ],
)
def test_short_link_rejects_untrusted_redirect_without_following(location):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(SourceError) as exc:
        resolve_source_url("https://v.douyin.com/abcd", transport=httpx.MockTransport(handler))
    assert calls == ["v.douyin.com"]
    assert "secret" not in str(exc.value)


def test_worker_does_not_resolve_short_links_directly():
    request = WorkerRequest(action="inspect", url="https://v.douyin.com/abcd", max_minutes=1)
    with pytest.raises(_Failure):
        execute(request)


def test_worker_selects_only_douyin_and_filters_metadata():
    seen = {}

    class Client:
        def __init__(self, options):
            seen.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            assert url == URL and download is False
            return {
                "id": "7274114540818681099",
                "duration": 3,
                "title": "Test",
                "uploader": "Author",
                "subtitles": {},
                "http_headers": {"Cookie": "test-only-secret"},
            }

    request = WorkerRequest(action="inspect", url=URL, max_minutes=1)
    result = execute(request, factory=Client)
    assert seen["allowed_extractors"] == ["Douyin"]
    assert seen["noplaylist"] and seen["cookiesfrombrowser"] is None and seen["proxy"] == ""
    assert result.info.platform == "douyin" and result.info.video_id == "7274114540818681099"
    assert "test-only-secret" not in result.model_dump_json()


def test_worker_rejects_id_mismatch():
    class Client:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            return {"id": "123", "duration": 1, "title": "Unexpected"}

    with pytest.raises(_Failure) as exc:
        execute(WorkerRequest(action="inspect", url=URL, max_minutes=1), factory=Client)
    assert exc.value.code == "invalid"


def test_download_contract_for_douyin_keeps_only_filtered_metadata(
    tmp_path, monkeypatch, media_tools
):
    seen = []
    info = SourceInfo(
        platform="douyin", url=URL, video_id="7274114540818681099", title="Test", duration_seconds=2
    )

    def worker(request, timeout):
        seen.append((request.action, request.url))
        if request.action == "download":
            (Path(request.directory) / "source.mkv").write_bytes(b"fake video")
        return WorkerResponse(
            status="ok",
            info=info,
            video_file="source.mkv" if request.action == "download" else None,
        )

    monkeypatch.setattr(bilibili, "_run_worker", worker)
    acquired = bilibili.fetch_url(URL + "?tracking=private", Settings(), directory=tmp_path)
    assert seen == [("inspect", URL), ("download", URL)]
    assert acquired.video.read_bytes() == b"fake video"
    assert acquired.subtitles is None and acquired.info.platform == "douyin"
    assert acquired.manifest.parent.name.startswith("douyin_")
    assert "tracking" not in acquired.manifest.read_text(encoding="utf-8")


def test_batch_dry_run_short_links_does_not_resolve_network(tmp_path, monkeypatch):
    inputs = tmp_path / "videos.txt"
    inputs.write_text(
        "https://v.douyin.com/abcd\nhttps://v.douyin.com/abcd?x=y\n", encoding="utf-8"
    )
    monkeypatch.setattr(bilibili, "resolve_source_url", lambda *a, **k: pytest.fail("no network"))
    plan = batch.preview_batch(inputs, Settings())
    assert plan["pending_tasks"] == 1 and plan["duplicate_rows"] == 1
    assert plan["network_requests_sent"] == 0


def test_worker_response_cannot_swap_video_identity(monkeypatch):
    fake = SourceInfo(platform="douyin", url=URL, video_id="123", title="x", duration_seconds=2)
    monkeypatch.setattr(bilibili.importlib.util, "find_spec", lambda _: object())

    class Process:
        returncode = 0

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, data, timeout):
            return WorkerResponse(status="ok", info=fake).model_dump_json(), None

    monkeypatch.setattr(bilibili.subprocess, "Popen", Process)
    with pytest.raises(SourceError):
        bilibili.inspect_url(URL, Settings())


def test_mixed_batch_deduplicates_douyin_and_keeps_origin(sample_video, tmp_path, monkeypatch):
    origin = AcquiredVideo(
        video=sample_video,
        subtitles=sample_video.with_suffix(".srt"),
        info=SourceInfo(
            platform="douyin",
            url=URL,
            video_id="7274114540818681099",
            title="Douyin test",
            duration_seconds=2,
        ),
        manifest=tmp_path / "source.json",
    )
    calls = []
    monkeypatch.setattr(batch, "fetch_url", lambda *a, **k: calls.append(a[0]) or origin)
    inputs = tmp_path / "videos.txt"
    inputs.write_text(f"{URL}?share=one\n{URL}/?share=two\n{sample_video}\n", encoding="utf-8")
    result = batch.run_batch(inputs, Settings(), output=tmp_path / "out")
    assert calls == [URL] and result.counts["skipped"] == 1
    assert result.counts["completed_with_limitations"] == 2
    state = json.loads((result.directory / "batch_status.json").read_text(encoding="utf-8"))
    meta = json.loads(
        (result.directory / state["jobs"][0]["output"] / "metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert meta["source_type"] == "douyin" and meta["source_url"] == URL


def test_douyin_cloud_missing_key_fails_before_download(monkeypatch, tmp_path):
    settings = Settings.model_validate(
        {
            "providers": {
                role: {
                    "provider": "deepseek",
                    "model": "deepseek-flash",
                    "api_key_env": "VIDEOMIND_TEST_KEY",
                }
                for role in ("vision", "text")
            }
        }
    )
    monkeypatch.setattr("videomind.cli.load_config", lambda _: settings)
    monkeypatch.delenv("VIDEOMIND_TEST_KEY", raising=False)
    monkeypatch.setattr("videomind.cli.fetch_url", lambda *a, **k: pytest.fail("no download"))
    assert main(["analyze", URL, "--config", str(Path("unused")), "--cloud", "--yes-paid"]) == 2
