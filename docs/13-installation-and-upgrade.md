# 本地安装、诊断、升级与回退

本说明针对 Engineering Flow `0.1.0.dev8`。当前支持范围为已实际验证的 macOS / Apple Silicon、Python 3.14.3（包要求 >=3.14）、Git 2.49.0、VS Code 1.137.0 / 内置 Copilot Chat 0.65.0 的 **Copilot** 会话。其他版本、系统和电脑尚未验收。构建产物仅在本地提供，没有发布到 PyPI 或插件市场。

## 安装 Core 与 Copilot 依赖

先在源码目录构建 wheel；开发环境构建需要固定的 setuptools 80.9.0：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[copilot]'
make wheel
```

在单独目录创建运行环境，从 wheel 安装；不要把开发目录的 editable 安装当作干净安装结果：

```sh
python3 -m venv /path/to/runtime
/path/to/runtime/bin/python -m pip install '/path/to/engineering_flow-0.1.0.dev8-py3-none-any.whl[copilot]'
/path/to/runtime/bin/python -m pip check
/path/to/runtime/bin/engineering-flow --workspace /path/to/repo doctor --require-mcp
```

`[copilot]` 固定官方 `mcp==2.3.0`，其传递依赖由 pip 解析并按实际安装清单记录。本轮还验证了先下载对应平台的依赖 wheel，再以 `--no-index --find-links /path/to/wheelhouse` 安装；wheelhouse 中须同时有依赖和产品 wheel，不能把一个产品 wheel 说成包含了所有依赖。

只用 CLI 时省略 `[copilot]`。缺少或损坏 SDK 时，普通 doctor 显示 CLI 降级；`doctor --require-mcp` 退出 1，不把 MCP 不可用视为通过。doctor 只读观察，不执行项目检查或创建任务数据库，插件装载/模型行为仍为 not_observed。

## 生成并注册插件

使用刚安装的运行环境 CLI，核对目标 Git 仓库：

```sh
/path/to/runtime/bin/engineering-flow --workspace /path/to/repo plugin build \
  --output /path/to/plugins/engineering-flow-dev8
/path/to/runtime/bin/engineering-flow --workspace /path/to/repo plugin inspect \
  /path/to/plugins/engineering-flow-dev8
```

build 拒绝覆盖已有目录。inspect 不执行包内命令，只核对完整文件清单及摘要、manifest/MCP 参数、绑定身份、当前 CLI 的版本/Python 环境和 SDK；额外文件、Hooks 或符号链接均拒绝。可用时 ready=true，问题时 stdout 仍是诊断 JSON 且退出 1。摘要用于检测损坏，不是身份认证或签名。

1. 在目标仓库打开 VS Code，先核对其路径与 binding.json 的 root 一致。
2. 运行 **Chat: Install Plugin from Source**，输入上述生成目录；插件格式与管理入口参见 [VS Code 官方参考](https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference)。
3. 在 Plugins 中核对 1 个 Engineering Flow Agent、2 个内部 Skills 与 MCP 服务，没有产品 Hooks。
4. 新建 **Copilot** 会话，选择 **Engineering Flow**。保持项目已有权限策略，按实际工具范围授权，无需全局自动审批。
5. 从开始任务或 task ID 续接；准备 Review、文档与交接使用同一入口。确认意见仍需操作者在独立终端运行 `review confirm`，Agent 不代输 challenge。

MCP 以绑定的 Python 和 `-I` 启动，减少当前目录/PYTHONPATH 对包导入的影响。插件固定路由到一个本机工作区，并不认证调用来自哪个 IDE 窗口；在另一仓库使用前必须生成和注册正确的包。Core 仍会拒绝错误分支/worktree 的任务恢复。不要自动改工作区信任列表或启用远程连接。

当前个人展示偏好通过每次调用的 summary/full 选择；项目检查仍由 `.engineering-flow.json` 定义。没有持久个人设置或快速/扩展预设，不提供个人关闭 required 的通道。

## 阅读长结果

默认 MCP JSON 超过 6000 UTF-8 字节时返回明确的摘要，`presentation.complete=false`，不把省略内容说成完整。状态/领域 ID 和关键结论优先内联，完整结果通过只读 `flow_read` 取得。显式 `view=full` 保留兼容完整 JSON，可能很大，普通宿主流程不需要它。

```json
{"response_id":"presentation.responseId 的值","path":"/instructions/SKILL.md","offset":0,"limit":2000}
```

- path 使用 JSON Pointer；`~1` 表示 `/`，`~0` 表示 `~`。例如 `/instructions/docs~1regressions.md`。
- 字符串按原文返回，不再是一条被 JSON 转义的长行；适用于 `/draft`、`/run/stdout/data`、`/content/data` 和规则文件。非字符串返回可恢复的分行 JSON。
- offset 单位为 Unicode 码点，按 nextOffset 继续，直到 null；不要把字节数或 token 数当 offset。返回全文 SHA-256、字符总数和起始行，分页自身也限制在 6000 字节内。
- 缓存只在当前 MCP 进程内，最多保留最近 16 个大结果，序列化字节预算 32 MiB；这不是 Python 堆大小保证。过大结果明确不可缓存，使用领域 ID 的 CLI show/resume；没有静默截断。
- 重启或淘汰后返回 response_expired。按领域 ID 重新 show/resume 取得引用，不能重复 start/propose/rewrite/build。缓存没有写入磁盘，也不是对话记录。
- 缓存保留捕获时状态，读取不会重新计算适用性。编辑后重新 resume/show；旧页、旧候选和旧通过记录不会升级为当前结论。

## 升级与回退

升级前停止或卸载当前插件，结束正在执行的产品操作，保留原 wheel、运行环境和生成目录。需要备份时使用 SQLite 在线 backup API，不直接复制正在使用的数据库文件；备份和记录只保存在本机。

建议将新运行时与插件放到新目录，以便直接恢复旧组合；本轮也实测了同一 venv 中 dev7→dev8→dev7→dev8 的安装和读取。命令示例：

```sh
/path/to/runtime/bin/python -m pip install --force-reinstall '/path/to/engineering_flow-0.1.0.dev8-py3-none-any.whl[copilot]'
/path/to/runtime/bin/python -m pip check
/path/to/runtime/bin/engineering-flow --workspace /path/to/repo doctor --require-mcp
/path/to/runtime/bin/engineering-flow --workspace /path/to/repo plugin build \
  --output /path/to/plugins/engineering-flow-dev8-new
