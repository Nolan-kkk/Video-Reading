"""Optional Chinese/English text recognition using RapidOCR's bundled CPU models."""

import importlib
import importlib.util
from pathlib import Path
from typing import Any

from videomind.config import OCRConfig
from videomind.errors import ConfigurationError, MediaError
from videomind.models.schemas import Evidence, OCRLine

MODELS = {
    "Det": "PP-OCRv6_det_small.onnx",
    "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "Rec": "PP-OCRv6_rec_small.onnx",
}


def bundled_models() -> dict[str, Path]:
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or spec.origin is None or importlib.util.find_spec("onnxruntime") is None:
        raise ConfigurationError('画面文字识别需要可选依赖：pip install "videomind[ocr]"。')
    root = Path(spec.origin).parent / "models"
    paths = {role: root / name for role, name in MODELS.items()}
    if not all(path.is_file() for path in paths.values()):
        raise ConfigurationError("RapidOCR 内置模型不完整；请重新安装受支持的 ocr 依赖。")
    return paths


class FrameOCR:
    def __init__(self, config: OCRConfig) -> None:
        paths = bundled_models()
        self.config = config
        try:
            rapidocr = importlib.import_module("rapidocr")
            params: dict[str, Any] = {
                "Global.log_level": "error",
                "Global.text_score": config.min_confidence,
                "EngineConfig.onnxruntime.intra_op_num_threads": 4,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
            # Explicit paths bypass RapidOCR's automatic model downloader.
            params.update({f"{role}.model_path": str(path) for role, path in paths.items()})
            self.engine = rapidocr.RapidOCR(params=params)
        except Exception:
            raise MediaError("画面文字识别初始化失败；请检查 ocr 依赖和本地模型。") from None

    def recognize(self, frame: Path, at_seconds: float) -> tuple[Evidence, ...]:
        try:
            result = self.engine(str(frame.resolve()))
            if result.txts is None or len(result.txts) == 0:
                return ()
            if result.scores is None or result.boxes is None:
                raise ValueError("Missing OCR geometry")
            lines = []
            for text, confidence, box in zip(result.txts, result.scores, result.boxes, strict=True):
                if not text.strip() or float(confidence) < self.config.min_confidence:
                    continue
                lines.append(
                    OCRLine.model_validate(
                        {"text": text, "confidence": float(confidence), "box": box.tolist()}
                    )
                )
            if not lines:
                return ()
            return (
                Evidence(
                    start_seconds=at_seconds,
                    end_seconds=at_seconds,
                    source="ocr",
                    text="\n".join(line.text for line in lines),
                    uncertainty="本地 OCR，未经人工核验；仅为画面文字，"
                    "不等同于语音或图像语义理解。",
                    ocr_lines=tuple(lines),
                ),
            )
        except Exception:
            raise MediaError("画面文字识别失败；原始关键帧和已有证据会保留。") from None
