# 批量任务重复请求：构造案例

这是自行编写的 Python + SQLite 示例，只保存本地批次和任务，不执行 Case、不连接生产设备或公司系统，也不是已接入的业务平台。

需求：同一个请求标识携带相同 Case 列表时复用原批次及任务；相同标识携带不同列表时报错。`batch_queue.py` 用 SQLite 事务实现，`buggy_queue.py` 故意每次创建新批次，用于展示真实检查失败。检查脚本显式加载四个案例：连续重试、请求内容冲突、重新打开数据库、同机四个实例并发。

M5 完整复现可在产品源码根运行 `make pilot-check`。它在新目录中从预置缺陷开始，经历失败、以现有正确实现修复、跳过、Review、文档应用后失效和新进程续接；原始输出及任务保留在 `.local/pilot-runs/随机ID/`。修复来自本例已有代码，不表示产品自动发现或模型生成；范围和逐项证据见 [M5 验收](../../docs/14-m5-acceptance.md)。

在 Engineering Flow 仓库运行：

```sh
.venv/bin/python -B examples/batch-queue/check_idempotency.py
# 下面的故意缺陷实现应返回非零，并显示真实断言失败。
.venv/bin/python -B examples/batch-queue/check_idempotency.py --implementation examples/batch-queue/buggy_queue.py
```

为了让示例配置成为 Git 仓库根配置，复制到单独的临时目录（不需要提交）：

```sh
EF_CLI="$PWD/.venv/bin/engineering-flow"
EF_DEMO=$(mktemp -d)
cp -R examples/batch-queue/. "$EF_DEMO/"
git -C "$EF_DEMO" init -b main
"$EF_CLI" --workspace "$EF_DEMO" task start \
  --goal '批量任务重试复用原批次' --accept '相同请求不重复创建任务' --file batch_queue.py
```

把返回的 `task.id` 替换到以下命令中的 `TASK_ID`：

```sh
"$EF_CLI" --workspace "$EF_DEMO" check run TASK_ID idempotency
"$EF_CLI" --workspace "$EF_DEMO" check run TASK_ID known-bug
"$EF_CLI" --workspace "$EF_DEMO" review build TASK_ID
"$EF_CLI" --workspace "$EF_DEMO" task resume TASK_ID
```

`idempotency` 是必需检查，四个案例应通过。`known-bug` 是可选的故意失败演示，执行器返回 stdout JSON 和退出码 3；它不替代必需检查。生成材料包含两次真实运行及原始输出，新进程恢复可读取同一记录。

修改临时目录里的 `batch_queue.py` 后，再执行 `task resume` 或 `review show REVIEW_ID`：历史 passed 保留，适用性变成 stale，必需项不再计为当前通过。保存修改并重跑 `idempotency`、重新 `review build` 后才会有对应新内容的证据包。旧文件包保留生成时快照；它不会实时检测文件变化。

范围：并发检查仅覆盖同机 SQLite 实例，不验证分布式服务、设备调度、网络超时或真实团队收益。所有测试数据与缺陷均为构造内容。

M2-2 的 `review build` 还生成 `review.html`，可用浏览器直接打开。它展示生成时快照、六种检查状态、原始内容和精确代码行链接，修改后需显式 build 新页。

`explanation.example.json` 是构造解释草稿，可绑定到已有材料并生成行为阅读路线：

```sh
"$EF_CLI" --workspace "$EF_DEMO" review explain REVIEW_ID --input "$EF_DEMO/explanation.example.json"
"$EF_CLI" --workspace "$EF_DEMO" review record REVIEW_ID \
  --decision request_changes --comment '需要补充真实分布式实例场景' --file batch_queue.py
"$EF_CLI" --workspace "$EF_DEMO" review build TASK_ID
```

解释始终标记为 AI 解释/未确认；意见标记为调用者意见。要确认一条意见，由操作者另在本地交互终端执行 `review confirm OPINION_ID` 并核对随机提示。非交互调用拒绝，不能通过传入 confirmed 或账号文字替代交互。终端来源不构成身份认证，同账号终端自动化仍可模拟；本仓库的 PTY 测试不代表真实用户批准。确认绑定快照和任务修订，修改后旧确认失效，且不替代任何必需检查。

显式暂缓检查可用 `check skip TASK_ID idempotency --reason '构造示例：测试环境不可用'`；即使曾通过，最新跳过仍会令该必需项不满足。

M3-1 的 `memory.example.json` 是带代码来源和适用条件的构造候选：

```sh
"$EF_CLI" --workspace "$EF_DEMO" memory propose TASK_ID --input "$EF_DEMO/memory.example.json"
"$EF_CLI" --workspace "$EF_DEMO" memory context TASK_ID --module queue --query retry
"$EF_CLI" --workspace "$EF_DEMO" task resume TASK_ID
```

候选在新进程恢复后仍是 proposed，不因来源存在或检查通过自动确认。修改或删除 `batch_queue.py` 后，`memory show MEMORY_ID` 返回 needs_revalidation，来源读取命令仍指向原快照。用 `--budget-bytes 2` 可构造完整排除场景：selected 为空，excluded 给出 budget 及继续读取命令。可在 `review record` 时使用 `--memory MEMORY_ID` 只评审该候选；其本地终端确认不推导整个任务获批。没有真人操作时，保持候选，不运行自动化终端来冒充用户批准。

## 文档建议与交接

`document.example.json` 是同一队列的构造维护草稿，来源指向 `batch_queue.py` 的真实行。复制示例后，可用 `document propose TASK_ID --input document.example.json` 保存新建 MAINTENANCE.md 的建议，再用 `document voice DOCUMENT_ID` 显式读取固定表达规则、`document export DOCUMENT_ID` 导出 diff、`task handoff TASK_ID` 生成交接。

这些命令不创建或覆盖 MAINTENANCE.md；需要由现有 Review 流程核对并应用。改写按 README 的两个摘要绑定原稿；候选和保护检查不等于语义等价或人工确认。建议被应用后快照变化，必须重新检查，旧材料仅保留历史状态。
