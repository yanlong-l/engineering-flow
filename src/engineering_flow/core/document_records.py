"""不可变文档修改建议，派生正文始终可由原文和建议重建。"""

import difflib
import re
from datetime import datetime

from .errors import FlowError
from .evidence import seal
from .memory_records import validate_proposal
from .paths import relative_path
from .records import SNAPSHOT_ID, text, texts, validate_id
from .voice import compare_protected

GENERATED = "<!-- engineering-flow:generated -->\n"


def source_proposal(proposal: dict) -> dict:
    return {"content": proposal["reason"], "kind": "explanation", "scope": {"kind": "project", "paths": [], "modules": []},
            "keywords": [], "sources": proposal["sources"]}


def validate_input(proposal: dict) -> None:
    if not isinstance(proposal, dict) or set(proposal) != {"target", "mode", "region", "draft", "reason", "sources", "protectedFacts"}:
        raise ValueError("proposal fields")
    relative_path(proposal["target"])
    if not proposal["target"].endswith(".md") or any(c in proposal["target"] for c in "\n\r\t\\"):
        raise ValueError("Markdown target")
    text(proposal["draft"], "技术草稿")
    text(proposal["reason"], "修改原因")
    if len(proposal["draft"].encode("utf-8")) > 65536:
        raise ValueError("draft limit")
    texts(proposal["protectedFacts"], "逐字保护的事实")
    if len(proposal["protectedFacts"]) > 64 or any(f not in proposal["draft"] for f in proposal["protectedFacts"]):
        raise ValueError("protected facts must exist in draft")
    if proposal["mode"] not in ("manual", "generated", "mixed"):
        raise ValueError("mode")
    region = proposal["region"]
    if proposal["mode"] == "mixed":
        if not isinstance(region, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", region):
            raise ValueError("region")
        if "<!-- engineering-flow:" in proposal["draft"]:
            raise ValueError("nested region")
    elif region is not None:
        raise ValueError("region only for mixed")
    validate_proposal(source_proposal(proposal))


def render_document(proposal: dict, before: str | None, body: str) -> str:
    mode = proposal["mode"]
    if mode == "generated":
        if before is not None and not before.startswith(GENERATED):
            raise ValueError("existing generated document lacks marker")
        if body.startswith(GENERATED):
            raise ValueError("draft must exclude generated marker")
        return GENERATED + body
    if before is None:
        raise ValueError("manual/mixed target must exist in snapshot")
    if mode == "manual":
        return body
    start = f"<!-- engineering-flow:{proposal['region']}:start -->"
    end = f"<!-- engineering-flow:{proposal['region']}:end -->"
    if before.count(start) != 1 or before.count(end) != 1:
        raise ValueError("region markers must be unique")
    a, b = before.index(start) + len(start), before.index(end)
    if a >= b or "<!-- engineering-flow:" in before[a:b]:
        raise ValueError("invalid or nested region")
    return before[:a] + "\n" + body.rstrip("\r\n") + "\n" + before[b:]


def before_content(proposal: dict, snapshot: dict, blobs: dict) -> str | None:
    entry = next((e for e in snapshot["files"] if e["path"] == proposal["target"]), None)
    current = entry["worktree"] if entry else None
    if not current or current["kind"] != "file":
        return None
    value = blobs[current["blob"]].decode("utf-8")
    if "\0" in value:
        raise ValueError("binary target")
    return value


def patch_text(proposal: dict, before: str | None, after: str) -> str:
    # 保留无末尾换行的明确标记，避免导出的补丁改变行连接。
    diff = difflib.unified_diff((before or "").splitlines(keepends=True), after.splitlines(keepends=True),
                               fromfile="a/" + proposal["target"] if before is not None else "/dev/null", tofile="b/" + proposal["target"])
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in diff)


def validate_document(document: dict) -> None:
    try:
        fields = {"schemaVersion", "id", "taskId", "taskRevision", "projectId", "workspaceId", "snapshotId", "createdAt", "origin",
                  "integrity", "proposal", "before", "after", "patch", "voice"}
        if set(document) != fields or type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1 or document["origin"] != "caller":
            raise ValueError("schema")
        for key in ("id", "taskId"):
            validate_id(document[key])
        for key in ("projectId", "workspaceId", "snapshotId", "integrity"):
            if not isinstance(document[key], str) or not SNAPSHOT_ID.fullmatch(document[key]):
                raise ValueError("reference")
        if type(document["taskRevision"]) is not int or document["taskRevision"] < 1:
            raise ValueError("revision")
        if seal(dict(document))["integrity"] != document["integrity"] or datetime.fromisoformat(document["createdAt"]).utcoffset() is None:
            raise ValueError("integrity")
        proposal, voice = document["proposal"], document["voice"]
        validate_input(proposal)
        if set(voice) != {"status", "module", "moduleDigest", "candidate", "issues", "parentId", "parentIntegrity"}:
            raise ValueError("voice fields")
        body = proposal["draft"]
        if voice["status"] == "not_requested":
            if voice != unrequested():
                raise ValueError("voice not requested")
        else:
            validate_id(voice["parentId"])
            if not SNAPSHOT_ID.fullmatch(voice["parentIntegrity"]) or not SNAPSHOT_ID.fullmatch(voice["moduleDigest"]) or not isinstance(voice["module"], dict):
                raise ValueError("voice module")
            text(voice["candidate"], "改写候选")
            if len(voice["candidate"].encode("utf-8")) > 65536:
                raise ValueError("candidate limit")
            issues = compare_protected(body, voice["candidate"], proposal["protectedFacts"])
            if issues != voice["issues"] or voice["status"] != ("rejected" if issues else "protected_checks_passed"):
                raise ValueError("voice result")
            if not issues:
                body = voice["candidate"]
        if document["after"] != render_document(proposal, document["before"], body) or document["patch"] != patch_text(proposal, document["before"], document["after"]):
            raise ValueError("derived document")
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, FlowError) as exc:
        raise FlowError("invalid_document", "文档建议损坏、保护内容不符或 schema 不受支持。") from exc


def unrequested() -> dict:
    return {"status": "not_requested", "module": None, "moduleDigest": None, "candidate": None, "issues": [], "parentId": None, "parentIntegrity": None}
