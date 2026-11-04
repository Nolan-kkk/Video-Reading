# VideoMind 开发计划

需求基线：仓库根目录 `VideoMind_Codex_Project_Brief.md`（完整保留交接原文）。
日期：2026-11-04。V0 已通过验收；V1 已有本地/平台闭环、真实云端验收待补；V2 正在推进。
最新用户选择仅需 B站、抖音和本地视频；不再实现原始需求草案中的 YouTube。

## 当前进展

V1 本地单视频处理、SRT/VTT、音频提取、场景关键帧、Markdown/JSON 导出和
DeepSeek 视觉/文本适配器已实现；通过离线与模拟响应验证。用户在续做时选择 DeepSeek，
实现采用当前官方支持的 deepseek-flash；不把它写成用户亲自选定的具体模型版本。
已生成原创六秒 PPT/代码/图表 + 字幕夹具，得到 0/2/4 秒关键帧和本地输出。
现已接入标准 B站 BV/av 单视频获取，并实际处理用户提供的 BV1NNNqzVEi4：
下载成功，当前公开请求无字幕，已生成跨全片分布的关键帧、本地音轨和限制说明。
未使用真实 Key 验证云端效果，未验证有字幕的真实平台样例，因此不宣布 V1 全部完成。
用户曾选择先用现成字幕；随后要求添加音频与图像识别，因此 0.1.2 阶段增加可选
faster-whisper 本地转录与 RapidOCR 画面文字识别，不新增云端语音服务商。
真实 32.6 秒样例已得到 17 段转录和 7 帧 OCR；有误听，保留原始结果，不宣称完整准确。
云端为主的产品方向保留；本地模型是显式安装的可选增强，基础核心不强制下载模型。
续做至 0.2.0：实现批量列表、规范去重、有界并发、状态原子写入、目录锁、产物指纹续跑、
显式失败重试与整批累计预算。真实本地混合批次与续跑通过；云端批次只使用模拟响应测试。
0.2.1 已接入抖音标准 URL 与两平台官方分享短链，完成离线契约和短链在线测试；
用户提供的抖音样例匿名元数据获取受平台限制，实际媒体下载和识别仍待验收。

## 1. 需求分析与约束

产品是通用视频到 Markdown 引擎，面向 Codex 和其他 AI 保留可追溯证据。
独立 Python 核心负责处理，CLI 负责交互，Skill 负责调用；核心不得依赖 Codex。

| 已确认要求 | 落实方式 | 验证阶段 |
| --- | --- | --- |
| GitHub 开源分发 | 本地安装、中英文说明、贡献与安全说明，发布前确定许可证 | V0 / V4 |
| 每位用户自带 Key、支付自己费用 | 仅解析用户明确配置的环境变量；无内置 Key、无作者后端、无账户回退 | V0 起每阶段 |
| 批量 B站、抖音和本地视频 | 来源适配器与批次调度独立；抖音真实获取仍待验收 | V1–V3 |
| 语音、字幕、PPT、代码和关键帧 | 字幕优先；转录、视觉、可选 OCR；统一时间线 | V1–V3 |
| 结构化 Markdown 供 AI 读取 | 原始证据与笔记分离，JSON 记录来源、状态和处理信息 | V1–V2 |
| 优先 Codex Skills、Python 独立 | Skill 只调用已实现 CLI；不把处理逻辑写入提示词 | V0 起 |
| Windows + NVIDIA、云端为主 | Python 3.11+；V0 不需要 CUDA、GPU 或大模型 | V0 起 |
| 费用可控 | 配置上限只是基础，付费入口必须执行预算预留与确认 | V1–V2 |

尚未决定：正式名称、MIT/Apache-2.0、云端语音 Provider、GUI 策略。
当前沿用 VideoMind 工作名；不声明 PyPI 名称可用、不发布、不擅自选许可证。
CLI 是落实 Codex 集成的实施顺序，不代表用户已经选择了最终 GUI 策略。

