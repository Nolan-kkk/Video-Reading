# Video-Reading

独立 Python 核心 + CLI + Codex Skill，将视频证据整理为 Markdown，供其他 AI 阅读。
当前版本 **0.2.1，V2 进行中**：支持本地/B站视频、字幕、可选本地语音转录与 OCR、
DeepSeek 视觉/文本，以及批量去重、并发、状态保存、校验续跑和整批预算。
真实本地批次与语音/OCR 已跑通；平台字幕成功读取、批量平台获取仅有离线契约验证，
真实云端语义理解效果仍未验收，因此 V1 的真实云端验收门槛仍待补齐。
已增加抖音链接接入与 B站/抖音官方短链解析；抖音实际下载尚未验收，当前样例匿名访问失败。

VideoMind is an open-source BYOK tool. Users supply their own API credentials and pay
their own AI provider charges. The project maintainer does not operate paid inference
for users or cover their API usage.

使用当前 Codex 会话模型时，使用者通过自己的 Codex 服务承担用量；若明确选择直接 API，
则使用者提供自己的 Key 和账户额度。没有作者共享 Key、回退账户或推理后端。
默认不调用云端 API；本地输入离线处理，平台链接会联网获取。本项目采用 [Apache-2.0 许可证](LICENSE)。

在 Codex 中使用 Skill 时，默认由当前用户自己的 Codex 会话模型阅读本地提取的证据并
生成分析，不需要另配 VideoMind 的 DeepSeek Key。Codex 会话的用量与计费由用户所用
服务决定；VideoMind 无法保证获取会话 Token 数，也不会伪造。独立 Python 核心仍可
脱离 Codex 使用；直接 DeepSeek API 是另行选择的可选路径。

[English](README_EN.md) · [原始需求](VideoMind_Codex_Project_Brief.md) ·
[开发计划与文件树](docs/development-plan.md) · [验收记录](docs/validation.md)

## 安装

Python 3.11+，Windows PowerShell，在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m videomind doctor
```

本地视频处理需要 FFmpeg 和 ffprobe。安装到 PATH，或设置
`VIDEOMIND_FFMPEG` / `VIDEOMIND_FFPROBE` 为可执行文件完整路径。
本次开发已将校验过 SHA-256 的 Windows 工具下载到本机 `.cache/tools`，不会随仓库分发。
这台开发电脑可在当前 PowerShell 会话运行：

```powershell
$env:VIDEOMIND_FFMPEG = (Resolve-Path '.cache\tools\ffmpeg.exe').Path
$env:VIDEOMIND_FFPROBE = (Resolve-Path '.cache\tools\ffprobe.exe').Path
```

其他机器应自行安装 FFmpeg，见 [安装说明](docs/installation.md)。基础提取无需 CUDA 或本地模型。

## 免费本地流程

```powershell
.\.venv\Scripts\python.exe -m videomind analyze 'D:\videos\lesson.mp4' --output .\output
```

自动读取同名 `.srt` 或 `.vtt`；也可用 `--subtitles captions.srt` 指定。
字幕必须是 UTF-8。有两个同名候选时必须明确选择。
按画面变化抽帧，加入稀疏时间覆盖和帧间隔限制，保留首帧、时间戳和图片。
可用 `--save-audio` 保存 16 kHz 单声道 WAV。

每次生成新的任务目录：

```text
output/video_<task-id>/
  metadata.json       # 状态、来源指纹、限制、模型、费用预留与用量
  evidence.json       # 结构化证据、来源、时间戳、识别不确定性
  transcript.md       # 字幕、语音转录、OCR、关键帧及视觉识别记录
  notes.md            # 离线为证据索引；云端为带引用的 AI 笔记
  code.md             # 可见代码识别结果；没有结果时明确说明
  uncertainties.md    # 按时间定位的待核查项及无法定位的全局限制
  usage.md            # 可选直接 API 返回的 Token；不包含 Codex 会话用量
  images/
  audio.wav           # --save-audio 或实际运行本地转录
