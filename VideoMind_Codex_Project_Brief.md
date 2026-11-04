# VideoMind — Codex 项目交接文档

> 版本：v0.1 项目规划整合稿  
> 整理日期：2026-11-04  
> 用途：将本次对话中的需求、选择、技术方案、开发计划与注意事项交给电脑版 Codex，作为后续实现的项目上下文。  
> 状态：**尚未开发；本文是需求与设计，不代表功能已经实现。**

## 0. 给 Codex 的任务说明

请阅读本文，将其作为 VideoMind 开源项目的初始产品需求文档（PRD）和技术设计草案。先检查本地项目状态，若没有现有代码，则从可运行的最小版本开始开发。优先保证用户自带 API Key（BYOK）、本地执行、费用可控、输出可追溯。不要把本文中的示意命令、配置或时间估计当成已经实现的功能。开发前可提出必要的技术决策，但不要无故扩大 MVP 范围。

## 1. 项目愿景与最终目标

用户希望开发一个开源到 GitHub 的 **多模态视频解析工具 / AI Skill**，暂定名 **VideoMind**（曾用构想名 VideoReader Skill、Video2Knowledge）。它能够读取视频内容，包括但不限于 **哔哩哔哩（Bilibili）、抖音（Douyin）、YouTube 和本地视频**，并将内容整理为 Markdown（`.md`），供 Codex 或其他 AI 后续阅读、总结、检索和问答。

**核心产品定位**：Universal Video-to-Markdown Engine（通用视频转 Markdown 引擎）。不是只做简单摘要，而是尽可能保留可追溯的语音、字幕、PPT、代码、图表、关键画面及时间戳。

**最重要的商业与技术约束**：项目完全采用 **BYOK（Bring Your Own Key）**。每个用户使用自己的 AI API Key 和自己的 API 账户额度，支付自己的 Token、音频、图像等推理费用；**绝不能使用或消耗项目作者的 API Key / 额度**。作者不为其他用户承担 AI 推理费用。

## 2. 用户已明确做出的选择

以下均为本次对话中明确选定的要求，不应在开发时随意改变：

| 问题 | 用户选择 | 解释 |
|---|---|---|
| Skill 运行平台 | **1B** | 优先支持 **Codex / OpenAI Skills** |
| 视频读取深度 | **2B** | **字幕 + 视频画面 + PPT + 代码**，不仅是语音摘要 |
| 使用方式 | **3B** | **批量输入多个视频链接，自动整理** |
| 开发电脑 | **1A** | **Windows + NVIDIA 显卡** |
| AI 处理方式 | **2C** | **主要使用云端 API**，而非在本地部署大型模型 |
| 发布形式 | 明确要求 | **GitHub 开源，其他人能下载使用** |
| 计费模式 | 明确要求 | **用户使用自己的 API Key / 自己的额度，绝不花作者的额度** |

**尚未由用户最终选定**：项目面向开发者还是普通用户的 UI 策略（此前建议先 CLI + Skill、后 GUI）；最终项目名称；许可证（MIT 或 Apache-2.0）；首批实际接入的云端模型及其版本。不要把建议误写成用户已经决定的事项。

## 3. 主要用户场景

1. 用户向 Codex 提供一个或多个视频链接，要求使用 VideoMind Skill 读取、理解并输出 Markdown。
2. 视频包含语音、字幕、教学 PPT、代码演示、图表、算法动画等，系统要尽量提取这些信息。
3. 每个视频生成独立的转录、结构化笔记、代码和图片资源；多个视频额外生成批次汇总。
4. 输出可由 Codex 或其他 AI 直接读取，用于学习、知识点提炼、跨视频比较与后续问答。
5. 用户从 GitHub 安装项目，自己配置 API Key；作者无需运行服务端，也不支付用户的推理费用。

### 目标交互（计划中的命令，尚未实现）

