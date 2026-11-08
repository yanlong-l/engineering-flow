# 决定、待定事项与参考来源

整理日期：2026-11-07。产品要求来自与用户的讨论；外部能力来自官方文档。官方资料会变化，开发时以目标客户端的实际版本和策略重新验证。

## 已确认的名称与产品要求

| 事项 | 内容 |
| --- | --- |
| 产品名 | Engineering Flow |
| 仓库名 | `yanlong-l/engineering-flow`，开发前已核对为空仓库并关联本地 origin；实际版本保存以 Git 历史为准 |
| 用户方向 | 工程师与 GitHub Copilot 的高质量产出和协作 |
| 范围 | 开发、代码 Review、文档、长期记忆和维护 |
| 页面 | 希望帮助工程师理解 AI 参与生成的代码 |
| 定制 | 支持个人工作流和可插拔选项 |
| 产品形态偏好 | 更完整的 Agent 或产品体验，减少挑选 Skills 的负担 |
| 现有模块 | 希望嵌入 engineer-voice |
| 开发组织 | 按 M0–M5 推进；最新进度与下一会话目标维护在 `STATUS.md` |

用户允许在合适情况下使用 Skill，但不希望产品停留在单个 Skill 或大量 Skills 的手工组合。

## 架构建议与采用状态

| 编号 | 建议 | 原因 |
| --- | --- | --- |
| D-01 | Agent Plugin 组织分发 | 可以将相关组件一并安装 |
| D-02 | 单一主 Agent | 用户操作简单，内部按阶段选择模块 |
| D-03 | 独立本地 Core | 统一状态和记录，便于 CLI/MCP 共用 |
| D-04 | 已比较并采用 Python Core | 沿用已验证环境，标准库支持 CLI 与事务存储；详见下方 M0 决定 |
| D-05 | 已比较并采用 SQLite | 减少文件方案的事务与锁管理代码，CLI 返回可读 JSON |
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
| Core 语言和存储 | 已采用 Python >=3.14 + 标准库 SQLite；本机验证 3.14.3 |
| 安装包格式和运行依赖 | 本地 Python wheel 与 console script 已实现；正式插件按目标客户端另行验收 |
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

### 2026-11-08：M5 可复现验收与候选范围

- 选择：在源码工具 `tools/run_pilot.py` 中编排独立 CLI 进程；只新建构造 Git 仓库、保存原始流与摘要，不在 Core 增加状态机、数据库或模型服务。加入 required `pilot` 和 `make pilot-check`，原有必需检查保留。
- 依据：零散可信度测试已有覆盖，但缺少从失败、修复、Review、文档应用到新进程续接的重复执行入口。将 P0 与 AT 对应实际测试和命令，防止仅从模型自述或单个总通过推导全部验收。
- 范围：产品运行时代码和资源保持 dev8/v6，不为验收工具人为改产品版本。候选继续采用本地 wheel；不公开发布或默认设定项目许可。FR-14 的个人偏好仅支持按调用 summary/full，持久配置和多预设延期。
- 限制：一个构造场景的重复运行不外推业务效果；自动 PTY/端口不当作真人批准，固定表达保护不证明一般语义等价。本轮本地浏览器预览被协议策略阻止，未绕过。首版范围与证据见 [M5 验收](14-m5-acceptance.md)。

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

### 2026-11-07：M0 技术选型与 M1-1 存取合同

