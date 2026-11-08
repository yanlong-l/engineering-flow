"""文档建议、显式表达改写和原稿降级；永不覆盖工作区文档。"""

import json
import os
import shutil
import tempfile
from pathlib import Path

from .document_records import before_content, patch_text, render_document, unrequested, validate_input
from .errors import FlowError
from .evidence import seal
from .memory import _base, _sources
from .records import text, validate_id
from .tasks import TaskService
from .voice import compare_protected, load_module
from .workspace import _git, inspect_workspace

LIMITATIONS = [
    "文档正文和改写均为调用者候选；来源存在和保护内容检查通过不证明技术语义正确。",
    "程序只导出修改建议，不覆盖工作区文件；人工正文及混合文档区域外的内容保留供评审。",
    "engineer-voice 是固定 Markdown Skill；加载不等于模型已执行，未观察模型执行。",
    "保护区比较不是 Markdown 完整解析或语义证明；条件、否定、建议强度和不确定性仍须 Review。",
    "本地终端确认不构成身份认证；文档建议批准不替代应用后代码快照上的检查与评审。",
]


def document_results(store, task: dict, capture) -> dict:
    records = store.documents(task_id=task["id"])
    events = store.evidence("review_events", task_id=task["id"])
    states = []
    for document in records:
        confirmation = None
        for event in events:
            if event["eventType"] == "confirmation" and event["scope"]["kind"] == "documents":
                if any(d["id"] == document["id"] for d in event["scope"]["documents"]):
                    confirmation = event
        reasons = []
        if document["snapshotId"] != capture.document["id"]:
            reasons.append("snapshot_changed")
        if document["taskRevision"] != task["revision"]:
            reasons.append("task_revision_changed")
        # 沿用来源状态，失败或跳过的来源不会变成成功结论。
        for source in document["proposal"]["sources"]:
            if source["kind"] != "code":
                evidence = store.evidence("check_runs" if source["kind"] == "check" else "review_events", evidence_id=source["id"])[0]
                if evidence["taskRevision"] != document["taskRevision"]:
                    reasons.append("source_task_revision_changed")
                if source["kind"] == "check" and evidence["snapshotAfterId"] != document["snapshotId"]:
                    reasons.append("source_check_not_current")
        states.append({"id": document["id"], "confirmationStatus": "proposed" if confirmation is None else
                       {"approve": "confirmed", "request_changes": "rejected", "comment": "proposed"}[confirmation["decision"]],
                       "confirmation": confirmation["id"] if confirmation else None,
                       "applicability": "needs_revalidation" if reasons else "current", "reasons": sorted(set(reasons)),
                       "applied": "not_observed"})
    return {"records": records, "states": states, "limitations": LIMITATIONS}