```

**抽帧本身不理解内容；本地 OCR 只识别文字，离线笔记仅为证据索引。**
`--output-mode raw` 省略 notes.md；notes/full 均保留原始证据，方便核查。
不确定性报告汇集已有标注，包含时间范围、证据和关键帧链接；全局限制单独列出。
本地语音/OCR 的通用提示不代表已找出具体错误，报告为空也不代表结果准确。
分析失败但已生成任务目录时，报告会保留已获得的证据与失败说明。
`--depth fast` 跳过画面，standard 使用画面变化阈值，deep 降低阈值但仍受帧数限制。
不保证捕获短暂画面或背景相同的小幅 PPT 变化。

## 本地音频与画面文字识别

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,speech,ocr]"
# 显式匿名下载约 486 MB 的多语言 small 模型，仅需准备一次
.\.venv\Scripts\python.exe -m videomind prepare-speech
.\.venv\Scripts\python.exe -m videomind analyze 'D:\videos\lesson.mp4' --transcribe --ocr --output output
```

`--transcribe` 使用 faster-whisper 在 CPU/int8 上运行；默认优先已有字幕，无字幕才转录。
需要即使有字幕也转录时，配置 `speech.prefer_subtitles: false`。`--ocr` 使用 RapidOCR
内置模型识别关键帧中英文，保留逐行置信度和四点坐标。都不需要 Key、不消耗 API 额度。
模型准备和依赖安装需联网，分析时不自动下载模型或上传音频。

默认模型目录 `.cache/models/faster-whisper-small`；可在 YAML 调整路径、语言和 CPU 线程。
`prepare-speech --size base` 可准备更小模型，但必须将 `speech.model_directory` 改为对应目录。
OCR 不能搭配跳过关键帧的 `--depth fast`。转录时会保留 audio.wav，方便复听。
详见 [本地识别说明与效果](docs/local-recognition.md)。

真实样例识别出 17 段语音与 7 帧文字，也出现“龙族→龙祖”等误听；原始结果不会静默改写。
OCR 不推断图表含义，不还原代码结构；这些语义任务可显式开启下方 DeepSeek 路径。

## B站与抖音链接

安装可选下载依赖，然后使用标准 BV/av 链接：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,download]"
# 只联网查询公开元数据和字幕语言，不下载视频，不调用 AI
.\.venv\Scripts\python.exe -m videomind fetch 'https://www.bilibili.com/video/BV1NNNqzVEi4/' --dry-run
# 下载单个视频并生成 Markdown，默认不调用 AI
.\.venv\Scripts\python.exe -m videomind analyze 'https://www.bilibili.com/video/BV1NNNqzVEi4/' --output output\bilibili
```

上例是用户提供的测试链接，当前公开请求没有取得独立字幕；添加 `--transcribe --ocr`
可启用本地转录和画面文字识别。未开启转录时会标记缺失语音。
下载本身涉及带宽和存储，不消耗 AI 额度。只处理自己有权使用的内容；本项目不分发测试视频。
`fetch URL --output <下载目录>` 可只下载，默认缓存位于 `.cache/downloads`。
`--subtitle-language zh-Hans` 可明确选字幕语言，缺失会报错；弹幕被排除。
平台字幕可能自动生成，会保留不确定性。视频画面上的烧录文字与可下载字幕是两回事。

抖音可传标准 `https://www.douyin.com/video/<数字ID>` 或 `https://v.douyin.com/<短码>`；
B站支持标准链接和 `https://b23.tv/<短码>`。短链只允许跳转到对应的可信平台地址。
抖音当前仅完成离线契约与短链实测：用户提供的视频匿名元数据获取失败，暂不能保证下载成功。
遇到限制可使用有权处理的本地文件。详见 [平台说明](docs/platforms.md)。

保留 B站 `?p=2` 等单个分P选择，移除分享追踪参数；不展开合集、不使用登录 Cookie
或绕过访问控制。访问失败可改用本地文件或显式提供 `--subtitles`。
下载默认限制 720p、1024 MiB、600 秒。详见 [平台与下载说明](docs/platforms.md)。

## DeepSeek 云端理解

按用户选择，首个适配器为 DeepSeek。当前官方文档说明
`deepseek-flash` 支持图像和文本，`deepseek-v4-pro` 仅接入文本能力。
参见 [Provider 能力与计费说明](docs/providers.md)，首次使用前核对官方信息。

