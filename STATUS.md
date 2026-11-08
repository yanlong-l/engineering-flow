# 当前开发状态与下一次交接

更新日期：2026-11-08。本文件是开发交接入口；结论以实际代码、运行记录和下列支持边界为准。

## 当前阶段

**M5 构造试点与明确范围内的技术验收完成，形成可安装的本地首版候选。** M0–M4 的正式产品实现、目标宿主和安装结果已核对复用；M5 完成可重复执行的 Python 构造流程、FR-01–FR-16 / AT-01–AT-16 逐项证据及范围判定。完整报告见 [M5 验收](docs/14-m5-acceptance.md)。

当前产品仍为 **0.1.0.dev8**，Python >=3.14，数据库 **v6**。M5 不改产品运行时代码、数据库或宿主资源。真人语义评审、真实团队试点和收益测量未做；程序/PTY 模拟不能冒充真人批准。用户后续已授权保存累计实现并推送 Git 分支，版本保存核对见下节；没有公开发布或 PR。

## 本轮实现（M5）

- 新增 `tools/run_pilot.py`：在全新构造 Git 仓库编排独立 `-I -m engineering_flow` 进程。故意缺陷失败→复制已有正确实现修复→检查错误/跳过→Review/解释/意见→候选记忆冲突→文档规则加载及错误改写拒绝→应用原稿后的失效→重新检查/交接/新进程恢复。修复来自既有示例，不声称模型发现或生成。
- 每次完整运行 **43 条命令、34 项程序断言**。保存实际产品/输入摘要、解释器/平台、参数/工作目录/退出码/经过时间、原始 stdout/stderr 及摘要；同目录保留脚本副本、独立仓库、SQLite 和 Review。失败不删除现场，已有输出目录拒绝覆盖。
- 新增 `make pilot-check`，纳入 `make check`；项目新增 required `pilot`（90 秒），保留原 unit-tests、copilot-runtime、example 三项 required，不新增个人关闭通道。
- 新增 `docs/14-m5-acceptance.md` 的 P0/AT 证据表和首版范围；同步 README、示例说明、路线、交接与决定。FR-14 个人展示限定为按调用 summary/full；持久个人设置/多预设延期。仍默认无产品 Hooks，不增加模型服务或多 Agent。
- 可安装候选继续采用本地 dev8 wheel，验收脚本由源码仓库提供。仅 wheel 元数据 README 更新，包内 **39 个产品文件与 M4 逐字一致**，无需人为改运行时版本。

## 仓库与改动归属

- 工作目录 `/Users/yanlong/projects/engineering-flow`；分支 **feat/m1-task-persistence**，M5 开发基线 HEAD **7e5c11f204e208e0927206d475821e22c4f9d928**。当前 HEAD、远程跟踪及工作区状态以 Git 查询为准；累计 M0–M5 实现纳入本次版本保存。
- 开始前 **83 个文件**备份在 `.local/development-round-9/initial-files/`，摘要/状态在 initial-files.json、initial-git.txt，数据库为在线备份 initial-state.sqlite3。上轮 **64 个受检文件全部匹配**；已有改动按 unknown/pre_existing_unknown 保存，不自动归为本轮或 AI。
- 本轮新增 tools/run_pilot.py、docs/14；修改 .engineering-flow.json、Makefile、README、示例 README、docs/08/09/10 和本 STATUS。其余已有文件不改写；逐文件差异见 round-changes.json。
- 根任务 **4285079dfa3e42e8a5653b8fad577a74** 在实施前创建，最终 checkpoint **revision 3**。上一轮任务与原证据保留；本轮初始数据库的 **17 条历史任务修订 JSON 全部原样保留**，schema v6、integrity_check=ok。

## 版本保存核对（2026-11-08）

