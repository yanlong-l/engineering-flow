# 数据、快照与状态

状态：M1 的任务/快照、M2 检查/HTML/本地终端评审及 M3 的记忆/文档建议/交接已实现；实际验收范围见 STATUS。终端确认不构成身份认证。

## M1 已实现的数据合同

- SQLite 路径为工作区根的 `.engineering-flow/state.sqlite3`，当前 `PRAGMA user_version=6`。`task_revisions` 以 `(task_id, revision)` 为主键保存完整 JSON；`snapshots` 以内容指纹为键保存清单；`blobs` 以 SHA-256 为键保存原始 bytes。三类写入同事务提交，失败不留半份任务或快照。
- 新任务 `schemaVersion=2`，保留 v1 的 ID、修订、目标、验收条件、进度、未决事项、时间和来源字段，增加 `relatedFiles`。`inputOrigin=caller` 不表示人工确认，状态仍仅支持 `active`；目前没有检查通过字段。
- `startingWorkspace` 固定保留启动观察，`savedWorkspace` 关联最后保存的快照；二者包含基于规范化 Git 路径的 `projectId` / `workspaceId`、分支/HEAD、Git 状态清单和 `snapshotId`。工作区来源为 `program_observation`。同 remote 不合并本地身份；移动仓库不自动迁移身份。
- 启动清单标为 `pre_existing_unknown`，以后观察仍为 `unknown`。`relatedFiles` 只标明显式任务关联，不能据此推断作者或同文件全部改动的归属。启动内容、暂存区和 diff 均保留，后续修改不覆盖原依据。
- 快照 `schemaVersion=1`，包含指纹 `id`、带时区的 `capturedAt`、程序来源、项目/工作区、分支/HEAD、scope、按路径排序的 files 及 staged/unstaged diff blob 引用。每个文件分别保存 index 的 Git 对象 ID/模式/blob 和 worktree 的存在状态、模式、blob/长度。二进制按原始 bytes 保存。
- 指纹覆盖除 `id` / `capturedAt` 之外的清单，包含文件内容摘要、暂存区、模式、Git 比较起点、diff 与范围；保存进度或重复采集不会仅因时间使指纹变化。读取会复核清单指纹、blob 摘要和文件长度。
- 默认采集 Git 跟踪文件与未忽略的未追踪文件，排除产品状态和 Git 元数据。根 `.engineering-flow.json` 的 `additionalInputs` 可声明被忽略的文件或目录，配置本身总是采集。`scope.ignoredPaths` 列出 Git 忽略项，声明输入可覆盖忽略。未声明的忽略内容、外部依赖与执行环境不在保证范围。
- 只支持普通文件；路径越界、符号链接、submodule、未解决合并、嵌套 Git 元数据、特殊文件、缺失声明或超过 2000 文件 / 去重内容 64 MiB 均报错。连续两次完整采集不一致则拒绝保存；两次相同仍不是原子或隔离快照，不能排除短暂修改后恢复。
- `resume` 不写入当前临时快照或用户文件。结果包含持久化 task、本次 currentWorkspace/currentSnapshot、与保存快照比较的 `snapshotComparison` 和与启动基线比较的 `changesSinceStart`。status 为 `current` / `stale` / `unknown`，只说明声明范围内的内容关系，不表示代码已检查。
- 恢复时项目、工作区、分支不匹配则拒绝；detached HEAD 切到其他提交也拒绝。命名分支的 HEAD 或内容变化返回 `stale`，旧任务内容保持原样。`snapshot show` 只在相同项目/工作区读取持久化快照，支持文件的 worktree/index 层和两个 diff；文本为 UTF-8，其他二进制为 base64 JSON。
- v1 数据库只读时原样保留，首次写入在事务内增加表；M1 时升级到 v2，M2-1/M2-2 分别升级到 v3/v4，M3-1 升级到 v5，旧任务 document 不改写。旧任务后续 checkpoint 保存 v2 修订，原启动 `snapshotId=null` 保持未知，不以新采集冒充历史。未知 schema 或损坏引用拒绝处理，当前没有自动修复/历史回退命令。
- 同任务写入使用 `expected-revision`；冲突返回 `revision_conflict`。存储对锁超时、SQLite 容量不足、只读分别返回 `storage_busy` / `storage_full` / `storage_readonly`，其他读写异常返回 `storage_error`。故障验证范围见 STATUS；系统断电、真实磁盘耗尽和网络文件系统未验证。

