# 批量处理与续跑（0.2.1）

支持本地视频、B站和抖音视频 URL 混合列表，以及官方 b23.tv / v.douyin.com 短链。
抖音媒体获取尚未实测成功；单项失败不阻止其他项。无新增云端服务商。

## 输入与基本操作

创建 UTF-8 文本，每行一项，空行和 # 开头的注释忽略。例如 videos.txt：

```text
# 相对路径以本列表所在目录为起点，不以终端目录为起点
./lesson.mp4
D:\videos\another lesson.mkv
https://www.bilibili.com/video/BV1NNNqzVEi4/
https://www.douyin.com/video/1234567890123456789
```

单批最多 500 项，列表最多 1 MiB。路径不需要包额外引号；包含空格时按整行读取。
同一本地规范路径或相同规范 URL 只处理一次；分享追踪参数移除，B站分P仍独立。
短链与指向同一视频的标准链接，在离线预检阶段无法确认彼此相同，因此不会跨形式去重。
不同路径下内容相同的文件暂不合并；不展开目录、播放列表或合集。
每个本地视频自动读取自己的同名 SRT/VTT；不支持给整个批次共用 --subtitles。

```powershell
# 离线读取列表和本地指纹，不查询平台、不下载媒体、不读 Key、不调用模型
.\.venv\Scripts\python.exe -m videomind batch videos.txt --dry-run
# 每次新建 output/batch_<id>/，单项失败后继续
.\.venv\Scripts\python.exe -m videomind batch videos.txt --output output
# 可选本地识别，需先按本地识别说明安装依赖/准备模型
.\.venv\Scripts\python.exe -m videomind batch videos.txt --transcribe --ocr --output output
```

URL 实际执行需要 download 依赖和网络；本地输入可完全离线。
`video.max_concurrent_tasks` 实际限制同时执行的视频数，默认 3，范围 1–32；
CPU、模型内存与网络会随并发增加，低资源机器可设 1。任务各自调用独立 Python 核心流程，
只有协调线程更新批次状态，避免并发覆盖清单。

输出：

```text
output/batch_<id>/
  batch_status.json      # 行号、状态、错误、尝试次数、产物指纹、累计费用预留
  batch_summary.md       # 每项来源、产物链接、最多 5 条分布式预览证据及时间戳
  .batch.lock            # 操作系统锁；进程退出后释放，文件本身可以保留
  video_<id>/            # 每项独立的 Markdown / JSON / 关键帧 / 可选 WAV
```

汇总是可追溯证据索引，未另外调用跨视频模型，不冒充跨视频综合结论。
证据预览按原始证据序列取样，覆盖首尾，但并不保证时间均匀或完整；综合分析仍应查看原始记录。
批次汇总提供每项 `uncertainties.md` 链接；每份报告归集有时间戳的待核查项和全局限制。
状态中 completed_with_limitations 表示单视频存在识别/覆盖限制；skipped 只用于重复项。
CLI 返回 0 表示没有失败项，1 表示批次有失败项，2 表示配置/预算等前置错误，130 表示中断。

## 跨视频 AI 综合

批次结束后，可对至少两个成功且有文字证据的视频单独生成跨视频报告：

```powershell
python -m videomind synthesize output\batch_<id> --config config.yaml --dry-run
python -m videomind synthesize output\batch_<id> --config config.yaml --yes-paid
```

预检不读 Key、不请求网络，显示纳入视频、排除的任务、发送内容和单次保守费用上限。
确认后使用配置中用户自己的 DeepSeek 文本 Key，发送证据文字、来源类型、时间戳、
处理限制、不确定性和可见代码，不发送完整视频、音频或图片。报告 `fusion_<id>.md` 位于批次
目录，引用逐视频证据和时间；失败、重复或无文字证据的任务会列为未纳入。
引用有效不保证模型结论正确，真实 DeepSeek 综合效果尚未验收。