- 用户明确要求 commit 并 push，目标为现有分支 `feat/m1-task-persistence` 和 `origin`（`https://github.com/yanlong-l/engineering-flow.git`）。提交范围为产品、测试、示例、配置与文档共85个文件；本地运行记录、数据库、虚拟环境及 wheel 仍按忽略规则排除。
- 保存前重新核对65个受检文件，全部匹配 M5 指纹；`git diff --check` 通过，候选文件扫描未发现高置信度凭据、二进制或超过1 MiB的文件。完整暂存检查发现 `tests/support.py` 多一个末尾空行，已仅移除一个换行符并核对 Python AST 完全相同，其余64个受检文件保持原字节。未重复运行未受影响的测试，实际161项结果仍对应上文快照。
- 默认 Git 连接因本机 `127.0.0.1:17890` 代理不可用失败；仅在本次命令中禁用该代理后，`ls-remote` 成功且未返回分支。没有改动持久 Git 代理配置。
- commit/push 的实际 SHA、远程确认与操作输出保存在 `.local/git-publish-20261108/`；后续交接用 `git log -1` 和 `git status -sb` 核对当前版本，不将基线 SHA 当作最新 HEAD。

## 实际检查与安装验收

沿用已验证本机 macOS / Apple Silicon、Python **3.14.3**、SQLite **3.52.0**、Git **2.49.0**。M4 宿主为 VS Code **1.137.0** / 内置 Copilot Chat **0.65.0** 的 **Copilot** 会话；本轮未更新/重注册宿主，不外推其他电脑、系统或版本。

| 实际检查 | 结果与范围 |
| --- | --- |
| 根 required unit-tests | **161 项，259.168 秒，全部通过、无 skip**；CheckRun `5ed0f53c94264d8db983fe4367adf257` |
| 根 required copilot-runtime | passed/current（检查完成时）；CheckRun `1f37959548144bfca86893c8f1d93930` |
| 根 required example | **四例通过**；CheckRun `74a31ee6db7849dabc94d334473199c7` |
| 根 required pilot | **43 命令 / 34 断言通过**；CheckRun `f66192551f5b4f6891d98002917f9440`，16.751 秒为脚本自身经过时间 |
| 最终开发环境试点 | **43/34 通过**，16.031 秒；独立新进程恢复修订3、当前必需项通过，无人工确认 |
| 干净 wheel 安装试点 | 新 venv 无系统包、从本地 wheelhouse 无索引安装 dev8[copilot]；**43/34 通过**，17.653 秒，-I 实际导入本 venv 的 site-packages |
| 安装版诊断与插件 | pip check、doctor --require-mcp、plugin build/inspect 通过，ready=true；没有注册 IDE 插件或自动执行 Hooks |
| 原始材料 | 三份完整试点的命令退出码、原始流长度/摘要、输入与实际产品摘要全部核对；Review 文件/diff/输出摘要、转义及锚点检查通过 |
| FR/AT 证据 | **32 行**对应表，引用的 **34 个测试方法**在本轮161项中实际通过；来源和未验证范围单列，不从索引推导真人认可 |
| 依赖/格式 | 开发环境、隔离安装环境 pip check 无损坏依赖；git diff --check 通过 |
| 数据保留 | 原17条任务修订原文不变，数据库v6，integrity_check=ok；已有试点输出拒绝覆盖并保持原摘要 |

四项 required 在快照 **6c7d24228a3e116609c7272d21201c425ecff68614fa5a3c907e94226b22a8af** 同为 passed/current、requiredChecksPassed=true，见 root-checks-current.json。随后仅补充验收结果与交接文档，完整声明输入改变，**最终根任务旧检查保持 passed，但 applicability=stale、requiredChecksPassed=false**。没有把旧快照通过冒充最终全部文档已验证。

**65 个受检源码/资源/测试/示例/配置/构建文件保持原字节**，指纹 **e820c4ea44571ee44c9e81ea71751ae4921cc63f5d7ac1afeeeab5c24ae275fa**，见 checked-code.json 与 handoff-checks.json。最终文档变更不修改测试断言或产品行为。

## 失败、范围与未验证事项

