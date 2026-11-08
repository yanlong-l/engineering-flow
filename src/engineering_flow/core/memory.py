"""有来源的候选记忆、保守适用性和确定性的上下文预算；不调用模型。"""

import json
import re
from uuid import uuid4

from .errors import FlowError
from .evidence import seal
from .memory_records import validate_proposal
from .paths import relative_path
from .records import text, texts, validate_id
from .tasks import TaskService, _now
from .workspace import inspect_workspace

DEFAULT_BUDGET = 8192
LIMITATIONS = [
    "记忆正文来自调用者，保存为候选；代码、检查或意见来源不证明正文推断正确。",
    "确认状态与适用性分开；本机终端确认不是身份认证，也不替代检查。",
    "对声明输入的完整快照保守失效；不推断依赖关系或自动检测语义矛盾。",
    "预算只限制 selected 的规范 UTF-8 JSON 字节数；元数据、排除清单及任务正文不在此预算内。",
]


def context_bytes(selected: list[dict]) -> bytes:
    return json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _overlap(first: str, second: str) -> bool:
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def _base(task: dict, capture) -> dict:
    return {"schemaVersion": 1, "id": uuid4().hex, "taskId": task["id"], "taskRevision": task["revision"],
            "projectId": capture.workspace["projectId"], "workspaceId": capture.workspace["workspaceId"],
            "snapshotId": capture.document["id"], "createdAt": _now(), "origin": "caller"}


def _dataset(store, capture) -> tuple[list[dict], dict, list[dict]]:
    memories = store.memory_documents("memories")
    relations = store.memory_documents("memory_events")
    tasks, snapshots, confirmations = {}, {}, {}
    states, approved = {}, set()
    for memory in memories:
        owner = memory["taskId"]
        if owner not in tasks:
            tasks[owner] = store.load(owner)
            confirmations[owner] = store.evidence("review_events", task_id=owner)
        ref = memory["snapshotId"]
        if ref not in snapshots:
            snapshots[ref] = store.load_snapshot(ref)[0]
        snapshot = snapshots[ref]
        same_workspace = all(memory[k] == capture.workspace[k] for k in ("projectId", "workspaceId"))
        same_branch = (snapshot["branch"] == capture.workspace["branch"] and
                       (snapshot["branch"] is not None or snapshot["head"] == capture.workspace["head"]))
        confirmation = None
        for event in confirmations[owner]:
            if event["eventType"] == "confirmation" and event["scope"]["kind"] == "memories":
                if any(m["id"] == memory["id"] for m in event["scope"]["memories"]):
                    confirmation = event
                    if event["decision"] == "approve":
                        approved.add(memory["id"])
        confirmed = ("proposed" if confirmation is None else
                     {"approve": "confirmed", "request_changes": "rejected", "comment": "proposed"}[confirmation["decision"]])
        reasons = []
        if memory["snapshotId"] != capture.document["id"]:
            reasons.append("snapshot_changed")
        if memory["taskRevision"] != tasks[owner]["revision"]:
            reasons.append("task_revision_changed")
        for source in memory["proposal"]["sources"]:
            if source["kind"] != "code":
                table = "check_runs" if source["kind"] == "check" else "review_events"
                evidence = store.evidence(table, evidence_id=source["id"])[0]
                if evidence["taskRevision"] != memory["taskRevision"]:
                    reasons.append("source_task_revision_changed")
                if source["kind"] == "check" and evidence["snapshotAfterId"] != memory["snapshotId"]:
                    reasons.append("source_check_not_current")
        states[memory["id"]] = {"confirmationStatus": confirmed,
            "confirmation": {"eventId": confirmation["id"], "actor": confirmation["actor"], "createdAt": confirmation["createdAt"]} if confirmation else None,
            "applicability": "needs_revalidation" if reasons else "current", "reasons": sorted(set(reasons)),
            "conflictsWith": [], "supersededBy": [], "sameWorkspace": same_workspace, "sameBranch": same_branch}
    edges = {}
    for event in relations:
        left, right = event["memoryId"], event["otherId"]
        if left not in states or (right is not None and right not in states):
            raise FlowError("invalid_memory", "关系引用的记忆缺失。")
        if event["eventType"] == "archive":
            states[left]["applicability"] = "archived"
        elif event["eventType"] == "supersedes":
            edges.setdefault(left, set()).add(right)
            if left in approved:
                states[right]["supersededBy"].append(left)
                if states[right]["applicability"] != "archived":
                    states[right]["applicability"] = "superseded"
            else:
                states[left]["conflictsWith"].append(right)
                states[right]["conflictsWith"].append(left)
        else:
            states[left]["conflictsWith"].append(right)
            states[right]["conflictsWith"].append(left)
    # 显式替代关系也不能循环；迭代检测不依赖 Python 递归深度。
    incoming = {key: 0 for key in states}
    for targets in edges.values():
        for key in targets:
            incoming[key] += 1
    pending = [key for key, count in incoming.items() if count == 0]
    visited = 0
    while pending:
        key = pending.pop()
        visited += 1
        for target in edges.get(key, ()):
            incoming[target] -= 1
            if incoming[target] == 0:
                pending.append(target)
    if visited != len(states):
        raise FlowError("invalid_memory", "记忆替代关系存在循环；未合成为结论。")
    for state in states.values():
        state["conflictsWith"] = sorted(set(state["conflictsWith"]))
        state["supersededBy"] = sorted(set(state["supersededBy"]))
        state["hasActiveConflict"] = any(states[key]["applicability"] not in ("superseded", "archived") and
                                         states[key]["confirmationStatus"] != "rejected" for key in state["conflictsWith"])
        state["eligibleAsCurrentBackground"] = (state["sameWorkspace"] and state["sameBranch"] and
            state["confirmationStatus"] == "confirmed" and state["applicability"] == "current" and not state["hasActiveConflict"])
    return memories, states, relations