实际 CLI 参数和配置见根目录 README。下面区分 M2-1 的已实现合同与后续对象设计；Review 材料不等于人工评审记录。

## M2-1 已实现的检查与 Review 合同

- 数据库 v3 追加 `check_runs` 与 `reviews`（均以 ID 为主键，保存 task_id 及完整 JSON）。只读 v1/v2 不迁移，首次写入事务升级；任务 schema 仍为 v2，原任务修订不改写。旧 dev1/dev2 CLI 拒绝读取升级后的库。
- CheckRun schema v1 由 Core 执行器生成，包含任务/修订、项目/工作区、配置定义、实际 argv/cwd、Python/平台、UTC 时间、执行前后快照、退出码、failure、stdout/stderr 及来源 runner。环境变量不复制。配置从执行前快照读取；不提供调用者写入 passed 的 CLI。
- 开始时将 running 与执行前快照同事务保存；结束时只允许同一次运行从 running 更新到终态，不可改写命令、任务或执行依据。终态输出与结束快照同事务保存，失败保留 running/unknown。M2-1 终态为 passed / failed / error，未运行是没有运行记录；M2-2 的 skipped 合同见下节。
- stdout/stderr 保留原始 bytes 的 UTF-8 或 base64、长度、SHA-256 和截断标记。每流最多保存 4 MiB，超限记录 error。CheckRun/Review 有完整性摘要，读取复核文档、输出和引用快照；这是损坏检测，不是身份认证或防篡改签名。
- applicability 单独计算：执行前、执行后和观察快照 ID 全同才 current；不同为 stale；仍运行或结束快照缺失为 unknown。历史 passed 不因过期改成 failed。同检查 ID 采用最近启动记录；必需项缺失/失败/错误/过期/未知均不能满足 requiredChecksPassed，未配置必需项也返回 false。
- 执行模式固定 workspace，继承调用者环境，以 POSIX 进程组终止超时或中断。未实现隔离环境、后台调度或 SIGKILL 后的子进程回收；前后采集相同不证明中途没有变化。正退出码按命令约定视为 failed；启动失败、信号、超时、输出或结束采集错误归 error，具体原因保留在 failure。
- Review schema v1 保存生成时任务修订、快照、相对启动基线的变化、同次读取的运行证据与适用性、范围限制；AI 解释和人工确认均为空。固定导出 review.json / review.md、引用清单、真实文件/diff/输出。文件包只描述生成时状态，review show 对照当前代码及任务修订返回 current/stale 和 currentVerification；build 追加新材料。
- 导出先保存数据库，后组装临时目录并 rename 到新 ID；失败可读数据库记录，但当前无文件包重建接口。调用者文字按 Markdown 文本转义，源码/日志保存在独立内容文件。HTML 安全展示、跳过和终端评审已在 M2-2 补充，见下节及 STATUS。

## M2-2 已实现的页面与评审合同

