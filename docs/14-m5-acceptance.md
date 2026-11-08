# M5 构造试点与首版验收

日期：2026-11-08。试点对象为自行编写的 `examples/batch-queue`，数据、重复请求缺陷、相反记忆和错误改写均为预置构造内容。修复时复制已有正确实现，未让产品自动发现缺陷或调用模型生成修复。本轮没有接入业务平台、设备或外部模型服务。

## 复现和证据

在已按安装说明安装产品的 Python 环境中，从本源码目录执行：

```sh
make pilot-check
# 或指定一个尚不存在的证据目录
.venv/bin/python -B tools/run_pilot.py --output .local/my-pilot
```

脚本新建独立 Git 仓库，全部产品操作通过该 Python 的 `-I -m engineering_flow` 独立进程调用；可用干净 wheel 安装环境的 Python 再运行同一脚本。默认产物位于 `.local/pilot-runs/随机ID/`，不提交源码仓库。重复指定已有目录会拒绝；失败时保留现场，不清理或覆盖原记录。脚本不注册宿主插件，不启动 Hooks，不输入终端确认 challenge。

`pilot.json` 包含实际产品文件及输入摘要、解释器/平台、43 次命令的参数/工作目录/退出码/经过时间、stdout/stderr 的路径与摘要，以及34项程序断言。`run_pilot.py` 副本和原始流同目录保留，SQLite 与 Review 包在 `repo/.engineering-flow/`。摘要用于完整性核对，不是签名或人类身份凭证。`status=passed` 只表示构造流程满足这些断言。

本轮证据统一保存在 `.local/development-round-9/`：

| 入口 | 作用 |
| --- | --- |
| `baseline-verification.json`、`initial-files/` | 开始前83文件备份；上轮64个受检文件全部匹配 |
| `pilot-dev-final/pilot.json` | 开发环境完整试点；任务 `4cce24aa11744d0db2617337df7ef7e7`，最终修订3 |
| `pilot-installed/pilot.json` | 新 venv、安装 wheel 后的同一试点；与 editable 运行分别记录 |
| `root-unit.json`、`root-runtime.json`、`root-example.json`、`root-pilot.json` | 本轮根任务真实执行器记录，失败/skip/current/stale 按记录原值判断 |
| `install.json`、`artifact-checks.json` | 独立安装、实际导入路径、依赖和 wheel/产品文件摘要 |
| `acceptance-index.json` | FR/AT 所指测试是否实际通过及试点收据核对 |
| `handoff-checks.json` | 最后快照、源码指纹及交接后适用性 |

M4 已验证的目标宿主、安装升级与无 SDK 降级沿用 round-8 的 `copilot-acceptance.json`、`final-mcp.json`、`acceptance-summary.json` 和 `base-final.json`；其产品源码与本轮开始指纹相同。本轮未重装 VS Code 插件、重跑宿主模型或宣称新的真人批准。

## 本轮实际结果

| 检查 | 实际结果 |
| --- | --- |
| 根任务 unit-tests | 161项，259.168秒，全部通过、无skip；CheckRun `5ed0f53c94264d8db983fe4367adf257` |
| 根任务 copilot-runtime | passed/current；CheckRun `1f37959548144bfca86893c8f1d93930` |
| 根任务 example | 四个行为案例通过；CheckRun `74a31ee6db7849dabc94d334473199c7` |
| 根任务 pilot | 完整43命令/34断言通过；CheckRun `f66192551f5b4f6891d98002917f9440` |
| 最终开发环境试点 | 16.031秒；43命令/34断言，最终修订3；时间只表示程序经过时间 |
| 干净安装环境试点 | 17.653秒；同一43命令/34断言，任务 `83af62bcc16d4362a107d68d352a830b`；实际导入该 venv 的 site-packages |
| 安装包/插件 | 无系统包 venv、无索引安装 dev8[copilot]，pip check、doctor --require-mcp、plugin build/inspect通过；39个产品文件与源码/安装版一致 |
| 逐项索引 | 32行 FR/AT 对应表，所引34个测试方法全部实际通过；三份试点原始流的字节数/摘要、预期退出码及输入/产品摘要核对通过 |
| 仓库与数据 | git diff --check、开发/安装环境依赖检查通过；开始前17条任务修订JSON原样保留，schema v6、integrity_check=ok |

