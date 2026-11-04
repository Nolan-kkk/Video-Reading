# 验证记录：0.2.0 / V2 进行中

2026-11-04，Windows / Python 3.11.9。历史：
[V0](validation-v0.md)、[本地闭环](validation-v1-local.md)、
[B站获取](validation-v1-bilibili.md)、[音频/OCR](validation-v1-recognition.md)。

## 本次实现

批量 UTF-8 列表、规范化去重、单项错误隔离、有界视频并发、原子状态与操作系统锁、
指纹校验续跑、显式失败重试、整批预检与逐尝试费用预留。生成 batch_status.json 和
带来源/时间戳的 batch_summary.md。核心仍可独立运行，Skill 只调用实际 CLI。

## 自动测试与检查

- pytest：165 passed，无跳过；网络默认禁止，没有使用真实 Key 或付费 API。
- 22 项批次/持久化测试，覆盖列表相对路径、BOM、规范 URL/追踪参数、重复项、空/超大列表、
  错粘凭据不入记录、真实 FFmpeg 混合成功/失败、平台错误隔离与 B站契约路径。
- 真实本地视频结果续跑不重算；字幕变化/删除产物使缓存失效，旧目录保留；配置变化拒绝
  复用；处理期间源变化不会缓存；产物目录越界被拒绝，状态中源被篡改也拒绝续跑。
- 并发测试使用屏障确认两个真实媒体任务同时执行，且峰值严格为配置的 2。
- 付费预检超整批预算或缺 Key 时，尚无下载或新输出。任务执行前已保存完整尝试预留。
  模拟中断后不自动重发付费任务；显式重试累计旧预留，不足预算拒绝追加尝试。
- 模拟真实 HTTP 契约的 3 视频并发云端批次完成 6 个视觉/文本请求，总预留小于 2 USD；
  每 worker 获得单项上限。随后删除假 Key、令费率过期，完成缓存仍可离线复用，无新请求。
- 操作系统锁拒绝同时续跑；原子替换失败不破坏前一份状态。
- Ruff、格式、严格 mypy 与 Linux 类型分支检查通过；Linux 尚无实机运行验收。
- Skill validator 以 Python UTF-8 模式运行通过（其默认 GBK 读取无法解析 Unicode 符号）；
  未修改系统 Skill 校验器。示例配置结构检查通过。

之前的 BYOK、时间戳、字幕、预算、模型响应、OCR/ASR 真实本地测试全部保留。
0.2.0 源码包/wheel 构建成功；干净核心 wheel 从源码目录外运行真实 FFmpeg 批次与续跑通过，
不安装 speech/OCR 仍可进行基本批量处理。安装包未包含模型、媒体、缓存或私密配置。
批次 JSON 实时更新，Markdown 在开始/结束/中断时生成，避免每项状态变化重复扫描全部证据。

## 真实混合批次与续跑

本地输入为原创六秒字幕/PPT/代码演示和用户授权的 B站已下载缓存视频（32.601 秒）。
后者作为本地路径输入，本次不重新请求平台。额外加入同路径重复、缺失视频和暂不支持的
YouTube URL，故意验证跳过及错误隔离。启用本地 speech/OCR，最大并发为 2，没有云端调用。

```powershell
# FFmpeg 路径与模型准备见 README；配置/列表是本机 .cache 中的验收文件
.\.venv\Scripts\python.exe -m videomind batch .cache\batch-v2\inputs.txt --config .cache\batch-v2\settings.yaml --dry-run
.\.venv\Scripts\python.exe -m videomind batch .cache\batch-v2\inputs.txt --config .cache\batch-v2\settings.yaml
.\.venv\Scripts\python.exe -m videomind batch .cache\batch-v2\inputs.txt --config .cache\batch-v2\settings.yaml --resume output\batch-v2\batch_b49e4148da4d
```

结果目录：**output/batch-v2/batch_b49e4148da4d**。

- 2 项 completed_with_limitations，1 项重复 skipped，2 项 failed；无 pending/running。
- 失败为刻意加入的缺失本地文件与未支持平台；成功任务仍生成完整独立产物。
- 累计 API 费用预留 0；没有真实付费请求，没有重新下载用户视频。
- 演示有字幕因此不转录；缓存视频实际运行本地 ASR/OCR。生成合成演示的音轨仍是测试音，
  不把它当真实语音验收。
- 续跑预检为 cached_tasks=2、pending_tasks=0；实际续跑后两项 attempts 仍为 1，
  输出目录与产物 SHA-256 不变，没有重复识别。
- CLI 返回 1 是批次存在刻意失败项的预期行为，不表示成功任务失败。

来源与识别错误均保留；批次汇总仅为证据索引，不宣称跨视频融合或逐字准确。

## 仍待推进

自动错误分类/退避、跨批次缓存、跨视频模型总结、YouTube/抖音、真实批量平台获取、
真实 DeepSeek 语义效果/账单验收、许可证与 GitHub/PyPI 发布尚未完成。
V1 的真实云端验收门槛继续保留，不因 V2 已有功能而宣告整个项目完成。
