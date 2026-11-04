# 验证记录：0.1.1 / V1 进行中

2026-11-04，Windows，Python 3.11.9。历史记录：
[V0](validation-v0.md)、[V1 本地闭环](validation-v1-local.md)。

## 当前检查

- pytest：118 passed，无跳过；默认测试禁止外部网络，平台与 AI 响应均模拟。
- Ruff、格式和严格 mypy：核心 22 个文件通过。Windows 实机运行；另检查 Linux 平台类型分支，
  不把静态检查称为 Linux 运行验证。
- 新增 BV/av URL 规范化、分P/追踪参数、拒绝其他域名/账号/短链/合集、缺可选依赖测试。
- 下载 worker 不继承 AI Key、代理凭据、PYTHONPATH；关闭配置/插件/Cookie、固定输出路径。
- 无效元数据、直播/时长、语言选择、弹幕排除、下载体积累计、超时终止和安全错误验证。
- 下载成功/失败状态持久化、下载结果路径验证、平台字幕不确定性与来源链接贯穿 Markdown。
- 远程 dry-run 不下载视频、不读取 Key、不调用 AI；缺云端 Key 在下载前失败。
- 真实 FFmpeg 回归测试验证稀疏画面覆盖，避免帧数预算在开头耗尽。
- 0.1.1 源码包/wheel 构建成功；干净环境未安装下载依赖时，本地流程可用且平台入口
  正确提示缺依赖。安装 download extra 后，非源码目录的 wheel 通过隔离 worker 实际获取
  用户链接元数据，无媒体下载或 AI 请求。
- 修复隔离环境缺失 SystemDrive/ProgramData 造成 Windows 系统缓存落入工作区的问题；
  只恢复必要系统路径，仍排除凭据，并通过实际 worker 回归验证。
- 56 个待入库文件常见凭据模式检查通过；源码包和 wheel 未混入缓存、视频、输出或 .env。

之前的 BYOK、预算、代码不确定性、证据引用、时间戳、媒体处理测试均保留。
测试不直接联网获取 B站，也没有使用真实 AI Key。

## 用户链接的实际验证

用户提供 BV1NNNqzVEi4 用于实际验收。规范化后：
https://www.bilibili.com/video/BV1NNNqzVEi4/ 。分享追踪参数已移除。

使用 yt-dlp 2026.10.26、FFmpeg/ffprobe 9.0.2，未登录、未读取 Cookie。
元数据获取成功：平台时长 32.621 秒，当前公开请求没有可用独立字幕轨。
这不证明画面没有烧录文字，或登录后也没有字幕；没有把弹幕替代字幕。

实际运行（先配置本机 FFmpeg 路径）：

```powershell
.\.venv\Scripts\python.exe -m videomind analyze 'https://www.bilibili.com/video/BV1NNNqzVEi4/' --output output\bilibili-v1 --save-audio
```

下载/转封装成功，本地媒体时长 32.601 秒。初次画面变化采样集中于 0–2.8 秒，
因此修正为“画面变化 + 最小间隔 + 稀疏时间覆盖”，仍受最大帧数限制。
复用已下载媒体复验，新结果在 output/bilibili-v1/video_5ade457f119c：

- 关键帧时间：0、2.8、8.267、13.733、19.167、24.633、29.9 秒。
- 生成 transcript.md、notes.md、code.md、metadata.json、evidence.json、images/ 和 audio.wav。
- 来源 URL、视频 ID、标题、作者、缺字幕限制和媒体指纹已保留。
- 状态 completed_with_limitations；音轨仅提取，未转录；notes 仅为证据索引。
- 全程未调用真实 AI，费用预留 0。媒体只在本机缓存/输出，不纳入 Git 或安装包。

原始获取状态：.cache/downloads/bilibili_777738104af3/source.json，未保存原始 SDK 响应、
请求头或签名 CDN 地址。失败下载另有安全错误状态，用户自行管理其部分文件。

## 尚未验证或实现

有字幕的真实平台获取成功路径只有离线契约测试，仍需可公开访问字幕的实际样例。
DeepSeek 的真实识别效果、语音转录未验收；没有真实模型调用或账单验证。
用户确认当前先用现成字幕，后续可以尝试音频识别；本次没有新增语音服务商。
YouTube/抖音、批量、缓存续跑、许可证与 GitHub/PyPI 发布仍在后续阶段。
