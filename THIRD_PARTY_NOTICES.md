# 第三方材料

Engineering Flow 在 `src/engineering_flow/resources/engineer_voice/` 内置 engineer-voice 的部分原创 Markdown 材料，用于显式向宿主 Agent 提供表达规则，不包含模型运行时。

- 来源：[yanlong-l/engineer-voice](https://github.com/yanlong-l/engineer-voice)。
- 版本：v0.2.0；固定提交：`8dcf520fb3974e9711cf193ca78a9839a7fce5f0`。
- 许可：MIT，Copyright (c) 2026 yanlong-l；原始 [LICENSE](src/engineering_flow/resources/engineer_voice/LICENSE) 随源码和 wheel 保留。
- 原样收录：SKILL.md、phrases.md、examples.md、docs/regressions.md、LICENSE。manifest.json 为 Engineering Flow 的来源及逐文件 SHA-256 清单。
- examples.md 链接的 `docs/github-examples.md` 含第三方节选，未随本产品收录；不会自动访问该链接。当前本地集成使用已收录的构造样例。上游 README、横幅、安装说明和其他验收材料未收录。

`tests/fixtures/voice_regressions.json` 根据上游七组构造样例制作程序保护回归，包含明确的逐字保护事实和接受/拒绝文本；少量可接受表述为本项目的保守词序检查调整。其通过只证明这些固定文本的程序行为，不是目标 Copilot 客户端的模型行为验收，也不是自动语义等价证明。

Copilot/MCP 可选依赖采用官方 [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) 的 `mcp==2.3.0`（MIT），通过 PyPI 安装，不将 SDK 源码复制进本项目资源。安装包的 `mcp-2.3.0.dist-info/licenses/LICENSE` 保留上游许可；其传递依赖遵循各自许可。独立 CLI 不要求此依赖。本轮实际安装版本清单保存在 STATUS 指向的本地证据目录。
