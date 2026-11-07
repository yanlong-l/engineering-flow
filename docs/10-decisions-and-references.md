# 决定、待定事项与参考来源

整理日期：2026-11-07。产品要求来自与用户的讨论；外部能力来自官方文档。官方资料会变化，开发时以目标客户端的实际版本和策略重新验证。

## 已确认的名称与产品要求

| 事项 | 内容 |
| --- | --- |
| 产品名 | Engineering Flow |
| 仓库名 | 用户已确认在 GitHub 创建 `engineering-flow`；完整远程地址和本地关联状态待开发时核对 |
| 用户方向 | 工程师与 GitHub Copilot 的高质量产出和协作 |
| 范围 | 开发、代码 Review、文档、长期记忆和维护 |
| 页面 | 希望帮助工程师理解 AI 参与生成的代码 |
| 定制 | 支持个人工作流和可插拔选项 |
| 产品形态偏好 | 更完整的 Agent 或产品体验，减少挑选 Skills 的负担 |
| 现有模块 | 希望嵌入 engineer-voice |
| 开发组织 | 按 M0–M5 推进；最新进度与下一会话目标维护在 `STATUS.md` |

用户允许在合适情况下使用 Skill，但不希望产品停留在单个 Skill 或大量 Skills 的手工组合。

## 架构建议，尚未实际验证

| 编号 | 建议 | 原因 |
| --- | --- | --- |
| D-01 | Agent Plugin 组织分发 | 可以将相关组件一并安装 |
| D-02 | 单一主 Agent | 用户操作简单，内部按阶段选择模块 |
| D-03 | 独立本地 Core | 统一状态和记录，便于 CLI/MCP 共用 |
| D-04 | TypeScript + Node.js 优先评估 | 便于接口、工具及 VS Code 相关集成 |
| D-05 | 可读文件与 SQLite 在 M0 比较 | 保留可读性，同时衡量并发、跨记录一致性和锁管理成本；尚未采用 |
| D-06 | 固定模板本地页面起步 | 尽快验证 Review 的实际帮助 |
| D-07 | 相关检索和来源记录先行 | 无需先建设大规模知识库 |
| D-08 | Hooks 可用则增强，显式操作保留 | 避免宿主能力差异阻断主流程 |
| D-09 | 暂不另建模型后端 | 沿用已有 Copilot，集中投入协作能力 |

上述建议不是用户已逐项批准的实现合同。后续可合理调整，保留变更原因和验证依据。

## 开发初期需要确定

| 事项 | 当前建议或验证方式 |
| --- | --- |
| 实际 IDE 与 Copilot 版本 | 本机 VS Code 1.137.0、内置 Copilot Chat 0.65.0；已验证 Copilot SDK 会话，见环境记录 |
| 公司是否允许插件、MCP、Hooks | 用户确认允许本地插件、本地工具和 MCP；Hooks 尚未实测 |
| 首个试点项目和语言 | 用户已确定 Python，自行编写示例项目 |
| Core 语言和存储 | M0 后根据维护成本确定 |
| 安装包格式和运行依赖 | 按官方格式和目标客户端实际加载结果选择 |
| 页面交互 | 首版静态展示；需要写入时选 CLI、本地服务或 Webview |
| 人工确认与团队共享 | 首版显式本地操作；团队协作与 PR 结合 |
| 许可与发布范围 | 尚未指定，不默认设定开源许可或发布可见性 |
| engineer-voice 的集成版本 | 实现时固定版本并保留其许可和归属 |
| 收集指标的方式 | 试点前明确采集范围，默认本地记录 |

技术选择不能阻止已有信息足够的独立工作；真正依赖宿主能力的实现先验证再承诺。

## 官方资料

以下能力说明用于架构判断。本机已验证的宿主组合见[环境记录](11-environment-readiness.md)；未验证组合仍需实际核对。

