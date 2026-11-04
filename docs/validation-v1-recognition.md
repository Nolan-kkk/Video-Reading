# 验证记录：0.1.2 / V1 进行中

2026-11-04，Windows，Python 3.11.9。历史记录：
[V0](validation-v0.md)、[V1 本地闭环](validation-v1-local.md)、
[V1 B站获取](validation-v1-bilibili.md)。

## 本次范围

新增可选 faster-whisper 本地 CPU/int8 语音识别和 RapidOCR 关键帧文字识别。
不新增云端语音供应商，不读取或使用真实 API Key；基础 Python 包不强制安装本地模型依赖。
CLI 增加 prepare-speech / analyze --transcribe / --ocr，配置、Skill、中英文说明同步更新。

## 测试与检查

- pytest：142 passed，无跳过。所有测试阻止外部 Python socket 网络；平台和 DeepSeek
  响应均为模拟。真实模型相关两项在本机实际运行；其他环境缺可选依赖/预备模型会明确跳过，
  测试不会自动联网下载。
- 真实 RapidOCR 用原创合成英文图片验证识别文字、置信度和坐标；真实 small ASR 验证
  两秒测试音不产生转录。这项测试音测试不是语音准确率验收。
- ASR 单元测试验证本地文件限定、CPU/int8、时间段及异常迭代安全失败；缺模型不触发下载。
- 模型准备契约测试验证匿名 token=False、固定 revision、限定文件与 SHA-256 清单。
- 流水线验证字幕优先、转录自动保存 WAV、无识别文本阻止云端付费、失败保留原始帧，
  部分 OCR 失败仍保留已转录语音和前一帧文字。
- 模拟多模态云端链路验证 transcription/ocr 原文实际进入 DeepSeek 整理请求，保留来源。
- 严格配置验证拒绝错误布尔值、越界线程/置信度、NaN 和不合法语言格式；模型路径相对配置。
- Ruff、格式、严格 mypy 通过；Linux 类型分支检查通过，不冒充 Linux 实机运行。
- Skill quick_validate 与示例配置结构验证通过。
- 0.1.2 源码包/wheel 构建成功；安装包内容检查排除媒体、模型、缓存、私密配置和输出。
- 干净虚拟环境只安装核心 wheel，从源码目录外执行真实 FFmpeg 本地流程成功；
  未安装 speech/OCR 时对应入口返回清晰缺依赖提示，不创建失败输出目录。

## 真实音频与画面验证

复用用户先前授权的 B站 BV1NNNqzVEi4 已下载媒体，没有再次下载视频。
平台公开请求无独立字幕，实际媒体 32.601 秒。使用：

```powershell
# 先按 README 设置本机 FFmpeg/ffprobe 路径
.\.venv\Scripts\python.exe -m videomind prepare-speech
.\.venv\Scripts\python.exe -m videomind analyze .cache\downloads\bilibili_777738104af3\source.mkv --transcribe --ocr --output output\audio-ocr-v1
```

模型准备从公共 Systran/faster-whisper-small 匿名下载，revision：
536b0662742c02347bc0e980a01041f333bce120。model.bin SHA-256：
3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671。
安装 faster-whisper 1.2.1 / CTranslate2 4.8.5 / RapidOCR 3.10.0 / ONNX Runtime 1.31.1。

首次 CLI 输出在 output/audio-ocr-v1/video_c4c82ec9b5c9。
随后通过 Python 核心传入已保存的 AcquiredVideo 来源信息，并阻止外部 Python socket 连接，
再次运行真实模型；最终输出在 **output/audio-image-v1/video_c5ad2fb15f0c**：

- 转录 17 个语音时间段，自动检测中文；CPU/int8、4 线程。
- 7 张关键帧均有 OCR，含《龙族》、江南著和部分中英烧录字幕。
- 帧时间 0、2.8、8.267、13.733、19.167、24.633、29.9 秒；不保证覆盖每句烧录字幕。
- transcript.md、evidence.json、metadata.json、notes.md、code.md、images/、audio.wav 均已生成。
- 保留 B站规范化 URL、视频 ID、作者、标题、媒体指纹、本地模型指纹、OCR 几何/置信度。
- 运行约 9.8 秒，仅代表本机这段样例；未执行云端请求，API 费用预留 0。
- 状态 completed_with_limitations：本地自动识别存在错误，notes 只是证据索引，图像语义
  与代码结构尚未通过真实云端模型验证。

已见误听：“龙族”识别为“龙祖”，“人流如织”识别为“人流如汁”；简繁字混用。
OCR 的书名可供对照，但未覆盖改写原始语音。没有逐字人工真值，不宣称 WER/CER 或通用准确率。
缓存、模型和用户视频仅在本机，不纳入 Git 或 VideoMind 安装包。

## 后续范围

DeepSeek 真实图像语义理解和整理效果仍未验收；未使用真实 Key 或核对账单。
有字幕的真实平台获取成功路径仍只有离线契约测试。内嵌字幕、YouTube/抖音、批量、
缓存续跑、许可证选择和 GitHub/PyPI 发布按后续阶段推进；不宣布整个 V1 已全部完成。