四项 required 在快照 `6c7d24228a3e116609c7272d21201c425ecff68614fa5a3c907e94226b22a8af` 同为 passed/current，`requiredChecksPassed=true`，见 `root-checks-current.json`。随后只更新本报告和交接说明，最终完整输入变化，根任务旧检查保留 passed 但适用性为 stale；65个受检代码/资源/测试/示例/配置/构建文件保持原字节。没有把旧快照通过冒充最终全部文档已受检。

本轮本地 wheel：`engineering_flow-0.1.0.dev8-py3-none-any.whl`，SHA-256 `a59bf3c0badf527760c7bc1c09d2c374a44909cd31c68302674e12232aff9a36`；包内产品文件与M4相同，wheel元数据的README已更新。候选副本在 round-9/candidate/，没有上传或发布。

## 贯穿流程和观察

1. 构造 Git 提交含故意重复创建的实现，开始任务前制造同文件暂存/未暂存修改；启动记录保留 `pre_existing_unknown`。
2. 调用者进度声称通过，Review 仍显示必需项 `not_run`。实际四例检查在缺陷实现上失败；保存真实断言输出。
3. 换为已有正确 SQLite 实现，HEAD 不变，checkpoint 升至修订2。四例检查覆盖连续重试、内容冲突、重开数据库、同机四实例并发，passed/current。
4. 可选检查实际产生命令不存在、超时、故意失败和脚本样式日志；另有未运行项。跳过必需项后 `requiredChecksPassed=false`，重新执行才恢复通过，项目 required 保留。
5. 生成 Review，导入明确标为 AI 的构造解释和调用者意见。非交互确认被 `confirmation_source` 拒绝；全程没有 confirmation 事件。
6. 保存两条相反候选并显式声明冲突，保留各自来源。文档规则显式加载，错误改写被拒绝且原稿保留；导出不写目标文件。
7. 仅在构造仓库中用 `git apply` 应用原稿，旧检查/Review/解释/意见/记忆失效，旧 HTML 原样保留。checkpoint 升至修订3，重新检查、生成交接，独立进程恢复相同记录。切到其他分支会拒绝续接。

HTML 的脚本转义、唯一锚点、本地链接和原始文件/diff/日志摘要均由程序核对。本轮尝试本地 `file:` 浏览器预览时被环境的协议策略拒绝，未绕过；本轮没有新增视觉验收结论。历史实际打开页面的结果保持其原有范围，参见 M2/M4 交接。

## P0 对应表

以下测试名是 `tests/` 中实际 unittest 方法，完整名称和本轮运行结果见 `acceptance-index.json`。程序模拟或 PTY 只验证合同，不等于真人操作。首版按显式本地流程验收；适用范围在此逐项说明。