| 来源 | 与本项目的关系 |
| --- | --- |
| [Agent Plugins](https://code.visualstudio.com/docs/agent-customization/agent-plugins) | 将 Agent、Skills 和工具等组件组织安装；检查具体格式和宿主支持 |
| [Plugin 编写参考](https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference) | manifest、组件目录及客户端专属配置的实际依据 |
| [Custom Agents](https://code.visualstudio.com/docs/agent-customization/custom-agents) | 角色、工具和指令配置；自身不等于完整持久化产品 |
| [Hooks](https://code.visualstudio.com/docs/agent-customization/hooks) | 候选自动触发机制；需验证预览状态、事件及执行行为 |
| [Copilot MCP 集成](https://docs.github.com/en/copilot/how-tos/copilot-in-your-ide/customize-copilot/extend-copilot-with-tools-and-context/extend-copilot-chat-with-mcp) | Core 工具接入 Copilot 的候选方式，受实际策略影响 |
| [MCP 架构](https://modelcontextprotocol.io/docs/learn/architecture) | 工具与上下文交换的协议概念；不自动提供本项目状态逻辑 |
| [Copilot Memory](https://docs.github.com/en/copilot/concepts/prompting-and-context/copilot-memory) | 可用时辅助协作，不替代本项目可审阅的长期记录 |
| [Copilot Code Review](https://docs.github.com/en/copilot/concepts/agent-capabilities/agent-powered-workflows-and-operations/code-review) | 评审建议仍需验证并结合人工判断 |
| [VS Code 扩展能力](https://code.visualstudio.com/api/extension-capabilities/overview) | 后期 IDE 内页面与交互的候选能力 |

## engineer-voice 来源

- [仓库与 README](https://github.com/yanlong-l/engineer-voice)
- [Skill 定义](https://github.com/yanlong-l/engineer-voice/blob/main/SKILL.md)
- [语义回归样例](https://github.com/yanlong-l/engineer-voice/blob/main/docs/regressions.md)

前期讨论中已阅读上述说明与样例，确认其涉及表达改写、技术语义保留及反例验收。存在样例不等于在目标客户端上已通过验收；Engineering Flow 集成时需要记录真实运行结果。

## 后续决定记录

### 2026-11-07：试点环境与本机可用组合

- 状态：用户已确定试点语言与环境；本机最小集成已验证。
- 选择：VS Code + GitHub Copilot，Python 自建示例；现阶段以通过验证的 Copilot SDK 会话目标作为本机集成路径。
- 依据：本地插件注册、自定义 Agent 选择、MCP 服务端回执与 Copilot 返回匹配、实际 Python 终端输出均已观察到。
- 限制：Local 会话存在 `Language model unavailable`；Hooks、正式安装包、升级和其他电脑未验证。Python 是试点语言，Core 语言仍未最终确定。
- 结果：[本机开发环境验证](11-environment-readiness.md)。

### 2026-11-07：开源复用候选与实施顺序

- 状态：调研建议，未安装新产品依赖，也未确定 Core 语言或存储。
- 建议：优先复用官方 MCP SDK；TypeScript 路线评估 Commander、Zod、Execa；Review 比较 diff2html 与 Pierre Diffs；需求模板、插件示例和诊断格式按需参考。快照适用性、来源、人工确认和记忆有效性保留在自己的 Core。
- 重要发现：MCP TypeScript SDK v2 的包名和许可说明与旧版本不同；write-file-atomic 8.0.0 的 Node 声明不包含本机已验证的 24.14.0。文件方案需与 SQLite 比较，不能将原子替换视为完整并发控制。
- 依据与限制：核对 20 个仓库的元数据、发布、默认分支提交和许可证，并阅读重点接口及测试配置；不等于本项目兼容性验收。此前 Python SDK 2.3.0 探针结果沿用环境记录。
- 结果：[开源项目复用调研](12-open-source-reuse-research.md)。仍按原定 M0 剩余准备与 M1-1 进入开发。

后续重要决定可采用以下格式：

```text
日期：
事项：
状态：候选 / 已采用 / 已替代
选择：
原因与适用范围：
实际验证：
相关代码、文档或结果：
```

少量重要决定在本文件追加；复杂设计需要时再拆独立文档，避免为每个日常细节创建大量记录。