```powershell
# CLI 单视频
videomind analyze "<video-url>" --mode full --output ./notes

# CLI 批量
videomind batch urls.txt --mode full --output ./notes

# Codex 自然语言调用
# “使用 VideoMind Skill 分析这些 B站和抖音链接，
#  提取字幕、PPT、代码和关键帧，分别生成 Markdown，最后汇总。”
```

## 4. 推荐架构

**独立 Python 核心 + CLI + Codex Skill 适配层**。不要把核心视频处理逻辑写死在 Skill 文本里。未来可以额外增加 Claude Skill、其他 Agent 集成或图形界面。

```text
用户（Codex Skill / CLI / 未来其他 Agent）
                   |
                   v
              VideoMind Core
                   |
       +-----------+-----------+
       |           |           |
       v           v           v
   Input/Batch   Extractor   Config/BYOK
       |           |           |
       +-----------+-----------+
                   |
                   v
          本地预处理（Python）
          |                 |
          v                 v
      字幕/音频          视频关键帧
          |                 |
          v                 v
      用户的语音 API     用户的视觉 API
          |                 |
          +--------+--------+
                   v
         时间戳对齐 / 信息融合
                   |
                   v
        用户的文本模型（可选）
                   |
                   v
        Markdown + JSON + 图片
                   |
                   v
           Codex / 其他 AI
```

### 架构原则

- **本地发起 API 请求**：用户机器直接调用用户所选模型提供商；不经过作者的代理服务器。
- **不内置作者的密钥**：没有可回退使用的共享 API Key；缺少用户密钥时应明确报错。
- **模块化平台适配**：Bilibili、Douyin、YouTube、本地文件分别实现适配器；失败不会导致整个批次崩溃。
- **模块化 AI 提供商**：转录、视觉、文本整理各自有 Provider 接口，允许混用不同模型。
- **信息可追溯**：保留原始转录、时间戳、关键帧和信息来源；不要只保留 AI 摘要。
- **可控成本**：用户可设置批次预算、并发、帧数、时长上限和确认步骤。
- **可扩展**：核心 CLI 不依赖 Codex，可独立运行和测试。

## 5. 技术栈建议

| 模块 | 建议 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | 主实现语言 |
| Skill | Codex Skills / `SKILL.md` | Codex 适配入口，需按当前 Codex 官方规范实现 |
| 视频/字幕获取 | `yt-dlp` | 各站点能力随时间变化，不保证所有链接可用 |
| 音视频处理 | FFmpeg | 音频分离、抽帧、转码 |
| 关键帧检测 | OpenCV | 画面变化检测、去重 |
| OCR | PaddleOCR（可选） | 识别 PPT / 代码文字，可根据实际安装复杂度调整 |
| 云端语音识别 | 用户选择的 Transcription Provider | 例如 OpenAI 对应能力 |
| 云端视觉理解 | 用户选择的 Vision Provider | 理解图表、PPT、代码和复杂画面 |
| 云端文本整理 | 用户选择的 Text Provider | 生成知识点、笔记、批次总结 |
| 数据校验 | Pydantic | 配置和中间数据结构 |
| 并发 | asyncio / 任务队列 | 控制并发与重试 |
| 输出 | Markdown + JSON + images | 人类可读 + 机器可用 |
| 测试 | pytest | 单元测试和集成测试 |

候选 API Provider：OpenAI、Google Gemini、Anthropic，以及兼容 OpenAI API 格式的第三方提供商。**不同服务商的转录、图像、视频、文本能力不完全一致，必须按能力检测，不能假设通用接口完全相同。**

参考官方/项目地址：

- yt-dlp: https://github.com/yt-dlp/yt-dlp
- FFmpeg: https://ffmpeg.org/
- OpenCV: https://opencv.org/
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- faster-whisper（可选本地转录方案）: https://github.com/SYSTRAN/faster-whisper
- OpenAI API: https://platform.openai.com/
- Gemini API: https://ai.google.dev/
- Anthropic API: https://docs.anthropic.com/

