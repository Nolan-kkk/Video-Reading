import json
from pathlib import Path

from videomind.exporters.markdown import export
from videomind.models.schemas import Evidence, OCRLine, RecognizedCode


def test_report_links_timed_issues_code_and_global_limitations(tmp_path):
    evidence = [
        Evidence(
            start_seconds=9,
            end_seconds=10.5,
            source="vision",
            text="partial code",
            uncertainty="图表单位模糊",
            frame=Path("images/frame.png"),
            code=(RecognizedCode(text="print(", uncertainty="右侧被遮挡"),),
        ),
        Evidence(
            start_seconds=2,
            end_seconds=2,
            source="ocr",
            text="slide",
            uncertainty="文字可能有误",
            ocr_lines=(
                OCRLine(
                    text="slide",
                    confidence=0.73,
                    box=((0, 0), (1, 0), (1, 1), (0, 1)),
                ),
            ),
        ),
        Evidence(start_seconds=0, end_seconds=1, source="subtitle", text="no flag"),
    ]
    export(
        tmp_path,
        evidence,
        {"status": "failed", "warnings": ["部分画面未采样"], "error": "处理失败"},
        notes=None,
        mode="raw",
    )
    report = (tmp_path / "uncertainties.md").read_text(encoding="utf-8")
    assert "无法定位到具体时间" in report and "部分画面未采样" in report
    assert "处理失败" in report
    assert report.index("E0002 · 00:00:02.000") < report.index("E0001 · 00:00:09.000")
    assert "00:00:10.500" in report and "transcript.md#e0001" in report
    assert "images/frame.png" in report and "右侧被遮挡" in report and "图表单位模糊" in report
    assert "partial code" in report and "slide" in report
    assert "0.730" in report and "并非准确率" in report
    assert "E0003 ·" not in report
    assert "uncertainties.md" in (tmp_path / "transcript.md").read_text(encoding="utf-8")
    assert (
        len(json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))["evidence"]) == 3
    )
    assert not (tmp_path / "notes.md").exists()


def test_empty_report_does_not_claim_accuracy(tmp_path):
    export(tmp_path, [], {"status": "completed"}, notes=None, mode="full")
    report = (tmp_path / "uncertainties.md").read_text(encoding="utf-8")
    assert "没有记录可定位的不确定性" in report
    assert "不代表视频中的内容均准确" in report
    assert "uncertainties.md" in (tmp_path / "notes.md").read_text(encoding="utf-8")


def test_usage_preserves_unknowns_and_marks_failed_result_incomplete(tmp_path):
    export(
        tmp_path,
        [],
        {
            "status": "failed",
            "billing": {
                "reserved_upper_usd": "1.0",
                "usage": [
                    {"input_tokens": 50, "output_tokens": 20},
                    {"input_tokens": None, "output_tokens": 10},
                ],
            },
        },
        notes=None,
        mode="raw",
    )
    usage = (tmp_path / "usage.md").read_text(encoding="utf-8")
    assert "输入 未知；输出 30 Token" in usage
    assert "用量可能不完整" in usage and "不是实际费用" in usage
