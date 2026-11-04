# DeepSeek 能力与费用（2026-11-04 核对）

用户选择 DeepSeek。首个实际适配器在 providers/deepseek.py，直接调用官方
https://api.deepseek.com/chat/completions，不经过作者，不读取代理环境，不跟随重定向。

在 Codex 中的默认路径为本地提取后由当前 Codex 会话模型分析，不需要本页的独立 API
配置；这不是承诺免费，实际额度取决于用户自己的 Codex 服务。VideoMind 无法从独立 API
的 `usage.md` 获取 Codex 会话 Token；直接 API 响应的用量与 Codex 会话用量必须区分。

| 模型 | 本工具接入能力 |
| --- | --- |
| deepseek-flash | 视觉 + 文本 |
| deepseek-v4-pro | 文本；视觉请求提前拒绝 |
| 其他模型/其他供应商 | 尚未实现或核验；付费路径拒绝 |

[官方模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、
[视觉输入](https://api-docs.deepseek.com/guides/vision/)、
[Chat Completions 契约](https://api-docs.deepseek.com/api/create-chat-completion/)、
[Token 说明](https://api-docs.deepseek.com/quick_start/token_usage/)。

模型能力会变化。此版本按官方当前标识接入，不把“兼容 OpenAI 格式”理解成能力一致。
DeepSeek 语音转录未接入；openai/gemini/anthropic 仅保留接口标识。
按最新要求新增可选本地 faster-whisper 语音和 RapidOCR，不新增云端服务商。
两者不需要 API Key；详见 [本地识别](local-recognition.md)。

## 价格快照与预留

按峰时、非缓存价格每百万 Token（USD）：
Flash 输入 0.30、输出 1.20；Pro 输入 1.32、输出 3.96。
代码快照核对日 2026-11-04，有效至 2026-11-11。过期后需维护者核对官方信息，
更新 billing.py 中的费率与日期并运行测试；用户不应只修改日期来绕过核验。

每请求按 1,048,576 输入 Token 的完整上下文上限，加配置的最大输出 Token 预留。
这有意高估普通请求，避免用字符近似做硬预算。关闭 thinking，显式传递输出上限。
默认 12 帧 + 1 次整理，预检最多 13 次、预留 4.1213952 USD；实际通常更低。
价格临时变化仍以提供商账单为准；该上限建立在已核对的价格/上下文契约之上。

单次运行先检查全程上限，逐请求再次扣预留。没有确认、Key、已核对能力或有效费率
就不请求；未知用量保留 null。失败/超时不释放已尝试请求的上限，不自动重试。
metadata.json 分开记录 planned_upper_usd、reserved_upper_usd 和 usage，
actual_invoice_usd 为 null，不假装算出了最终账单。

batch 对去重后的所有待执行视频求和，再加上已有尝试预留；超过整批上限则在下载前阻止。
每个 worker 只分配单项请求上限，批次状态先持久化整次尝试额度；失败不回收，续跑不清零。
批次完整尝试预留通常比各视频实际请求预留更高，不代表实际消耗；详见 [批次规则](batch.md)。

## 数据与结果

发送关键帧 PNG 和字幕/转录/OCR 等证据文字，不发送整段视频或 WAV。图片限制 8 MiB，
整理文本限制 1 MiB，不静默截断大输入。按证据 ID 引用笔记；虚构 ID、截断响应、
无效 JSON 会失败并保留原始证据。代码只保存可见识别内容及不确定性。

当前仅模拟响应契约测试通过。没有使用真实用户 Key，也没有验证真实云端识别准确度。