## 6. 视频处理工作流

### 6.1 输入与批量任务

- 接收单个 URL、URL 列表文本文件或本地视频文件。
- 识别平台、规范化 URL、去重、生成任务 ID。
- 获取可用的标题、作者、时长、来源链接等元数据。
- 设置任务状态（pending / running / completed / failed / skipped）。
- 任务失败应记录原因并允许单独重试；已完成任务可缓存复用。

### 6.2 获取内容

- 优先读取平台可合法访问的现成字幕及时间戳。
- 无字幕时，若允许且可获取音频，则提取音频并使用用户的云端语音识别 API。
- 使用 FFmpeg/OpenCV 选择关键帧，优先检测画面变化，避免每秒截图造成成本浪费。
- 识别 PPT、屏幕代码、图表、示意图等内容，必要时结合 OCR 与多模态模型。
- 对较短暂出现的关键画面，后续可优化抽帧策略，避免固定间隔抽帧漏掉内容。

### 6.3 多模态对齐

使用统一时间戳将字幕、语音、关键帧、OCR、视觉描述关联起来。

示例中间结构：

```json
{
  "start_seconds": 180,
  "end_seconds": 200,
  "transcript": "这里介绍时间复杂度",
  "frames": ["images/frame_180.png", "images/frame_195.png"],
  "concepts": ["Time Complexity"],
  "sources": ["transcription", "vision"]
}
```

### 6.4 生成 Markdown

建议分离原始信息与 AI 整理结果：

- `transcript.md`：尽量忠实保存字幕、语音转录、PPT/OCR、代码、画面描述和时间戳。
- `notes.md`：按章节组织的摘要、知识点、术语、代码讲解、图表解释和时间戳。
- `code.md`：视频中出现的代码，注明来源时间、语言和识别不确定性。
- `metadata.json`：标题、来源、处理模型、任务状态、耗时、错误和可追溯元数据。
- `images/`：关键帧图片。
- `batch_summary.md`：跨视频综合总结，标注每条结论的来源视频与时间戳。

**质量要求**：不要把 OCR 或模型推测当成无误原文；标明来源和不确定性。若视频中代码识别不完整，不能静默补全后冒充原始代码。

## 7. 输出目录示例

```text
output/
├── batch_summary.md
├── batch_status.json
├── video_001/
│   ├── metadata.json
│   ├── transcript.md
│   ├── notes.md
│   ├── code.md
│   └── images/
│       ├── frame_001.png
│       └── frame_002.png
├── video_002/
│   ├── metadata.json
│   ├── transcript.md
│   ├── notes.md
│   ├── code.md
│   └── images/
└── video_003/
    └── ...
```

输出模式（建议）：

| 模式 | 内容 |
|---|---|
| `raw` | 字幕、语音、OCR、代码、画面描述等原始提取信息 |
| `notes` | 章节、知识点、示例、解释和摘要 |
| `full` | 同时输出 raw 和 notes，推荐作为默认模式 |

分析深度（建议）：

| 模式 | 处理方式 |
|---|---|
| `fast` | 优先字幕/语音 + 摘要 |
| `standard` | 加入关键帧、OCR 和结构化笔记 |
| `deep` | 更全面的多模态画面分析、代码与图表理解 |

“输出模式”与“分析深度”最好在 CLI 参数中明确区分，避免两个不同概念都使用 `--mode`。

## 8. BYOK：必须严格执行的安全与费用规则

这是项目最重要的非功能性需求：

