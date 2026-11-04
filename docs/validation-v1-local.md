# 验证记录：0.1.0 / V1 进行中

2026-11-04，Windows，Python 3.11.9。V0 历史记录见 [validation-v0.md](validation-v0.md)。

## 当前结果

- pytest：80 passed，无跳过。包含真实 FFmpeg 媒体处理与模拟 API 契约测试。
- Ruff、格式、严格 mypy：通过；核心 18 个 Python 文件。
- FFmpeg/ffprobe 9.0.2：从 FFmpeg 下载页所链 gyan.dev 获取，校验发行方 SHA-256，
  仅解出本机 .cache/tools 中的可执行文件，没有修改系统 PATH 或提交二进制。
- Skill 已更新为本地视频与 DeepSeek 云端工作流，不声称已完成批量/平台/语音识别。
- 0.1.0 源码包与 wheel 构建成功；独立干净虚拟环境安装 wheel，从非源码目录运行
  真实六秒视频，获得字幕、三张关键帧和 Markdown/JSON，费用预留为 0。
- 源码包包含 Skill、文档、测试夹具与演示脚本；缓存、媒体、输出和私密环境文件未打包。
- 48 个待入库文件的常见凭据模式检查通过；未打印秘密值。

复现：README 中的 pytest / Ruff / mypy 命令。媒体测试优先使用环境变量/PATH，
这台开发机的测试可使用 .cache/tools。其他机器没有工具会明确 skip，不能视为媒体验收通过。
Windows asyncio 使用内部回环 socketpair；测试只为标准库构造内部通道开放该步骤，
外部连接/DNS 继续被禁止，API 使用 httpx.MockTransport，不调用真实服务。

## 已验证行为

- 视频探测、时长上限、真实场景变化帧数/时间戳、实际 16 kHz 单声道音轨。
- UTF-8 SRT 与 WebVTT，原始文本、时间戳、无效字幕拒绝。
- 免费本地完整产物、相对图片路径、字幕来源、未识别代码的明确标记。
- DeepSeek 固定域名和用户 Key、thinking 关闭、输出上限、视觉数据形状与响应结构。
- 无确认/缺 Key/预算不足/价格过期/不支持图像的模型均在请求前失败。
- HTTP 错误/重定向/超时不回显原文、不自动重试，保留可能计费的预算预留。
- 代码不完整保留识别不确定性；模型笔记必须引用存在的证据 ID。
- 截断/无效结果拒绝，未知用量为 null；回显 Key 脱敏。
- API 失败保留字幕、关键帧、失败 metadata 与费用预留。

## 实际 CLI 演示

使用 scripts/create_demo.py 生成原创六秒视频：PPT、Python 代码、图表三幕、旁挂字幕、
440 Hz 测试音。测试音不是语音；字幕是作者编写的夹具文本，不是 ASR 输出。

本机命令（设置 VIDEOMIND_FFMPEG / VIDEOMIND_FFPROBE 后）：

```powershell
.\.venv\Scripts\python.exe scripts\create_demo.py --output .cache\demo-v1
.\.venv\Scripts\python.exe -m videomind analyze .cache\demo-v1\demo.mp4 --output output\demo-v1 --save-audio
.\.venv\Scripts\python.exe -m videomind analyze .cache\demo-v1\demo.mp4 --config config.example.yaml --cloud --dry-run
```

已生成 output/demo-v1/video_eec5444583e5。验证了三张关键帧分别为 0、2、4 秒，
三条字幕保留原始时间，transcript/notes/code/evidence/metadata/images/audio 均存在。
人工查看代码帧，可见完整循环文字；未调用视觉模型，因此 code.md 没有冒充识别结果。
状态为 completed_with_limitations，离线 notes 仅为证据索引，费用预留为 0。

云端 dry-run 得到最多 13 次请求、4.1213952 USD 的保守预留（预算 5 USD），
paid_requests_sent=0，credentials=not_checked。没有读取或使用真实 API Key。

## 未完成的 V1 验收

真实 DeepSeek API 可用性/识别效果、用户实际账单、真实语音转录和授权 B站公开视频
均未验证。没有宣称完整 V1 已完成。后续需运行者在自己环境配置自己的 Key，
选定有权处理的真实样本，复核预留并明确允许实际付费调用。
用户已选择当前先使用现成字幕、不新增服务商；无字幕语音后备暂缓，长期需求保留。
平台下载先从 B站单例开始。

没有批量、缓存续跑、多平台下载、开源许可证或 GitHub/PyPI 发布。
价格快照只在核对窗口内有效，不能把模拟响应通过称为模型效果验证。
