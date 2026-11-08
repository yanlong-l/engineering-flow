"""执行器证据和固定 Review 材料的版本及完整性检查。"""

import base64
from datetime import datetime

from .errors import FlowError
from .records import SNAPSHOT_ID, validate_id, validate_record
from .paths import relative_path
from .snapshots import canonical, digest, validate_snapshot


def seal(document: dict) -> dict:
    document["integrity"] = digest(canonical({k: v for k, v in document.items() if k != "integrity"}))
    return document


def output(data: bytes, *, truncated: bool = False) -> dict:
    try:
        content, encoding = data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        content, encoding = base64.b64encode(data).decode("ascii"), "base64"
    return {"encoding": encoding, "data": content, "size": len(data), "sha256": digest(data), "truncated": truncated}


def output_bytes(value: dict) -> bytes:
    if value["encoding"] not in ("utf-8", "base64"):
        raise ValueError("invalid encoding")
    return value["data"].encode("utf-8") if value["encoding"] == "utf-8" else base64.b64decode(value["data"], validate=True)


def snapshot_references(document: dict, kind: str) -> set[str]:
    refs = {document["snapshotId"]}
    if kind == "check_runs":
        if document["snapshotAfterId"] is not None:
            refs.add(document["snapshotAfterId"])
    elif kind == "reviews":
        for key in ("startingWorkspace", "savedWorkspace"):
            if document["task"][key]["snapshotId"] is not None:
                refs.add(document["task"][key]["snapshotId"])
        for run in document["runs"]:
            refs.update(snapshot_references(run, "check_runs"))
        for event in document.get("reviewRecords", []):
            refs.add(event["snapshotId"])
        for proposal in document.get("documents", {}).get("records", []):
            refs.add(proposal["snapshotId"])
    return refs


def validate_evidence(document: dict, kind: str) -> None:
    try:
        if (kind not in ("check_runs", "reviews", "review_events") or type(document["schemaVersion"]) is not int
                or document["schemaVersion"] not in ((1, 2) if kind == "check_runs" else (1, 2, 3))):
            raise ValueError("schema")
        validate_id(document["id"])
        validate_id(document["taskId"])
        if any(not isinstance(document[k], str) or not SNAPSHOT_ID.fullmatch(document[k])
               for k in ("projectId", "workspaceId", "snapshotId", "integrity")):
            raise ValueError("reference")
        if seal(dict(document))["integrity"] != document["integrity"]:
            raise ValueError("integrity")
        timestamp = "startedAt" if kind == "check_runs" else "createdAt"
        if datetime.fromisoformat(document[timestamp]).utcoffset() is None:
            raise ValueError("timestamp")
        if kind == "check_runs":
            skipped = document["status"] == "skipped" and document["schemaVersion"] == 2
            if skipped:
                if (document["origin"] != "caller" or document["executionMode"] != "not_executed" or document["argv"]
                        or not isinstance(document["reason"], str) or not document["reason"].strip()
                        or document["exitCode"] is not None or document["failure"] is not None
                        or document["snapshotAfterId"] != document["snapshotId"]):
                    raise ValueError("skip cannot claim execution")
            elif document["origin"] != "runner" or document["executionMode"] != "workspace":
                raise ValueError("origin or mode")
            if document["status"] not in (("skipped",) if skipped else ("running", "passed", "failed", "error")):
                raise ValueError("status")
            for key in ("stdout", "stderr"):
                value = document[key]
                raw = output_bytes(value)
                if digest(raw) != value["sha256"] or len(raw) != value["size"] or type(value["truncated"]) is not bool:
                    raise ValueError("output integrity")
                if skipped and raw:
                    raise ValueError("skip output")
            if document["status"] == "running":
                if any(document[k] is not None for k in ("endedAt", "snapshotAfterId", "exitCode", "failure")):
                    raise ValueError("running result")
            else:
                if datetime.fromisoformat(document["endedAt"]).utcoffset() is None:
                    raise ValueError("end timestamp")
                after = document["snapshotAfterId"]
                if after is not None and (not isinstance(after, str) or not SNAPSHOT_ID.fullmatch(after)):
                    raise ValueError("after snapshot")
                if document["status"] == "passed" and (document["exitCode"] != 0 or document["failure"] is not None or after is None):
                    raise ValueError("passed result")
                if document["status"] == "failed" and (type(document["exitCode"]) is not int or document["exitCode"] <= 0 or document["failure"] is not None):
                    raise ValueError("failed result")
                if document["status"] == "error" and not isinstance(document["failure"], dict):
                    raise ValueError("error result")
        elif kind == "reviews":
            if document["origin"] != "program_observation" or document["task"]["id"] != document["taskId"]:
                raise ValueError("review origin or task")
            validate_record(document["task"])
            validate_snapshot(document["snapshot"], document["snapshotId"])
            for run in document["runs"]:
                validate_evidence(run, "check_runs")
                if run["taskId"] != document["taskId"]:
                    raise ValueError("review run task")
            if document["humanConfirmation"] is not None or (document["schemaVersion"] == 1 and document["aiExplanation"] is not None):
                raise ValueError("unsupported review claims")
            if document["schemaVersion"] >= 2:
                for event in document["reviewRecords"]:
                    validate_evidence(event, "review_events")
                    if event["taskId"] != document["taskId"]:
                        raise ValueError("event task")
            if document["schemaVersion"] == 3:
                from .document_records import validate_document
                for proposal in document["documents"]["records"]:
                    validate_document(proposal)
                    if proposal["taskId"] != document["taskId"]:
                        raise ValueError("document task")
        else:
            _validate_event(document)
    except (ValueError, TypeError, KeyError, AttributeError, FlowError) as exc:
        raise FlowError("invalid_evidence", "检查或 Review 证据损坏、引用错误或 schema 不受支持。") from exc