综合使用配置的 `billing.max_budget_usd_per_batch` 作为**独立的综合预算**，与之前视频
分析的预算分开计算；预检显示此前综合预留和新请求预留，均为保守上限而非账单。
`synthesis_status.json` 在请求前记录预留，失败或中断也不退回。再次尝试可能收费，
需要重新预检、明确授权，并同时使用 `--yes-paid --new-attempt`；从不自动重试。
该功能单次最多发送 1 MiB 证据，超限时须缩小批次，不会静默截断。批次必须完成且
产物指纹通过校验；旧批次缺少新产物时需先按续跑规则处理。

## 续跑、缓存失效与重试

```powershell
.\.venv\Scripts\python.exe -m videomind batch videos.txt --resume output\batch_<id>
# 使用与原任务相同的 --config / --transcribe / --ocr / --cloud 等处理选项
.\.venv\Scripts\python.exe -m videomind batch videos.txt --resume output\batch_<id> --retry-failed
```

续跑不同时传 --output，也不自动重新下载已完成 URL。会校验所有已记录产物 SHA-256。
本地视频和旁挂字幕内容也参与校验；被修改或丢失时，本地免费任务新建输出重做，保留旧目录。
旧批次若缺少新加入的不确定性报告，也会被视为缓存不完整：本地免费任务重做，
云端任务按下述规则等待显式重试，绝不静默重新付费。旧目录不会自动补写。
云端结果失效、上次付费任务仍在 running 或失败时，必须显式 --retry-failed，且新付费操作
仍需符合 Key、费用确认和累计预算规则。不会自动重发可能已经计费的请求。

缓存标识包括软件版本、处理配置、模型名、已启用本地依赖版本与模型文件指纹；不包含 Key。
列表或内容处理配置改变时拒绝续跑旧批次，请新建批次。并发数、预算上限和环境变量名称
可以调整，不会因轮换 Key 而使已完成产物失效。
本地免费 interrupted 任务可自动恢复；普通失败项只有 --retry-failed 才重做。

URL 复用的是这个批次已完成的快照，不联网判断视频后来是否更改。没有跨批次全局缓存；
再次运行不带 --resume 会新建批次，云端可能再次计费。单条无效输入不保存其原始值。
状态使用原子替换；操作系统目录锁避免两个进程同时续跑同一批次。
JSON 随任务进度更新；Markdown 在开始、完成或中断时刷新，避免大批次反复读取所有证据。
Ctrl+C 会停止分派新任务，保存中断记录，并等待已经启动的操作按自身超时结束。

## 整批预算

```powershell
.\.venv\Scripts\python.exe -m videomind batch videos.txt --config config.yaml --cloud --dry-run
# 运行者接受整批保守费用和数据发送后，显式开启
.\.venv\Scripts\python.exe -m videomind batch videos.txt --config config.yaml --cloud --yes-paid
```

预检按去重后的待执行项累加每视频完整请求上限；累计超过 billing.max_budget_usd_per_batch
时，在下载、创建新批次目录和付费请求前失败。默认预算可能不足以处理多条云端视频，
可减少帧数或由运行者明确调整预算；估算方法见 [Provider 说明](providers.md)。

每项开始前，先把完整尝试上限写入 batch_status，再启动处理。每个 worker 的 API 预算
只等于分配给它的上限，不能各自消耗整个批次预算。续跑/重试时旧预留不清零，预算可明确
提高；新请求还要满足“旧预留 + 所有待执行上限 <= 批次预算”。
失败项即使在请求前失败也保留该次完整尝试预留，宁可高估；这不是实际花费或服务商账单。
已完成的云端缓存无需 Key 或有效价格即可离线阅读；一旦有新云端任务，重新执行预检。

批次汇总不产生额外模型调用；每视频可选发送关键帧和字幕/转录/OCR 文本到用户的 DeepSeek。
作者没有共享 Key、付费代理或推理后端。没有真实付费调用作为开发测试。

## 本阶段边界

已做真实本地批次和离线模拟云端验证；真实 B站批量下载成功路径仍是契约测试，单视频下载
已有实测。失败重试为显式操作，尚无自动退避和跨批次缓存；
抖音媒体获取及真实 DeepSeek 账单仍待验收。后续按计划继续。