1. 用户自行提供 API Key，优先使用环境变量或本地安全配置；仓库中仅提供 `.env.example`。
2. **绝不提交作者自己的密钥，不在代码、测试、示例、日志、异常、Markdown 中暴露任何密钥。**
3. 所有付费 AI 请求从用户本地环境直连所选服务商，不能通过作者运营的付费代理或后端。
4. 缺少必需 API Key 时明确报错，不得回退使用作者账户。
5. 用户承担自己的语音、图像、文本推理费用；不同模型计费方式不同，不一定都按 Token 计费。
6. 提供 API 预算上限、最大视频时长、最大关键帧数、并发上限、重试次数与可选费用确认。
7. 成本估算必须基于模型实际价格/请求量；估算不等于精确账单，预算限制应尽量在请求前执行。
8. 不默认把完整视频上传到作者的服务器。**但云端 API 模式下，必要的音频、关键帧或文本会发送到用户选择的模型提供商**，应在文档中透明披露。
9. 默认本地保存输出，不上传作者的服务器。
10. 本地运行不意味着完全没有额外成本：用户的带宽、磁盘、第三方 API 费用由用户自行承担；作者如果启用 CI 或托管服务，可能产生自己的基础设施费用，但不得与用户推理费用混淆。

### 配置示例（仅为规划草案）

```yaml
providers:
  transcription:
    provider: openai
    model: YOUR_TRANSCRIPTION_MODEL
  vision:
    provider: gemini
    model: YOUR_VISION_MODEL
  text:
    provider: openai
    model: YOUR_TEXT_MODEL

video:
  max_concurrent_tasks: 3
  max_duration_minutes: 120

vision:
  max_frames_per_video: 60

billing:
  mode: user_provided_api_key
  max_budget_usd_per_batch: 5
  confirm_before_paid_requests: true

output:
  directory: ./output
  format: markdown
  save_transcript: true
  save_images: true
```

示例 `.env.example`：

```dotenv
OPENAI_API_KEY=your_api_key_here
GEMINI_API_KEY=your_api_key_here
ANTHROPIC_API_KEY=your_api_key_here
```

以上模型名是占位符，实际使用时需验证对应提供商和模型的能力。不要假设仅靠 YAML 配置就能保证安全，必须在程序代码和测试中落实。

## 9. 推荐仓库结构

```text
videomind/
├── README.md
├── README_EN.md
├── LICENSE
├── CONTRIBUTING.md
├── SECURITY.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── config.example.yaml
├── src/
│   └── videomind/
│       ├── cli.py
│       ├── config.py
│       ├── pipeline.py
│       ├── extractors/
│       │   ├── base.py
│       │   ├── bilibili.py
│       │   ├── youtube.py
│       │   ├── douyin.py
│       │   └── local.py
│       ├── providers/
│       │   ├── base.py
│       │   ├── openai.py
│       │   ├── gemini.py
│       │   └── anthropic.py
│       ├── processors/
│       │   ├── audio.py
│       │   ├── frames.py
│       │   ├── ocr.py
│       │   └── timeline.py
│       ├── exporters/
│       │   ├── markdown.py
│       │   └── json.py
│       └── models/
│           └── schemas.py
├── skills/
│   └── codex/
│       └── SKILL.md
├── tests/
├── examples/
└── docs/
    ├── installation.md
    ├── configuration.md
    ├── providers.md
    └── architecture.md
```

注意：Codex 的实际 Skill 安装/发现目录需以当前官方规范为准，不能仅因为仓库里有 `skills/codex/SKILL.md` 就认定 Codex 会自动发现。

## 10. 平台支持与边界

目标支持 Bilibili、Douyin、YouTube、本地文件，但必须承认：

- 平台接口、字幕获取方式、可访问性可能变化。
- 可能遇到登录要求、地区限制、版权或平台服务条款限制。
- 仅处理用户有权访问和处理的内容，不实现绕过访问控制的功能。
- 平台解析失败时给出清晰错误、记录任务状态，允许用户跳过或提供合法获得的本地文件。
- 对于没有字幕的视频，语音转录是后备方案；对于没有画面可获取的来源，应明确报告无法完成视觉分析。

## 11. GitHub 开源与分发

目标是让任何人从 GitHub 获取代码、安装并配置自己的 API Key。

建议的文档与工程规范：