/path/to/runtime/bin/engineering-flow --workspace /path/to/repo plugin inspect \
  /path/to/plugins/engineering-flow-dev8-new
```

卸载旧注册，再从新目录注册并新建会话；需要时 Reload Window。不要同时保留同名插件的多份活动注册，也不要修改安装缓存当作升级。

本机清理时，卸载注册及 Reload Window 后旧 MCP 进程仍曾保留；应核对并结束属于该安装且已无运行操作的服务，再修改运行环境。UI 中 Plugins=0 只证明注册清理，不证明所有子进程已退出。不要结束其他安装或工作区的服务。

生成包绑定产品版本、Python 环境、工作区及文件清单。运行时版本或环境不符会拒绝启动；没有这些新字段的旧包在 dev8 返回 plugin_rebuild_required。运行中的服务检测到安装版本变化也拒绝继续操作，不承诺热升级。

回退时先停服务，恢复原 wheel/依赖环境，并重新注册与其配套的原插件目录。dev7 不支持 dev8 新启动参数，不能只换 Python 包而继续使用 dev8 插件。dev7/dev8 数据库均为 v6，本轮验证原任务修订及候选不被改写；更早 dev1–dev5 不能读取 v6。未来若升级数据库 schema，必须先核对该版本的迁移和回退合同，不能泛化本次回退结论。

## 常见故障与降级

| 观察 | 处理 |
| --- | --- |
| python_missing / 程序无法启动 | 原 Python 路径已失效；恢复原环境或在正确环境生成新目录。移动 venv 后不要依赖旧 console script 的 shebang |
| runtime_mismatch / runtime_changed | 停止服务，用预期版本/环境重新安装、生成并注册，或恢复旧组合 |
| invalid_plugin | 核对来源，重新生成目录；不执行包内未知命令，不手动绕过文件清单 |
| workspace_mismatch | 核对仓库根、分支和 worktree；移动仓库不等于迁移身份，不自动把旧任务归到新位置 |
| mcp_unavailable | 安装固定可选 SDK，使用对应环境 doctor；CLI 的显式保存、检查和交接仍可用 |
| failed / error / skipped / stale / unknown | 保留实际记录，按原因修正或重跑；不使用旧通过掩盖当前结果 |
| MCP 取消或断线 | 查询已保存状态；开始的检查可能继续至配置超时，停止进程不保证后台完成 |
| 没有 Hooks | 正式默认路径。显式 checkpoint/check/review/document/handoff 可完整运行 |

项目 `.engineering-flow.json` 的 required 不能由个人展示偏好关闭。本仓库 unit-tests 超时由 300 调至 600 秒，依据 M4-1 的 374.671 秒实际回归；新增 required 的 copilot-runtime 诊断，避免缺少 SDK 时只靠被跳过的集成测试得出全通过。检查记录仍绑定完整声明输入，交接文档变化也会使旧结果需要重新判断。
