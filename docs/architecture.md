# 架构（0.2.1 / V2 进行中）

Codex Skill → CLI → 独立 Python 核心：
可选批次列表 → 规范化去重 / 状态 / 有界并发 / 校验续跑 → 单视频流程：
本地文件 / B站或抖音公开获取 → 本地探测 → 字幕 / 可选本地转录 → 场景帧 / 可选 OCR → 可选 DeepSeek 视觉 → 时间线证据 →
可选 DeepSeek 文本整理 → Markdown / JSON / 图片。

- config.py / security.py：严格无内联密钥配置，只解析用户指定环境变量；不读取 Codex 认证。
- extractors/base.py：过滤后的公开来源信息与本地视频/字幕位置。
- extractors/bilibili.py：URL 规范化、时长和语言预检、隔离进程、超时终止进程树、获取状态。
- extractors/sources.py：B站/抖音来源路由和官方短链解析；严格限制重定向目标。
- extractors/worker.py：可选 yt-dlp，固定下载路径；屏蔽日志与插件/配置/浏览器 Cookie，
  不继承 AI Key 或代理登录信息，限制单个分P、分辨率、下载体积和重试。
- processors/media.py：本地 FFmpeg/ffprobe 子进程，参数数组、不使用 shell、限制协议和超时。
- processors/subtitles.py：UTF-8 SRT/VTT 原始时间戳和文本。
- processors/speech.py：可选 faster-whisper CPU/int8、本地文件限定、VAD、字幕优先；
  prepare-speech 独立匿名下载公共模型，固定 revision 并保存文件指纹。
- processors/ocr.py：可选 RapidOCR/ONNX CPU，显式使用随依赖安装的模型，保留文字框/置信度。
- models/schemas.py：subtitle/transcription/ocr/vision/frame 来源、代码、不确定性。
  frame 只代表图片已提取；OCR 只代表文字识别；transcription 独立于原始字幕。
- providers/base.py：独立的三类模态接口；DeepSeek 实现其中 vision/text。
- billing.py：已核对能力、有效价格、整次预检、逐请求预算预留、显式授权。
- providers/deepseek.py：固定官方域名，禁重定向，关闭环境代理，无自动重试；严格响应结构及引用。
- pipeline.py：单视频编排；先保存原始证据，失败保留状态；每次独立目录，不覆盖/不复用缓存。
- batch.py：列表与来源规范化、单项隔离、线程池并发、整批成本预检、逐尝试预留日志、
  源文件/模型/产物指纹校验与显式失败重试；复用仅限 --resume 指定批次。
- persistence.py：UTF-8 原子替换、fsync、操作系统文件锁；进程退出后释放锁。
- exporters/markdown.py：transcript、code、notes、metadata、evidence；保留原始层，代码不静默补全。
- scripts/create_demo.py：原创合成夹具，不下载第三方视频，不调用模型。

所有付费调用从运行者本机直达所选服务商；没有作者服务端、共享 Key、遥测或账户回退。
必要的图像与文字会发送给 DeepSeek；输出默认保存在本地。详见 SECURITY.md。

每视频内部串行；批次限制同时执行的视频数。协调线程更新状态，worker 使用各自分配的费用上限。
平台获取使用网络，本地 FFmpeg 仍限制 file/pipe 协议。
同背景的小变化或短暂画面可能漏检；抖音实际媒体获取尚未通过在线验收。
内嵌字幕、自动退避、跨批次缓存尚未实现。
费用是基于有效价格的保守预留，不是全账户账单限制；重复运行可能再次计费。