- 首轮 pilot-dev-first 因验收脚本错误读取不存在的 confirmations 字段而失败，修正为检查实际 reviewRecords 事件后重跑；原始失败现场保留。初次 pilot-dev 也保留，最终使用同步示例说明后的 pilot-dev-final。构造业务断言失败、超时、缺命令、跳过、旧快照和错误改写均如实保留。
- 本轮尝试 `file:` 本地浏览器预览时被环境协议策略拒绝，未绕过；本轮只完成 HTML 解析、脚本转义、锚点/本地引用及字节核对。既有实际页面打开结果维持原范围，没有新增视觉验收结论。
- **一个预置场景的重复运行**不算多个业务样本。自动执行时间不代表工程师投入、理解/评审/续接成本或节省工时；没有真人对照或团队收益测量，前期产品建设和维护投入未计时。
- 确认正向测试使用受信测试端口或自动 PTY，非交互和伪造状态被拒绝；没有真正的人类批准或身份认证。表达保护覆盖固定七组回归及本次预置错误改写，M4 两次真实宿主案例沿用；真人语义评审与通用语义等价未验证。
- 只支持已验证本机组合、绑定一个本地工作区和 Python + SQLite 构造示例。跨电脑/客户端安装、自动身份迁移、多仓库路由、持久个人配置、多预设、团队共享/认证来源、外部连接及大历史性能未验收。
- Hooks 关闭，无自动 checkpoint、后台恢复、强杀后的孤儿回收或热升级保证。快照覆盖声明输入，未声明忽略文件/外部依赖及中途修改后恢复不在保证内；静态页需显式 show/build 刷新。损坏自动修复、断电、真实磁盘耗尽与其他平台未验收。
- 项目整体许可和公开发布可见性仍未指定；本地候选不表示已发布。

## 证据与复核入口

本轮目录 **`.local/development-round-9/`**。M4 完整交接在本轮 initial-files/STATUS.md；round-8 的宿主、MCP 分页、升级/回退及无 SDK 证据保留且摘要纳入 acceptance-index.json。本轮39个产品文件与其受检版本相同，未冒充重新进行宿主模型验收。

- root-unit.json、root-runtime.json、root-example.json、root-pilot.json：真实产品执行器 CheckRun；root-checks-current.json 保存文档补录前四项 current；root-final-resume.json 保存最终真实适用性。
- pilot-dev-final/pilot.json：任务 **4cce24aa11744d0db2617337df7ef7e7**，最终 Review **4c73a058f8344c6da6e0214a5ea69f55**，修订3。对应 repo/.engineering-flow/reviews/ 下保留 HTML、原始引用与交接。
- pilot-installed/pilot.json：安装版任务 **83af62bcc16d4362a107d68d352a830b**，最终 Review **11fa047998234f348035115c0f597f5a**，修订3；所有失败、跳过和过期记录保留，未生成 confirmation 事件。
- acceptance-index.json / index_acceptance.py：从真实 CheckRun 的 unittest 原始输出核对32行/34个引用方法；复核三份43命令/34断言试点的全部原始流和摘要。索引只证明所列程序证据，不计算人类认可或团队收益。
- install.json、artifact-checks.json、installed-doctor.json、plugin-inspect.json、wheel.log：安装、导入路径、插件与产物。候选为 **candidate/engineering_flow-0.1.0.dev8-py3-none-any.whl**，SHA-256 **a59bf3c0badf527760c7bc1c09d2c374a44909cd31c68302674e12232aff9a36**，与 dist/ 同名产物一致；未上传。
- checked-code.json、handoff-checks.json、round-changes.json、database-checks.json：受检文件指纹、最终分支/快照/适用性、实际变更及数据完整性。记录仅保存在本机，不含全部会话或凭据。

根任务续接：

```sh
.venv/bin/engineering-flow task resume 4285079dfa3e42e8a5653b8fad577a74
```

## 下一次工作的起点

1. 先核对本分支、HEAD/upstream、工作区状态、M5受检指纹和本次保存清单（support.py仅末尾空行格式修正），恢复上述修订3，读取 M5 报告。文档补录及后续 Git 提交导致根检查 stale 是预期事实；如需最终完整输入均为 current，按当前输入重跑四项 required，不修改旧结论。
2. 技术候选可用于后续真人评审或实际任务试用：选择一个明确验收的小需求，记录实际理解/定位/续接、遗漏与返工，以及准备/安装投入；由操作者判断文档语义和 Review 意见。当前未观察到真人操作，不提前填写通过或收益。
3. 后续代码/环境改变时按影响重新验证；P1/P2、自动 Hooks、团队后台、发布及许可分别决定，不把它们默认纳入已完成首版范围。