1. 复制 `config.example.yaml` 为被 Git 忽略的 `config.yaml`。
2. 私下把自己的 Key 设置到 `DEEPSEEK_API_KEY` 环境变量。不要发到聊天、提交 Git，
   或放进命令参数。程序不会自动读取 `.env` 或 Codex 登录凭据。
3. 先查看不会读 Key、不会付费的预检：

```powershell
.\.venv\Scripts\python.exe -m videomind analyze 'D:\videos\lesson.mp4' --config config.yaml --cloud --dry-run
```

确认数据去向和预算后，由运行者显式开启付费：

```powershell
.\.venv\Scripts\python.exe -m videomind analyze 'D:\videos\lesson.mp4' --config config.yaml --cloud --yes-paid
```

云端发送关键帧和证据文本到 `api.deepseek.com`，不发送给作者，也不上传完整视频或音轨。
缺 Key、能力不支持、价格过期、预算不足、未确认费用会在请求前失败。
超时可能已经计费，因此当前不自动重试。API 失败会保留原始证据和失败状态。

费用预留按每次完整上下文输入上限、最大输出和峰时非缓存价格计算，通常高于实际费用，
不是精确账单。当前快照核对于 2026-11-04，有效至 2026-11-11；过期阻止付费调用。
预算只约束本次运行，不是服务商账户全局限额。重复运行暂不复用缓存，云端可能再次计费。

带音轨却无字幕时，云端处理需要 `--transcribe` 的本地转录结果，或显式提供 SRT/VTT；
只有运行者明确接受缺失语音时才使用 `--visual-only`。本地转录/OCR 文本在 `--cloud`
开启后也会作为证据发往 DeepSeek；WAV 留在本机。未新增云端语音服务商。

## 运行原创演示

```powershell
.\.venv\Scripts\python.exe scripts\create_demo.py --output .cache\my-demo
.\.venv\Scripts\python.exe -m videomind analyze .cache\my-demo\demo.mp4 --output output\my-demo --save-audio
```

生成六秒 PPT/代码/图表和旁挂字幕。音轨是测试音，**不是真实语音**。
生成器需 dev 依赖中的 Pillow；输出目录不可含已有 demo.mp4。
本机已生成演示在 `output/demo-v1`，详见 [验收记录](docs/validation.md)。

## Codex 与开发

Skill 位于 [.agents/skills/videomind/SKILL.md](.agents/skills/videomind/SKILL.md)，
可用 `$videomind`；核心独立运行。[安装与发现](docs/installation.md)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

默认测试禁止外部网络并使用假凭据；媒体集成测试需要 FFmpeg/ffprobe。
已准备 Windows/Linux GitHub Actions 配置，使用本地模型和假响应执行完整测试，
不使用 API Key；配置尚未在 GitHub 上实际运行。详见 [贡献指南](CONTRIBUTING.md)。
尚未完成：抖音实际下载验收、自动退避、跨批次缓存、真实云端综合验收及 GitHub 发布。
真实平台字幕、真实云端效果仍待验收；见 [开发计划](docs/development-plan.md)。

## 批量处理与续跑

把每行一个本地视频路径或 B站/抖音 URL 写入 UTF-8 的 videos.txt：

```powershell
.\.venv\Scripts\python.exe -m videomind batch videos.txt --dry-run
.\.venv\Scripts\python.exe -m videomind batch videos.txt --output output --transcribe --ocr
# 使用原处理配置，校验并复用已完成结果
.\.venv\Scripts\python.exe -m videomind batch videos.txt --resume output\batch_<id> --transcribe --ocr
```

相对路径基于列表文件目录；无效输入/单项失败不影响其他项。默认最多同时处理 3 个视频，
生成 batch_status.json、batch_summary.md 和各视频独立结果。续跑校验媒体、字幕、模型及产物，
免费任务结果失效可重做；失败项用 --resume --retry-failed 明确重试。
付费任务可能已经计费时不自动重发，整批预留超预算会在下载/调用前停止。
汇总是带时间戳的证据索引，未额外调用跨视频模型。详见 [批次说明](docs/batch.md)。

需要跨视频 AI 综合时，可在批次完成后使用 `videomind synthesize`；先用 `--dry-run`
查看发送内容和独立的综合预算，再由用户授权 `--yes-paid`。报告引用视频证据和时间；
该云端路径尚未用真实 DeepSeek API 验收，使用说明及重复请求保护见批次说明。