## 2. 架构与数据流

输入 → 来源适配 → 元数据/字幕 → 音频及关键帧预处理 → 能力匹配 →
用户 Provider → 时间戳证据 → 原始 Markdown / 可选整理笔记 / JSON。

- Provider 分语音、视觉、文本三类接口，可分别选供应商。
- 配置中的提供商名称只是声明，不能据此推断它支持全部模态或具体模型。
- 字幕和 OCR 是原始证据；模型整理必须另存并关联证据。代码识别不完整必须标注。
- API Key 仅运行时解析，不进入配置数据、Markdown、缓存键、状态或异常。
- 原始视频、下载、输出和私密配置不进入 Git；不运行作者推理服务。

## 3. 分阶段实施与验收

### V0：工程和 Codex 入口（已完成，历史范围）

交付：可安装 src-layout 包、`videomind` / `python -m videomind`、`doctor`、
`check-config`、严格 YAML 校验、环境变量密钥解析、三个 Provider Protocol、
时间戳证据契约、Skill、README、pytest/格式/类型检查。

验收：在 Windows 虚拟环境安装；从非仓库目录调用 CLI；缺 Key 返回非零且不泄密；
拒绝占位模型、共享计费模式、未知/重复配置字段；测试禁止网络连接。
V0 当时不实现 `analyze` / `batch`，不调用 API。V1 新增 analyze；V2 新增 batch。

### V1：单视频最小闭环

顺序分为可测试的小步：

1. 本地输入、ffprobe 元数据、最大时长校验；SRT/VTT 时间戳读取和单元测试。
2. FFmpeg 音频分离与少量画面变化关键帧；为子进程设置超时，不使用 shell 拼接。
3. 选择并查询用户指定模型的官方文档、能力、计费；实现一个真实语音和视觉适配器。
4. 付费请求统一入口：先检查 Key、目标域名、能力、规模、价格、预算与确认，再调用。
   缺价格/无法给出保守成本上界时阻止付费操作；V2 再完善整批预算。
5. 对齐字幕/语音/画面；生成 transcript.md、notes.md、code.md、metadata.json、images/。
   `code.md` 无代码时明确说明，不编造；缺视觉素材时标注无法完成该部分。
6. 单独添加 B站适配，使用用户有权处理的公开样本验证；不绕过访问控制。
7. 按新增要求接入可选本地 ASR/OCR，保持字幕优先、模型显式准备、时间戳/置信度和失败保留。
   使用真实模型跑样例；不把 OCR 当图像语义理解，不把合成测试音当真实语音验收。

测试：可合成、可分发的短语音 + PPT/代码夹具；FFmpeg 集成测试；录制或伪造 Provider
响应验证路径、时间戳、输出及错误。真实 API 测试显式开启，使用运行者自己的 Key 和
小额预算，默认测试和 CI 不使用任何真实密钥。保留证据用于人工核对识别效果。

阶段门槛：离线集成测试通过；一段获授权的真实本地视频经用户 API 得到可追溯输出；
至少一种公开视频来源通过验证。未做真实验证时只能标为“离线验证”，不能宣布 V1 完成。

### V2：批量与可靠性

已完成第一步：输入/去重、单项隔离、有界并发、原子状态、锁、指纹失效、同批次续跑、
显式重试、整批预算预检和逐尝试持久化预留。汇总含来源与时间戳证据，不调用融合模型。
已接入单次跨视频模型总结及模拟测试；未完成自动错误分类/退避、跨批次缓存和真实云端验收。

顺序：输入列表和规范化去重 → 独立任务状态持久化 → 有界并发 → 缓存/续跑 →
可重试错误分类和退避 → 按批次费用预留、计量及汇总。

