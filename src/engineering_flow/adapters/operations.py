"""MCP 操作目录及参数映射；状态、来源和适用性仍由既有 Core 计算。"""

from pathlib import Path

from engineering_flow.core.checks import CheckService
from engineering_flow.core.diagnostics import diagnose
from engineering_flow.core.documents import DocumentService
from engineering_flow.core.errors import FlowError
from engineering_flow.core.feedback import FeedbackService
from engineering_flow.core.memory import DEFAULT_BUDGET, MemoryService
from engineering_flow.core.reviews import ReviewService
from engineering_flow.core.tasks import TaskService

STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
ID = {"type": "string", "pattern": "^[0-9a-f]{32}$"}


def operation(required=None, **fields):
    return {"type": "object", "properties": fields, "required": required or [], "additionalProperties": False}


CODE_REFERENCE = operation(["file", "layer", "startLine", "endLine"], file=STRING,
                           layer={"type": "string", "enum": ["worktree", "index"]},
                           startLine={"type": "integer", "minimum": 1}, endLine={"type": "integer", "minimum": 1})
SOURCE = operation(["kind"], kind={"type": "string", "enum": ["code", "check", "review_event"],
    "description": "code 必须传 file/layer/startLine/endLine；check 或 review_event 必须只传 kind/id。Core 拒绝缺失、多余或无效来源。"},
    **CODE_REFERENCE["properties"], id=ID)
SOURCES = {"type": "array", "minItems": 1, "items": SOURCE}
DOCUMENT_PROPOSAL = operation(["target", "mode", "region", "draft", "reason", "sources", "protectedFacts"],
    target={"type": "string", "description": "仓库相对 .md 路径"},
    mode={"type": "string", "enum": ["manual", "generated", "mixed"]},
    region={"type": ["string", "null"], "description": "manual/generated 必须传 null；mixed 传命名区域"},
    draft=STRING, reason=STRING, sources=SOURCES,
    protectedFacts={**STRINGS, "description": "逐字保护的事实；无额外事实也必须传 []"})
REWRITE = operation(["proposalIntegrity", "moduleDigest", "rewritten"],
                    proposalIntegrity=STRING, moduleDigest=STRING, rewritten=STRING)
MEMORY_PROPOSAL = operation(["content", "kind", "scope", "keywords", "sources"],
    content=STRING, kind={"type": "string", "enum": ["explanation", "design_decision", "convention", "limitation"]},
    scope=operation(["kind", "paths", "modules"], kind={"type": "string", "enum": ["project", "paths"]}, paths=STRINGS, modules=STRINGS),
    keywords=STRINGS, sources=SOURCES)