class DocumentService(TaskService):
    def propose(self, task_id: str, proposal: dict) -> dict:
        try:
            validate_input(proposal)
        except (ValueError, TypeError, KeyError, AttributeError, FlowError, UnicodeError) as exc:
            raise FlowError("invalid_input", "文档建议需 target/mode/region/draft/reason/sources/protectedFacts；不接受自报确认。") from exc
        task, capture = self._resume(task_id)
        try:
            before = before_content(proposal, capture.document, capture.blobs)
            root = Path(capture.workspace["root"])
            target = root / proposal["target"]
            parents = list(target.parents)[:len(target.relative_to(root).parts) - 1]
            if (target.is_symlink() or any(p.is_symlink() or p.exists() and not p.is_dir() for p in parents)
                    or before is None and os.path.lexists(target)):
                raise ValueError("target exists outside declared snapshot or is symlink")
            if before is None and not any(e["path"] == proposal["target"] for e in capture.document["files"]):
                if _git(root, "check-ignore", "--no-index", "-z", "--stdin", input_data=proposal["target"].encode("utf-8") + b"\0", allowed=(0, 1)):
                    raise ValueError("new target would be ignored and absent from future snapshots")
            after = render_document(proposal, before, proposal["draft"])
        except (ValueError, UnicodeError, OSError) as exc:
            raise FlowError("invalid_input", f"目标必须是快照内的 UTF-8 文档，生成文档需标记，混合区域需唯一且无嵌套：{exc}") from exc
        document = seal(dict(_base(task, capture), proposal=proposal, before=before, after=after,
                             patch=patch_text(proposal, before, after), voice=unrequested()))
        self._store(capture.workspace).save_document(document, capture=capture)
        return self.get(document["id"])

    def get(self, document_id: str) -> dict:
        validate_id(document_id)
        store = self._store(inspect_workspace(self.workspace_path))
        rows = store.documents(document_id=document_id)
        if not rows:
            raise FlowError("document_not_found", "找不到该文档建议。")
        document = rows[0]
        task, capture = self._resume(document["taskId"])
        results = document_results(store, task, capture)
        state = next(s for s in results["states"] if s["id"] == document_id)
        return {"document": document, "state": state, "sources": _sources(store, dict(document, proposal=document["proposal"])), "limitations": LIMITATIONS}

    def voice(self, document_id: str) -> dict:
        result = self.get(document_id)
        document = result["document"]
        return {"documentId": document_id, "proposalIntegrity": document["integrity"], "draft": document["proposal"]["draft"],
                "protectedFacts": document["proposal"]["protectedFacts"], "state": result["state"], **load_module(), "limitations": LIMITATIONS}

    def rewrite(self, document_id: str, content: dict) -> dict:
        original = self.get(document_id)
        document = original["document"]
        if original["state"]["applicability"] != "current" or document["voice"]["status"] != "not_requested":
            raise FlowError("document_stale", "改写需当前快照下的原始建议；重新读取来源并提出建议。")
        module = load_module()
        if module["status"] != "loaded":
            return {**original, "rewrite": module}
        try:
            if not isinstance(content, dict) or set(content) != {"proposalIntegrity", "moduleDigest", "rewritten"}:
                raise ValueError("rewrite fields")
            if content["proposalIntegrity"] != document["integrity"] or content["moduleDigest"] != module["moduleDigest"]:
                raise ValueError("rewrite identity")
            text(content["rewritten"], "改写候选")
            if len(content["rewritten"].encode("utf-8")) > 65536:
                raise ValueError("rewrite limit")
        except (ValueError, TypeError, KeyError, FlowError, UnicodeError) as exc:
            raise FlowError("invalid_input", "改写需原建议摘要、已加载模块摘要和 rewritten，不能自报检查或确认。") from exc
        task, capture = self._resume(document["taskId"])
        if document["snapshotId"] != capture.document["id"] or document["taskRevision"] != task["revision"]:
            raise FlowError("document_stale", "提交改写期间代码或任务发生变化。")
        proposal = document["proposal"]
        issues = compare_protected(proposal["draft"], content["rewritten"], proposal["protectedFacts"])
        body = proposal["draft"] if issues else content["rewritten"]
        try:
            after = render_document(proposal, document["before"], body)
        except ValueError as exc:
            raise FlowError("invalid_input", "改写包含非法文档标记。") from exc
        voice = {"status": "rejected" if issues else "protected_checks_passed", "module": module["module"],
                 "moduleDigest": module["moduleDigest"], "candidate": content["rewritten"], "issues": issues,
                 "parentId": document_id, "parentIntegrity": document["integrity"]}
        revised = seal(dict(_base(task, capture), proposal=proposal, before=document["before"], after=after,
                            patch=patch_text(proposal, document["before"], after), voice=voice))
        self._store(capture.workspace).save_document(revised, capture=capture)
        return self.get(revised["id"])

    def export(self, document_id: str) -> dict:
        result = self.get(document_id)
        document = result["document"]
        store = self._store(inspect_workspace(self.workspace_path))
        parent = store.path.parent / "documents"
        temporary = None
        try:
            if parent.is_symlink():
                raise OSError("文档导出目录不能是符号链接")
            parent.mkdir(exist_ok=True)
            destination = parent / document_id
            artifacts = {"proposal.json": json.dumps(document, ensure_ascii=True, indent=2), "before.md": document["before"] or "",
                         "after.md": document["after"], "change.patch": document["patch"]}
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() or any((destination / name).is_symlink() or (destination / name).read_bytes().decode("utf-8") != value for name, value in artifacts.items()):
                    raise OSError("已有导出与原记录不符，未覆盖")
            else:
                temporary = Path(tempfile.mkdtemp(prefix=".building-", dir=parent))
                for name, value in artifacts.items():
                    (temporary / name).write_text(value, encoding="utf-8")
                os.rename(temporary, destination); temporary = None
            return {**result, "directory": str(destination), "patchPath": str(destination / "change.patch")}
        except (OSError, UnicodeError) as exc:
            raise FlowError("document_export", f"原建议保留在数据库，导出失败：{exc}") from exc
        finally:
            if temporary:
                shutil.rmtree(temporary, ignore_errors=True)
