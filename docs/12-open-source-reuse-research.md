# 开源项目复用调研与实施建议

调研日期：2026-11-07。状态：开发前候选分析，尚未安装或采用这些产品依赖。Core 语言、存储和页面组件仍需在对应阶段通过小规模验证后确定；Python 已确定为试点语言，不自动决定 Core 语言。

## 结论

Engineering Flow 可以复用成熟开源组件完成协议接入、命令行、运行时数据校验、进程执行、持久化基础和代码差异展示。最值得投入自研的是把这些组件连成可信的协作流程：哪些代码被检查过、结果何时过期、改动从哪里来、哪些解释经过人工确认，以及新会话应恢复什么。

建议采用“少量基础依赖 + 自己的 Core + 部分流程模板”的组合。当前未发现一个已核对项目可以直接覆盖我们的可信度要求；也没有必要先搭建一个新的自主编码 Agent 或模型服务。

优先级如下：

| 处理方式 | 建议 |
| --- | --- |
| 优先验证后采用 | 官方 MCP SDK；若选 TypeScript，再采用 Commander、Zod，检查执行阶段评估 Execa |
| 在两种方案中选择 | 文件持久化与 SQLite；静态 diff2html 与交互较丰富的 Pierre Diffs |
| 借鉴设计和局部材料 | Spec Kit、OpenSpec、Awesome Copilot、Cline checkpoints、reviewdog 的诊断格式 |
| 用作开发验证 | fast-check、Playwright、pytest；FastAPI 仅按 Python 示例需求引入 |
| 首版暂缓 | Mem0 作为记忆运行时、完整替换 Copilot 的 Agent 框架、同时安装多个流程工具 |

“优先”是建议顺序，不代表兼容性或产品验收已经完成。本文不据 Star 数、上游性能宣传或模型自评估算本项目节省工期。

## 调研范围与证据等级

本次通过 GitHub 连接读取 20 个公开仓库的元数据、默认分支提交和 Release，并核对许可证；对重点候选阅读相关接口、模板、文档和 CI 配置。当前这 20 个仓库均未被标记为归档，但维护强度有明显差异。

- **上游事实**：仓库文件和发布信息能够支持的功能、接口、许可、测试配置。
- **本项目判断**：适合哪项需求、引入成本和建议时机，是基于现有规划的分析。
- **本机已验证**：此前 Python MCP SDK 2.3.0 与 pytest 9.2.0 的环境及最小调用，见[环境记录](11-environment-readiness.md)。这不是正式产品集成测试。
- **仍未验证**：本文其他候选在 Engineering Flow 中的安装、打包、异常恢复和端到端效果。本轮没有安装新依赖，也没有运行这些项目的完整测试或进行完整安全审计。

下文源码链接固定到本次观察的提交，便于复核。Release 与默认分支可能不同；实际安装必须选定明确版本并锁定依赖，不能把默认分支的说明直接视为发布包行为。

## 1. 需求、设计与任务组织：借鉴 Spec Kit 和 OpenSpec

**建议：借鉴模板与变更组织，暂不把两个工具整体装进产品。**

