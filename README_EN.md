# Video-Reading

An independent Python core, CLI and Codex Skill for traceable video-to-Markdown output.
**0.2.1 / V2 in progress:** local/Bilibili videos, optional speech/OCR, DeepSeek text/vision,
and persistent batches with deduplication, bounded concurrency, verified resume and total budgets.
The user's 32.6-second video produced 17 speech segments
and text from 7 sampled frames using real local models, with some recognition errors.
Douyin URL support and Bilibili/Douyin short-link resolution are implemented, but Douyin media
download has not been validated: anonymous metadata requests for the user's sample were blocked.
Successful platform caption retrieval has offline contract tests only; live cloud accuracy is unverified.

VideoMind is an open-source BYOK tool. Users supply their own API credentials and pay
their own AI provider charges. The project maintainer does not operate paid inference
for users or cover their API usage.

There is no shared key, maintainer fallback account or hosted inference. The project is licensed
under [Apache-2.0](LICENSE). Cloud API calls are disabled by default; URL acquisition uses the network.

## Install and run

Python 3.11+, Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m videomind doctor
.\.venv\Scripts\python.exe -m videomind analyze 'D:\videos\lesson.mp4' --output output
```

Install FFmpeg and ffprobe on PATH, or set VIDEOMIND_FFMPEG / VIDEOMIND_FFPROBE to executable
paths. On Linux/macOS use .venv/bin/python. Basic extraction needs no CUDA or local model.

Same-name UTF-8 SRT/VTT sidecars are discovered; --subtitles selects an explicit file.
Scene-change frames include sparse time coverage and minimum spacing. --save-audio saves 16 kHz mono WAV.
Output includes metadata.json, evidence.json, transcript.md, code.md, uncertainties.md, images/ and notes.md.
The uncertainty report links timestamped evidence and frames, and lists global limitations
separately. Generic recognition caveats do not identify specific errors, and an empty report
does not prove accuracy. Existing output directories are not updated automatically.
Offline notes are only an evidence index; extracted frames alone do not imply understanding.
Each analyze run creates a new task folder. Batch resume can reuse verified completed results.

## Batches and resume

Create UTF-8 videos.txt with one local path, Bilibili URL, or Douyin URL per line:

```powershell
.\.venv\Scripts\python.exe -m videomind batch videos.txt --dry-run
.\.venv\Scripts\python.exe -m videomind batch videos.txt --output output
.\.venv\Scripts\python.exe -m videomind batch videos.txt --resume output\batch_<id>
```

Paths are relative to the list. Defaults allow 3 concurrent videos (configurable 1–32).
Failures are isolated and duplicates skipped. Outputs include batch_status.json and a timestamped
evidence index in batch_summary.md, without a cross-video model call. Resume checks source,
caption, model/configuration and artifact fingerprints. Use --retry-failed explicitly for failed
jobs; unknown paid outcomes are never automatically resent. Cumulative reservations survive
resume and paid retries. Batch dry-run never queries platforms or reads keys.
See [batch details](docs/batch.md). Cross-batch caching and automatic backoff remain future work.

For an optional cross-video AI report, run `videomind synthesize <batch-folder> --config config.yaml
--dry-run` first. The explicit `--yes-paid` operation sends evidence text and limitations using
the user's DeepSeek key; its cumulative budget is separate from the original batch budget.
The generated report cites video evidence. Live synthesis quality is not yet verified.

## Local speech and image text recognition

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,speech,ocr]"
.\.venv\Scripts\python.exe -m videomind prepare-speech
.\.venv\Scripts\python.exe -m videomind analyze lesson.mp4 --transcribe --ocr --output output
```

Preparation explicitly downloads the public multilingual small model (~486 MB), anonymously.
Analysis uses local CPU/int8 faster-whisper only; no automatic model download or API key.
Captions take precedence unless speech.prefer_subtitles is false. RapidOCR uses bundled models
to recognize Chinese/English frame text, retaining line confidence and geometry. OCR requires
standard/deep depth. Transcription retains audio.wav for review. For base/tiny preparation,
configure speech.model_directory to match. See [local recognition](docs/local-recognition.md).
OCR does not interpret charts or reconstruct code; cloud vision provides that optional semantic path.

