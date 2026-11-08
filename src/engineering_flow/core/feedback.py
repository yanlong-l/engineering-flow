"""有快照与范围的解释、意见及独立确认；调用者意见不能自封为人工确认。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import uuid4

from .errors import FlowError
from .evidence import seal, validate_explanation
from .paths import relative_path
from .records import text, texts, validate_id
from .tasks import TaskService, _now
from .workspace import inspect_workspace
from .snapshots import canonical


@dataclass(frozen=True)
class ConsentReceipt:
    opinion_integrity: str
    actor: dict


class ConfirmationPort(ABC):
    """由受信本地适配器实现；不通过 JSON/MCP 暴露为输入。"""

    @abstractmethod
    def request(self, opinion: dict) -> ConsentReceipt:
        raise NotImplementedError


def event_results(store, task: dict, snapshot: dict, *, events: list[dict] | None = None) -> dict:
    events = store.evidence("review_events", task_id=task["id"]) if events is None else events
    latest, memory_latest, document_latest = {}, {}, {}
    states = []
    for event in events:
        state = "current" if event["snapshotId"] == snapshot["id"] and event["taskRevision"] == task["revision"] else "stale"
        states.append({"eventId": event["id"], "eventType": event["eventType"], "applicability": state})
        if event["eventType"] == "confirmation" and state == "current":
            if event["scope"]["kind"] == "memories":
                for memory in event["scope"]["memories"]:
                    memory_latest[memory["id"]] = (event, memory)
            elif event["scope"]["kind"] == "documents":
                for document in event["scope"]["documents"]:
                    document_latest[document["id"]] = (event, document)
            else:
                latest[canonical(event["scope"])] = event
    effective = ({event["id"] for event in latest.values()} | {event["id"] for event, _ in memory_latest.values()}
                 | {event["id"] for event, _ in document_latest.values()})
    for state in states:
        if state["eventType"] == "confirmation":
            state["effective"] = state["eventId"] in effective
            state["effectiveMemoryIds"] = [key for key, (event, _) in memory_latest.items() if event["id"] == state["eventId"]]
            state["effectiveDocumentIds"] = [key for key, (event, _) in document_latest.items() if event["id"] == state["eventId"]]
    scopes = [{"eventId": e["id"], "scope": e["scope"], "decision": e["decision"], "actor": e["actor"]} for e in latest.values()]
    scopes += [{"eventId": e["id"], "scope": {"kind": "memories", "files": [], "memories": [memory]},
                "decision": e["decision"], "actor": e["actor"]} for e, memory in memory_latest.values()]
    scopes += [{"eventId": e["id"], "scope": {"kind": "documents", "files": [], "documents": [document]},
                "decision": e["decision"], "actor": e["actor"]} for e, document in document_latest.values()]
    return {"records": events, "states": states,
            "confirmedScopes": scopes,
            "limitations": ["终端确认记录本机账号及交互来源，不是身份认证；同账号的终端自动化或直接存储访问仍处于本地信任边界。",
                            "文件范围的确认仅覆盖明确列出的文件，不表示整个任务或必需检查已通过。"]}


class FeedbackService(TaskService):
    def _review(self, review_id: str):
        validate_id(review_id)
        workspace = inspect_workspace(self.workspace_path)
        rows = self._store(workspace).evidence("reviews", evidence_id=review_id)
        if not rows:
            raise FlowError("review_not_found", "找不到该 Review 材料。")
        review = rows[0]
        task, capture = self._resume(review["taskId"])
        self._result(task, capture)
        return review, task, capture

    @staticmethod
    def _base(review: dict, event_type: str, origin: str) -> dict:
        return {"schemaVersion": 1, "id": uuid4().hex, "taskId": review["taskId"], "reviewId": review["id"],
                "taskRevision": review["task"]["revision"], "projectId": review["projectId"], "workspaceId": review["workspaceId"],
                "snapshotId": review["snapshotId"], "createdAt": _now(), "eventType": event_type, "origin": origin}

    def explain(self, review_id: str, content: dict) -> dict:
        try:
            validate_explanation(content)
        except (KeyError, ValueError, TypeError, FlowError) as exc:
            raise FlowError("invalid_input", "AI 解释必须包含 summary 和 behaviors，行为需验收条件编号与快照代码引用。") from exc
        review, task, capture = self._review(review_id)
        for behavior in content["behaviors"]:
            if any(i > len(review["task"]["acceptanceCriteria"]) for i in behavior["acceptanceCriteria"]):
                raise FlowError("invalid_input", "解释中的验收条件编号不存在。")
        event = dict(self._base(review, "explanation", "ai"), content=content)
        self._store(capture.workspace).save_evidence("review_events", seal(event), captures=[])
        return {"record": event, "applicability": "current" if capture.document["id"] == review["snapshotId"] and task["revision"] == event["taskRevision"] else "stale"}

    def record(self, review_id: str, *, decision: str, comment: str, files: list[str] | None = None,
               memory_ids: list[str] | None = None, document_ids: list[str] | None = None) -> dict:
        text(comment, "评审意见")
        if decision not in ("comment", "approve", "request_changes"):
            raise FlowError("invalid_input", "评审意见仅支持 comment / approve / request_changes；不能直接写入 confirmed。")
        paths = files or []
        texts(paths, "评审文件")
        review, task, capture = self._review(review_id)
        available = {e["path"] for e in review["snapshot"]["files"]}
        for file in paths:
            relative_path(file)
            if file not in available:
                raise FlowError("invalid_input", f"评审文件不在材料快照内：{file}")
        event = dict(self._base(review, "opinion", "caller"), decision=decision, comment=comment,
                     scope={"kind": "files" if paths else "task", "files": sorted(set(paths))}, actor=None)
        if memory_ids:
            if paths or document_ids or len(memory_ids) > 16 or len(set(memory_ids)) != len(memory_ids):
                raise FlowError("invalid_input", "记忆评审不能混用文件范围，最多选择 16 条且不能重复。")
            from .memory import MemoryService
            memories = [MemoryService(self.workspace_path).get(key)["memory"] for key in memory_ids]
            if any(any(m[k] != event[k] for k in ("taskId", "taskRevision", "snapshotId", "projectId", "workspaceId")) for m in memories):
                raise FlowError("memory_stale", "记忆与材料快照或任务修订不同；请先读取当前来源并提出新候选。")
            event.update(schemaVersion=2, scope={"kind": "memories", "files": [], "memories": memories})
        if document_ids:
            if paths or memory_ids or len(document_ids) > 16 or len(set(document_ids)) != len(document_ids):
                raise FlowError("invalid_input", "文档评审不能混用其他范围，最多 16 条且不能重复。")
            from .documents import DocumentService
            documents = [DocumentService(self.workspace_path).get(key)["document"] for key in document_ids]
            if any(any(d[k] != event[k] for k in ("taskId", "taskRevision", "snapshotId", "projectId", "workspaceId")) for d in documents):
                raise FlowError("document_stale", "文档建议与材料的任务修订或快照不同。")
            event.update(schemaVersion=3, scope={"kind": "documents", "files": [], "documents": documents})
        self._store(capture.workspace).save_evidence("review_events", seal(event), captures=[])
        return {"record": event, "confirmed": False}

    def confirm(self, opinion_id: str, *, authority: ConfirmationPort | None = None) -> dict:
        if not isinstance(authority, ConfirmationPort):
            raise FlowError("confirmation_source", "确认需要受支持的本地交互适配器；调用者文字、身份字段或 JSON 不能作为确认依据。")
        validate_id(opinion_id)
        workspace = inspect_workspace(self.workspace_path)
        store = self._store(workspace)
        rows = store.evidence("review_events", evidence_id=opinion_id)
        if not rows or rows[0]["eventType"] != "opinion":
            raise FlowError("opinion_not_found", "找不到可确认的评审意见。")
        opinion = rows[0]
        review, task, capture = self._review(opinion["reviewId"])
        if opinion["snapshotId"] != capture.document["id"] or opinion["taskRevision"] != task["revision"]:
            raise FlowError("review_stale", "材料或任务修订已过期，请刷新材料并重新评审。")
        receipt = authority.request(opinion)
        if not isinstance(receipt, ConsentReceipt) or receipt.opinion_integrity != opinion["integrity"]:
            raise FlowError("confirmation_source", "交互回执不属于该意见。")
        # 人工阅读/交互期间的代码或任务修改必须再次判定，不能只检查入口时状态。
        current_task, after = self._resume(opinion["taskId"])
        if after.document["id"] != capture.document["id"] or current_task["revision"] != task["revision"]:
            raise FlowError("review_stale", "交互期间代码或任务修订变化，未保存确认。")
        event = dict(self._base(review, "confirmation", "local_terminal"), opinionId=opinion_id,
                     opinionIntegrity=opinion["integrity"], scope=opinion["scope"], decision=opinion["decision"],
                     comment=opinion["comment"], actor=receipt.actor)
        event["schemaVersion"] = opinion["schemaVersion"]
        store.save_evidence("review_events", seal(event), captures=[])
        return {"record": event, "applicability": "current"}