- 中文 `README.md` + 英文 `README_EN.md`。
- `LICENSE`：候选 MIT 或 Apache-2.0；**尚未最终决定**。
- `CONTRIBUTING.md`：如何提交 PR、报告问题、运行测试。
- `SECURITY.md`：密钥安全、漏洞报告、隐私说明。
- `.gitignore`：排除 `.env`、密钥、缓存、临时视频和用户输出。
- 单元测试、CI、基本类型检查与格式化。
- 支持开发模式 `pip install -e .`。
- 后续如需 `pip install videomind`，必须先确认 PyPI 包名可用并完成发布；目前该命令只是目标。

README 中应明确说明：

> VideoMind is an open-source BYOK tool. Users supply their own API credentials and pay their own AI provider charges. The project maintainer does not operate paid inference for users or cover their API usage.

## 12. 建议开发阶段与验收

### V0：工程骨架 + Codex 调用

- 创建 Python 包、CLI 入口、配置加载和 Provider 接口。
- 创建符合 Codex 规范的 `SKILL.md`。
- 提供 `.env.example`、README、测试框架。
- 验收：Codex 能调用 CLI；缺少用户 Key 时安全失败；没有作者密钥。

### V1：单视频端到端 MVP

- 先支持**用户有权处理的本地视频**，再增加一个 B站公开示例作为平台验证。
- 获取字幕或提取音频，通过用户 API 进行转录。
- 提取少量关键帧并调用用户视觉 API。
- 输出 `metadata.json`、`transcript.md`、`notes.md`、`images/`。
- 验收：一段包含语音和 PPT/代码的测试视频能够得到可追溯 Markdown。

### V2：批量与可靠性

- 批量 URL、去重、并发控制、缓存、断点续跑、失败重试。
- 输出 `batch_status.json` 和 `batch_summary.md`。
- 增加预算上限和 API 费用估算。
- 验收：多视频处理时单个失败不会影响其他任务；重复运行不无谓重算。

### V3：多平台 + 多 Provider

- 扩展 YouTube、抖音适配；增加 Gemini 和其他 Provider。
- 处理能力差异、速率限制、模型失败、隐私提示。
- 验收：支持的来源和模型组合有自动化测试及明确错误提示。

### V4：开源发布与后续扩展

- 完善中英文文档、贡献指南、GitHub Actions、版本发布。
- 可选：Claude Skill、GUI、知识库/RAG、多视频知识融合。
- 验收：新用户按 README 能安装、配置自己的 API Key、运行示例。

此前对话曾给出数天至数周的粗略开发时间估计，但实际时间高度依赖开发经验、平台访问限制和模型接口变化；**不作为承诺工期**。

## 13. 重要设计取舍

1. **优先 CLI，不优先 GUI**：因为用户明确选择 Codex Skill；普通用户 GUI 仍可作为后续扩展。此前提出的“开发者优先 / 普通用户优先 / 分阶段兼顾”问题，用户尚未正式作答。
2. **云端 AI 为主**：Windows + NVIDIA 不意味着必须配置 CUDA 或部署本地大模型；先减少安装难度。
3. **保留原始层**：不要让摘要成为唯一数据来源。
4. **优先字幕，按需转录**：减少不必要的 API 消耗。
5. **按画面变化抽帧**：减少重复图片和视觉 API 费用。
6. **Provider 分层**：转录、视觉和文本模型可分别选择，不强制一个厂商包办全部任务。
7. **无作者后端**：第一版不需要作者运营的推理服务器，防止误用作者额度。
8. **真实能力说明**：不要在 README 声称所有抖音/B站/YouTube 视频都能解析；应列出支持范围和限制。

## 14. 最小可行验收清单

