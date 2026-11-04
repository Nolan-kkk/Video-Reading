# 本地语音与画面文字识别（自 0.1.2 支持）

`doctor` 可离线显示 FFmpeg、可选依赖、语音模型文件和 OCR 模型文件的就绪情况，
以及价格快照是否过期；`doctor --config config.yaml` 检查配置指定的语音模型目录。
检查不加载模型或读取 API Key，也不保证模型文件完整正确。

本地语音模型提供片段平均对数概率时，低于 -1.0 的片段会在 `uncertainties.md` 中
提示优先回听并显示分数；原文不会更改。这是模型分数而非准确率，也不能检出所有错误。

这一步按最新需求增加可选本地识别，没有新增云端语音供应商。Python 核心可独立运行。
本地识别不需要任何 API Key；显式开启 `--cloud` 后，识别文字才随其他证据发往 DeepSeek。

如需尝试更大模型，可显式执行 `python -m videomind prepare-speech --size medium`，
随后将配置中的 `speech.model_directory` 指向 `.cache/models/faster-whisper-medium`
（相对配置文件目录）。该公开模型约 1.53 GB，CPU 运行可能更慢、占用更多内存；
不会自动下载，也不能保证在所有视频上优于 small。尚未进行 medium 与 small 的真实样例对比。
参考 [模型文件大小](https://huggingface.co/Systran/faster-whisper-medium/tree/main)。

## 安装和运行

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,speech,ocr]"
.\.venv\Scripts\python.exe -m videomind prepare-speech
.\.venv\Scripts\python.exe -m videomind analyze 'D:\videos\lesson.mp4' --transcribe --ocr --output output
```

仍需 FFmpeg/ffprobe。源代码安装用上述命令；发布包安装时可用 `pip install "videomind[speech,ocr]"`。
当前尚未发布到 PyPI。CPU/int8 不需要 CUDA，较长视频耗时取决于机器性能。

`prepare-speech` 从公开 `Systran/faster-whisper-small` 仓库匿名下载，显式 `token=False`，
不使用 Hugging Face 登录 Token。按获取时的提交版本固定文件，保存 revision 和 SHA-256 清单
到模型目录的 videomind-model.json。small 模型文件合计约 486 MB，下载需要额外临时空间。
网络失败时可重新执行准备命令；分析入口本身不联网补齐模型。

支持 `--size tiny/base/small`；small 默认用于多语言。其他大小或自备转换模型需在配置中
指定对应 `speech.model_directory`。可用 `prepare-speech --directory <目录>` 改下载位置。
必须同时有 config.json、model.bin、tokenizer.json 和 vocabulary.txt/json，避免缺 tokenizer
时第三方库自动寻找远程资源。依赖中自带 VAD 模型。

OCR 使用 RapidOCR 3.10 自带的 PP-OCRv6 检测/识别和方向分类 ONNX 模型，显式指定本地
文件，禁用其自动模型下载分支，不调用会下载字体的可视化方法。依赖安装本身需联网。
模型和依赖有各自许可证，不会被打入 VideoMind 的源码包或 wheel。

## 执行规则与输出

- `--transcribe` 或 `speech.enabled: true` 开启转录；默认有有效字幕就直接使用字幕。
  `speech.prefer_subtitles: false` 会同时保留字幕和转录，不互相覆盖。
- 无音轨会跳过转录并标记；识别无文本会标记不确定性。无字幕且转录无文本时，云端请求
  默认停止；`--visual-only` 是明确接受缺失语音的选项。
- `--ocr` 或 `ocr.enabled: true` 开启文字识别；fast 没有帧，因此拒绝该组合。
  OCR 只处理采样帧，不能保证捕获所有烧录字幕或每页 PPT。
- transcript.md 和 evidence.json 分别记录 transcription / ocr / subtitle / vision / frame。
  OCR 保留每行置信度和四点坐标（以导出 PNG 的像素为单位），不伪装成完整字幕轨。
- 转录保留 audio.wav；metadata 的 local_recognition 记录执行/跳过/失败状态、模型引擎、
  音频模型指纹、语言、CPU 线程、段数和 OCR 阈值。失败保留已有证据和关键帧。
- 本地 OCR 不推断画面事件、图表含义或代码语言/结构，code.md 不把普通 OCR 字符串
  冒充可运行代码。图像语义、代码结构和整理笔记继续使用可选 DeepSeek BYOK 路径。

## 实测效果与边界

2026-11-04，在 Windows / Python 3.11.9，复用用户授权的 BV1NNNqzVEi4 已下载文件。
没有独立字幕轨；视频 32.601 秒。small + CPU/int8、4 线程自动识别为中文，转录 17 段；
7 张关键帧均有 OCR 文字，包含《龙族》、江南著及部分中英烧录字幕。没有付费请求。

识别出现“龙族→龙祖”“人流如织→人流如汁”等疑似误听，简繁字也有混用。
OCR 可能识别到水印和重复书名，置信度不是准确率保证。原始层保留这些结果，不用标题或
OCR 静默修正语音。尚无人工逐字标注，未计算 WER/CER，也不据一个样例保证通用准确率。

离线回归使用合成文字图片验证真实 OCR；真实语音模型也验证了测试音不产生转录。
其他测试模拟 SDK 响应验证时间戳、失败、字幕优先和证据串联。没有真实 DeepSeek API 验证。

实现与使用依据：[faster-whisper 官方仓库](https://github.com/SYSTRAN/faster-whisper)、
[RapidOCR 使用文档](https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/usage/)、
[RapidOCR 模型许可](https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/)。