[github/spec-kit](https://github.com/github/spec-kit/tree/c43849408ac0de2ca6a52f14eaae71449776057b) 的 [需求模板](https://github.com/github/spec-kit/blob/c43849408ac0de2ca6a52f14eaae71449776057b/templates/spec-template.md) 适合参考用户场景、独立验收和边界情况的组织；[任务模板](https://github.com/github/spec-kit/blob/c43849408ac0de2ca6a52f14eaae71449776057b/templates/tasks-template.md) 提供需求与任务关联的写法。[Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec/tree/0fa4a9705c20ef1c571fe3ded74435733e4b73a1) 的 [概念设计](https://github.com/Fission-AI/OpenSpec/blob/0fa4a9705c20ef1c571fe3ded74435733e4b73a1/docs/concepts.md) 和 [工作流 schema](https://github.com/Fission-AI/OpenSpec/blob/0fa4a9705c20ef1c571fe3ded74435733e4b73a1/schemas/spec-driven/schema.yaml) 适合参考“已有行为 + 本次变更”的分离方式。

对我们的具体用途：

- 创建任务时，用简短结构记录目标、验收条件、范围、未决问题和来源。
- 需求变化时保留版本与变更原因；Review 材料说明它对应哪个需求版本。
- 后续可以把验收项关联到实现位置、检查运行和人工意见，减少逐份文档寻找证据的负担。字段范围在实现时与需求文档同步。

这些是模板和设计参考，不自动引入它们全部阶段、命令或目录。本仓库已有规划，不需要再生成一套同义文档。工具生成的清单与“已完成”文字，也不能替代我们的检查执行记录。

需要留意：Spec Kit 当前默认活动 feature 有自己的状态机制，不能假定切换 Git 分支就会切换 feature；OpenSpec 的流程也会生成独立材料。整体并入会增加状态同步工作。此外 OpenSpec README 说明命令/版本遥测默认开启并可退出；我们只参考材料，若以后集成 CLI，应明确配置并核对实际行为。来源：[Spec Kit quickstart](https://github.github.com/spec-kit/quickstart)、[OpenSpec 当前说明](https://github.com/Fission-AI/OpenSpec/blob/0fa4a9705c20ef1c571fe3ded74435733e4b73a1/README.md)。

**阶段：M0 阅读取舍，M1 最小任务结构；无需新增一个产品入口。**

## 2. Copilot 接入与分发：官方 MCP SDK + Awesome Copilot

**建议：协议使用官方 SDK；插件参考官方格式与经过挑选的示例。**

[modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk/tree/1e608caeb5130b2ad0fa067c84b26a038c1c6e36) 当前 v2 使用 `@modelcontextprotocol/server`、`@modelcontextprotocol/client` 等拆分包。旧的 `@modelcontextprotocol/sdk` 属于 v1 系列，不能混用教程。服务端适配层只暴露 Core 操作，避免另存任务状态。来源：[v2 说明](https://github.com/modelcontextprotocol/typescript-sdk/blob/1e608caeb5130b2ad0fa067c84b26a038c1c6e36/README.md)、[服务端包配置](https://github.com/modelcontextprotocol/typescript-sdk/blob/1e608caeb5130b2ad0fa067c84b26a038c1c6e36/packages/server/package.json)。

若选择 Python Core，优先使用 [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk/tree/77001c96f9507be0f4d009b83210a384a5e08bda)；本机已用 2.3.0 验证 Copilot 工具调用。此次当前文档采用 `MCPServer`，以前的 FastMCP 示例不能直接当作 v2 接口。先复用已经通过的调用路径，再对正式工具校验参数、错误和恢复。来源：[Python SDK 说明](https://github.com/modelcontextprotocol/python-sdk/blob/77001c96f9507be0f4d009b83210a384a5e08bda/README.md)。

质量依据是上游存在协议一致性和实际样例的检查配置，例如 [TypeScript conformance](https://github.com/modelcontextprotocol/typescript-sdk/blob/1e608caeb5130b2ad0fa067c84b26a038c1c6e36/.github/workflows/conformance.yml)、[TypeScript examples](https://github.com/modelcontextprotocol/typescript-sdk/blob/1e608caeb5130b2ad0fa067c84b26a038c1c6e36/.github/workflows/examples.yml)、[Python shared checks](https://github.com/modelcontextprotocol/python-sdk/blob/77001c96f9507be0f4d009b83210a384a5e08bda/.github/workflows/shared.yml)。这些配置不等于我们已跑过全部组合。客户端仍应实测协议协商和结构化结果，本机此前协商的是 `2025-11-25`，不能从 SDK 支持更新规范推导宿主已经使用它。

[github/awesome-copilot](https://github.com/github/awesome-copilot/tree/797337f33f73e35d08d82f840e21c4b8c4932d88) 可提供 Agent、Skill、Hooks 和插件组织参考。其 [插件结构检查](https://github.com/github/awesome-copilot/blob/797337f33f73e35d08d82f840e21c4b8c4932d88/.github/workflows/check-plugin-structure.yml) 和 [Skill 检查](https://github.com/github/awesome-copilot/blob/797337f33f73e35d08d82f840e21c4b8c4932d88/.github/workflows/validate-skills.yml) 值得参考。结构检查不能证明提示词有效，也不能证明 Hooks 在我们的客户端触发。只选择少量适用内容，固定来源与版本，通过自己的单一主入口调用。

**阶段：M0 沿用已有探针证据；M4 完成正式接入、安装与兼容性验证。** 本项目现有插件格式与 User scope 限制以环境记录为准，不照搬别的宿主配置。

## 3. CLI 与数据约束：Commander、Zod

若选 TypeScript Core，[tj/commander.js](https://github.com/tj/commander.js/tree/a5a7dc084d4d2b7932e85ca049c5204e50a2c721) 适合处理参数、子命令、帮助和参数错误；[colinhacks/zod](https://github.com/colinhacks/zod/tree/19c40d2072288b4cafec851e9d056a72a88e5973) 适合校验配置、任务记录及工具输入，并让类型与运行时约束保持接近。它们可以减少基础解析代码，但不能决定谁有权确认记录或旧结果是否仍然适用。

本次观察 Commander 15.1.0 声明 Node `>=22.12.0`；已验证的 Node 24.14.0 落在该声明范围。这只是版本条件满足，尚未进行本项目安装验收。Zod 应固定主版本，不把接口校验库再发展成一套重复状态机。来源：[Commander 配置](https://github.com/tj/commander.js/blob/a5a7dc084d4d2b7932e85ca049c5204e50a2c721/package.json)、[Zod 说明](https://github.com/colinhacks/zod/blob/19c40d2072288b4cafec851e9d056a72a88e5973/README.md)。

质量依据：[Commander 多平台检查](https://github.com/tj/commander.js/blob/a5a7dc084d4d2b7932e85ca049c5204e50a2c721/.github/workflows/tests.yml)、[Zod 检查配置](https://github.com/colinhacks/zod/blob/19c40d2072288b4cafec851e9d056a72a88e5973/.github/workflows/test.yml)。数据迁移、旧记录兼容与权限边界仍需我们验证。

若选 Python Core，CLI 可先用标准库 `argparse`；schema 库届时选一种，不为了对齐这张清单引入 Node 运行时。页面脚本仍可独立打包。

**阶段：M1-1，围绕任务创建、保存和新进程恢复引入。**

## 4. Git 与快照：优先复用原生 Git，参考 Cline 的 checkpoint 体验

Git 已提供稳定机器输出，适合读取已暂存、未暂存和未追踪文件状态。建议使用原生 Git CLI 与明确的参数边界，不先重写 Git。来源：[git status 官方说明](https://git-scm.com/docs/git-status)。

[cline/cline](https://github.com/cline/cline/tree/94eecbbe1a2f899c66b118d13656651b0a884e1f) 的 [checkpoint 文档](https://github.com/cline/cline/blob/94eecbbe1a2f899c66b118d13656651b0a884e1f/docs/core-workflows/checkpoints.mdx) 展示了独立影子仓库、文件比较与跨编辑器会话 checkpoint 的产品思路。我们可以参考“每个记录可回到对应代码”的体验，不需要安装 Cline 取代 Copilot。本次只据该文档评估 checkpoint 方案，没有验证其当前实现的恢复正确性。

本项目仍需自行处理：

- 仓库、worktree、分支、任务和快照分别标识；记录任务开始前已有改动与未知归属。
- 快照覆盖相关未提交内容及其他影响检查的声明输入；HEAD 不变不能视为代码未变。
- 获取快照和执行检查期间工作区可能继续变化；检测到变化或无法确定一致性时，结果不能标为当前已验证。
- 未追踪文件、忽略文件策略、符号链接、二进制文件、嵌套仓库等应有明确支持范围；不能声称一条 `git diff` 捕获全部内容。
- 恢复任务上下文不等于回滚用户文件。首版不因引入 checkpoint 参考而自动增加破坏性的还原命令。

**阶段：M1-2。** 是否采用影子仓库需单独衡量磁盘占用、初始化成本和隔离行为；并非本次已确定选择。

## 5. 真实检查执行：Execa；诊断格式参考 reviewdog

若选 TypeScript，[sindresorhus/execa](https://github.com/sindresorhus/execa/tree/247faa0ff0641020e8790475989cee72df85d62b) 可减少子进程执行、输出流、取消和超时处理的基础工作。当前 10.2.1 声明 Node `>=22`，CI 配置覆盖多个 Node 版本及 macOS / Linux / Windows。来源：[包配置](https://github.com/sindresorhus/execa/blob/247faa0ff0641020e8790475989cee72df85d62b/package.json)、[CI 配置](https://github.com/sindresorhus/execa/blob/247faa0ff0641020e8790475989cee72df85d62b/.github/workflows/main.yml)、[终止行为](https://github.com/sindresorhus/execa/blob/247faa0ff0641020e8790475989cee72df85d62b/docs/termination.md)。

建议以可执行程序和参数数组调用，只有明确配置需要时才使用 shell。库的错误对象不等于产品的检查结论；由我们的执行器保留：

- 检查配置版本、工作目录、实际命令、开始与结束快照、时间及退出状态。
- stdout / stderr 的本地引用、截断说明，以及失败、启动错误、超时、中断、跳过和未运行的区别。
- 必需检查规则、任务恢复后的运行状态和适用性。MCP 工具调用断开不能被解释为检查已经成功或一定停止。

这些属于 Core 与 runner 的职责。Python 路线可先使用标准库 `subprocess`，同样需要落实上述语义。

[reviewdog/reviewdog](https://github.com/reviewdog/reviewdog/tree/9df010aa712945780d9d7d58b6a56067b7d2755c) 的 [Reviewdog Diagnostic Format](https://github.com/reviewdog/reviewdog/blob/9df010aa712945780d9d7d58b6a56067b7d2755c/proto/rdf/reviewdog.proto) 可参考诊断来源、文件位置、严重程度和建议修复的结构，后续有利于接入多种检查器。其 [SARIF / 本地 reporter 说明](https://github.com/reviewdog/reviewdog#sarif-format) 可作为未来格式适配依据。

首版不需要部署 reviewdog 服务或把结果发到 PR。其默认按新增行过滤等展示策略也不能直接作为我们的完整检查结论：过滤后的空列表不代表全部检查无问题。原始输出与过滤范围应保留；AI 建议与工具诊断仍应分别标识。

**阶段：M2-1 评估 Execa；M2 借鉴诊断结构；PR 写入适配以后按需求实施。**

## 6. 本地持久化：文件方案需要补足边界，同时评估 SQLite

原架构建议从可读 JSON / Markdown 文件起步。调研后建议在 M0 将 SQLite 一并比较；这里只增加候选，不提前改成已采用。

| 候选 | 可复用部分 | 当前取舍 |
| --- | --- | --- |
| [npm/write-file-atomic](https://github.com/npm/write-file-atomic/tree/23e111d95367e1d987c1b4d7823791eaaf6b21df) | 临时文件、刷盘和原子替换；同进程同文件写入排队 | 单个文件替换不等于跨文件事务、跨进程互斥或业务版本冲突检查 |
| [moxystudio/node-proper-lockfile](https://github.com/moxystudio/node-proper-lockfile/tree/9f8c303c91998e8404a911dc11c54029812bca69) | 基于目录锁和心跳的锁机制 | 当前默认分支最后提交为 2021-01-25；没有近期维护与 Node 24 验证证据，降低优先级 |
| [WiseLibs/better-sqlite3](https://github.com/WiseLibs/better-sqlite3/tree/f8e2d541208281368129929a96f70f937c0735ef) | SQLite 事务与查询接口；可将关联状态放入事务 | 原生模块，需验证目标机器安装、打包和升级；可读材料通过 JSON / Markdown 导出保留 |

有一个实际版本冲突：`write-file-atomic@8.0.0` 声明 Node `^22.22.2 || ^24.15.0 || >=26.0.0`，**不包括已验证的 Node 24.14.0**。7.0.1 声明 `^20.17.0 || >=22.9.0`，可作为维持当前 Node 版本时的候选；这不代表旧版本的风险和功能已经验收。来源：[8.0.0 配置](https://github.com/npm/write-file-atomic/blob/23e111d95367e1d987c1b4d7823791eaaf6b21df/package.json)、[7.0.1 配置](https://github.com/npm/write-file-atomic/blob/v7.0.1/package.json)。

proper-lockfile 的心跳与过期锁机制值得了解，但它自己的 README 也列出不一致锁参数等无法可靠发现的情况。不能仅凭“支持网络文件系统”的简介宣称我们已支持网络共享存储。来源：[锁机制与限制](https://github.com/moxystudio/node-proper-lockfile/blob/9f8c303c91998e8404a911dc11c54029812bca69/README.md)。

better-sqlite3 当前 13.0.3 声明 Node `>=22`，仓库有多平台 Node 22/24 等测试配置；包的 exports 包含 darwin-arm64，仍需本机实际安装。来源：[包配置](https://github.com/WiseLibs/better-sqlite3/blob/f8e2d541208281368129929a96f70f937c0735ef/package.json)、[构建检查](https://github.com/WiseLibs/better-sqlite3/blob/f8e2d541208281368129929a96f70f937c0735ef/.github/workflows/build.yml)。Node 24.14.0 自带的 `node:sqlite` 在该版本官方文档中仍标为实验性，不能用新版本文档替代目标版本判断：[24.14.0 文档](https://nodejs.org/download/release/v24.14.0/docs/api/sqlite.html)。Python Core 则可先评估标准库 `sqlite3`。

**建议的选择原则：** 若文件方案可以用少量代码明确保证版本冲突、单任务并发和中断恢复，就保留其可读性优势；若跨记录一致性迫使我们自行搭建事务和复杂锁管理，优先考虑 SQLite。无论选哪一种，检查日志和大文件的落盘与数据库提交之间仍需明确失败处理。

**阶段：M0 比较最小验证，M1-1 确定基础方案，M1-2 验收并发和中断。**

## 7. Review 页面与 UI：diff2html 和 Pierre Diffs 二选一

**建议：页面外壳由我们按固定模板设计，代码差异区复用成熟组件。**

| 候选 | 适合的体验 | 引入成本与边界 |
| --- | --- | --- |
| [rtfpessoa/diff2html](https://github.com/rtfpessoa/diff2html/tree/72331ff5d13a8d4d1f11256a7b554dd0d69d7014) | 本地 Review 阅读稿；统一或左右对照差异、行号与高亮 | 适合优先验证静态 HTML；评审意见、证据关联、快照失效提示由我们实现 |
| [pierrecomputer/pierre](https://github.com/pierrecomputer/pierre/tree/e5350b378e424cf1eef206e62677bcb379f48c53) 的 `@pierre/diffs` | 行选择、批注、自定义主题及较丰富的代码阅读交互 | 提供原生 JavaScript 与 React 入口，React 并非必需；仍需打包主题/高亮/worker 等资源并验证离线行为 |

diff2html 的 [项目说明](https://github.com/rtfpessoa/diff2html) 和 [构建发布流程](https://github.com/rtfpessoa/diff2html/blob/72331ff5d13a8d4d1f11256a7b554dd0d69d7014/.github/workflows/test-and-publish.yml) 可供核对。当前默认分支 package.json 的版本占位与 Release 标签不同，不能从该字段推断应安装版本；候选发布为 3.4.55。Pierre 的 [组件说明](https://github.com/pierrecomputer/pierre/blob/e5350b378e424cf1eef206e62677bcb379f48c53/packages/diffs/README.md)、[包边界](https://github.com/pierrecomputer/pierre/blob/e5350b378e424cf1eef206e62677bcb379f48c53/packages/diffs/package.json) 和 [测试配置](https://github.com/pierrecomputer/pierre/blob/e5350b378e424cf1eef206e62677bcb379f48c53/.github/workflows/ci.yml) 支持进一步比较；当前稳定 Diffs Release 为 1.6.4，另有 1.7.0 beta，不默认选预发布。

对“高级感”的实际帮助应体现在阅读效率：

- 文件导航、需求摘要、代码差异和检查证据保持稳定位置；先看到风险与缺失，再按需展开细节。
- 字体、间距、状态色和明暗主题保持一致；检查通过、过期和待人工确认不能只靠颜色区分。
- 批注定位到快照、文件与行；代码变化后明确提示旧定位，而不是无依据地挪到新行。
- 大 diff、长行、重命名、删除和二进制文件有可读的降级与限制提示。
- 代码、文件名、日志和 AI 解释按内容转义，页面资源本地提供；不能因用了成熟组件就省略页面注入与失效引用检查。

M2-1 可先用最简可读报告跑通证据链；M2-2 对两个组件做同一组材料比较，**最终只保留一个 diff 实现**。静态页面无法自行感知外部文件变更时，应明确生成时间和快照；实时提示能力取决于后续本地服务或宿主集成，不归因于 diff 组件本身。

**阶段：M2 比较与采用；M4 再完成统一交互和安装体验。** 暂无理由为了使用一个代码组件就先建设完整 React 平台。

## 8. 状态正确性和页面验证：fast-check、Playwright、pytest

[dubzzz/fast-check](https://github.com/dubzzz/fast-check/tree/0a18452f36c7e9c7ed46f82952f6e7d68bed44e5) 支持基于性质和模型的测试及失败样例重放，适合验证容易遗漏的操作顺序。来源：[能力说明](https://github.com/dubzzz/fast-check/blob/0a18452f36c7e9c7ed46f82952f6e7d68bed44e5/packages/fast-check/README.md)。建议用在“保存 → 检查 → 修改 → 恢复 → 再评审”等状态序列，验证任何当前通过结果都不能错误引用旧输入。先写小而独立的规则模型，避免把实现复制一遍再证明两者相同。

[microsoft/playwright](https://github.com/microsoft/playwright/tree/07c7069cdbb1f5c7331d3f4d2abd864dcfde745a) 适合实际打开本地 Review 页面，检查代码/日志注入、定位、过期状态和不同视口下的可读性。上游有多平台浏览器与安装测试配置，见 [上游测试配置](https://github.com/microsoft/playwright/blob/07c7069cdbb1f5c7331d3f4d2abd864dcfde745a/.github/workflows/tests_primary.yml)；本项目只运行与改动相关的检查，起步不要求全浏览器组合。浏览器二进制下载和目标机器运行仍需确认。

[pytest-dev/pytest](https://github.com/pytest-dev/pytest/tree/171c924acfd66d03ab51d08da2509461da6233a7) 已用于本机最小 Python 验证，可继续用于示例项目的实际成功、失败及回归案例。[fastapi/fastapi](https://github.com/fastapi/fastapi/tree/1ca09c13584ca45aa0921e5e40b31d49c5e3135a) 可在示例需要 API 时采用；它只是示例业务框架，不是本地 Core 或 Review 页面必须新增的服务。

**阶段：M1 验证关键状态；M2 验证页面；M5 复用明确的 Python 场景验收。** 不以安装测试框架或覆盖率数字代替真实结果。

## 9. 长期记忆：先保留结构化记录，Mem0 暂不作为首版依赖

[mem0ai/mem0](https://github.com/mem0ai/mem0/tree/f1791daa86d469249c9b002f62644d58a1eb96a0) 适合关注需要模型提取与语义检索的记忆场景。但其 [当前说明](https://github.com/mem0ai/mem0/blob/f1791daa86d469249c9b002f62644d58a1eb96a0/README.md) 明确需要 LLM，[配置结构](https://github.com/mem0ai/mem0/blob/f1791daa86d469249c9b002f62644d58a1eb96a0/mem0/configs/base.py) 包含模型、嵌入和向量存储。它支持不同后端，不能据此断言必须上云；但整体接入会增加模型、检索及部署配置。

我们的首要问题是“这条项目记录来源是什么、对当前分支是否适用、谁确认过、冲突如何呈现”。引入语义记忆库并不能自动提供这些产品规则。首版建议按任务、模块、路径、关键词和记录来源检索；遇到检索不足的实际证据后，再比较向量检索方案。

已有 engineer-voice 按当前规划在 M3 检查版本与许可后集成。本文没有将它视为已安装，也不把一个表达改写模块扩展为新的模型服务。

**阶段：M3 先实现有来源的记录；语义检索基础设施留给后续需求。**

## 必须留在 Engineering Flow Core 的职责

| 职责 | 现有组件为何不能代替 |
| --- | --- |
| 任务、工作区、快照和启动基线 | Git 提供底层事实，不知道本次任务范围与修改归属 |
| 需求与实际证据对应 | Spec 模板表达意图，不证明实现和验收已完成 |
| 检查与评审的适用性 | 进程库和 diff 组件不计算代码变化后的有效范围 |
| AI 解释、工具观察、人工确认的来源 | 任意文本、标签或模型自述不能充当独立执行/确认记录 |
| 记忆的范围、冲突与过期 | 检索相似度不等于团队规则当前有效 |
| CLI / MCP / 页面共用规则 | 多个适配库不会自动共享业务状态和权限 |

建议给外部库保留薄适配层，让 Core 依赖我们的数据结构，避免将第三方完整结果对象长期直接写成产品数据合同。原始输出作为证据保留，规范化记录带 schema 版本。

## 与现有阶段衔接的实施顺序

| 单元 | 复用或参考的内容 | 采用前需要拿到的实际结果 |
| --- | --- | --- |
| M0 剩余准备 | Core 语言、存储候选与运行依赖 | 在已验证环境中完成选定存储的写入、重启读取与必要打包验证；记录选择原因 |
| M1-1 | CLI / schema / 存储；精简的需求模板 | 创建、保存、关闭进程、新进程恢复同一任务，内容一致 |
| M1-2 | 原生 Git；必要时参考 checkpoint 方案；针对性的性质测试 | dirty/untracked、已有改动、不同 worktree、并发与中断行为可核验 |
| M2-1 | 进程库与最简固定 Review 材料 | 运行真实通过和失败检查并绑定正确快照，输出可追溯 |
| M2-2 | 选定一个 diff 组件；Playwright | 对相同材料验证定位、长 diff、注入、离线资源和代码变化后的失效展示 |
| M3 | 本地结构化记录、模板、engineer-voice | 确认来源、冲突、过期、缺失模块与新会话续接得到验证 |
| M4 | 官方 MCP SDK、适量插件示例与校验规则 | 正式插件实际调用同一 Core，显式无 Hooks 流程可用，干净环境可安装 |
| M5 | pytest 与按需引入的 Python 示例框架 | 完成完整任务验收，并列出仍未验证的兼容范围 |

不为本次调研新增里程碑或固定审批流程。下一次开发仍从 [STATUS.md](../STATUS.md) 中的 M0 剩余准备与 M1-1 开始。

## 许可与供应链处理

本次核对的多数项目使用 MIT、ISC 或 Apache-2.0；实际采用时保留适用许可、版权和 NOTICE，复制模板或代码同样记录上游路径与版本。根许可证不代表所有依赖、图标、字体或文档资产都使用同一许可。

MCP TypeScript SDK 是一个需要特别区分的案例：其 LICENSE 说明新贡献使用 Apache-2.0，尚未取得重新许可同意的既有贡献保留 MIT，普通文档使用 CC-BY-4.0。不能将整个仓库简单标成“MIT”或把两种代码许可理解为任意二选一。[v2.4.0 LICENSE](https://github.com/modelcontextprotocol/typescript-sdk/blob/v2.4.0/LICENSE)

本项目自身的许可和发布范围仍未确定，不因引用开源依赖而自动选择。正式引入时固定发布版本、提交锁文件并核对实际解析依赖；需要联网、写外部系统或启用遥测的适配器按明确配置接入。

## 仓库与版本核对记录

以下为本次读取的观察值。提交日期是默认分支最新提交的 committer 日期，使用 UTC；不使用仓库 `pushed_at` 充当默认分支最近开发日期。Release 列为空不代表没有包版本；这是 GitHub Release 记录，最终仍需核对分发包。所有行当前均未归档。

| 仓库（固定到观察提交） | 许可文件 | 默认分支提交日期 / SHA | 观察到的 Release |
| --- | --- | --- | --- |
| [modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk/tree/1e608caeb5130b2ad0fa067c84b26a038c1c6e36) | [Apache-2.0 / 部分既有 MIT；文档另见说明](https://github.com/modelcontextprotocol/typescript-sdk/blob/1e608caeb5130b2ad0fa067c84b26a038c1c6e36/LICENSE) | 2026-10-31 · `1e608ca` | [v2.4.0](https://github.com/modelcontextprotocol/typescript-sdk/releases/tag/v2.4.0) · 2026-10-23 |
| [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk/tree/77001c96f9507be0f4d009b83210a384a5e08bda) | [MIT](https://github.com/modelcontextprotocol/python-sdk/blob/77001c96f9507be0f4d009b83210a384a5e08bda/LICENSE) | 2026-11-05 · `77001c9` | [v2.3.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0) · 2026-10-02 |
| [tj/commander.js](https://github.com/tj/commander.js/tree/a5a7dc084d4d2b7932e85ca049c5204e50a2c721) | [MIT](https://github.com/tj/commander.js/blob/a5a7dc084d4d2b7932e85ca049c5204e50a2c721/LICENSE) | 2026-11-07 · `a5a7dc0` | [v15.1.0](https://github.com/tj/commander.js/releases/tag/v15.1.0) · 2026-11-07 |
| [sindresorhus/execa](https://github.com/sindresorhus/execa/tree/247faa0ff0641020e8790475989cee72df85d62b) | [MIT](https://github.com/sindresorhus/execa/blob/247faa0ff0641020e8790475989cee72df85d62b/license) | 2026-10-23 · `247faa0` | [v10.2.1](https://github.com/sindresorhus/execa/releases/tag/v10.2.1) · 2026-10-23 |
| [colinhacks/zod](https://github.com/colinhacks/zod/tree/19c40d2072288b4cafec851e9d056a72a88e5973) | [MIT](https://github.com/colinhacks/zod/blob/19c40d2072288b4cafec851e9d056a72a88e5973/LICENSE) | 2026-11-06 · `19c40d2` | [v4.6.7](https://github.com/colinhacks/zod/releases/tag/v4.6.7) · 2026-10-12 |
| [npm/write-file-atomic](https://github.com/npm/write-file-atomic/tree/23e111d95367e1d987c1b4d7823791eaaf6b21df) | [ISC](https://github.com/npm/write-file-atomic/blob/23e111d95367e1d987c1b4d7823791eaaf6b21df/LICENSE.md) | 2026-06-18 · `23e111d` | [v8.0.0](https://github.com/npm/write-file-atomic/releases/tag/v8.0.0) · 2026-05-08 |
| [moxystudio/node-proper-lockfile](https://github.com/moxystudio/node-proper-lockfile/tree/9f8c303c91998e8404a911dc11c54029812bca69) | [MIT](https://github.com/moxystudio/node-proper-lockfile/blob/9f8c303c91998e8404a911dc11c54029812bca69/LICENSE) | 2021-01-25 · `9f8c303` | 本次 Release 列表为空 |
| [rtfpessoa/diff2html](https://github.com/rtfpessoa/diff2html/tree/72331ff5d13a8d4d1f11256a7b554dd0d69d7014) | [MIT](https://github.com/rtfpessoa/diff2html/blob/72331ff5d13a8d4d1f11256a7b554dd0d69d7014/LICENSE.md) | 2026-01-31 · `72331ff` | [3.4.55](https://github.com/rtfpessoa/diff2html/releases/tag/3.4.55) · 2026-01-01 |
| [pierrecomputer/pierre](https://github.com/pierrecomputer/pierre/tree/e5350b378e424cf1eef206e62677bcb379f48c53) | [Apache-2.0](https://github.com/pierrecomputer/pierre/blob/e5350b378e424cf1eef206e62677bcb379f48c53/LICENSE.md) | 2026-11-05 · `e5350b3` | [diffs-v1.6.4](https://github.com/pierrecomputer/pierre/releases/tag/diffs-v1.6.4) · 2026-11-03；另有 1.7.0 beta |
| [github/spec-kit](https://github.com/github/spec-kit/tree/c43849408ac0de2ca6a52f14eaae71449776057b) | [MIT](https://github.com/github/spec-kit/blob/c43849408ac0de2ca6a52f14eaae71449776057b/LICENSE) | 2026-11-07 · `c438494` | [v1.3.2](https://github.com/github/spec-kit/releases/tag/v1.3.2) · 2026-11-06 |
| [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec/tree/0fa4a9705c20ef1c571fe3ded74435733e4b73a1) | [MIT](https://github.com/Fission-AI/OpenSpec/blob/0fa4a9705c20ef1c571fe3ded74435733e4b73a1/LICENSE) | 2026-11-07 · `0fa4a97` | [v1.16.1](https://github.com/Fission-AI/OpenSpec/releases/tag/v1.16.1) · 2026-11-07 |
| [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/797337f33f73e35d08d82f840e21c4b8c4932d88) | [MIT](https://github.com/github/awesome-copilot/blob/797337f33f73e35d08d82f840e21c4b8c4932d88/LICENSE) | 2026-11-06 · `797337f` | 本次 Release 列表为空 |
| [reviewdog/reviewdog](https://github.com/reviewdog/reviewdog/tree/9df010aa712945780d9d7d58b6a56067b7d2755c) | [MIT](https://github.com/reviewdog/reviewdog/blob/9df010aa712945780d9d7d58b6a56067b7d2755c/LICENSE) | 2026-11-06 · `9df010a` | [v0.21.2](https://github.com/reviewdog/reviewdog/releases/tag/v0.21.2) · 2026-09-18 |
| [dubzzz/fast-check](https://github.com/dubzzz/fast-check/tree/0a18452f36c7e9c7ed46f82952f6e7d68bed44e5) | [MIT](https://github.com/dubzzz/fast-check/blob/0a18452f36c7e9c7ed46f82952f6e7d68bed44e5/LICENSE) | 2026-11-07 · `0a18452` | [v4.10.2](https://github.com/dubzzz/fast-check/releases/tag/v4.10.2) · 2026-09-19 |
| [microsoft/playwright](https://github.com/microsoft/playwright/tree/07c7069cdbb1f5c7331d3f4d2abd864dcfde745a) | [Apache-2.0](https://github.com/microsoft/playwright/blob/07c7069cdbb1f5c7331d3f4d2abd864dcfde745a/LICENSE) | 2026-11-07 · `07c7069` | [v1.65.0](https://github.com/microsoft/playwright/releases/tag/v1.65.0) · 2026-11-05 |
| [pytest-dev/pytest](https://github.com/pytest-dev/pytest/tree/171c924acfd66d03ab51d08da2509461da6233a7) | [MIT](https://github.com/pytest-dev/pytest/blob/171c924acfd66d03ab51d08da2509461da6233a7/LICENSE) | 2026-11-07 · `171c924` | [9.2.0](https://github.com/pytest-dev/pytest/releases/tag/9.2.0) · 2026-10-27 |
| [fastapi/fastapi](https://github.com/fastapi/fastapi/tree/1ca09c13584ca45aa0921e5e40b31d49c5e3135a) | [MIT](https://github.com/fastapi/fastapi/blob/1ca09c13584ca45aa0921e5e40b31d49c5e3135a/LICENSE) | 2026-11-05 · `1ca09c1` | [0.162.0](https://github.com/fastapi/fastapi/releases/tag/0.162.0) · 2026-10-23 |
| [mem0ai/mem0](https://github.com/mem0ai/mem0/tree/f1791daa86d469249c9b002f62644d58a1eb96a0) | [Apache-2.0](https://github.com/mem0ai/mem0/blob/f1791daa86d469249c9b002f62644d58a1eb96a0/LICENSE) | 2026-11-06 · `f1791da` | [v2.2.1](https://github.com/mem0ai/mem0/releases/tag/v2.2.1) · 2026-09-25 |
| [WiseLibs/better-sqlite3](https://github.com/WiseLibs/better-sqlite3/tree/f8e2d541208281368129929a96f70f937c0735ef) | [MIT](https://github.com/WiseLibs/better-sqlite3/blob/f8e2d541208281368129929a96f70f937c0735ef/LICENSE) | 2026-08-10 · `f8e2d54` | [v13.0.3](https://github.com/WiseLibs/better-sqlite3/releases/tag/v13.0.3) · 2026-08-05 |
| [cline/cline](https://github.com/cline/cline/tree/94eecbbe1a2f899c66b118d13656651b0a884e1f) | [Apache-2.0](https://github.com/cline/cline/blob/94eecbbe1a2f899c66b118d13656651b0a884e1f/LICENSE) | 2026-11-06 · `94eecbb` | [v4.1.26](https://github.com/cline/cline/releases/tag/v4.1.26) · 2026-10-26 |

这些版本用于复核调研，不构成一次安装全部依赖或始终追随最新版本的决定。