- [ ] Windows 上可以按文档安装并运行 CLI。
- [ ] 可使用用户自己的 API Key；没有 Key 时不会发起付费请求。
- [ ] 仓库、日志和产物不包含任何真实密钥。
- [ ] 支持本地视频输入，并验证至少一种公开视频来源。
- [ ] 可以提取字幕或语音，并保留时间戳。
- [ ] 可以抽取关键帧，识别 PPT、代码或图表中的至少一种。
- [ ] 输出 `transcript.md`、`notes.md`、`metadata.json` 和图片资源。
- [ ] 批量任务可以独立记录成功/失败状态。
- [ ] 支持费用/任务规模上限和明确的隐私提示。
- [ ] Codex Skill 能调用独立 CLI。
- [ ] 文档明确所有 AI 费用由用户自己承担。

## 15. 推荐 Codex 开发启动指令

将下面这段文字直接发给电脑版 Codex（本文作为上下文）：

> 请阅读 `VideoMind_Codex_Project_Brief.md`，按照其中已确认的需求开发一个开源 Python 项目。核心原则是 BYOK：所有 AI API 请求必须使用终端用户自己配置的密钥，绝不能使用项目作者的密钥或服务器。先实现 V0 + 一个可验证的 V1 最小闭环：Python CLI、配置与密钥校验、Provider 抽象、合法本地视频处理、字幕/音频提取、少量关键帧、云端 AI 解析、Markdown 输出，以及 Codex Skill 入口。使用清晰的模块边界、类型注解、pytest 和 README。先列出实施计划与文件树，再开始编码。不要假设平台适配、PyPI 发布或模型接口已可用；每一步提供实际测试方法。禁止将真实 API Key 写入仓库。

---

## 附录 A：本次对话关键需求与决策记录（按时间顺序）

1. 用户最初提出：想做一个 Skill，能读取视频内容，包括但不限于抖音、哔哩哔哩，读取后生成 Markdown 文档反馈给 AI，并询问可行性和复杂度。
2. 助手提出“视频获取 → 字幕/音频/关键帧 → AI 处理 → Markdown”的架构，建议 Python、yt-dlp、FFmpeg、Whisper、视觉模型、OCR，并指出多平台获取是难点。
3. 用户选择 **1B、2B、3B**：Codex / OpenAI Skills；读取字幕 + 画面 + PPT + 代码；批量输入多个视频链接。
4. 助手据此提出 VideoReader Skill、批量管理、时间戳对齐、分层 Markdown、断点续跑、fast/standard/deep 分析模式，并询问电脑和处理方式。
5. 用户选择 **1A、2C**：Windows + NVIDIA；主要使用云端 API。
6. 助手建议“本地视频获取和预处理 + 云端语音/视觉/文本模型”，避免第一版配置本地大模型。
7. 用户进一步提出：希望很多人能使用，开源到 GitHub，人们使用自己的 API 消耗 Tokens。
8. 助手将方案升级为 **VideoMind**：独立 Python Core + CLI + Codex Skill、BYOK、多 Provider、开源分发和未来可扩展 UI。
9. 用户再次强调：**“人们花费自己的额度，不花费我的额度。”**
10. 助手明确确认：无作者代理服务器、无作者共享 Key、用户本地直连自己的 AI 提供商，用户自己承担 AI 调用费用。
11. 用户要求：把以上对话整合为一个 Markdown 文件，交给电脑版 Codex 打开。

## 附录 B：待后续确认事项

- 正式项目名是否继续使用 `VideoMind`，以及 GitHub / PyPI 名称是否可用。
- 许可证选择 MIT 还是 Apache-2.0。
- 首批 Provider 具体模型与价格查询策略。
- 首个可重复验证的视频样本及其授权/可访问性。
- CLI 的输出模式、分析深度、预算参数最终命名。
- 是否在稳定 CLI + Skill 后开发 GUI（此前建议分阶段兼顾，但未最终确认）。

**最终原则：开源代码由作者维护；每位使用者在自己的环境运行程序，使用自己的 API Key，消耗自己的 AI 服务额度，输出自己的 Markdown。**
