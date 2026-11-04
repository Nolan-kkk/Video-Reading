import io
import json
from pathlib import Path

import pytest

from videomind.extractors import worker
from videomind.extractors.bilibili import WorkerRequest
from videomind.extractors.worker import _Failure, execute

URL = "https://www.bilibili.com/video/BV1NNNqzVEi4/"


def raw_info(**updates):
    return {
        "id": "BV1NNNqzVEi4",
        "title": "test",
        "duration": 2,
        "subtitles": {"danmaku": [{"ext": "xml"}], "zh-Hans": [{"ext": "srt", "data": "text"}]},
        **updates,
    }


def fake_factory(info, *, write_files=False, hook=None):
    class Client:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            assert self.options["allowed_extractors"] == ["BiliBili"]
            assert self.options["cachedir"] is False
            assert self.options["cookiesfrombrowser"] is None
            assert self.options["proxy"] == ""
            self.options["match_filter"](info)
            if hook:
                hook(self.options)
            if write_files:
                directory = Path(self.options["outtmpl"]).parent
                (directory / "source.mkv").write_bytes(b"fake-media")
                (directory / "source.zh-Hans.srt").write_text("test captions", encoding="utf-8")
            return info

    return Client


def request(tmp_path=None, **updates):
    return WorkerRequest(
        action="download" if tmp_path else "inspect",
        url=URL,
        directory=str(tmp_path) if tmp_path else None,
        ffmpeg="ffmpeg",
        max_minutes=1,
        **updates,
    )


def test_danmaku_is_excluded_and_caption_choice_is_explicit():
    result = execute(request(), factory=fake_factory(raw_info()))
    assert result.info.subtitle_languages == ("zh-Hans",)
    assert result.info.selected_subtitle == "zh-Hans"


def test_no_captions_is_reported_without_inventing_transcript():
    result = execute(
        request(), factory=fake_factory(raw_info(subtitles={"danmaku": [{"ext": "xml"}]}))
    )
    assert result.info.subtitle_languages == ()
    assert result.info.selected_subtitle is None


@pytest.mark.parametrize(
    "updates",
    [
        {"duration": None},
        {"duration": 120},
        {"duration": float("inf")},
        {"is_live": True},
        {"_type": "playlist"},
    ],
)
def test_invalid_live_or_long_media_is_rejected_before_download(updates):
    with pytest.raises(_Failure) as error:
        execute(request(), factory=fake_factory(raw_info(**updates)))
    assert error.value.code == "duration"


def test_requested_missing_language_is_not_silently_replaced():
    with pytest.raises(_Failure) as error:
        execute(request(subtitle_language="en"), factory=fake_factory(raw_info()))
    assert error.value.code == "subtitle"


def test_download_uses_fixed_paths_and_preserves_selected_caption(tmp_path):
    result = execute(
        request(tmp_path, subtitle_language="zh-Hans"),
        factory=fake_factory(raw_info(), write_files=True),
    )
    assert result.video_file == "source.mkv"
    assert result.subtitle_file == "captions.srt"
    assert (tmp_path / "captions.srt").read_text(encoding="utf-8") == "test captions"


def test_combined_stream_bytes_are_limited_before_more_downloads(tmp_path):
    def hook(options):
        callback = options["progress_hooks"][0]
        callback({"filename": "video", "downloaded_bytes": 6})
        callback({"filename": "audio", "downloaded_bytes": 6})

    with pytest.raises(_Failure) as error:
        execute(request(tmp_path, max_bytes=10), factory=fake_factory(raw_info(), hook=hook))
    assert error.value.code == "size"


def test_worker_cli_never_echoes_invalid_input(monkeypatch, capsys):
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO("invalid-test-only-secret"))
    assert worker.main() == 2
    output = capsys.readouterr().out
    assert "invalid-test-only-secret" not in output
    assert json.loads(output)["error"] == "invalid"


def test_worker_cli_suppresses_backend_errors(monkeypatch, capsys):
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(request().model_dump_json()))

    def failure(*args, **kwargs):
        raise RuntimeError("test-only-cookie-and-signed-url")

    monkeypatch.setattr(worker, "execute", failure)
    assert worker.main() == 2
    output = capsys.readouterr().out
    assert "test-only-cookie" not in output
    assert json.loads(output)["error"] == "unavailable"


def test_worker_classifies_access_restriction_without_exposing_details(monkeypatch, capsys):
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(request().model_dump_json()))

    def failure(*args, **kwargs):
        raise RuntimeError("Fresh cookies needed: test-only-secret-and-signed-url")

    monkeypatch.setattr(worker, "execute", failure)
    assert worker.main() == 2
    output = capsys.readouterr().out
    assert "test-only-secret" not in output
    assert json.loads(output)["error"] == "restricted"