def _sources(store, memory: dict) -> list[dict]:
    sources = []
    for source in memory["proposal"]["sources"]:
        item = dict(source, snapshotId=memory["snapshotId"])
        if source["kind"] == "code":
            item.update(origin="program_observation", readCommand=["snapshot", "show", memory["snapshotId"], "--file", source["file"], "--layer", source["layer"]])
        else:
            table = "check_runs" if source["kind"] == "check" else "review_events"
            evidence = store.evidence(table, evidence_id=source["id"])[0]
            item.update(origin=evidence["origin"], integrity=evidence["integrity"])
            if source["kind"] == "check":
                item.update(status=evidence["status"], readCommand=["check", "show", source["id"]])
            else:
                item.update(eventType=evidence["eventType"], readCommand=["review", "show", evidence["reviewId"]])
        sources.append(item)
    return sources


def memory_context(store, task: dict, capture, *, query: str = "", paths: list[str] | None = None,
                   modules: list[str] | None = None, budget: int = DEFAULT_BUDGET) -> dict:
    if type(budget) is not int or not 2 <= budget <= 1048576:
        raise FlowError("invalid_input", "budget-bytes 必须为 2–1048576 的整数。")
    text(query, "查询", allow_empty=True)
    texts(paths if paths is not None else [], "检索路径")
    texts(modules if modules is not None else [], "检索模块")
    selected_paths = sorted(set(task.get("relatedFiles", []) + (paths or [])))
    for path in selected_paths:
        relative_path(path)
    terms = re.findall(r"[\w-]+", (query or task["goal"]).casefold())
    memories, states, relations = _dataset(store, capture)
    candidates, excluded = [], []
    for memory in memories:
        key = memory["id"]
        state, proposal = states[key], memory["proposal"]
        ref = {"id": key, "readCommand": ["memory", "show", key]}
        if not state["sameWorkspace"] or not state["sameBranch"]:
            excluded.append(dict(ref, reason="workspace_mismatch" if not state["sameWorkspace"] else "branch_mismatch"))
            continue
        matches = []
        if memory["taskId"] == task["id"]:
            matches.append("task")
        if proposal["scope"]["kind"] == "project":
            matches.append("project")
        if any(_overlap(p, s) for p in selected_paths for s in proposal["scope"]["paths"]):
            matches.append("path")
        if set(m.casefold() for m in modules or []) & set(m.casefold() for m in proposal["scope"]["modules"]):
            matches.append("module")
        search = (proposal["content"] + " " + " ".join(proposal["keywords"])).casefold()
        if any(term in search for term in terms):
            matches.append("keyword")
        excluded_reason = (state["applicability"] if state["applicability"] in ("archived", "superseded") else
                           "rejected" if state["confirmationStatus"] == "rejected" else "unrelated" if not matches else None)
        if excluded_reason:
            excluded.append(dict(ref, reason=excluded_reason, state=state))
            continue
        item = dict(ref, taskId=memory["taskId"], snapshotId=memory["snapshotId"], content=proposal["content"],
                    kind=proposal["kind"], scope=proposal["scope"], matches=matches, state=state, sources=_sources(store, memory))
        score = sum({"task": 8, "path": 4, "module": 2, "keyword": 1, "project": 0}[m] for m in matches)
        candidates.append((not state["eligibleAsCurrentBackground"], -score, key, item))
    selected = []
    for _, _, key, item in sorted(candidates):
        if len(context_bytes(selected + [item])) <= budget:
            selected.append(item)
        else:
            excluded.append({"id": key, "reason": "budget", "state": states[key], "readCommand": ["memory", "show", key]})
    return {"taskId": task["id"], "taskRevision": task["revision"], "snapshotId": capture.document["id"],
            "budgetBytes": budget, "usedBytes": len(context_bytes(selected)), "budgetEncoding": "canonical UTF-8 JSON of selected",
            "selected": selected, "excluded": excluded,
            "complete": not any(e["reason"] == "budget" for e in excluded),
            "relations": [e for e in relations if states[e["memoryId"]]["sameWorkspace"] and states[e["memoryId"]]["sameBranch"]],
            "limitations": LIMITATIONS}


