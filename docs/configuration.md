# 配置与执行边界

通过 --config 显式加载 UTF-8 YAML。不会自动读 .env、寻找共享 Key 或读取 Codex 登录。
字段拼写错误、重复字段、内联 api_key、错误类型会安全失败，不回显文件原文。

## 本地与云端

默认 `analyze` 不需要配置或 Key；可提供配置调整时长、帧数和输出。
`providers: {}` 允许本地运行。check-config --structure-only 只校验结构；
不带该选项会要求至少一个云端角色并检查所配置 Key 非空且不是占位符，
不验证真实账户、余额或模型能力。

云端使用配置中的 DeepSeek vision/text 角色。默认模式需要两者；raw 不使用 text，
fast 不使用 vision。只检查实际需要的角色；不会为省略的角色寻找其他账户。
openai/gemini/anthropic 标识仍是接口预留，没有实际适配器。

示例 config.example.yaml 可直接做结构校验，其中只有环境变量名称，没有 Key。
把自己的 Key 放在 DEEPSEEK_API_KEY，且必须从运行 CLI 的同一个环境可见。
.env.example 只是说明。工具无法从字符串验证账户所有人，运行者应使用自己账户。

## 参数

| 配置 | 默认值 | 执行情况 |
| --- | --- | --- |
| video.max_duration_minutes | 120 | ffprobe 后、抽帧/API 前拦截 |
| video.max_concurrent_tasks | 3 | 实际同时执行的视频数，1–32；每视频内部串行 |
| video.max_retries | 2 | 允许的最大值；当前付费请求不重试 |
| vision.max_frames_per_video | 12 | 实际抽帧硬上限；云端请求预检上限 |
| vision.scene_threshold | 0.3 | 画面变化阈值；deep 使用一半 |
| vision.max_width | 1280 | 图片等比缩小，上限可配 320–1920 |
| billing.mode | user_provided_api_key | 唯一合法模式 |
| billing.max_budget_usd_per_batch | 5 | batch 为整批累计上限；analyze 为单次上限 |
| billing.confirm_before_paid_requests | true | cloud 还需 --yes-paid；false 时 cloud 本身是开启开关 |
| billing.max_output_tokens_per_request | 2048 | 范围 1–8192，传给 DeepSeek；关闭 thinking |
| output.directory | ./output | 相对配置文件目录；--output 覆盖它 |
| output.mode | full | raw 省略笔记；notes/full 都保留原始证据 |
| output.depth | standard | fast 不抽帧；standard/deep 场景变化抽帧 |

analyze 每次独立任务目录，不覆盖已有结果；batch --resume 会校验并复用已完成结果。
--save-audio 显式保留本地音轨，不上传音频。
使用 --transcribe 则会本地识别并保留音轨，不上传 WAV。
云端遇到无字幕音轨需要本地转录；--visual-only 明确接受缺失语音，并在输出标记限制。
当前仅 UTF-8 SRT/VTT 旁挂字幕，尚不提取内嵌字幕。

## B站下载配置

可选 `download` 依赖不影响本地流程，安装见 README。

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| download.directory | .cache/downloads | 相对配置文件目录的下载根目录 |
| download.max_height | 720 | 选择此高度以内的画质，范围 144–1080 |
| download.max_download_mb | 1024 | 视频/音频下载进度累计与最终媒体体积检查 |
| download.timeout_seconds | 600 | 下载及合并的总超时，范围 10–3600；元数据阶段至多 90 秒 |

体积进度检查可能超出一个下载缓冲块；合并/转封装的临时副本还需额外磁盘空间。
`fetch --output` 覆盖下载根目录；`analyze --output` 只覆盖 Markdown 输出根目录。
字幕语言通过 --subtitle-language 指定，或按中文、英文等优先级选择公开可用轨道。
不读取 Cookie、不保证平台字幕可匿名访问。字幕缺失不触发付费后备；本地转录需显式开启。

## 本地识别配置

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| speech.enabled | false | --transcribe 也可开启本地 CPU/int8 识别 |
| speech.prefer_subtitles | true | 有有效字幕就跳过 ASR；false 时分别保留两份 |
| speech.model_directory | .cache/models/faster-whisper-small | 相对配置文件目录；预先准备的本地模型 |
| speech.language | null | 自动检测；可指定 zh/en 等 Whisper 语言代码 |
| speech.cpu_threads | 4 | 1–32，限制 ASR 的 CPU 线程 |
| ocr.enabled | false | --ocr 也可开启关键帧中英文文字识别 |
| ocr.min_confidence | 0.5 | 0–1，低于阈值的文字行不进入证据 |

两项都不需要 Key。配置没有供应商 Key 默认值或云端回退。
prepare-speech 才会下载模型，analyze/dry-run 不自动准备。dry-run 不加载本地模型。
OCR 与 fast 组合报错。详见 [本地识别](local-recognition.md)。

## 费用

见 [providers.md](providers.md)。dry-run 按最大帧数预留，实际调用只处理抽出的帧。
每个已尝试请求的预留不会因超时/失败释放；用量未知保持 null，账单始终交由服务商确认。
费率快照过期直接阻止付费调用，避免静默使用陈旧价格；本地流程不受影响。
批次启动前对所有待执行项求和；每尝试完整上限在执行前持久化，不因重试或续跑清零。
各 worker 只获得自己那份预算；[批量与续跑规则](batch.md) 说明缓存、恢复与未知付费状态。