EXPLANATION = operation(["summary", "behaviors"], summary=STRING,
    behaviors={"type": "array", "minItems": 1, "items": operation(["title", "description", "acceptanceCriteria", "references"],
        title=STRING, description=STRING, acceptanceCriteria={"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}},
        references={"type": "array", "minItems": 1, "items": CODE_REFERENCE})})


# 不接受 workspace、执行结论、确认人或 confirmed。嵌套正文由 Core 严格校验。
OPERATIONS = {
    "task": {
        "start": operation(["goal", "acceptance"], goal=STRING, acceptance=STRINGS, progress=STRING, issues=STRINGS, related_files=STRINGS),
        "resume": operation(["task_id"], task_id=ID),
        "checkpoint": operation(["task_id", "expected_revision", "progress"], task_id=ID,
                                expected_revision={"type": "integer", "minimum": 1}, progress=STRING,
                                goal=STRING, acceptance=STRINGS, issues=STRINGS, related_files=STRINGS),
        "handoff": operation(["task_id"], task_id=ID),
    },
    "check": {
        "run": operation(["task_id", "check_id"], task_id=ID, check_id=STRING),
        "show": operation(["run_id"], run_id=ID),
        "skip": operation(["task_id", "check_id", "reason"], task_id=ID, check_id=STRING, reason=STRING),
    },
    "review": {
        "build": operation(["task_id"], task_id=ID),
        "show": operation(["review_id"], review_id=ID),
        "explain": operation(["review_id", "content"], review_id=ID, content=EXPLANATION),
        "record": operation(["review_id", "decision", "comment"], review_id=ID,
                            decision={"type": "string", "enum": ["comment", "approve", "request_changes"]},
                            comment=STRING, files=STRINGS, memory_ids=STRINGS, document_ids=STRINGS),
    },
    "memory": {
        "propose": operation(["task_id", "proposal"], task_id=ID, proposal=MEMORY_PROPOSAL),
        "show": operation(["memory_id"], memory_id=ID),
        "context": operation(["task_id"], task_id=ID, query=STRING, paths=STRINGS, modules=STRINGS,
                             budget={"type": "integer", "minimum": 1, "default": DEFAULT_BUDGET}),
        "relate": operation(["memory_id", "relation", "reason"], memory_id=ID, reason=STRING, other_id=ID,
                            relation={"type": "string", "enum": ["conflicts_with", "supersedes", "archive"]}),
    },
    "document": {
        "propose": operation(["task_id", "proposal"], task_id=ID, proposal=DOCUMENT_PROPOSAL),
        **{name: operation(["document_id"], document_id=ID) for name in ("show", "export", "voice")},
        "rewrite": operation(["document_id", "content"], document_id=ID, content=REWRITE),
    },
    "snapshot": {
        "show": operation(["snapshot_id"], snapshot_id={"type": "string", "pattern": "^[0-9a-f]{64}$"}, file=STRING,
                          diff={"type": "string", "enum": ["staged", "unstaged"]},
                          layer={"type": "string", "enum": ["worktree", "index"]}),
    },
    "doctor": {"inspect": operation()},
}

DESCRIPTIONS = {
    "task": "开始/续接/显式保存/交接。start 需 goal、acceptance；checkpoint 需 task_id、expected_revision、progress。归属和检查状态由 Core 观察。handoff 不宣告完成。",
    "check": "run(task_id, check_id) 真实执行项目检查，show(run_id) 查询，skip(task_id, check_id, reason) 记录未执行。task_id 是 task.id 的 32 位 ID，不能传 snapshotId。只接受项目检查 ID，不接受命令或自报结果。失败或 stale 返回 isError；skip 不满足 required。同步执行，取消 MCP 请求不终止已开始的检查，最长按项目 timeoutSeconds。",
    "review": "build(task_id)、show(review_id)、explain(review_id, content)、record(review_id, decision, comment, 可选 files/memory_ids/document_ids)。解释为 AI，approve 意见不是人工确认。此工具没有 confirm。",
    "memory": "propose(task_id, proposal)、show(memory_id)、context(task_id, query/paths/modules/budget)、relate(memory_id, relation, reason, other_id)。正文只保存候选；来源、冲突和失效由 Core 计算。",
    "document": "propose(task_id, proposal)、show/export/voice(document_id)、rewrite(document_id, content)。voice 显式读取校验后的 Markdown 规则；宿主需实际按规则改写，再提交 proposalIntegrity/moduleDigest/rewritten。程序保护不证明语义等价，不覆盖工作区。",
    "snapshot": "show(snapshot_id, 可选 file 或 diff、layer)。读取持久化原始快照，不拿当前文件冒充历史。",
    "doctor": "inspect，无其他参数。只读观察运行环境、声明输入、项目检查和固定表达模块；不运行检查、不推断插件装载/Hooks/模型调用成功。",
}


def tool_schema(group: str) -> dict:
    # Copilot 的部分模型路径会将 oneOf 操作分支合并成最后一个 action。
    # 公开兼容的平面 schema；逐 action 的必填/多余字段仍在服务端严格验证。
    properties = {"action": {"type": "string", "enum": list(OPERATIONS[group])},
                  "view": {"type": "string", "enum": ["summary", "full"], "default": "summary",
                           "description": "默认 summary 限制内联大小；presentation 不完整时通过 flow_read 分页读全文。full 是明确请求的兼容完整 JSON，可能很大，不用于常规宿主流程。"}}
    for action, schema in OPERATIONS[group].items():
        properties.update(schema["properties"])
    for name, field in list(properties.items()):
        if name in ("action", "view"):
            continue
        used = [a for a, s in OPERATIONS[group].items() if name in s["properties"]]
        required = [a for a, s in OPERATIONS[group].items() if name in s["required"]]
        properties[name] = {**field, "description": field.get("description", "") +
                            f" 用于 action={','.join(used)}；必填于 {','.join(required) or '无'}。其他 action 不得传此字段。"}
    return {"type": "object", "properties": properties, "required": ["action"], "additionalProperties": False}


def dispatch(workspace: Path, group: str, action: str, arguments: dict) -> dict:
    if group not in OPERATIONS or action not in OPERATIONS[group]:
        raise FlowError("invalid_input", "未知操作；人工确认仅限独立终端入口。")
    args = dict(arguments)
    if group == "doctor":
        return diagnose(workspace)
    services = {"task": TaskService, "check": CheckService, "review": ReviewService,
                "memory": MemoryService, "document": DocumentService, "snapshot": TaskService}
    service = services[group](workspace)
    if group == "task" and action == "handoff":
        return ReviewService(workspace).build(args.pop("task_id"))
    if group == "review" and action in ("explain", "record"):
        service = FeedbackService(workspace)
    method = "get" if action == "show" else action
    if group == "snapshot":
        method = "snapshot"
    positional = {"task": "task_id", "check": "run_id" if action == "show" else "task_id",
                  "review": "task_id" if action == "build" else "review_id",
                  "memory": "task_id" if action in ("context", "propose") else "memory_id",
                  "document": "task_id" if action == "propose" else "document_id", "snapshot": "snapshot_id"}[group]
    if group == "task" and action == "start":
        return service.start(**args)
    identifier = args.pop(positional)
    if group == "check" and action in ("run", "skip"):
        return getattr(service, method)(identifier, args.pop("check_id"), **args)
    return getattr(service, method)(identifier, **args)