任务状态：pending/running/completed/failed/skipped。缓存标识包含输入指纹、模型、
相关配置和处理版本，不包含 Key。写入应原子化；中断恢复时识别未完成任务。
在重试之前预留费用；不盲目重发已可能计费而状态未知的请求。
输出 batch_status.json 和有来源、时间戳的 batch_summary.md。

测试：成功/失败/重复混合列表；并发上限；崩溃恢复；缓存失效；预算耗尽；
429、超时、不可重试错误；未知账单与实际使用分开记录。
验收：单项失败不拖垮批次，重复运行不无谓重算，超预算请求在发送前被阻止。

### V3：平台与 Provider 扩展

完善抖音适配与实际验收；按需扩 Gemini/Anthropic 或其他明确兼容的接口。
平台登录/地区限制给出可行动错误和本地输入后备，不保证所有链接可用。
每个 Provider 声明能力；测试不支持转录、缺时间戳、图像限制、结构化响应不合法、
模型不可用、限流等差异。增加 OCR 和短暂关键画面的采样优化时另做成本/召回率评估。

验收：支持矩阵可复现，平台契约测试离线可跑；少量获授权在线样例显式运行，
把网络/平台变化与核心回归区分记录。

### V4：开源发布

已准备 Windows/Linux GitHub Actions 配置（Python 3.11、无真实 Key、测试不允许跳过），
本机已运行同样的测试入口；尚未发布仓库或在 GitHub 实际运行。
仍需选定许可证、确认仓库/包名；补 LICENSE、发布说明、依赖与安装检查、示例许可和问题模板。
用干净环境按中英文 README 验收，再发布 GitHub；PyPI 另行确认与发布。
GUI、Claude Skill、RAG 和更深跨视频融合均为后续可选项。

## 4. 文件结构与责任

```text
.
├── VideoMind_Codex_Project_Brief.md  # 原始需求
├── README.md / README_EN.md
├── CONTRIBUTING.md / SECURITY.md
├── pyproject.toml / MANIFEST.in / .gitignore / .env.example / config.example.yaml
├── .agents/skills/videomind/SKILL.md # 仓库内发现；可单独复制给其他工作区
├── src/videomind/
│   ├── __init__.py / __main__.py / py.typed
│   ├── cli.py                      # 参数、退出码、安全诊断
│   ├── config.py / security.py / errors.py
│   ├── providers/base.py           # 能力、使用量、三个 Protocol
│   ├── models/schemas.py           # 证据与时间戳
│   ├── pipeline.py                 # V1：单视频编排，已实现
│   ├── extractors/                 # base.py/bilibili.py/sources.py/worker.py
│   ├── processors/                 # media.py / subtitles.py / speech.py / ocr.py
│   ├── exporters/markdown.py        # Markdown + JSON，已实现
│   ├── billing.py                  # 单次请求预留；batch 分配单项上限
│   ├── batch.py / persistence.py    # V2 编排、累计预算、指纹续跑、原子状态和锁
│   └── cache.py                    # 未来跨批次缓存，未创建
├── tests/                          # 与每个阶段一起增加
├── scripts/create_demo.py / run_ci_tests.py # 原创演示与 CI 无跳过测试入口
├── examples/                       # V1 起：可分发样例及许可
├── docs/
│   ├── development-plan.md / architecture.md
│   ├── installation.md / configuration.md / validation.md
│   └── providers.md / local-recognition.md / batch.md
├── LICENSE                         # 许可证选定后
└── .github/workflows/ci.yml         # 已准备；等待 GitHub 实际运行
```

只创建已有职责的文件；后续文件不放假实现或空壳。核心绝不导入 Skill/Codex。

## 5. 执行规则

每个小步先明确可观测行为，再实现并运行对应测试。阶段结束记录命令、结果、
外部依赖和未验证部分。失败先修复再推进，不把 mock 测试称为真实平台/模型验证。
不以预计天数作为交付承诺。未获用户 Key 和样例时继续离线实现与测试，不读取作者
或 Codex 的登录凭据，也不偷偷借用其他账户。

