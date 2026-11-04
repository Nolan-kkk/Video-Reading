# 参与开发

项目当前推进 V2；请先阅读原始需求与 [分阶段计划](docs/development-plan.md)。
项目采用 [Apache-2.0 许可证](LICENSE)；请确保你有权按该许可证提交贡献。

Python 3.11+：创建 `.venv` 后 `python -m pip install -e ".[dev]"`。
Windows 可直接使用 `.venv\Scripts\python.exe`，无需激活环境。

提交前运行：

```text
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy
```

测试必须离线可运行，不得使用真实凭据。新 Provider 应有能力契约、成本/使用量记录、
安全错误与请求前费用保护，并使用假响应测试。真实付费验证必须由运行者显式开启，
配置自己的 Key 和预算；不能放进默认测试或 CI。

本地媒体测试需要 FFmpeg/ffprobe，未安装会明确跳过；提交媒体处理变更时应安装并确认
对应集成测试实际运行。当前离线测试固定价格核对日期，防止费率自然过期破坏契约测试；
真实执行仍使用系统日期并拒绝过期快照。Pillow 用于原创演示和测试图片，不是核心运行依赖。

仓库内提供 Windows/Linux 的 GitHub Actions 检查配置。它安装 FFmpeg、OCR 和语音依赖，
显式匿名准备约 76 MB 的 tiny 模型，并用 `python scripts/run_ci_tests.py` 运行全部测试；
只要有测试跳过，CI 就失败。模型与依赖下载使用网络和 CI 运行资源，不调用 AI API，
也不配置任何用户或作者 Key。随后运行格式、类型与源码包构建。
Workflow 尚未在 GitHub 上执行；需仓库发布后实际观察两个系统的结果。
本地复现可设 `VIDEOMIND_TEST_SPEECH_MODEL` 指向已准备的 tiny 或 small 模型目录；
默认普通 pytest 允许缺可选依赖时显示跳过，以便只安装核心的贡献者运行其他测试。

提供可重现步骤与脱敏输入。不要附真实 Key、cookies、私有视频、用户输出或账户日志。
遵守阶段边界，不把尚未实现的命令写成已可用。每阶段记录测试结果与未验证部分。