- 数据库 v4 追加不可变 `review_events`，旧 v1/v2/v3 只读不迁移，首次写入同事务升级，原任务/检查/Review JSON 保留。检查兼容 schema v1/v2，Review 兼容 v1/v2，事件 schema v1。新 HTML 模板在 wheel 内由 Python 生成，无前端或模型运行依赖。
- 显式 skip 写 schema v2 的检查记录：origin=caller、executionMode=not_executed、实际 argv 空、exitCode 空、输出空、reason 必填；检查定义及 required 原样保留。跳过纳入同 ID 最新记录选择，不能计为 passed，也不能用旧 passed 绕过。
- 新 Review schema v2 保存同次读取的 reviewRecords/reviewFeedback；aiExplanation 指向最新 AI 解释事件，旧 humanConfirmation 兼容字段保持空。真正的意见/确认位于事件集合，按各自 snapshotId 和 taskRevision 计算适用性。
- 解释事件 origin=ai，内容是 summary 与 behaviors，行为关联验收条件编号和文件/layer/行号。程序拒绝越界路径与非法结构；缺失文件、越界行号或二进制行号显示引用失效，不跳转到当前或相似文件。过期解释保留原快照代码链接，不能成为当前说明。
- 意见事件 origin=caller，含 comment / approve / request_changes、正文及 task/files 范围；没有确认人。approve 意见不等于人工确认，普通入口不接受 confirmed/actor/origin 等自报字段。
- 确认事件 origin=local_terminal，通过 ConfirmationPort 的本地交互适配器获取回执；控制终端展示完整意见/快照/范围并要求随机 challenge。actor 的 OS uid/账号/tty 来自适配器，assurance=local_session_not_identity_verified。Core 在交互前后检查快照及任务修订，保存时再次核对任务修订与所引用意见的完整性摘要。
- 这采用本机交互信任边界，不提供真人身份认证。同账号 PTY/Agent 自动化、受信适配器代码或直接数据库访问仍可模拟本地交互。测试使用自动化 PTY 与端口替身，不能据此记为真实用户批准；团队强来源需后续认证/PR Review 适配器。AT-16 当前验证范围是拒绝直接确认数据、自报身份和非交互输入。
- 确认仅作用于其明确范围；同范围最新当前确认形成 confirmedScopes，旧确认仍保留。文件确认不推导任务整体获批，任何确认不替代必需检查。代码或任务修订变化即 stale；后续同范围确认令旧记录 effective=false，页面显示历史记录。
- 固定 HTML 内联转义的代码/diff/输出，包含生成时间、静态能力说明、来源分区、六种检查展示、快照代码行锚点和受限外链（仅本地结构化材料）。CSP 禁脚本与外部资源，页面没有写入通道。review show 返回当前适用性及 refreshNeeded；即使代码未变，有新检查或意见也需 build 新页。

## M3-1 已实现的记忆合同

- 数据库 v5 追加 `memories` 与 `memory_events`，ID/任务索引及完整 JSON，正文和关系事件均不可变。只读 v1–v4 不迁移；首次写入和新快照/blob/记忆在同一事务升级，保留旧 document。旧 dev1–dev4 不能读取升级后的库。
- 记忆 schema v1：ID、taskId/taskRevision、projectId/workspaceId、snapshotId、createdAt、origin=caller、proposal 和 integrity。proposal 只接受 content/kind/scope/keywords/sources，不提供 confirmed/actor/current 等自报字段。source 引用代码的路径、层与真实行号，或同任务/同快照的终态检查/评审事件 ID；读写时核对实际记录和内容。完整性摘要只检测损坏，不提供签名。
- `confirmationStatus` 与 `applicability` 在读取时计算，不改写历史。确认来自明确包含该记忆完整文档的评审回执；创建时间、确认时间、actor、快照都可追溯。完整声明输入或所属任务修订变化即 needs_revalidation，原确认仍可保留为历史 confirmed。不通过把“来源仍在”推导为“正文正确”。
- 评审事件兼容 v1/v2，v2 增加 memories 范围，内含所选原始记忆文档，最多 16 条；普通 task/files 保持原合同。终端展示完整 scope 后确认，保存时核对原文/摘要、任务修订和快照；每条记忆采用后续独立确认，不因任务批准而自动获批，也不把记忆批准扩大成任务批准。
- 关系事件 schema v1，含 memoryId、eventType、otherId、reason、任务修订、当前快照、调用者来源与摘要。conflicts_with 双向提示；supersedes 有向且禁止循环，候选未确认时只提示差异，曾确认后旧项退出默认检索，后续撤回/归档新项不自动复活旧规则；archive 保留历史并退出默认检索。关系是显式声明，不是语义证明。
- `memory context` 和任务结果的 memoryContext 返回 selected/excluded、关系、快照、预算及限制。预算精确限制 selected 的规范 UTF-8 JSON 字节数，整条排除不截断正文/来源；遗漏项保留原因和读取参数。候选、过期与冲突内容带状态；只有已确认、current、同工作区/分支且无显式冲突的条目 eligibleAsCurrentBackground=true。
- source 删除、损坏、错误分支、复制数据库到其他 worktree、预算遗漏、未完成检查来源和事务/修订冲突均显式处理。大历史性能、自动语义识别、外部认证来源与团队共享尚未实现。

