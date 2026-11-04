"""Generate an original 6-second PPT/code/chart fixture; no downloaded media or API calls."""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from videomind.processors.media import run_tool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/demo"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "demo.mp4").exists():
        parser.error("demo.mp4 already exists; use another output directory")
    try:
        font = ImageFont.truetype(
            "C:/Windows/Fonts/consola.ttf" if sys.platform == "win32" else "DejaVuSansMono.ttf", 30
        )
    except OSError:
        font = ImageFont.load_default(size=30)
    scenes = [
        (
            "white",
            "black",
            "VideoMind: source evidence\n\n1. Keep timestamps\n"
            "2. Keep visible text\n3. Mark uncertainty",
        ),
        (
            "#101827",
            "#e0edff",
            "Python code\n\nfor i in range(3):\n    print(i)\n\nExpected output: 0, 1, 2",
        ),
        (
            "#faf3de",
            "#145b49",
            "A simple chart\n\nA  ####\nB  ########\nC  ############\n\nValues: A=1, B=2, C=3",
        ),
    ]
    images = []
    for index, (background, foreground, text) in enumerate(scenes, 1):
        image = Image.new("RGB", (960, 540), background)
        ImageDraw.Draw(image).multiline_text((50, 55), text, font=font, fill=foreground, spacing=12)
        path = output / f"scene_{index}.png"
        image.save(path)
        images.append(path)
    arguments = ["-nostdin", "-v", "error"]
    for path in images:
        arguments.extend(["-loop", "1", "-framerate", "4", "-t", "2", "-i", str(path)])
    arguments.extend(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "3:a",
            "-c:v",
            "mpeg4",
            "-q:v",
            "2",
            "-c:a",
            "aac",
            "-shortest",
            str(output / "demo.mp4"),
        ]
    )
    run_tool("ffmpeg", arguments)
    (output / "demo.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,900\nKeep source timestamps and mark uncertainty.\n\n"
        "2\n00:00:02,000 --> 00:00:03,900\nThis loop prints zero, one and two.\n\n"
        "3\n00:00:04,000 --> 00:00:05,900\nThe chart values are one, two and three.\n",
        encoding="utf-8",
    )
    (output / "ABOUT.txt").write_text(
        "Original VideoMind test fixture: three generated slides with matching sidecar captions.\n"
        "Audio is a synthetic 440 Hz tone, NOT speech. Captions are authored fixture content.\n"
        "This fixture tests extraction/alignment, not speech recognition or real AI accuracy.\n",
        encoding="utf-8",
    )
    print(output / "demo.mp4")


if __name__ == "__main__":
    main()
