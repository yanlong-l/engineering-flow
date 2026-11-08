"""任务、快照和续接适用性；多个入口共用这些规则。"""

import base64
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import FlowError
from .paths import relative_path
from .records import SCHEMA_VERSION, SNAPSHOT_ID, text, texts, validate_id
from .snapshots import Capture, capture_snapshot, compare_snapshots
from .store import TaskStore
from .workspace import inspect_workspace

LIMITATIONS = [
    "快照仅覆盖声明输入，未声明的忽略文件不在范围内；ignoredPaths 列出忽略项。",
    "连续两次读取一致不等于隔离或原子快照，不能排除采集期间短暂修改后恢复。",
    "任务进度来自调用者，不代表检查通过、人工确认或任务验收完成。",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskService:
    def __init__(self, workspace: Path):
        self.workspace_path = workspace

    @staticmethod
    def _store(workspace: dict) -> TaskStore:
        return TaskStore(Path(workspace["root"]) / ".engineering-flow" / "state.sqlite3")

    @staticmethod
    def _match(record: dict, workspace: dict) -> None:
        saved = record["savedWorkspace"]
        mismatch = any(saved[key] != workspace[key] for key in ("projectId", "workspaceId", "branch"))
        # detached HEAD 没有分支身份；切到另一提交必须显式拒绝。
        mismatch |= saved["branch"] is None and saved["head"] != workspace["head"]
        if mismatch:
            raise FlowError("workspace_mismatch", "当前项目、工作区、分支或 detached HEAD 与保存位置不同；未续接或修改任务。")

    def _result(self, record: dict, capture: Capture) -> dict:
        from .checks import check_results
        from .feedback import event_results
        from .memory import memory_context
        from .documents import document_results
        store = self._store(capture.workspace)
        snapshots = {}
        for key in ("startingWorkspace", "savedWorkspace"):
            ref = record[key]["snapshotId"]
            if ref is not None and ref not in snapshots:
                document, _ = store.load_snapshot(ref)
                snapshots[ref] = document
            if ref is not None and any(snapshots[ref][k] != record[key][k] for k in ("projectId", "workspaceId", "branch", "head")):
                raise FlowError("invalid_snapshot", "任务和快照身份不符。")
        related = record.get("relatedFiles", [])
        warnings = list(LIMITATIONS)
        if record["startingWorkspace"]["snapshotId"] is None:
            warnings.append("旧任务未记录启动内容快照；该基线保持未知，不能用当前内容补造。")
        saved = snapshots.get(record["savedWorkspace"]["snapshotId"])
        baseline = snapshots.get(record["startingWorkspace"]["snapshotId"])
        return {"task": record, "currentWorkspace": capture.workspace, "currentSnapshot": capture.document,
                "snapshotComparison": compare_snapshots(saved, capture.document, related),
                "changesSinceStart": compare_snapshots(baseline, capture.document, related), "limitations": warnings,
                "verification": check_results(store, record, capture),
                "reviewFeedback": event_results(store, record, capture.document),
                "memoryContext": memory_context(store, record, capture),
                "documents": document_results(store, record, capture)}

    @staticmethod
    def _related(paths: list[str], capture: Capture) -> list[str]:
        texts(paths, "关联文件")
        available = {entry["path"] for entry in capture.document["files"]}
        for path in paths:
            relative_path(path)
            if path not in available:
                raise FlowError("invalid_input", f"关联文件未纳入当前快照：{path}；忽略文件需在 .engineering-flow.json 中声明。")
        return sorted(set(paths))

    def start(self, *, goal: str, acceptance: list[str], progress: str = "", issues: list[str] | None = None,
              related_files: list[str] | None = None) -> dict:
        text(goal, "目标")
        texts(acceptance, "验收条件", nonempty=True)
        text(progress, "进度", allow_empty=True)
        texts(issues if issues is not None else [], "未决事项")
        capture = capture_snapshot(self.workspace_path)
        related = self._related(related_files if related_files is not None else [], capture)
        starting_workspace = deepcopy(capture.workspace)
        for change in starting_workspace["observedChanges"]:
            change["ownership"] = "pre_existing_unknown"
        now = _now()
        record = {
            "schemaVersion": SCHEMA_VERSION, "id": uuid4().hex, "revision": 1,
            "status": "active", "goal": goal, "acceptanceCriteria": acceptance, "relatedFiles": related,
            "progress": progress, "unresolvedIssues": issues if issues is not None else [],
            "createdAt": now, "updatedAt": now, "inputOrigin": "caller",
            "startingWorkspace": starting_workspace, "savedWorkspace": capture.workspace,
        }
        self._store(capture.workspace).append(record, expected_revision=0, capture=capture)
        return self._result(record, capture)

    def _resume(self, task_id: str) -> tuple[dict, Capture]:
        validate_id(task_id)
        workspace = inspect_workspace(self.workspace_path)
        record = self._store(workspace).load(task_id)
        self._match(record, workspace)
        capture = capture_snapshot(self.workspace_path)
        self._match(record, capture.workspace)
        return record, capture

    def resume(self, task_id: str) -> dict:
        record, capture = self._resume(task_id)
        return self._result(record, capture)

    def checkpoint(self, task_id: str, *, expected_revision: int, progress: str,
                   goal: str | None = None, acceptance: list[str] | None = None,
                   issues: list[str] | None = None, related_files: list[str] | None = None) -> dict:
        if type(expected_revision) is not int or expected_revision < 1:
            raise FlowError("invalid_input", "expected-revision 必须是正整数。")
        text(progress, "进度", allow_empty=True)
        if goal is not None:
            text(goal, "目标")
        if acceptance is not None:
            texts(acceptance, "验收条件", nonempty=True)
        if issues is not None:
            texts(issues, "未决事项")
        previous, capture = self._resume(task_id)
        # 在保存新修订前也核验旧引用，不能绕过损坏的历史基线。
        self._result(previous, capture)
        record = deepcopy(previous)
        record.update(schemaVersion=SCHEMA_VERSION, progress=progress, updatedAt=_now(), revision=expected_revision + 1,
                      savedWorkspace=capture.workspace,
                      relatedFiles=self._related(related_files, capture) if related_files is not None else previous.get("relatedFiles", []))
        if goal is not None:
            record["goal"] = goal
        if acceptance is not None:
            record["acceptanceCriteria"] = acceptance
        if issues is not None:
            record["unresolvedIssues"] = issues
        self._store(capture.workspace).append(record, expected_revision=expected_revision, capture=capture)
        return self._result(record, capture)

    def snapshot(self, snapshot_id: str, *, file: str | None = None, diff: str | None = None, layer: str = "worktree") -> dict:
        if not isinstance(snapshot_id, str) or not SNAPSHOT_ID.fullmatch(snapshot_id):
            raise FlowError("invalid_input", "快照 ID 必须是 64 位十六进制指纹。")
        workspace = inspect_workspace(self.workspace_path)
        document, blobs = self._store(workspace).load_snapshot(snapshot_id)
        if any(workspace[key] != document[key] for key in ("projectId", "workspaceId")):
            raise FlowError("workspace_mismatch", "该快照属于其他项目或工作区。")
        if file is None and diff is None:
            return {"snapshot": document}
        if diff is not None:
            if diff not in ("staged", "unstaged") or file is not None:
                raise FlowError("invalid_input", "diff 必须为 staged 或 unstaged，且不能同时指定文件。")
            ref = document["diffs"][diff]
        else:
            relative_path(file)
            if layer not in ("worktree", "index"):
                raise FlowError("invalid_input", "layer 必须为 worktree 或 index。")
            entry = next((e for e in document["files"] if e["path"] == file), None)
            value = entry[layer] if entry is not None else None
            if value is None or "blob" not in value:
                raise FlowError("content_not_found", "该文件在指定快照和层中没有内容。")
            ref = value["blob"]
        data = blobs[ref]
        try:
            content, encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            content, encoding = base64.b64encode(data).decode("ascii"), "base64"
        return {"snapshotId": snapshot_id, "file": file, "layer": diff or layer,
                "content": {"sha256": ref, "encoding": encoding, "data": content}}