## M3-2 已实现的文档与交接合同

- 数据库 v6 追加不可变 `document_proposals`。只读 v1–v5 不迁移；首次写入、快照/blob/文档建议和 schema 升级同事务提交，旧任务 JSON 保留。包 dev6；旧 dev1–dev5 不能读取升级后的库。
- 文档建议 schema v1 保存调用者输入 proposal、任务修订/快照、before/after/patch、voice 和 integrity。输入为 target/mode/region/draft/reason/sources/protectedFacts；只能引用同任务/快照的实际来源。原文从保存的 worktree blob 读取，读取时重新计算 after/patch 并核对原文、来源及摘要，不接受自报 confirmed/current/actor。
- mode 区分 manual/generated/mixed；完整生成标记与命名区域由 Core 验证，混合区域外字节保持原样。程序只保存和导出建议，不改工作区。文档被应用后完整输入快照改变，旧结果按既有合同失效，不把内容恰好匹配当作已确认应用事件。
- voice 初始 not_requested；显式加载固定 Skill 返回 loaded 或 unavailable，modelExecution=not_observed。rewrite 绑定原建议完整性及固定模块摘要，追加新的文档候选，原始草稿保留。常见保护区、数值/已识别单位、敏感词序及显式事实变化时 status=rejected、after 使用原稿；否则 protected_checks_passed，仍是候选。此结果不是自动语义等价判断或人工批准。
- Review 与文档范围事件新增 schema v3，旧 v1/v2 继续读取；确认沿用现有本地终端适配器。documents 范围内嵌完整不可变建议，保存和读取时与数据库原件核对。任务/文件/记忆与文档确认互不推导；分组后各条目单独选择最新确认。确认状态与 needs_revalidation 分开，终端信任边界保持原样。
- 新 Review 附带 documents 和 handoff；task resume 也返回文档状态。task handoff 共用一次 Review 构建，固定导出 handoff.md/json 和各建议原文/修改/patch。代码/任务/证据/记忆/文档状态改变时 show 返回 refreshNeeded，历史材料不改写。交接仅保存程序观察和调用者下一步，completion=not_asserted，不新增任务完成状态。

## 基本对象

以下仍包含后续 Handoff 等规划对象。

| 对象 | 主要字段与含义 |
| --- | --- |
| Project | 本地项目 ID、仓库来源、根目录、配置版本 |
| Workspace | worktree 标识、当前分支、当前 HEAD、工作区路径 |
| Task | ID、目标、验收条件、进度、关联文件、启动快照、未决事项 |
| Snapshot | ID、仓库与 worktree、比较起点、输入清单、内容指纹、采集范围 |
| CheckRun | 检查 ID、命令、开始与结束时间、执行快照、退出状态、输出引用 |
| ReviewRecord | 范围、对应快照、意见、显式操作来源、确认状态 |
| MemoryRecord | 内容、类型、适用范围、来源、确认状态、有效性 |
| Handoff | 任务、完成情况、下一步、待确认记录、对应快照 |

所有持久记录包含 `schemaVersion`、稳定 ID 和时间。运行时自行产生的观察记录与 AI 提议分别存储。字段调整需要兼容旧数据或有迁移说明。

## 任务状态与检查状态分开

任务可以采用以下候选状态：

```text
draft → active → review_ready → completed
           ↑          |
           └── rework ┘
```

`review_ready` 表示材料已准备并明确列出了缺项，不代表代码已获批准。`completed` 表示任务按选定流程完成交接，不能自动推导为已合并、已发布或所有检查通过。

阻塞原因、等待反馈和下一步作为独立字段，避免用大量任务状态代替具体说明。

检查执行状态建议为：

