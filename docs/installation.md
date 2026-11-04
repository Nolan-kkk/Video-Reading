# 安装与 Codex 接入

Python 3.11+：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m videomind doctor
```

Windows PowerShell 不需激活环境；Linux/macOS 使用 .venv/bin/python。
运行本地媒体还需要 FFmpeg 和 ffprobe；基础提取不需要 NVIDIA、CUDA 或本地模型。

从 [FFmpeg 下载页](https://ffmpeg.org/download.html)选择平台发行。
Windows 可使用其链接的 [gyan.dev 构建](https://www.gyan.dev/ffmpeg/builds/)，
核对 SHA-256 后解压，将 bin 加入 PATH，或显式设置：

```powershell
$env:VIDEOMIND_FFMPEG = 'D:\tools\ffmpeg\bin\ffmpeg.exe'
$env:VIDEOMIND_FFPROBE = 'D:\tools\ffmpeg\bin\ffprobe.exe'
```

这些变量只用于寻找可执行程序。程序不会自动下载外部工具。
本次开发本机 .cache/tools 里已有校验过的 FFmpeg 9.0.2，不会提交到仓库。
安装依赖或工具需要联网；本地提取和默认测试不需要外部网络。

B站获取额外需要 yt-dlp，可安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,download]"
```

未安装可选 download 依赖时，本地处理仍可运行；B站入口返回清晰安装提示。
当前验证版本为 yt-dlp 2026.10.26。平台变化可能需要在已声明兼容范围内更新依赖。
下载 worker 不读取 yt-dlp 配置/插件或浏览器登录信息。

本地识别可选安装 `pip install -e ".[dev,speech,ocr]"`，随后运行
`python -m videomind prepare-speech` 显式下载 small 模型。使用 `analyze <视频>
--transcribe --ocr`。不需要 Key 或 CUDA，也不会自动调用云端。
完整步骤和模型准备边界见 [本地识别](local-recognition.md)。

## Skill

仓库包含 .agents/skills/videomind/SKILL.md，按
[官方 Skill 文档](https://learn.chatgpt.com/docs/build-skills)（2026-11-04 核对）
放在仓库发现目录。使用 $videomind，或把整个技能目录复制到目标仓库的 .agents/skills。
如果客户端没有刷新，重启后检查技能列表。Python 包仍须单独安装。

示例请求：
“使用 $videomind 离线读取我提供的本地视频和字幕，生成带时间戳的 Markdown。”
多视频可用 batch UTF-8 列表入口，核心独立运行，不依赖额外调度服务；见 [批次说明](batch.md)。

Skill 默认离线；用户明确要求云端时先做 dry-run，说明费用预留和数据发送。
不要为了开发测试自动读取或使用任何真实 Key。真实付费执行需要运行者自己的账户及授权。
静态格式验证和 CLI 测试不等于所有客户端的发现 UI 都已经人工验收。