## Public Bilibili and Douyin videos

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,download]"
.\.venv\Scripts\python.exe -m videomind fetch 'https://www.bilibili.com/video/BV1NNNqzVEi4/' --dry-run
.\.venv\Scripts\python.exe -m videomind analyze 'https://www.bilibili.com/video/BV1NNNqzVEi4/' --output output\bilibili
```

Standard Bilibili BV/av and Douyin numeric video URLs are accepted; official b23.tv and
v.douyin.com short links are resolved through restricted redirects. Bilibili p= selects one part.
Tracking parameters are removed. No user cookies, browser login, playlists or access-control bypass.
Douyin acquisition is experimental and may fail due to platform access restrictions; a local file
the user has rights to process remains the fallback. See [platform notes](docs/platforms.md).
Acquisition runs in an isolated worker without AI keys or upstream user config/plugins.
Default limits are 720p, 1024 MiB and 600 seconds; downloads consume bandwidth/storage, not AI quota.
Danmaku is excluded. Missing captions remain missing; burned-in text is not a downloadable track.
Platform captions retain uncertainty. Use --subtitle-language to select a track, or --subtitles
for an authorized local sidecar. See [platform limitations](docs/platforms.md).

## Optional DeepSeek cloud processing

The user selected DeepSeek. Copy config.example.yaml to config.yaml and privately set your own
DEEPSEEK_API_KEY environment variable. No .env or Codex authentication is read automatically.

```powershell
.\.venv\Scripts\python.exe -m videomind analyze lesson.mp4 --config config.yaml --cloud --dry-run
# Only after reviewing and accepting the displayed cost bound:
.\.venv\Scripts\python.exe -m videomind analyze lesson.mp4 --config config.yaml --cloud --yes-paid
```

The preview reads no key and sends no API request. Cloud processing sends frames and source
text directly to api.deepseek.com, not to the maintainer. It does not upload the full video or audio.
The documented deepseek-flash model supports images and text; deepseek-v4-pro supports text
only in this adapter. See [provider sources and billing](docs/providers.md).

Every request reserves a conservative full-context input ceiling plus capped output, using
peak cache-miss rates. This is deliberately higher than typical actual costs, not an invoice.
The price snapshot was checked on 2026-11-04 and expires after 2026-11-11. Expiry, missing keys,
unsupported models, insufficient budget and missing paid approval block execution.
Timeouts are not retried because a request may already be billed. Failed runs retain raw evidence.
The budget is per run; it does not cap the entire provider account or future repeated runs.

Cloud runs without captions require local --transcribe results or an explicit sidecar, unless
--visual-only accepts missing speech. No new cloud speech vendor is added. When --cloud is
enabled, speech/OCR text is sent to DeepSeek along with other evidence; WAV stays local.
Recognition uncertainty and partial code are retained; notes reference existing source IDs.

--output-mode raw omits notes; notes/full retain original evidence for audit.
--depth fast skips vision; standard detects scene changes; deep lowers the threshold within
the configured frame cap. Short-lived or small slide changes may still be missed.

## Demo, Skill and tests

```powershell
.\.venv\Scripts\python.exe scripts\create_demo.py --output .cache\my-demo
.\.venv\Scripts\python.exe -m videomind analyze .cache\my-demo\demo.mp4 --output output\my-demo
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

The original six-second demo has slides, code, a chart, authored sidecar captions and a test tone
(not speech). Generation requires Pillow from the dev dependencies. Media tests need FFmpeg/ffprobe;
all default API tests use mocks and block external network connections.
GitHub Actions is configured for Windows and Linux with a local tiny speech model and no AI API
keys; it fails if any test is skipped. The workflow has not yet run on GitHub.

The Codex Skill is in .agents/skills/videomind/SKILL.md; invoke $videomind after Python installation.
[Installation](docs/installation.md), [development plan](docs/development-plan.md),
[validation](docs/validation.md), [security](SECURITY.md), [contributing](CONTRIBUTING.md).
