"""最简固定 Review 材料：快照、原始 diff/文件/检查输出的本地证据包。"""

import json
import os
import shutil
import string
import tempfile
from pathlib import Path
from uuid import uuid4

from .errors import FlowError
from .checks import check_results
from .evidence import output_bytes, seal, snapshot_references
from .feedback import event_results
from .review_html import render_review
from .records import validate_id
from .tasks import TaskService, _now
from .workspace import inspect_workspace


class ReviewService(TaskService):
    def build(self, task_id: str) -> dict:
        task, capture = self._resume(task_id)
        result = self._result(task, capture)
        store = self._store(capture.workspace)
        runs = store.evidence("check_runs", task_id=task_id)
        verification = check_results(store, task, capture, history=runs)
        events = store.evidence("review_events", task_id=task_id)
        feedback = event_results(store, task, capture.document, events=events)
        explanation = next((e for e in reversed(events) if e["eventType"] == "explanation"), None)
        record = {"schemaVersion": 3, "id": uuid4().hex, "taskId": task_id, "task": task,
                  "projectId": capture.workspace["projectId"], "workspaceId": capture.workspace["workspaceId"],
                  "snapshotId": capture.document["id"], "createdAt": _now(), "origin": "program_observation",
                  "snapshot": capture.document, "changesSinceStart": result["changesSinceStart"],
                  "verification": verification, "runs": runs,
                  "aiExplanation": explanation, "humanConfirmation": None,
                  "reviewRecords": events, "reviewFeedback": feedback,
                  "documents": result["documents"],
                  "handoff": {"origin": "program_observation", "memoryContext": result["memoryContext"],
                              "nextStepsOrigin": "caller", "nextSteps": task["unresolvedIssues"],
                              "completion": "not_asserted"},
                  "limitations": result["limitations"] + result["verification"]["limitations"] + [
                      "材料仅描述生成时快照，不实时观察代码；review show 重新计算适用性，review build 生成新材料。",
                      "AI 解释未经自动确认；终端确认不替代自动检查或任务验收。",
                  ] + feedback["limitations"] + result["documents"]["limitations"]}
        store.save_evidence("reviews", seal(record), captures=[capture])
        directory = self._export(record, store)
        return {"review": record, "directory": str(directory), "materialPath": str(directory / "review.md"),
                "htmlPath": str(directory / "review.html"),
                "handoffPath": str(directory / "handoff.md"),
                "applicability": "current"}

    def get(self, review_id: str) -> dict:
        validate_id(review_id)
        workspace = inspect_workspace(self.workspace_path)
        store = self._store(workspace)
        rows = store.evidence("reviews", evidence_id=review_id)
        if not rows:
            raise FlowError("review_not_found", "找不到该 Review 材料。")
        record = rows[0]
        task, capture = self._resume(record["taskId"])
        result = self._result(task, capture)
        current = record["snapshotId"] == capture.document["id"] and record["task"]["revision"] == task["revision"]
        return {"review": record, "applicability": "current" if current else "stale",
                "currentSnapshotId": capture.document["id"], "currentTaskRevision": task["revision"],
                "currentVerification": result["verification"], "currentReviewFeedback": result["reviewFeedback"],
                "currentDocuments": result["documents"],
                "refreshNeeded": not current or result["verification"] != record["verification"]
                or result["reviewFeedback"] != record.get("reviewFeedback", {})
                or result["documents"] != record.get("documents", {"records": [], "states": [], "limitations": result["documents"]["limitations"]})
                or result["memoryContext"] != record.get("handoff", {}).get("memoryContext", result["memoryContext"])}

    @staticmethod
    def _export(record: dict, store) -> Path:
        """用产品目录内新建的临时目录组装，完成后一次 rename；历史材料不覆盖。"""
        parent = store.path.parent / "reviews"
        temporary = None
        try:
            if parent.is_symlink():
                raise OSError("Review 目录不能是符号链接")
            parent.mkdir(exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".building-", dir=parent))
            (temporary / "review.json").write_text(json.dumps(record, ensure_ascii=True, indent=2), encoding="utf-8")
            references = []

            def safe(value) -> str:
                # 所有调用者文字按文本转义；链接和 Markdown 结构仅由固定模板生成。
                return "".join(f"&#{ord(c)};" if c in string.punctuation or c in "\r\n" else c for c in str(value))

            lines = ["# Engineering Flow · Review 材料", "",
                     f"生成时间：{record['createdAt']}", "",
                     f"快照：`{record['snapshotId']}`；任务修订：{record['task']['revision']}。仅描述生成时内容。", "",
                     "## 需求与待判断事项", "", safe(record["task"]["goal"]), "", "验收条件：", ""]
            lines += [f"- {safe(value)}" for value in record["task"]["acceptanceCriteria"]]
            lines += ["", "进度（调用者输入）：" + safe(record["task"]["progress"]), "", "未决事项：", ""]
            lines += [f"- {safe(value)}" for value in record["task"]["unresolvedIssues"]] or ["- 未记录。"]
            lines += ["", "## 程序观察：快照与代码", "", "修改归属保持未知。启动前已有改动保留在启动快照，不自动归为本任务或 AI。", ""]
            snapshots = [("生成时", record["snapshotId"]), ("任务启动时", record["task"]["startingWorkspace"]["snapshotId"])]
            known = {ref for _, ref in snapshots}
            snapshots += [("历史证据", ref) for ref in sorted(snapshot_references(record, "reviews") - known)]
            relevant = set(record["task"].get("relatedFiles", [])) | {c["path"] for c in record["changesSinceStart"]["changes"]}
            for document in record.get("documents", {}).get("records", []):
                relevant.add(document["proposal"]["target"])
                relevant.update(s["file"] for s in document["proposal"]["sources"] if s["kind"] == "code")
            for event in record.get("reviewRecords", []):
                if event["eventType"] == "explanation":
                    relevant.update(r["file"] for b in event["content"]["behaviors"] for r in b["references"])
                else:
                    relevant.update(event["scope"]["files"])
            for index, (label, ref) in enumerate(snapshots):
                if ref is None:
                    lines += [f"{label}：旧任务没有内容快照，基线未知。", ""]
                    continue
                snapshot, blobs = store.load_snapshot(ref)
                folder = temporary / f"snapshot-{index}"
                folder.mkdir()
                (folder / "manifest.json").write_text(json.dumps(snapshot, ensure_ascii=True, indent=2), encoding="utf-8")
                lines += [f"{label}：`{ref}` · [清单](snapshot-{index}/manifest.json)", ""]
                for diff, blob in snapshot["diffs"].items():
                    file = f"snapshot-{index}/{diff}.txt"
                    (temporary / file).write_bytes(blobs[blob])
                    references.append({"snapshotId": ref, "diff": diff, "path": file, "sha256": blob})
                    lines.append(f"- [{diff} diff]({file})")
                for number, entry in enumerate(snapshot["files"]):
                    if entry["path"] not in relevant:
                        continue
                    for layer in ("worktree", "index"):
                        value = entry[layer]
                        if value is None or "blob" not in value:
                            lines.append(f"- {safe(entry['path'])} · {layer}：无内容（缺失或删除）。")
                            continue
                        blob = value["blob"]
                        file = f"snapshot-{index}/file-{number}-{layer}.txt"
                        (temporary / file).write_bytes(blobs[blob])
                        references.append({"snapshotId": ref, "file": entry["path"], "layer": layer, "path": file, "sha256": blob})
                        lines.append(f"- {safe(entry['path'])} · [{layer} 原始内容]({file})")
                lines.append("")
            lines += ["## 程序观察：真实检查", "", "历史退出结果和对生成时快照的适用性分开呈现；只有 passed/current 可计为该必需检查通过。", ""]
            lines.append("必需检查均满足：" + ("是" if record["verification"]["requiredChecksPassed"] else "否（含未配置必需项）"))
            lines.append("")
            for item in record["verification"]["checks"]:
                definition = item["check"]
                lines.append(f"- {safe(definition['id'])} · required={definition['required']} · {item['status']} / {item['applicability']}")
            if not record["verification"]["checks"]:
                lines.append("- 未配置检查，无可核验的通过结论。")
            for run in record["runs"]:
                folder = temporary / run["id"]
                folder.mkdir()
                (folder / "run.json").write_text(json.dumps(run, ensure_ascii=True, indent=2), encoding="utf-8")
                state = next(h["applicability"] for h in record["verification"]["history"] if h["runId"] == run["id"])
                lines += ["", f"### {safe(run['check']['id'])} · {run['status']} / {state}", "",
                          f"运行 ID：`{run['id']}` · [命令、时间和完整记录]({run['id']}/run.json)", "",
                          f"执行前：`{run['snapshotId']}`；执行后：`{run['snapshotAfterId']}`；退出码：{run['exitCode']}。", ""]
                if run.get("reason"):
                    lines += ["跳过原因（调用者输入）：" + safe(run["reason"]), ""]
                for stream in ("stdout", "stderr"):
                    data = output_bytes(run[stream])
                    file = f"{run['id']}/{stream}.txt"
                    (temporary / file).write_bytes(data)
                    references.append({"runId": run["id"], "stream": stream, "path": file, "sha256": run[stream]["sha256"]})
                    lines.append(f"- [{stream} 原始输出]({file})（truncated={run[stream]['truncated']}）")
            lines += ["", "## AI 解释与评审记录", ""]
            if record.get("aiExplanation"):
                explanation = record["aiExplanation"]
                lines += ["AI 解释（未确认）：" + safe(explanation["content"]["summary"]), ""]
            else:
                lines += ["AI 解释：未提供。", ""]
            feedback = record.get("reviewFeedback", {"records": [], "states": []})
            states = {s["eventId"]: s["applicability"] for s in feedback["states"]}
            for event in feedback["records"]:
                if event["eventType"] != "explanation":
                    label = "终端确认记录" if event["eventType"] == "confirmation" else "调用者意见（未确认）"
                    lines += [f"- {label} / {states[event['id']]} · {safe(event['decision'])} · {safe(event['comment'])} · 范围 {safe(event['scope'])}"]
            lines += ["", "## 范围与限制", ""]
            lines += [f"- {safe(value)}" for value in record["limitations"]]
            lines += ["", "[完整结构化材料](review.json) · [引用与摘要](references.json)", ""]
            (temporary / "references.json").write_text(json.dumps(references, ensure_ascii=True, indent=2), encoding="utf-8")
            (temporary / "review.md").write_text("\n".join(lines), encoding="utf-8")
            (temporary / "review.html").write_text(render_review(record, store), encoding="utf-8")
            if "handoff" in record:
                handoff = {"reviewId": record["id"], "snapshotId": record["snapshotId"], "task": record["task"],
                           "verification": record["verification"], "reviewFeedback": record["reviewFeedback"],
                           "documents": record["documents"], **record["handoff"], "limitations": record["limitations"]}
                (temporary / "handoff.json").write_text(json.dumps(handoff, ensure_ascii=True, indent=2), encoding="utf-8")
                notes = ["# Engineering Flow · 交接材料", "", f"快照：`{record['snapshotId']}`；任务修订：{record['task']['revision']}。",
                         "", "材料仅描述生成时状态；任务完成未被断言。下一会话先运行：", "",
                         f"`engineering-flow task resume {record['taskId']}`", "", "目标（调用者）：" + safe(record["task"]["goal"]),
                         "", "进度（调用者）：" + safe(record["task"]["progress"]), "", "## 未决事项与下一步（调用者）", ""]
                notes += ["- " + safe(v) for v in record["handoff"]["nextSteps"]] or ["- 未记录，不代表全部完成。"]
                notes += ["", "## 检查与来源", "", "必需检查均满足：" + str(record["verification"]["requiredChecksPassed"]),
                          "", "[Review 页面](review.html) · [原始检查、文档、确认及记忆状态](handoff.json)", "", "## 文档修改建议", ""]
                states = {s["id"]: s for s in record["documents"]["states"]}
                for document in record["documents"]["records"]:
                    folder = temporary / ("document-" + document["id"])
                    folder.mkdir()
                    for name, content in {"before.md": document["before"] or "", "after.md": document["after"], "change.patch": document["patch"],
                                          "proposal.json": json.dumps(document, ensure_ascii=True, indent=2)}.items():
                        (folder / name).write_text(content, encoding="utf-8")
                    state = states[document["id"]]
                    notes += [f"- {safe(document['proposal']['target'])} · {state['confirmationStatus']} / {state['applicability']} · "
                              f"[修改建议](document-{document['id']}/change.patch) · engineer-voice：{document['voice']['status']}；应用未被观察。"]
                notes += ["", "## 相关记忆", ""]
                for memory in record["handoff"]["memoryContext"]["selected"]:
                    notes += [f"- {safe(memory['content'])} · {memory['state']['confirmationStatus']} / {memory['state']['applicability']} · ID {memory['id']}"]
                notes += ["", "上下文预算完整：" + str(record["handoff"]["memoryContext"]["complete"]), "", "## 限制", ""]
                notes += ["- " + safe(v) for v in record["limitations"]]
                (temporary / "handoff.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
            destination = parent / record["id"]
            os.rename(temporary, destination)
            temporary = None
            return destination
        except OSError as exc:
            raise FlowError("review_export", f"证据已保存在数据库，材料导出失败；可用 review show 读取：{exc}") from exc
        finally:
            if temporary is not None:
                shutil.rmtree(temporary, ignore_errors=True)
