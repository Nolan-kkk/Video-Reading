# V0 验证记录

日期：2026-11-04（Asia/Shanghai）。环境：Windows、Python 3.11.9。
范围：V0 / 0.0.1；不是 V1 视频处理验收。

## 运行结果

| 检查 | 命令/方法 | 结果 |
| --- | --- | --- |
| 源码安装 | `.venv\Scripts\python.exe -m pip install -e ".[dev]"` | 成功 |
| 单元及 CLI 集成测试 | `.venv\Scripts\python.exe -m pytest -q` | 45 passed |
| 静态检查 | `.venv\Scripts\python.exe -m ruff check .` | 通过 |
| 格式 | `.venv\Scripts\python.exe -m ruff format --check .` | 通过 |
| 类型 | `.venv\Scripts\python.exe -m mypy` | 10 个核心文件，无问题 |
| 依赖一致性 | `.venv\Scripts\python.exe -m pip check` | 无损坏依赖 |
| 打包 | `.venv\Scripts\python.exe -m build` | sdist 与 wheel 构建成功 |
| 干净 wheel 安装 | 独立 `.cache/wheel-smoke` 虚拟环境安装构建的 wheel | 成功 |
| wheel 跨目录运行 | 在 `.cache/cli-smoke` 调用 wheel 环境的 CLI 和 Python 模块 | 成功 |
| Skill 格式 | skill-creator 的 `quick_validate.py .agents/skills/videomind` | Skill is valid |
| 需求保真 | 仓库副本与桌面原文 SHA-256 比对 | 一致 |
| Git 排除 | .venv、.cache、dist、build、config.yaml、.env、output | 均被忽略 |

当前验证依赖：Pydantic 2.14.2、PyYAML 6.0.3、pytest 9.2.0、Ruff 0.17.3、mypy 1.20.2。
项目声明兼容范围；本记录不表示每个版本组合、Linux 或 macOS 都经过运行验证。

## 行为覆盖

- 缺失/空白/占位 Key 返回安全失败，其他环境变量中的账户不能成为回退。
- 显式空环境映射不会偷偷读取进程环境。
- Key 不出现在对象显示、JSON 序列化、CLI 标准输出和错误输出。
- 参数误填 Key、YAML 语法错误、内联密钥、未知字段的诊断不回显敏感输入。
- 拒绝不安全 YAML 对象、重复字段、空 Provider、模型占位符、非法限额和共享计费模式。
- 输出路径相对配置目录，配置检查不创建输出目录。
- 证据保留时间戳、来源、不确定性；拒绝负数、倒序和无限时间戳。
- 从其他目录调用安装后的 `python -m videomind doctor`；验证 UTF-8 中文输出。
- 独立 wheel 环境中验证版本、doctor、缺 Key 退出 2、假 Key 本地检查成功，并确认导入
  来源为该环境 site-packages。没有借用 editable 包路径。

所有测试凭据均为 `test-only-*` 等假值。pytest 阻止 socket 连接/DNS；没有运行真实
付费 API 验证。构建/安装下载依赖使用网络，不等于推理调用。

打包时发现默认 sdist 遗漏 conftest 与 Skill/文档，已添加 MANIFEST.in；
源码包包含测试夹具、配置模板、需求与 Skill。wheel 只分发核心和 CLI，Skill 从源码仓库获取。

## 未验证与下一阶段

- 当前没有 FFmpeg/ffprobe，V0 不需要；V1 的真实媒体验收前须安装。
- 没有处理真实视频，没有云端适配器，未验证平台下载、转录、视觉、模型能力、价格或预算执行。
- 已验证 Skill 格式及 Codex 工具执行 CLI；尚未人工验证各目标客户端技能列表中的发现行为。
- 许可证、正式包名、真实模型与样本仍待决定；没有发布 GitHub 或 PyPI。
- 下一阶段按开发计划实现本地视频与字幕，再做音频、关键帧、带费用保护的用户 API 及输出。

