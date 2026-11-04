import pytest

from videomind.errors import MediaError
from videomind.processors.subtitles import read_subtitles


@pytest.mark.parametrize("kind,timing", [("srt", "00:00:01,200"), ("vtt", "00:01.200")])
def test_subtitles_preserve_text_and_time(tmp_path, kind, timing):
    path = tmp_path / f"sub.{kind}"
    header = "WEBVTT\n\n" if kind == "vtt" else ""
    path.write_text(
        f"{header}1\n{timing} --> 00:00:02.000\nprint('hi')\nsecond line\n", encoding="utf-8"
    )
    evidence = read_subtitles(path, 3)
    assert evidence[0].start_seconds == 1.2
    assert evidence[0].text == "print('hi')\nsecond line"
    assert evidence[0].source == "subtitle"


@pytest.mark.parametrize(
    "content",
    [
        "not subtitles",
        "1\n00:00:05,000 --> 00:00:06,000\na",
        "1\n00:00:02,000 --> 00:00:01,000\na",
        "1\n00:00:00,000 --> 00:00:01,000\n",
        "1\ninvalid --> invalid\na",
    ],
)
def test_invalid_subtitles_fail_instead_of_fabricating(tmp_path, content):
    path = tmp_path / "sub.srt"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(MediaError):
        read_subtitles(path, 3)