- `planned`：计划运行。
- `running`：运行中。
- `passed`：已执行且满足该检查的成功条件。
- `failed`：已执行且业务断言或检查条件失败。
- `error`：检查无法正常完成，例如命令不可用或输出解析失败。
- `cancelled`：被取消或中断。
- `skipped`：明确跳过，并说明原因。

没有 CheckRun 的检查显示“未运行”。检查的历史执行结果保持不变，另行计算它对当前代码的适用性：`current`、`stale` 或 `unknown`。

## 快照范围

HEAD 不能代表尚未提交的代码。快照至少记录：

- Git 比较起点、当前 HEAD 和 worktree 标识。
- 追踪文件的当前内容变化，包括增加、删除、重命名及必要的模式变化。
- 明确纳入的未追踪源码与检查输入。
- 与检查相关的配置和依赖描述文件。
- 采集时忽略的范围及理由。

Core 自身的日志、报告和生成状态应从输入指纹中排除，避免每次保存报告都使检查失效。项目忽略规则不能无声地排除会影响验证的源码；无法确认输入范围时说明限制。

首版可以对已声明的完整源码输入集保守失效，再逐步引入可靠的依赖范围。不能为了减少重新检查而猜测“这个文件应该无关”。

文件路径以受支持的仓库根为基准，拒绝越界引用；符号链接等特殊情况需要明确采集策略并记录范围。

## 检查与并发修改

运行前后都采集输入快照。发现变化时，检查结果不得标为当前代码的有效结果。前后快照相同仍不能完全证明执行期间没有并发修改，因此同时记录执行方式。

首版在当前工作区执行时如实说明该限制。严格要求下，在准备好的独立快照中执行并验证依赖环境；不要把仅比较前后文件的实现描述为完全隔离。

执行记录保存命令与参数、工作目录、必要环境版本、开始和结束时间、退出码、输出位置和超时情况。避免复制所有环境变量。退出码为 0 也应依据检查语义核对，例如“未发现任何测试”不自动满足有测试数量要求的检查。

## 示例：检查执行记录

以下为构造数据，不代表项目已有该命令或测试结果：

```json
{
  "schemaVersion": 1,
  "id": "demo-check-001",
  "taskId": "demo-task-001",
  "checkId": "unit-tests",
  "snapshotId": "demo-snapshot-before",
  "snapshotAfterId": "demo-snapshot-before",
  "executionMode": "workspace",
  "status": "passed",
  "exitCode": 0,
  "outputRef": "checks/demo-check-001/output.txt",
  "origin": "runner"
}
```

运行记录由检查执行器写入。模型可以建议需要哪些检查，但不能通过提交相同结构的数据伪装成执行器已经执行。

## 改动归属

任务启动时保存已有改动清单。以后分别标识：启动时已有、本任务明确关联、归属待确认。对同一文件中已有修改和新修改混杂的情况保留 diff 对比，不能只按文件名将整份修改归入任务。

报告可以说明“当前任务涉及的改动”，不默认断言“全部由 AI 生成”。代码作者归属不从单次 diff 推断。

## 失效传播

1. 输入变化后，受影响的检查适用性变为 `stale` 或 `unknown`。
2. Review 页面的解释和代码引用标记为针对旧快照。
3. 评审确认保留在旧快照上，不迁移为新代码已获确认。
4. 依赖变化内容的记忆进入待核验状态。
5. 完成新的检查、解释或评审后，生成新的记录版本。

本地静态页面无法在关闭后自动观察代码。页面必须显示生成时间和快照，并在打开或显式刷新时重新比较；只有具备运行中的观察程序，才承诺实时提示。

## 完成、交接与恢复

交接至少包含当前快照、最后进度、下一步、未运行或过期的检查、待确认决定和文档状态。恢复时先核对项目、worktree、分支和代码变化，再选择适用上下文。

发现不匹配时返回差异并提供选择，不静默覆盖当前工作。旧分支知识可作为历史参考，但必须标明来源与待核验状态。

并发写入采用锁或记录版本比较；写入中断后恢复最后有效版本。损坏或缺失的记录应可诊断，不能假造一个成功状态继续执行。