- 状态：已采用，适用于当前本地单机任务存取。
- 选择：Python >=3.14；标准库 `argparse`、`sqlite3` 和 `unittest`；`venv` + pip 管理开发环境，`src/` 布局、`pyproject.toml` 与 console script 打包。运行时无第三方依赖，构建后端固定 `setuptools==80.9.0`。不引入模型服务、MCP SDK 或前端依赖作为本轮前提；本项目许可与公开发布仍未指定。
- 语言比较：TypeScript 便于共享前端和 MCP 类型，但当前 Python 3.14.3 与 Python MCP 探针已有真实执行依据；Python 标准库即可完成本轮 CLI 和数据库工作，后续 MCP 适配仍调用相同 Core。前端需要时独立构建，不要求 Core 同时改用 Node。没有因为试点用 Python 就直接跳过语言比较。
- 存储比较：JSON 的可读性较好，但需要另行处理跨进程锁、原子替换和历史版本；SQLite 将记录追加和修订比较放在事务中，减少自行维护存储协议。Python 自带 sqlite3，无需安装 better-sqlite3 原生模块，也不依赖不兼容本机 Node 的 write-file-atomic 8。CLI JSON 作为当前可读出口，Markdown 导出留待需要时实现。
- 合同：数据库与任务 schema 均为 v1，按任务 ID 与修订号追加完整文档。调用者需提供预期修订，未知版本拒绝打开，不作自动迁移。任务进度标记为 `caller`，Git 观察标记为 `program_observation`；不允许用这些字段表达检查通过或人工确认。
- 实际验证：本机 Python 3.14.3 / SQLite 3.52.0 完成编辑安装、独立进程存取测试；wheel 构建与隔离环境安装结果见 STATUS。测试覆盖过期修订、基础分支检查和损坏记录诊断；完整并发、中断恢复与 worktree 隔离仍在 M1-2。
- 限制：依赖系统 Python 提供 sqlite3；本轮只验证 macOS / Apple Silicon 的当前版本。基础 Git 状态不是代码快照。当前进度、失败与下一步以 [STATUS](../STATUS.md) 为准。
- 接口依据：[Python 3.14 sqlite3 文档](https://docs.python.org/3.14/library/sqlite3.html)、[Python 打包说明](https://packaging.python.org/en/latest/tutorials/packaging-projects/)。产品结果以实际运行记录为依据。

### 2026-11-07：M1-2 内容快照、边界与存储升级

- 状态：已采用；本机支持范围和故障场景已实际检查，详见 STATUS。
- 选择：清单与原始 blob 全部放 SQLite，和任务修订同事务提交；不引入独立内容文件的提交窗口。快照使用 SHA-256、文件工作区/暂存区两层、原始二进制 diff 和显式范围，忽略状态目录，不仅依赖 HEAD。
- 范围：默认 Git 跟踪与未忽略文件；以 `.engineering-flow.json` 显式增加被忽略输入，不静默猜测依赖。只支持普通文件，拒绝符号链接/submodule/未解决合并等边界，超过 2000 个文件或去重后 64 MiB 报错。两次完整采集比较用于发现持续变化；不是原子或隔离快照，后续检查执行模式仍需明确。
- 归属：启动快照固定保存已有改动内容。后续比较只说明新增/删除/修改；显式关联文件不等于确认改动作者，同文件混合修改保持未知。
- 升级：数据库和新任务 schema v2，快照 schema v1；只读旧库不迁移，写入事务升级并保留旧 document。旧启动快照为空则始终保留未知。旧 dev1 CLI 不兼容已升级数据库，当前包为 dev2。
- 实际依据：独立进程修订竞争、写入中断强杀、锁超时、SQLite max_page_count 容量失败、只读连接、部分 DDL 迁移失败均以真实 SQLite 操作验证；worktree 同分支强制检出、不同分支、同 remote 克隆与数据库复制验证了身份拒绝。
- 限制：容量测试是 SQLite 页数上限，不是耗尽系统磁盘；强杀恢复不是断电保证。其他平台、网络文件系统、身份移动迁移、内容垃圾回收和完整检查/Review 仍未完成。

### 2026-11-07：M2-1 真实执行、适用性与最简 Review

- 状态：已采用，适用于本机 POSIX 工作区执行；验收结果见 STATUS。
- 选择：继续复用标准库 subprocess 与 SQLite，不引入模型服务、外部 runner、前端运行时或自主多 Agent。配置使用 argv 数组，从执行前快照读取；完整参数 `{python}` 解析为 CLI 的 Python。只支持受限时间的同步执行，先保存 running，再记录终态与结束快照，其他进程可查询。
- 结果语义：退出 0 按命令约定为 passed，正退出码为 failed，启动/信号/超时/采集失败为 error；测试数量和业务断言由检查脚本负责。每流输出保存上限 4 MiB，超限为 error，保留可核对摘要的原始前缀；二进制用 base64。不接受调用者提交的“通过”文字。
- 适用性：声明的完整输入集保守失效；前后及观察快照全同才 current。采用最近启动的运行，不用更早通过隐藏后续失败或未完成。全部必需项须 passed/current，未配置必需项也不推导全通过。配置变更本身改变快照，个人覆盖和跳过暂不实现。
- 存储：数据库升级 v3 只新增 check_runs/reviews，任务 schema 保持 v2，证据 schema v1。旧修订原文保留，只读 v1/v2 不迁移。完整性摘要是损坏检测，不是密码签名或身份认证；有直接数据库权限的调用者仍处于本地信任边界内。
- 最简材料：先完成固定 JSON/Markdown 及实际快照/文件/diff/输出引用，调用者文字转义；不在 M2-1 扩大为 HTML 页面。材料固定生成时快照和任务修订，show 返回当前适用性，build 追加新包；AI 解释与人工确认明确为空。HTML、跳过和可信人工评审留到 M2-2。
- 构造示例：自建批量任务队列，SQLite 同请求复用与内容冲突检查；另有明确标记的故意缺陷实现展示实际失败。检查脚本显式装载四个案例，使用 `-B` 避免首次缓存目录改变范围清单。无业务数据或生产设备，也不作为团队收益证明。
- 限制：workspace 执行和前后采集不等于隔离，外部依赖与临时修改后恢复不在保证内。SIGINT/SIGTERM 尽力终止进程组；SIGKILL/结束写入失败可能留下 running/unknown，不能补造完成，子进程可能继续。无后台调度、孤儿回收、检查历史分页或材料包重建，其他平台仍待验证。

### 2026-11-07：M2-2 固定 HTML、跳过与本地终端评审

- 状态：已采用，本机支持范围见 STATUS；不增加独立服务或前端运行时。
- 页面：固定 Python 模板生成 HTML，所有代码、日志、AI/调用者文本经转义；CSP default-src none，不含脚本或页面写入通道。用持久化快照、内容层与实际行号生成内部链接，无法解析的引用明确失效；不读取当前文件冒充历史。原生 details 提供展开，桌面/窄屏共用布局。
- 状态：skip 是未执行的调用者记录，保存原因且保留项目 required，不计为 passed；历史通过不能越过后续 skip。页面同时显示历史退出状态和生成时适用性。旧静态页保留，show 对照当前代码/任务/证据返回刷新需要，build 追加新页。
- 来源：解释 origin=ai，意见 origin=caller；approve 意见不自动确认为人类决定。独立 ConfirmationPort 由本地终端适配器实现，显示意见与快照/范围并要求当次随机 challenge，从 OS 读取 uid/账号/tty，交互前后重新采集以阻止过期确认。普通 JSON/非交互调用无确认入口，CLI 没有自报 actor/origin/confirmed/--yes 参数。
- 信任边界：当前选择本机交互来源，不声称身份认证。记录 assurance=local_session_not_identity_verified；同账号终端/PTY/Agent、受信适配器和数据库写权限仍可模拟本地操作。自动化 PTY 只验证流程，不作为真实用户已批准的证据。若团队需要抵御同账号自动化的真人来源，应通过独立认证或可核验 PR Review 适配器扩展，而不是夸大终端提示的证明能力。
- 范围：确认绑定快照和任务修订，明确 task/files 范围，同范围最新当前记录参与 confirmedScopes；文件确认不代表整体获批，任何确认不代替必需检查。历史确认保留并显示过期或被后续记录替代。
- 迁移：数据库 v4 增加不可变 review_events，旧记录不改写，读取 v1/v2/v3 不迁移；Review v2 包含解释/意见/确认历史，旧 v1 可读。dev1/dev2/dev3 拒绝读取升级后的库，当前包 dev4。
- 验证：真实 Chromium 检查六种状态、代码/日志安全、内部锚点与响应式；CLI 测试覆盖快照变化、交互期间变化、取消、非交互拒绝、限定范围及迁移回滚。详细命令、结果及早期失败保留在 STATUS 的本地证据目录。

### 2026-11-07：M3-1 有来源的候选记忆与上下文选择

- 状态：已采用；实际检查与未验证范围见 STATUS。
- 存储：继续使用本地标准库 Core + SQLite；v5 追加不可变 memories/memory_events，与来源快照同事务写入并检查任务修订。只读旧库不迁移，原 JSON 保留。明确提交候选，不默认收集对话；没有模型调用、向量数据库、额外服务或自主多 Agent。
- 来源：正文统一记录调用者输入，避免仅凭入口猜作者；真实代码行、终态 CheckRun 和 Review 事件分别保留观察、runner、ai、caller 或本地终端来源。来源可读不代表正文推断成立。外部 URL、人名和模型置信度不充当已核验来源。
- 适用性：沿用完整声明输入快照的保守失效，任务修订也参与判断；不引入未经验证的文件依赖推断。确认历史与 current/needs_revalidation 分开，源文件删除仍能读取原快照。复核时产生新候选，不静默改写或补造旧结论。
- 确认：复用 Review 意见/独立终端回执，v2 记忆范围包含完整候选与摘要。任务或文件确认不隐式确认记忆；记忆确认不代表任务获批。一组记忆中的后续单条决定只替代对应条目。信任边界继续是 local_session_not_identity_verified；测试端口与 PTY 不是真人批准。
- 检索：任务、父子路径、模块标签、关键词及项目范围决定相关性；当前无冲突的已确认记录优先，再按明确分值和稳定 ID 排序。输入预算选用 selected 的规范 UTF-8 JSON 字节数，避免假称各模型 token 数相同；元数据不在预算内。整条排除，提供原因和继续读取参数，不截断条件或来源。
- 冲突与替代：只保存显式声明及原因，不做语义识别。未确认替代候选不能隐藏旧项；新项曾获批准后旧项退出默认上下文，后续拒绝新项不自动复活旧规则。保留冲突两端、替代和归档事件；禁止自关联、替代循环、跨工作区及分支关系。
- 范围：本轮不接入 engineer-voice、不修改产品使用者的文档、不做团队共享或自动语义核验；M3-2 再核对实际模块文件/许可与语义保护样例。大历史性能、分页、归档撤销、外部认证及其他平台未专项验收。

### 2026-11-07：M3-2 文档建议、固定表达模块与交接

- 状态：已采用，本机实际检查见 STATUS；正式宿主集成继续在 M4。
- 文档：保存显式目标和原因，支持 manual/generated/mixed；只产生不可变建议与 diff，不引入自动覆盖或另一个确认系统。混合区域必须有唯一、有序、无嵌套标记；完整生成文档须新建或已有明确生成标记。来源、代码快照和任务修订沿用 Core，后续应用按完整输入变化失效。
- 存储与确认：数据库 v6 追加 document_proposals；文档 schema v1，Review/文档范围事件 v3。v1–v5 只读不迁移，写入同事务升级。Review 意见内嵌原始建议并与数据库原件核对，终端确认维持 local_session_not_identity_verified；任务/文件批准不隐式确认文档建议，建议批准不替代应用后检查。
- engineer-voice：GitHub 连接器核实 v0.2.0 固定提交 `8dcf520fb3974e9711cf193ca78a9839a7fce5f0` 和 MIT 许可。收录原创 Skill、词表、构造样例和回归材料，保留原始许可；含第三方节选的 GitHub 实录未收录。来源清单、逐文件摘要与许可随 wheel 提供，见 THIRD_PARTY_NOTICES。
- 调用边界：它是 Markdown Skill，没有可执行模型服务。显式 voice 加载规则，由当前宿主 Agent 改写；rewrite 仅接收绑定原建议和模块摘要的候选，程序不证明实际模型执行。缺失模块保持原稿；保护区、数值/已识别单位、敏感词序或显式事实变化时保存拒绝候选，after 回退原稿。程序保护不能证明语义等价，也可能保守拒绝同义改写，主体/对象/因果仍需人工 Review。
- 交接：task handoff 共用 Review，一次快照输出目标、进度、未决事项、真实检查、评审、文档和带状态的记忆；completion=not_asserted，避免以材料生成冒充任务完成。
- 验收：固定七组语义样例验证保护与回退，临时 Git/SQLite/CLI 验证快照变化、分支/worktree、确认范围和迁移回滚；程序测试、当前 Agent 的构造改写和真实 Copilot 的模型行为验收分开记录。不新增模型服务、自主多 Agent、外部上传或全部对话采集。

### 2026-11-07：M4-1 正式插件、共享 MCP 与宿主合同

- 状态：已采用；本机真实 Copilot 和检查依据见 STATUS。M4-2 安装/升级与 M5 首版验收继续进行。
- 分发：沿用 Agent Plugins 1.0，随 wheel 打包一个 Agent 与两个内部 Skills，由 plugin build 输出绑定工作区和当前 Python 路径的新目录；不复制源码或任务库，不自动改 IDE 设置。不引入自主多 Agent、独立模型服务、后台调度或网络监听。
- 适配：官方 Python SDK `mcp==2.3.0` 作为 `[copilot]` 可选依赖；Core/CLI 继续无第三方必需运行依赖。七组 stdio 工具只映射既有 Core，schema v6 不变。人工确认不暴露给 MCP，仍保留独立终端的信任边界。
- 宿主兼容：本机一条 Copilot 模型路径仅呈现了 oneOf 操作组的最后一个 action；公开 schema 改为平面 action 枚举，逐操作的必填/多余字段校验保留在服务端。补全候选、改写与引用的参数说明。原先 text 与 structuredContent 在本机重复展开且长 JSON 单行不便读取，改为只返回一份 UTF-8、分行 JSON 文本；错误保留 isError/code/message，失败检查保留真实运行记录。
- 执行：每个 MCP 服务串行，工作线程共用同步 Core；请求取消不停止已经开始的检查，配置超时仍生效。连接或进程停止不等于后台保证，强制结束可留 running/unknown。未获回复时先查询状态，不自动重试写操作。绑定仅约束本机路由，不能认证调用来自哪个 IDE 窗口。
- 修正：真实宿主发现已忽略的根 `.engineering-flow/` 首次创建后会进入 Git ignoredPaths，使无源码改动的新任务 stale。采集时明确排除该根状态目录，嵌套项目忽略目录仍列出。旧快照和历史结果不改写，旧清单与新采集不同时保守失效，重新检查后产生新记录。
- Hooks：临时插件实测 sessionStart/postToolUse，只保存事件名、字段名、cwd 和工具名，不保存提示词/参数/输出内容。未实现或验收产品自动保存、超时/失败语义；正式插件不配置 Hooks，显式 checkpoint/check/review/document/handoff 保持可用。
- 验收边界：真实 Copilot 读取已校验 engineer-voice 规则并提交一条实际改写，Core 保护比较通过，文档仍为 proposed/current，未应用或人工确认。此为构造案例，不证明通用语义等价。长输出仍会产生宿主临时文件读取，继续在 M4-2 优化。
- 依据：[VS Code 插件参考](https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference)、[Copilot Hooks 合同](https://docs.github.com/en/copilot/reference/hooks-reference)、[Python SDK](https://github.com/modelcontextprotocol/python-sdk)；实际目标仍为 VS Code 1.137.0 / Copilot Chat 0.65.0，最新网页不替代本机验证。

### 2026-11-08：M4-2 展示协议与可核对的本地安装

- 状态：已采用，M4 当前本机支持范围完成；M5 逐项验收另行推进。
- 展示：默认 UTF-8 JSON 预算 6000 字节，大结果带明确 incomplete 标记和领域 ID；第八组只读 flow_read 按 JSON Pointer 和 Unicode 码点分页。规则/草稿以原文读取，避免转义长行和宿主反复读临时文件。显式 full 保留兼容；展示选择不修改 Core 或 required。
- 生命周期：完整结果仅在服务进程内作不可变副本，LRU 16 个大结果、序列化预算 32 MiB，不声称限制 Python 堆大小；缓存标为捕获时状态。过大/重启/淘汰均明确告知，按领域 ID 查询，禁止以重新写操作恢复读取。没有对话采集或磁盘响应缓存。
- 安装：dev8 插件绑定 schema v2 固定版本、sys.prefix、Python、工作区及完整文件摘要；-I 从安装包导入。inspect 不执行配置命令，拒绝缺失/额外文件、Hooks、符号链接及绑定错配。旧 dev7 绑定要求重新生成，运行中版本变化拒绝继续，不支持热升级。摘要是损坏检测，不是签名或宿主认证。
- 诊断：SDK 同时核对固定 metadata 版本和实际 lowlevel 导入；doctor --require-mcp 在不可用时退出 1，普通 CLI 保留降级。项目 unit-tests timeout 从 300 调至 600，依据上一轮实际 374.671 秒；新增 required copilot-runtime，防止 SDK 缺失时集成测试 skip 被误当完整通过。没有移除或个人覆盖 required。
- 验证：新 venv 无索引安装固定 SDK，dev7→dev8→dev7→dev8 保留 v6 数据，旧包/错误版本/移动环境与仓库/分支错配均实际拒绝。真实 Copilot 使用安装包完成显式流程及分页、一次拒绝后修正的改写和交接，候选未应用或确认。最终完整 161 项与 4 项示例通过，详见 STATUS。
- 范围：默认显式流程、项目命令和按调用展示选择构成本次 M4 配置范围；不增加持久个人设置、多预设或 Hooks 自动化。卸载注册和重载窗口不保证服务退出，本机遗留的构造服务已在核对身份后终止。其他机器/客户端、通用语义等价和真实人工批准未验收。

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
