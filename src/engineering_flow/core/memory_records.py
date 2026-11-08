"""候选记忆与关系事件的固定结构；摘要用于损坏检测，不提供身份认证。"""

from datetime import datetime

from .errors import FlowError
from .evidence import seal
from .paths import relative_path
from .records import SNAPSHOT_ID, text, texts, validate_id

KINDS = ("explanation", "design_decision", "convention", "limitation")


def code_content(source: dict, snapshot: dict, blobs: dict) -> bytes:
    if set(source) != {"kind", "file", "layer", "startLine", "endLine"} or source["layer"] not in ("index", "worktree"):
        raise ValueError("code source fields")
    relative_path(source["file"])
    if any(type(source[k]) is not int for k in ("startLine", "endLine")) or not 1 <= source["startLine"] <= source["endLine"]:
        raise ValueError("line range")
    entry = next((e for e in snapshot["files"] if e["path"] == source["file"]), None)
    value = entry[source["layer"]] if entry else None
    if not value or "blob" not in value:
        raise ValueError("missing source file")
    data = blobs[value["blob"]]
    decoded = data.decode("utf-8")
    if "\0" in decoded or source["endLine"] > len(decoded.splitlines()):
        raise ValueError("non-text or missing source line")
    return data


def validate_proposal(content: dict) -> None:
    if not isinstance(content, dict) or set(content) != {"content", "kind", "scope", "keywords", "sources"}:
        raise ValueError("proposal fields")
    text(content["content"], "记忆内容")
    if len(content["content"].encode("utf-8")) > 16384 or content["kind"] not in KINDS:
        raise ValueError("content limit or kind")
    scope = content["scope"]
    if not isinstance(scope, dict) or set(scope) != {"kind", "paths", "modules"} or scope["kind"] not in ("project", "paths"):
        raise ValueError("scope")
    texts(scope["paths"], "适用路径")
    texts(scope["modules"], "模块")
    texts(content["keywords"], "关键词")
    if (scope["kind"] == "project") != (not scope["paths"]):
        raise ValueError("scope paths")
    for path in scope["paths"]:
        relative_path(path)
    sources = content["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
        raise ValueError("sources")
    if any(len(values) > 64 for values in (scope["paths"], scope["modules"], content["keywords"])):
        raise ValueError("list limit")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("source")
        if source.get("kind") == "code":
            if set(source) != {"kind", "file", "layer", "startLine", "endLine"}:
                raise ValueError("code source fields")
            relative_path(source["file"])
            if source["layer"] not in ("worktree", "index") or any(type(source[k]) is not int for k in ("startLine", "endLine")):
                raise ValueError("code source")
            if not 1 <= source["startLine"] <= source["endLine"]:
                raise ValueError("line range")
        elif source.get("kind") in ("check", "review_event"):
            if set(source) != {"kind", "id"}:
                raise ValueError("evidence source fields")
            validate_id(source["id"])
        else:
            raise ValueError("unsupported source")


def validate_memory(document: dict, kind: str) -> None:
    try:
        base = {"schemaVersion", "id", "taskId", "taskRevision", "projectId", "workspaceId", "snapshotId", "createdAt", "origin", "integrity"}
        fields = {"proposal"} if kind == "memories" else {"memoryId", "eventType", "otherId", "reason"}
        if kind not in ("memories", "memory_events") or set(document) != base | fields:
            raise ValueError("fields")
        if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1 or document["origin"] != "caller":
            raise ValueError("schema or origin")
        for key in ("id", "taskId"):
            validate_id(document[key])
        if type(document["taskRevision"]) is not int or document["taskRevision"] < 1:
            raise ValueError("task revision")
        for key in ("projectId", "workspaceId", "snapshotId", "integrity"):
            if not isinstance(document[key], str) or not SNAPSHOT_ID.fullmatch(document[key]):
                raise ValueError("reference")
        if seal(dict(document))["integrity"] != document["integrity"] or datetime.fromisoformat(document["createdAt"]).utcoffset() is None:
            raise ValueError("integrity or timestamp")
        if kind == "memories":
            validate_proposal(document["proposal"])
        else:
            validate_id(document["memoryId"])
            text(document["reason"], "关系原因")
            if document["eventType"] not in ("conflicts_with", "supersedes", "archive"):
                raise ValueError("event type")
            if document["eventType"] == "archive":
                if document["otherId"] is not None:
                    raise ValueError("archive target")
            else:
                validate_id(document["otherId"])
                if document["memoryId"] == document["otherId"]:
                    raise ValueError("self relation")
    except (KeyError, ValueError, TypeError, AttributeError, FlowError) as exc:
        raise FlowError("invalid_memory", "记忆或关系记录损坏、引用错误或 schema 不受支持。") from exc