def _validate_event(document: dict) -> None:
    validate_id(document["reviewId"])
    if type(document["taskRevision"]) is not int or document["taskRevision"] < 1:
        raise ValueError("revision")
    event = document["eventType"]
    if event == "explanation":
        if document["origin"] != "ai":
            raise ValueError("explanation origin")
        validate_explanation(document["content"])
        return
    if event not in ("opinion", "confirmation") or document["decision"] not in ("comment", "approve", "request_changes"):
        raise ValueError("opinion decision")
    if not isinstance(document["comment"], str) or not document["comment"].strip():
        raise ValueError("comment")
    scope = document["scope"]
    if scope.get("kind") == "documents" and document["schemaVersion"] == 3:
        from .document_records import validate_document
        if set(scope) != {"kind", "files", "documents"} or scope["files"] != [] or not isinstance(scope["documents"], list) or not 1 <= len(scope["documents"]) <= 16:
            raise ValueError("document scope")
        ids = set()
        for proposal in scope["documents"]:
            validate_document(proposal)
            if proposal["id"] in ids or any(proposal[k] != document[k] for k in ("taskId", "taskRevision", "projectId", "workspaceId", "snapshotId")):
                raise ValueError("document review scope")
            ids.add(proposal["id"])
    elif scope.get("kind") == "memories" and document["schemaVersion"] == 2:
        from .memory_records import validate_memory
        if set(scope) != {"kind", "files", "memories"} or scope["files"] != [] or not isinstance(scope["memories"], list) or not 1 <= len(scope["memories"]) <= 16:
            raise ValueError("memory scope")
        ids = set()
        for memory in scope["memories"]:
            validate_memory(memory, "memories")
            if memory["id"] in ids or any(memory[k] != document[k] for k in ("taskId", "taskRevision", "projectId", "workspaceId", "snapshotId")):
                raise ValueError("memory review scope")
            ids.add(memory["id"])
    elif scope["kind"] not in ("task", "files") or set(scope) != {"kind", "files"} or not isinstance(scope["files"], list):
        raise ValueError("scope")
    elif (scope["kind"] == "task") != (not scope["files"]):
        raise ValueError("scope files")
    for file in scope["files"]:
        relative_path(file)
    if event == "opinion":
        if document["origin"] != "caller" or document.get("actor") is not None:
            raise ValueError("caller cannot claim human confirmation")
    else:
        validate_id(document["opinionId"])
        actor = document["actor"]
        if (document["origin"] != "local_terminal" or actor["source"] != "interactive_terminal"
                or type(actor["uid"]) is not int or not isinstance(actor["account"], str) or not actor["account"]
                or not isinstance(actor["tty"], str) or not actor["tty"]
                or actor["assurance"] != "local_session_not_identity_verified"
                or not SNAPSHOT_ID.fullmatch(document["opinionIntegrity"])):
            raise ValueError("confirmation source")


def validate_explanation(content: dict) -> None:
    if (not isinstance(content, dict) or set(content) != {"summary", "behaviors"}
            or not isinstance(content["summary"], str) or not content["summary"].strip()
            or not isinstance(content["behaviors"], list) or not content["behaviors"]):
        raise ValueError("explanation schema")
    for behavior in content["behaviors"]:
        if set(behavior) != {"title", "description", "acceptanceCriteria", "references"}:
            raise ValueError("behavior fields")
        for key in ("title", "description"):
            if not isinstance(behavior[key], str) or not behavior[key].strip():
                raise ValueError("behavior text")
        if (not isinstance(behavior["acceptanceCriteria"], list) or not behavior["acceptanceCriteria"]
                or any(type(i) is not int or i < 1 for i in behavior["acceptanceCriteria"])):
            raise ValueError("criteria")
        if not isinstance(behavior["references"], list) or not behavior["references"]:
            raise ValueError("references")
        for ref in behavior["references"]:
            if set(ref) != {"file", "layer", "startLine", "endLine"} or ref["layer"] not in ("worktree", "index"):
                raise ValueError("code reference")
            relative_path(ref["file"])
            if any(type(ref[k]) is not int for k in ("startLine", "endLine")) or not 1 <= ref["startLine"] <= ref["endLine"]:
                raise ValueError("line range")