class MemoryService(TaskService):
    def propose(self, task_id: str, proposal: dict) -> dict:
        try:
            validate_proposal(proposal)
        except (FlowError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise FlowError("invalid_input", "候选需 content、kind、scope、keywords、sources；不能自报 confirmed、来源身份或适用状态。") from exc
        task, capture = self._resume(task_id)
        for path in proposal["scope"]["paths"]:
            if not any(_overlap(path, e["path"]) and (e["path"] == path or e["path"].startswith(path + "/")) for e in capture.document["files"]):
                raise FlowError("invalid_input", f"适用路径不在当前快照：{path}")
        memory = seal(dict(_base(task, capture), proposal=proposal))
        self._store(capture.workspace).save_memory("memories", memory, capture=capture)
        return self.get(memory["id"])

    def get(self, memory_id: str) -> dict:
        validate_id(memory_id)
        workspace = inspect_workspace(self.workspace_path)
        store = self._store(workspace)
        memories = store.memory_documents("memories")
        memory = next((m for m in memories if m["id"] == memory_id), None)
        if memory is None:
            raise FlowError("memory_not_found", "找不到该记忆。")
        task, capture = self._resume(memory["taskId"])
        _, states, relations = _dataset(store, capture)
        return {"memory": memory, "state": states[memory_id], "sources": _sources(store, memory),
                "relations": [e for e in relations if memory_id in (e["memoryId"], e["otherId"])], "limitations": LIMITATIONS}

    def context(self, task_id: str, **kwargs) -> dict:
        task, capture = self._resume(task_id)
        return memory_context(self._store(capture.workspace), task, capture, **kwargs)

    def relate(self, memory_id: str, *, relation: str, other_id: str | None = None, reason: str) -> dict:
        if relation not in ("conflicts_with", "supersedes", "archive") or ((relation == "archive") != (other_id is None)):
            raise FlowError("invalid_input", "archive 不接受 other；conflicts_with / supersedes 必须有 other。")
        text(reason, "关系原因")
        current = self.get(memory_id)
        if other_id is not None:
            self.get(other_id)
            if memory_id == other_id:
                raise FlowError("invalid_input", "不能关联同一条记忆。")
        task, capture = self._resume(current["memory"]["taskId"])
        store = self._store(capture.workspace)
        if relation == "supersedes":
            edges = {}
            for event in store.memory_documents("memory_events"):
                if event["eventType"] == "supersedes":
                    edges.setdefault(event["memoryId"], set()).add(event["otherId"])
            pending, seen = [other_id], set()
            while pending:
                key = pending.pop()
                if key == memory_id:
                    raise FlowError("invalid_input", "替代关系不能构成循环。")
                if key not in seen:
                    seen.add(key)
                    pending.extend(edges.get(key, ()))
        event = seal(dict(_base(task, capture), memoryId=memory_id, eventType=relation, otherId=other_id, reason=reason))
        store.save_memory("memory_events", event, capture=capture)
        return {"event": event, **self.get(memory_id)}
