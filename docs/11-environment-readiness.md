# 本机开发环境验证

验证日期：2026-11-07。范围为当前 macOS 机器和实际打开的 VS Code；不外推到其他电脑或客户端。

## 结论

当前环境具备开始 Engineering Flow Core 和 Python 示例项目开发的条件。已跑通：本地插件加载 → 选择自定义 Agent → Copilot 实际调用本地 MCP 工具 → 执行 Python 终端命令。

本次通过的会话目标为 VS Code 中的 **Copilot**，即 Copilot SDK 本地运行方式。另一种 **Local** 会话返回了 `Language model unavailable`，该路径尚未解决，不列为已验证组合。

这次只完成环境检查和最小集成探针，不表示产品运行时、Review 页面、长期记忆或正式安装包已经实现，也不表示 M0 的全部技术选型已经完成。

## 用户确认的信息

- 已购买 GitHub Copilot Pro，并在网站及 VS Code 中登录。
- 公司环境允许本地 Agent Plugin、本地工具与 MCP。
- 首个试点采用 Python，先自行编写示例项目。

订阅名称和公司政策来自用户确认。本次另外在 VS Code 界面观察到了 GitHub 登录账号，并以真实 Copilot 请求验证了可用调用路径；未读取付款资料或认证凭据。

## 实际观察到的版本

| 组件 | 版本或状态 |
| --- | --- |
| 系统 | macOS / Apple Silicon，`Darwin arm64` |
| Git | 2.49.0 |
| Node.js | 24.14.0 |
| npm | 11.9.0 |
| Python | 3.14.3 |
| 系统 pip | 26.0 |
| VS Code | 1.137.0 |
| VS Code 内置 Copilot Chat | 0.65.0 |
| 临时虚拟环境 pytest | 9.2.0 |
| 临时虚拟环境 MCP Python SDK | 2.3.0 |

Copilot Chat 本机位于 VS Code 应用的内置扩展目录。此前默认扩展列表没有单独的安装条目，不能据此判断 Copilot 未安装。

## 已运行的验证

| 项目 | 实际操作和证据 | 结果 |
| --- | --- | --- |
| Python 隔离环境 | 创建临时 venv，从 PyPI 安装固定版本 pytest 和 MCP SDK | 通过 |
| Python 检查 | 实际运行 3 项 pytest 检查：虚拟环境与版本、子进程成功输出、子进程非零退出与 stderr | `3 passed in 0.08s` |
| 依赖完整性 | 虚拟环境中执行 `python -m pip check` | `No broken requirements found.` |
| Git 能力 | 临时仓库创建提交和第二个 worktree；修改文件后核对 HEAD 未变且工作区能识别修改 | 通过 |
| 本机回环访问 | 在 `127.0.0.1` 临时端口启动 HTTP 服务并请求 | HTTP 200，返回 `EF_LOOPBACK_OK`；服务随后关闭 |
| 下载连接 | 请求 PyPI、npm registry、GitHub API；另执行 `npm view typescript version` | 均成功；不表示所有未来依赖都已验证 |
| 本地插件 | 经 VS Code 的 Install Plugin from Source 注册探针 | Plugins 显示已安装、启用，并列出 1 个 Agent、1 个 MCP 服务 |
| 自定义 Agent | 在会话选择 `EF Environment Probe` | 通过 |
| 独立 MCP 通信 | Python SDK 客户端完成 initialize、tools/list、tools/call | 通过，协商协议 `2025-11-25` |
| Copilot 调用 MCP | Copilot 会话实际调用 `ef_probe_echo`，与服务端独立写入的回执核对 | 通过 |
| Copilot 终端工具 | 实际执行 Python 打印命令，并展开终端工具输出核对 | 输出 `EF_COPILOT_TERMINAL_OK` |

Copilot 运行时保持 Auto 模型选择，本次界面显示路由到 Claude Sonnet 5.5；这只是本次运行信息，不作为产品绑定模型。

## MCP 调用的交叉核对

测试工具只处理本次验证字符串，并向自己的证据文件写入回执。

- 调用参数 nonce：`vscode-copilot-b6d42e7c`。
- 调用参数 message：`environment-ready`。
- 服务端实际生成的 receipt：`aaf6431d2cbba2fe`。
- 服务进程 Python：3.14.3；进程 ID：55792。
- 服务端时间：`2026-11-07T06:31:34.743393+00:00`。

Copilot 返回内容与服务端写入记录一致。该结果的依据包含真实服务执行记录，不只使用模型的“成功”文字。终端输出另在 VS Code 的实际工具输出区域目视核对。

## 遇到的问题和处理

1. **Python MCP SDK 接口版本变化。** 初版探针使用 1.x 风格的 `FastMCP` 导入及部分字段，实际安装的是 2.3.0，导致失败。改用本机 SDK 提供的 `MCPServer` 和 snake_case 字段后，独立客户端与 Copilot 调用均通过。后续按锁定版本实现，不直接套用旧示例。
2. **本地插件注册的设置范围。** 本机 `chat.pluginLocations` 只允许写入 User settings。工作区设置导致 VS Code 报错；移除工作区中的该配置，再经官方来源安装入口注册后成功。该过程实际验证的是本地目录注册，正式分发安装与升级另行验收。
3. **临时目录的受限模式。** `/tmp` 对应的临时工作区处于 Restricted Mode。改用已有受信任的 `~/projects` 下的隔离目录继续验证，未修改工作区信任列表。
4. **Local 会话模型不可用。** Local 会话返回 `Language model unavailable`。新建会话并选择 Copilot 目标后成功执行工具。现阶段采用已通过的组合，Local 的根因仍待诊断，不据此推断用户订阅无效。

插件探针按 [VS Code 插件参考](https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference) 的 Agent Plugins 1.0 结构组织；会话与 MCP 配置按 [VS Code MCP 说明](https://code.visualstudio.com/docs/agent-customization/mcp-servers) 核对。上述支持最终以本次实际执行结果为准。

## 记录与清理

- 可检查的本地证据保留在 `.local/environment-check/evidence/`，包含运行摘要、MCP 回执、Git/回环检查结果、安装包版本和探针源文件指纹。
- 探针源文件保留在 `.local/environment-check/probe-source/`，仅用于复核；其中路径与本次临时环境绑定，不是产品安装命令。
- 本次虚拟环境位于系统临时目录，未向系统 Python 安装这些依赖。
- 探针已通过 VS Code 界面卸载，插件数量恢复为 0。
- MCP 调用仅允许一次，终端命令按单次请求允许；没有开启全自动审批或外部机器访问。
- `.local/` 已加入 `.gitignore`。没有复制全部 Copilot 对话、环境变量、账号令牌或公司源码。

## 开发时继续处理

- 初始化产品仓库和工程结构，决定 Core 的实现语言、依赖与存储。
- Python 是已确定的试点语言；Core 是否采用 TypeScript / Node.js 仍需完成选型。
- 编写不依赖真实设备或公司数据的 Python 示例项目，围绕批量任务的重复请求行为验证完整流程。
- 本机 Hooks 的事件、载荷和失败处理尚未实际验证；显式保存、检查、生成 Review 和恢复路径仍作为基础要求。
- 正式插件安装包、升级、干净环境安装和其他电脑尚未验证。