| 要求 | 实现与实际证据 | 首版范围/未验证 |
| --- | --- | --- |
| FR-01 单一入口 | M4 真实 Copilot 开始/续接/Review/交接；`test_cli_and_mcp_share_revision_snapshot_and_stale_results`；试点43命令 | 一个正式 Agent、两个内部 Skills、八组共享 Core 工具 |
| FR-02 初始化/诊断 | 试点 doctor；`test_diagnostic_does_not_execute_or_create_state_or_claim_host`、`test_invalid_configuration_and_missing_inputs_are_diagnosed` | 显式 Git 仓库及配置，不自动配置任意业务项目 |
| FR-03 任务记录 | 试点 start/checkpoint/新进程 resume；`test_create_checkpoint_and_new_process_resume_exact_record` | 目标/验收/关联文件/进度/未决事项；任务完成不自动断言 |
| FR-04 已有改动 | 试点暂存与未暂存内容；`test_preexisting_and_later_changes_in_one_file_keep_evidence_and_unknown_ownership` | 归属未知，不推断作者 |
| FR-05 上下文选择 | 试点 conflicting-context；`test_task_paths_modules_keywords_and_project_scope_choose_relevant_records`、`test_budget_exact_utf8_boundary_and_all_omissions_have_read_references` | 确定性检索、预算及继续读取；无语义检索 |
| FR-06 真实检查 | 试点 intentional-defect/repaired-check/missing-command/timeout/known-bug | 原始流、退出码、前后快照；本机工作区执行 |
| FR-07 Review 页面 | 试点 explanation、三次材料引用核对；`test_explanation_links_exact_snapshot_line_and_flags_invalid_references` | 固定 HTML 行号/diff/输出路线；本轮新视觉预览未完成 |
| FR-08 变化失效 | 试点 stale-review/stale-memory；`test_run_mutating_source_is_historical_pass_but_stale` | 完整声明输入保守失效，外部依赖不在快照内 |
| FR-09 人工记录 | 试点拒绝非交互；`test_confirmed_scope_is_bound_to_snapshot_and_survives_restart`、`test_real_terminal_adapter_challenge_and_cancellation_via_automated_pty` | 范围/快照/本机来源可保存；正向确认是模拟，未获真人批准、无身份认证 |
| FR-10 恢复隔离 | 试点 new-process-resume/wrong-branch；`test_same_branch_name_worktrees_have_distinct_identities`、`test_kill_after_blobs_and_snapshot_before_task_commit_recovers_last_revision` | 独立进程/分支/worktree；不承诺崩溃后后台继续 |
| FR-11 项目记忆 | 试点双候选冲突/过期；`test_deleted_confirmed_source_keeps_history_but_is_not_current_background`、`test_proposed_replacement_does_not_hide_old_rule_and_confirmed_replacement_is_traceable` | 显式来源/关系和状态；无自动矛盾识别 |
| FR-12 文档维护 | 试点 propose/export/apply 后失效；`test_mixed_only_replaces_unique_region_and_preserves_outside_bytes` | Markdown 显式建议，不自动分析全部受影响文档或静默应用 |
| FR-13 表达模块 | 试点 voice/rejected-rewrite；`test_fixed_upstream_semantic_regressions_reject_condition_negation_scope_and_strength_changes`、M4 真实宿主改写 | 固定 Markdown 规则/许可和保护；七组固定语义案例，通用等价与真人语义评审未验证 |
| FR-14 配置/展示 | 四个项目 required；`test_default_summary_read_and_stale_observation_share_core`、`test_full_json_and_raw_rule_pointer_preserve_conditions_and_binding` | 一个默认显式流程、项目 argv、按调用 summary/full；持久个人配置/多预设延期 |
| FR-15 无 Hooks | 全部试点显式命令；`test_plugin_export_binds_paths_preserves_existing_and_has_no_hooks` | 产品 Hooks 默认关闭，无自动 checkpoint 承诺 |
| FR-16 来源区分 | 试点 AI 解释/程序 CheckRun/调用者意见；`test_unrun_required_check_and_caller_text_do_not_become_pass_or_confirmation`、`test_failed_check_and_ai_explanation_sources_keep_their_actual_origins` | 三类来源及适用性分开；调用者不自动等于人类 |

## 关键可信度场景

