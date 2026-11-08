"""只解析参数和呈现结果，任务规则由 Core 执行。"""

import argparse
import json
import sys
from pathlib import Path

from engineering_flow import __version__
from engineering_flow.core.errors import FlowError
from engineering_flow.core.tasks import TaskService
from engineering_flow.core.checks import CheckService
from engineering_flow.core.reviews import ReviewService
from engineering_flow.core.feedback import FeedbackService
from engineering_flow.core.memory import MemoryService, DEFAULT_BUDGET
from engineering_flow.core.documents import DocumentService


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="engineering-flow", description="Engineering Flow 本地任务、快照、检查与 Review 材料")
    cli.add_argument("--version", action="version", version=__version__)
    cli.add_argument("--workspace", type=Path, default=Path.cwd(), help="Git 工作区路径；默认当前目录")
    groups = cli.add_subparsers(dest="group", required=True)
    doctor = groups.add_parser("doctor", help="只读诊断本地环境、声明输入与可选 MCP；不执行检查")
    doctor.add_argument("--require-mcp", action="store_true", help="MCP 不可用时退出 1，可作为项目必需检查")
    plugin = groups.add_parser("plugin", help="生成绑定当前工作区的 Copilot 插件目录")
    plugin_actions = plugin.add_subparsers(dest="action", required=True)
    plugin_build = plugin_actions.add_parser("build")
    plugin_build.add_argument("--output", type=Path, required=True, help="新目录，拒绝覆盖；不会修改宿主设置")
    plugin_inspect = plugin_actions.add_parser("inspect", help="只读核对生成目录、当前运行时与工作区绑定")
    plugin_inspect.add_argument("directory", type=Path)
    task = groups.add_parser("task", help="创建、保存和恢复任务")
    actions = task.add_subparsers(dest="action", required=True)
    start = actions.add_parser("start", help="创建任务并保存启动时观察")
    start.add_argument("--goal", required=True)
    start.add_argument("--accept", action="append", required=True, help="验收条件，可重复")
    start.add_argument("--progress", default="")
    start.add_argument("--issue", action="append", default=[])
    start.add_argument("--file", action="append", default=[], help="显式关联快照内文件，可重复；不推断作者")
    save = actions.add_parser("checkpoint", help="保存进度，要求当前修订号")
    save.add_argument("id")
    save.add_argument("--expected-revision", type=int, required=True)
    save.add_argument("--progress", required=True)
    save.add_argument("--goal")
    save.add_argument("--accept", action="append", help="替换全部验收条件，可重复")
    issues = save.add_mutually_exclusive_group()
    issues.add_argument("--issue", action="append", help="替换全部未决事项，可重复")
    issues.add_argument("--clear-issues", action="store_true")
    files = save.add_mutually_exclusive_group()
    files.add_argument("--file", action="append", help="替换关联文件列表，可重复")
    files.add_argument("--clear-files", action="store_true")
    resume = actions.add_parser("resume", help="按 ID 读取最后提交的任务修订")
    resume.add_argument("id")
    handoff = actions.add_parser("handoff", help="生成绑定快照的 Review 与交接材料，不宣告任务完成")
    handoff.add_argument("id")
    snapshots = groups.add_parser("snapshot", help="读取同工作区中的历史快照与原始内容")
    snapshot_actions = snapshots.add_subparsers(dest="action", required=True)
    show = snapshot_actions.add_parser("show")
    show.add_argument("id")
    content = show.add_mutually_exclusive_group()
    content.add_argument("--file", help="仓库相对文件路径")
    content.add_argument("--diff", choices=("staged", "unstaged"))
    show.add_argument("--layer", choices=("worktree", "index"), default="worktree")
    checks = groups.add_parser("check", help="真实执行项目配置检查，读取历史结果和当前适用性")
    check_actions = checks.add_subparsers(dest="action", required=True)
    run = check_actions.add_parser("run")
    run.add_argument("task_id")
    run.add_argument("check_id")
    skip = check_actions.add_parser("skip", help="显式记录未执行；不满足必需项")
    skip.add_argument("task_id")
    skip.add_argument("check_id")
    skip.add_argument("--reason", required=True)
    check_show = check_actions.add_parser("show")
    check_show.add_argument("id")
    reviews = groups.add_parser("review", help="生成固定 HTML/JSON/Markdown 证据包，保存解释与评审")
    review_actions = reviews.add_subparsers(dest="action", required=True)
    build = review_actions.add_parser("build")
    build.add_argument("task_id")
    review_show = review_actions.add_parser("show")
    review_show.add_argument("id")
    record = review_actions.add_parser("record", help="记录调用者评审意见，不能直接写人工确认")
    record.add_argument("id", help="Review 材料 ID")
    record.add_argument("--decision", choices=("comment", "approve", "request_changes"), required=True)
    record.add_argument("--comment", required=True)
    record.add_argument("--file", action="append", default=[])
    record.add_argument("--memory", action="append", default=[], help="只评审选定的候选记忆，可重复；不能混用 --file")
    record.add_argument("--document", action="append", default=[], help="只评审选定的文档建议，不能混用其他范围")
    confirm = review_actions.add_parser("confirm", help="由本地操作者在交互终端确认一条意见")
    confirm.add_argument("id", help="意见记录 ID")
    explain = review_actions.add_parser("explain", help="将 AI 结构化解释绑定到指定材料快照")
    explain.add_argument("id", help="Review 材料 ID")
    explain.add_argument("--input", type=Path, required=True)
    memories = groups.add_parser("memory", help="保存有来源的候选、查看状态和选择任务上下文")
    memory_actions = memories.add_subparsers(dest="action", required=True)
    propose = memory_actions.add_parser("propose", help="显式保存候选；不自动确认或收集对话")
    propose.add_argument("task_id")
    propose.add_argument("--input", type=Path, required=True)
    memory_show = memory_actions.add_parser("show")
    memory_show.add_argument("id")
    context = memory_actions.add_parser("context")
    context.add_argument("task_id")
    context.add_argument("--query", default="")
    context.add_argument("--path", action="append", default=[])
    context.add_argument("--module", action="append", default=[])
    context.add_argument("--budget-bytes", type=int, default=DEFAULT_BUDGET)
    link = memory_actions.add_parser("relate", help="保存显式冲突、替代或归档；不自动判断语义")
    link.add_argument("id")
    link.add_argument("--relation", choices=("conflicts_with", "supersedes", "archive"), required=True)
    link.add_argument("--other")
    link.add_argument("--reason", required=True)
    documents = groups.add_parser("document", help="保存并导出文档建议，显式加载 engineer-voice；不覆盖工作区")
    document_actions = documents.add_subparsers(dest="action", required=True)
    doc_propose = document_actions.add_parser("propose")
    doc_propose.add_argument("task_id")
    doc_propose.add_argument("--input", type=Path, required=True)
    for name in ("show", "export", "voice", "rewrite"):
        action = document_actions.add_parser(name)
        action.add_argument("id")
        if name == "rewrite":
            action.add_argument("--input", type=Path, required=True)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    service = TaskService(args.workspace)
    try:
        if args.group == "doctor":
            from engineering_flow.core.diagnostics import diagnose
            result = diagnose(args.workspace)
        elif args.group == "plugin":
            from engineering_flow.adapters.copilot import build_plugin, inspect_plugin
            result = build_plugin(args.workspace, args.output) if args.action == "build" else inspect_plugin(args.workspace, args.directory)
        elif args.group == "document":
            documents = DocumentService(args.workspace)
            if args.action in ("propose", "rewrite"):
                try:
                    content = json.loads(args.input.read_bytes())
                except (OSError, ValueError) as exc:
                    raise FlowError("invalid_input", "无法读取文档建议或改写 JSON。") from exc
                result = documents.propose(args.task_id, content) if args.action == "propose" else documents.rewrite(args.id, content)
            else:
                result = {"show": documents.get, "export": documents.export, "voice": documents.voice}[args.action](args.id)
        elif args.group == "memory":
            memories = MemoryService(args.workspace)
            if args.action == "propose":
                try:
                    content = json.loads(args.input.read_bytes())
                except (OSError, ValueError) as exc:
                    raise FlowError("invalid_input", "无法读取候选记忆 JSON。") from exc
                result = memories.propose(args.task_id, content)
            elif args.action == "show":
                result = memories.get(args.id)
            elif args.action == "relate":
                result = memories.relate(args.id, relation=args.relation, other_id=args.other, reason=args.reason)
            else:
                result = memories.context(args.task_id, query=args.query, paths=args.path, modules=args.module, budget=args.budget_bytes)
        elif args.group == "check":
            checks = CheckService(args.workspace)
            if args.action == "skip":
                result = checks.skip(args.task_id, args.check_id, reason=args.reason)
            else:
                result = checks.run(args.task_id, args.check_id) if args.action == "run" else checks.get(args.id)
        elif args.group == "review":
            reviews = ReviewService(args.workspace)
            feedback = FeedbackService(args.workspace)
            if args.action == "record":
                result = feedback.record(args.id, decision=args.decision, comment=args.comment, files=args.file, memory_ids=args.memory, document_ids=args.document)
            elif args.action == "confirm":
                from engineering_flow.adapters.terminal import TerminalConfirmation
                result = feedback.confirm(args.id, authority=TerminalConfirmation())
            elif args.action == "explain":
                try:
                    content = json.loads(args.input.read_bytes())
                except (OSError, ValueError) as exc:
                    raise FlowError("invalid_input", "无法读取结构化解释 JSON。") from exc
                result = feedback.explain(args.id, content)
            else:
                result = reviews.build(args.task_id) if args.action == "build" else reviews.get(args.id)
        elif args.group == "snapshot":
            result = service.snapshot(args.id, file=args.file, diff=args.diff, layer=args.layer)
        elif args.action == "handoff":
            result = ReviewService(args.workspace).build(args.id)
        elif args.action == "start":
            result = service.start(goal=args.goal, acceptance=args.accept, progress=args.progress, issues=args.issue, related_files=args.file)
        elif args.action == "checkpoint":
            result = service.checkpoint(
                args.id, expected_revision=args.expected_revision, progress=args.progress,
                goal=args.goal, acceptance=args.accept, issues=[] if args.clear_issues else args.issue,
                related_files=[] if args.clear_files else args.file,
            )
        else:
            result = service.resume(args.id)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        if args.group == "doctor" and (not result["cliReady"] or args.require_mcp and not result["mcpReady"]):
            return 1
        if args.group == "plugin" and args.action == "inspect" and not result["ready"]:
            return 1
        # run 的失败结果仍以成功的结构化协议返回 stdout，同时令 shell/CI 能阻止后续发布。
        if args.group == "check" and args.action == "run" and (result["run"]["status"] != "passed" or result["applicability"] != "current"):
            return 3
        return 0
    except FlowError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=True), file=sys.stderr)
        return 1
