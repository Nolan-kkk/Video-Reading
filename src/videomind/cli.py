"""Local-first CLI; cloud requests require explicit BYOK and cost approval."""

import argparse
import asyncio
import importlib.util
import io
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from videomind import __version__
from videomind.batch import preview_batch, run_batch
from videomind.billing import PRICE_CHECKED_ON, PRICE_SOURCE, PRICE_VALID_THROUGH, utc_today
from videomind.config import Settings, load_config
from videomind.errors import ConfigurationError, VideoMindError
from videomind.extractors.base import SourceInfo
from videomind.extractors.bilibili import fetch_url, inspect_url
from videomind.pipeline import analyze, check_cloud_access, preview
from videomind.processors.media import find_tool, probe
from videomind.processors.ocr import bundled_models
from videomind.processors.speech import prepare_speech, speech_model_ready
from videomind.security import resolve_credentials
from videomind.synthesis import preview_synthesis, synthesize


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's default error echoes unknown values, which may be pasted keys.
        self.print_usage(sys.stderr)
        self.exit(2, "VideoMind: 参数无效，请使用 --help；不要把 API Key 放在命令参数中。\n")


def _processing_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--config", type=Path)
    command.add_argument("--output", type=Path, help="输出根目录；每次新建任务目录")
    command.add_argument("--subtitle-language", help="平台字幕语言；批次本地文件忽略此项")
    command.add_argument("--output-mode", choices=["raw", "notes", "full"])
    command.add_argument("--depth", choices=["fast", "standard", "deep"])
    command.add_argument("--cloud", action="store_true", help="启用用户自己的 DeepSeek API")
    command.add_argument("--yes-paid", action="store_true", help="接受预检费用和云端数据发送")
    command.add_argument("--dry-run", action="store_true", help="仅预检，不调用 AI；批次不联网")
    command.add_argument("--visual-only", action="store_true", help="无字幕/转录时接受缺失语音")
    command.add_argument("--save-audio", action="store_true", help="保存本地音轨")
    command.add_argument("--transcribe", action="store_true", help="本地语音转录，默认优先已有字幕")
    command.add_argument("--ocr", action="store_true", help="本地关键帧中英文文字识别")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        prog="videomind",
        description="VideoMind：本地/B站/抖音视频转 Markdown；可显式启用用户自己的 DeepSeek API。",
    )
    parser.add_argument("--version", action="version", version=f"VideoMind {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="离线检查运行环境，不读取 API Key")
    doctor.add_argument("--config", type=Path, help="检查配置指定的本地语音模型目录")
    prepare = commands.add_parser("prepare-speech", help="匿名联网下载可选语音模型，不调用 AI API")
    prepare.add_argument("--size", choices=["tiny", "base", "small", "medium"], default="small")
    prepare.add_argument(
        "--directory", type=Path, help="本地模型目录，默认 .cache/models/faster-whisper-<size>"
    )
    check = commands.add_parser("check-config", help="离线校验配置和用户 Key；不调用 API")
    check.add_argument("--config", type=Path, required=True)
    check.add_argument("--structure-only", action="store_true", help="只校验配置，不检查 Key")
    fetch = commands.add_parser("fetch", help="获取单个公开 B站/抖音视频和字幕；不调用 AI")
    fetch.add_argument("url")
    fetch.add_argument("--config", type=Path)
    fetch.add_argument("--output", type=Path, help="下载缓存根目录")
    fetch.add_argument("--subtitle-language", help="明确选择可用字幕语言")
    fetch.add_argument(
        "--dry-run", action="store_true", help="联网查询元数据，不下载视频、不调用 AI"
    )
    command = commands.add_parser("analyze", help="处理单个本地文件或 B站/抖音 URL，默认不调用 AI")
    command.add_argument("source")
    command.add_argument("--subtitles", type=Path, help="UTF-8 SRT/VTT；默认寻找同名旁挂字幕")
    _processing_options(command)
    batch = commands.add_parser("batch", help="读取 UTF-8 列表，去重、逐项分析并保存批次状态")
    batch.add_argument("source", help="列表文件；每行一个本地路径或标准 B站/抖音 URL")
    _processing_options(batch)
    batch.add_argument("--resume", type=Path, help="续跑已有批次目录，校验已完成产物")
    batch.add_argument("--retry-failed", action="store_true", help="续跑时显式重做失败任务")
    fusion = commands.add_parser("synthesize", help="综合已完成批次的多视频证据（用户自备 Key）")
    fusion.add_argument("batch_directory", type=Path)
    fusion.add_argument("--config", type=Path, required=True)
    fusion.add_argument("--dry-run", action="store_true", help="预览发送数据和费用，不读取 Key")
    fusion.add_argument("--yes-paid", action="store_true", help="确认数据发送和综合费用")
    fusion.add_argument("--new-attempt", action="store_true", help="明确允许再次发送综合请求")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Stable UTF-8 JSON and diagnostics, including when Windows redirects output.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    source_info: SourceInfo | None
    try:
        if args.command == "doctor":
            settings = load_config(args.config) if args.config else Settings()
            ffmpeg_ready = find_tool("ffmpeg") is not None
            ffprobe_ready = find_tool("ffprobe") is not None
            speech_dependency = importlib.util.find_spec("faster_whisper") is not None
            model_ready = speech_model_ready(settings.speech)
            try:
                bundled_models()
                ocr_models_ready = True
            except ConfigurationError:
                ocr_models_ready = False
            guidance = []
            if not ffmpeg_ready or not ffprobe_ready:
                guidance.append(
                    "安装 FFmpeg/ffprobe 并加入 PATH，或设置 VIDEOMIND_FFMPEG/FFPROBE。"
                )
            if not speech_dependency:
                guidance.append('安装本地语音依赖：pip install "videomind[speech]"。')
            if not model_ready:
                guidance.append("语音模型未准备：运行 prepare-speech，或在配置中指定已有模型目录。")
            if not ocr_models_ready:
                guidance.append('安装或修复 OCR 依赖：pip install "videomind[ocr]"。')
            price_current = PRICE_CHECKED_ON <= utc_today() <= PRICE_VALID_THROUGH
            if not price_current:
                guidance.append("云端价格快照已过期或系统日期异常；核对官方价格并更新后再调用。")
            result: dict[str, object] = {
                "stage": "V2-in-progress",
                "version": __version__,
                "python": ".".join(str(part) for part in sys.version_info[:3]),
                "ffmpeg_available": ffmpeg_ready,
                "ffprobe_available": ffprobe_ready,
                "paid_requests_enabled": False,
                "video_analysis_available": True,
                "batch_analysis_available": True,
                "cross_video_synthesis_available": True,
                "default_max_concurrent_tasks": Settings().video.max_concurrent_tasks,
                "cloud_provider": "deepseek",
                "bilibili_download_available": importlib.util.find_spec("yt_dlp") is not None,
                "douyin_download_dependency_available": importlib.util.find_spec("yt_dlp")
                is not None,
                "speech_dependency_available": speech_dependency,
                "speech_model_files_available": model_ready,
                "speech_model_directory": str(settings.speech.model_directory),
                "ocr_model_files_available": ocr_models_ready,
                "recommended_actions": guidance,
                "pricing_snapshot_current": price_current,
                "pricing_checked_on": str(PRICE_CHECKED_ON),
                "pricing_valid_through": str(PRICE_VALID_THROUGH),
                "pricing_source": PRICE_SOURCE,
                "ocr_dependency_available": importlib.util.find_spec("rapidocr") is not None
                and importlib.util.find_spec("onnxruntime") is not None,
                "note": "本地处理需要 FFmpeg/ffprobe；离线检查文件和依赖，"
                "未加载模型、验证正确性或读取 API Key。",
            }
        elif args.command == "prepare-speech":
            directory = args.directory or Path(f".cache/models/faster-whisper-{args.size}")
            prepared = prepare_speech(directory, args.size)
            result = {
                "model_directory": str(prepared),
                "paid_requests_sent": 0,
                "note": "公开模型已下载；分析时仅加载本地模型。",
            }
        elif args.command == "check-config":
            settings = load_config(args.config)
            if not args.structure_only:
                resolve_credentials(settings)
            result = {
                "stage": "V2-in-progress",
                "configuration_valid": True,
                "credentials": "not_checked" if args.structure_only else "present_not_verified",
                "configured_roles": list(settings.providers.configured()),
                "paid_requests_enabled": False,
                "note": "仅本地检查；未验证账户、模型能力、余额或 API 可用性。",
            }
        elif args.command == "fetch":
            settings = load_config(args.config) if args.config else Settings()
            if args.dry_run:
                source_info = inspect_url(args.url, settings, language=args.subtitle_language)
                result = {
                    "source": source_info.model_dump(mode="json"),
                    "video_downloaded": False,
                    "paid_requests_sent": 0,
                }
            else:
                acquired = fetch_url(
                    args.url, settings, directory=args.output, language=args.subtitle_language
                )
                result = {
                    "video": str(acquired.video),
                    "subtitles": str(acquired.subtitles) if acquired.subtitles else None,
                    "source_manifest": str(acquired.manifest),
                    "source": acquired.info.model_dump(mode="json"),
                    "paid_requests_sent": 0,
                }
        elif args.command == "synthesize":
            settings = load_config(args.config)
            if args.dry_run:
                result = preview_synthesis(args.batch_directory, settings)
            else:
                report = synthesize(
                    args.batch_directory,
                    settings,
                    yes_paid=args.yes_paid,
                    new_attempt=args.new_attempt,
                )
                result = {"status": "completed", "report": str(report)}
        else:
            if args.yes_paid and not args.cloud:
                raise ConfigurationError("--yes-paid 仅能与 --cloud 一起使用。")
            settings = load_config(args.config) if args.config else Settings()
            overrides = {}
            if args.output_mode:
                overrides["mode"] = args.output_mode
            if args.depth:
                overrides["depth"] = args.depth
            settings = settings.model_copy(
                update={
                    "output": settings.output.model_copy(update=overrides),
                    "speech": settings.speech.model_copy(
                        update={"enabled": args.transcribe or settings.speech.enabled}
                    ),
                    "ocr": settings.ocr.model_copy(
                        update={"enabled": args.ocr or settings.ocr.enabled}
                    ),
                }
            )
            if args.command == "batch":
                if args.resume is not None and args.output is not None:
                    raise ConfigurationError("续跑使用 --resume，不同时设置 --output。")
                options = {
                    "cloud": args.cloud,
                    "resume": args.resume,
                    "retry_failed": args.retry_failed,
                    "language": args.subtitle_language,
                    "visual_only": args.visual_only,
                    "save_audio": args.save_audio,
                }
                if args.dry_run:
                    batch_plan = preview_batch(Path(args.source), settings, **options)
                    print(json.dumps(batch_plan, ensure_ascii=False, indent=2))
                    return 0
                batch_result = run_batch(
                    Path(args.source),
                    settings,
                    output=args.output,
                    approve_paid=args.yes_paid,
                    **options,
                )
                print(batch_result.model_dump_json(indent=2))
                return 1 if batch_result.counts["failed"] else 0
            remote = args.source.lower().startswith(("http://", "https://"))
            if not remote and args.subtitle_language:
                raise ConfigurationError(
                    "--subtitle-language 仅适用于平台 URL；本地使用 --subtitles。"
                )
            if args.dry_run:
                plan = preview(settings, cloud=args.cloud)
                source_info = (
                    inspect_url(args.source, settings, language=args.subtitle_language)
                    if remote
                    else None
                )
                duration = (
                    source_info.duration_seconds
                    if source_info
                    else probe(
                        Path(args.source), settings.video.max_duration_minutes
                    ).duration_seconds
                )
                result = {
                    **plan,
                    "duration_seconds": duration,
                    "source": source_info.model_dump(mode="json")
                    if source_info
                    else {"platform": "local"},
                    "video_downloaded": False,
                    "credentials": "not_checked",
                    "local_speech_enabled": settings.speech.enabled,
                    "local_ocr_enabled": settings.ocr.enabled,
                    "local_models": "not_loaded_or_downloaded",
                }
            else:
                if remote and args.cloud:
                    check_cloud_access(settings, approve_paid=args.yes_paid)
                origin = (
                    fetch_url(args.source, settings, language=args.subtitle_language)
                    if remote
                    else None
                )
                media = origin.video if origin else Path(args.source)
                subtitles = args.subtitles or (origin.subtitles if origin else None)
                analysis = asyncio.run(
                    analyze(
                        media,
                        settings,
                        output=args.output,
                        subtitles=subtitles,
                        cloud=args.cloud,
                        approve_paid=args.yes_paid,
                        visual_only=args.visual_only,
                        save_audio=args.save_audio,
                        origin=origin,
                    )
                )
                result = {
                    "status": analysis.status,
                    "output_directory": str(analysis.directory),
                    "error": analysis.error,
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1 if analysis.error else 0
    except VideoMindError as exc:
        print(f"VideoMind: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("VideoMind: 本地读写失败，请检查权限、磁盘空间和路径。", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("VideoMind: 已中断；可检查已有输出。批次可使用 --resume 检查续跑。", file=sys.stderr)
        return 130
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