| 场景 | 本轮可复核依据 | 结论的边界 |
| --- | --- | --- |
| AT-01 已有改动 | 试点 start；`test_existing_staged_unstaged_untracked_and_rename_are_observations` | 保留原内容和未知归属 |
| AT-02 worktree 隔离 | `test_same_branch_name_worktrees_have_distinct_identities`、`test_different_worktree_has_no_task_and_copied_database_is_rejected` | 真实临时 Git worktree |
| AT-03 HEAD 不变 | 试点 repair-checkpoint、stale-review；`test_head_unchanged_content_changes_are_stale_and_saved_content_survives` | 未提交和未追踪内容计入 |
| AT-04 检查期间修改 | `test_run_mutating_source_is_historical_pass_but_stale`、`test_post_snapshot_error_is_saved_and_never_passed` | 前后观测；不排除中途变化后恢复 |
| AT-05 失败/超时/缺命令 | 试点 intentional-defect/timeout/missing-command | failed 与 error 分开保留 |
| AT-06 AI 自称通过 | 试点 unrun-review；`test_unrun_required_check_and_caller_text_do_not_become_pass_or_confirmation` | 无执行记录则未运行 |
| AT-07 评审后修改 | 试点 stale-review；`test_opinion_is_not_confirmation_and_changed_code_invalidates_old_confirmation` | 正向确认由测试端口模拟；旧确认不沿用 |
| AT-08 已确认来源删除 | `test_deleted_confirmed_source_keeps_history_but_is_not_current_background` | 模拟确认后真实删除；历史来源仍可读 |
| AT-09 矛盾决定 | 试点 conflicting-context；`test_conflicting_decisions_keep_sources_and_do_not_merge_into_rules` | 调用者显式声明冲突，不自动语义判断 |
| AT-10 中断与重启 | `test_sigterm_records_interruption_and_sigkill_leaves_unknown_running`、`test_kill_after_blobs_and_snapshot_before_task_commit_recovers_last_revision` | 真实进程/事务中断；非断电、非孤儿回收 |
| AT-11 无 Hooks | 全部试点与 M4 正式宿主流程 | 显式操作可用；自动保存延期 |
| AT-12 必需项不可个人关闭 | 试点 skip-required/resume-skipped；`test_required_skip_preserves_requirement_and_supersedes_earlier_pass` | 无个人关闭接口；团队制度仍需 CI 落实 |
| AT-13 脚本文本 | 试点 log-text/HTML 检查；`test_html_covers_all_states_and_escapes_code_logs_and_caller_text` | 解析/转义/引用通过，本轮浏览器预览受策略阻止 |
| AT-14 旧静态页 | 试点 stale-review；`test_old_review_stays_bound_to_old_code_and_refresh_shows_stale_checks` | 旧包不改写；show/build 显式刷新 |
| AT-15 改写条件/否定 | 试点 rejected-rewrite；七组固定回归测试 | 拒绝并保留原稿；未证明一般语义等价 |
| AT-16 伪造确认 | 试点 noninteractive-confirm；`test_caller_cannot_set_confirmation_identity_or_use_noninteractive_input`、`test_proposal_cannot_self_confirm_or_claim_identity_and_needs_real_sources` | 拒绝直接状态/身份及管道；同账号终端自动化属于信任边界 |

## 样本、失败及投入

样本为**一个预置场景**在开发环境和干净安装环境重复运行，不算两个独立业务样本。自动脚本经过时间只描述机器执行，不是工程师投入、理解成本、Review 时间或节省工时。没有对照组、真人理解/续接测量、团队采用或收益估计；产品开发、配置和前期 M0–M4 建设也未计时，不用自动执行耗时替代它们。

首轮 `pilot-dev-first` 在恢复后的断言错误读取了不存在的 `confirmations` 字段，脚本失败；修正为核对实际 `reviewRecords` 的 confirmation 事件后重跑，原失败现场保留。这是验收工具缺陷，未当作产品通过。构造业务失败、超时、缺命令、跳过、过期和错误改写均保留原始记录。

## 首版范围判定

**M5 构造试点与上述范围内的技术验收完成，形成可安装的本地首版候选。** 技术候选继续使用 **0.1.0.dev8 / 数据库 v6**，本轮不改产品运行时代码、数据库或宿主资源版本。候选包与验收工具分开：wheel 安装产品；源码仓库提供可复现验收脚本。只承诺已验证本机组合和 Python + SQLite 构造示例。

FR-01–FR-16 和 AT-01–AT-16 按上表范围具有程序或既有宿主证据。FR-09/AT-07/08 的确认正向测试、FR-13/AT-15 的语义保护有明确限制；FR-14 只支持按调用展示偏好。真人语义评审、一般语义保证、跨电脑安装、真实团队试点和收益测量继续保留为未完成事项，不作为通过记录。公开发布、可见性和 P1/P2 扩展另行决定。
