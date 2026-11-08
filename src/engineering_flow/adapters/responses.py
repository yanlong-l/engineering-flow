"""MCP 展示与进程内分页；不改变 Core 记录或重新判断其结论。"""

import hashlib
import json
from collections import OrderedDict
from datetime import datetime, timezone

from engineering_flow.core.errors import FlowError

INLINE_BYTES = 6000
CACHE_BYTES = 32 * 1024 * 1024
CACHE_ITEMS = 16


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def pick(value, *keys):
    return {k: value[k] for k in keys if k in value}


def checks(value):
    return {"requiredChecksPassed": value["requiredChecksPassed"], "checks": [
        {**pick(c, "runId", "status", "applicability", "verified"), **pick(c["check"], "id", "required")}
        for c in value["checks"]], "historyCount": len(value.get("history", []))}


def summary(result: dict) -> dict:
    view = pick(result, "applicability", "refreshNeeded", "directory", "materialPath", "htmlPath", "handoffPath",
                "patchPath", "currentSnapshotId", "currentTaskRevision", "documentId", "proposalIntegrity", "moduleDigest", "status", "modelExecution", "protectedFacts")
    view.update(pick(result, "cliReady", "mcpReady", "version", "mcp", "host", "issues"))
    for name in ("task", "run", "review", "memory", "document", "record", "snapshot"):
        item = result.get(name)
        if isinstance(item, dict):
            view[name] = pick(item, "id", "revision", "taskId", "taskRevision", "snapshotId", "snapshotAfterId", "status",
                              "origin", "inputOrigin", "exitCode", "decision", "eventType", "integrity", "createdAt", "endedAt")
            if name == "task":
                view[name].update(pick(item, "goal", "acceptanceCriteria", "progress", "unresolvedIssues"))
            if name == "run":
                view[name].update(check=pick(item["check"], "id", "required"), **pick(item, "failure", "reason"))
                for stream in ("stdout", "stderr"):
                    view[name][stream] = {**pick(item[stream], "encoding", "size", "sha256", "truncated"),
                                          "readPath": f"/run/{stream}/data"}
            if name == "document":
                view[name]["target"] = item["proposal"]["target"]
                view[name]["voice"] = pick(item["voice"], "status", "issues", "parentId")
            if name == "snapshot":
                view[name]["fileCount"] = len(item["files"])
    if "currentSnapshot" in result:
        view["currentSnapshot"] = pick(result["currentSnapshot"], "id", "capturedAt")
        view["currentWorkspace"] = pick(result["currentWorkspace"], "root", "branch", "head")
    for key in ("snapshotComparison", "changesSinceStart"):
        if key in result:
            view[key] = {**pick(result[key], "status", "savedSnapshotId", "currentSnapshotId"),
                         "changeCount": len(result[key]["changes"])}
    for key in ("verification", "currentVerification"):
        if key in result:
            view[key] = checks(result[key])
    if "review" in result:
        view["verificationAtBuild"] = checks(result["review"]["verification"])
    if "state" in result:
        view["state"] = result["state"]
    if "memoryContext" in result:
        context = result["memoryContext"]
        view["memoryContext"] = {**pick(context, "complete", "budgetBytes", "usedBytes"),
                                 "selectedCount": len(context["selected"]), "readPath": "/memoryContext/selected"}
    if "documents" in result:
        view["documentStates"] = result["documents"]["states"]
    if "instructions" in result:
        view["rules"] = [{"file": name, "readPath": "/instructions/" + name.replace("~", "~0").replace("/", "~1")}
                         for name in result["instructions"]]
        view["draftReadPath"] = "/draft"
    if "content" in result and isinstance(result["content"], dict):
        view.update(pick(result, "snapshotId", "file", "layer"))
        view["content"] = {**pick(result["content"], "sha256", "encoding"), "readPath": "/content/data"}
    if "error" in result:
        view["error"] = pick(result["error"], "code", "message")
    return view


class ResponseStore:
    """完整结果仅保存在本 MCP 进程内；LRU 限制指序列化字节，不是 Python 堆大小。"""

    def __init__(self, *, capacity=CACHE_BYTES, max_items=CACHE_ITEMS):
        self.capacity, self.max_items = capacity, max_items
        self.items = OrderedDict()
        self.size = 0

    def present(self, result: dict, *, full=False) -> dict:
        raw = encode(result).encode("utf-8")
        if full or len(raw) <= INLINE_BYTES:
            return result
        identifier = hashlib.sha256(raw).hexdigest()
        available = len(raw) <= self.capacity
        if available:
            if identifier not in self.items:
                self.items[identifier] = (json.loads(raw), len(raw))
                self.size += len(raw)
            self.items.move_to_end(identifier)
            while self.size > self.capacity or len(self.items) > self.max_items:
                _, (_, size) = self.items.popitem(last=False)
                self.size -= size
        reference = {"complete": False, "kind": "summary", "bytes": len(raw),
                     "scope": "captured_result_not_live", "cacheScope": "this_server_process",
                     "capturedAt": datetime.now(timezone.utc).isoformat(),
                     "responseId": identifier if available else None,
                     "read": {"tool": "flow_read", "response_id": identifier, "path": "", "offset": 0} if available else None,
                     "fallback": "按领域 ID 用 CLI show/resume 读取；未收到回复时先查询，不重试写操作。",
                     "unavailableReason": None if available else "response_exceeds_cache_capacity"}
        view = summary(result)
        body = {**view, "presentation": reference}
        if len(encode(body).encode("utf-8")) > INLINE_BYTES:
            # 大量检查/候选/正文不能被静默截成看似完整的列表。
            body = {k: pick(v, "id", "revision", "taskId", "taskRevision", "snapshotId", "status", "exitCode")
                    for k, v in view.items() if k in ("task", "run", "review", "memory", "document", "record", "snapshot")}
            body.update(pick(view, "applicability", "refreshNeeded", "cliReady", "mcpReady", "version", "status", "modelExecution"))
            if "error" in result:
                body["error"] = {"code": result["error"]["code"], "message": "完整错误见 presentation.read。"}
            body["presentation"] = reference
        return body

    def read(self, response_id: str, *, path="", offset=0, limit=2000) -> dict:
        if (not isinstance(response_id, str) or not isinstance(path, str) or len(path) > 2048
                or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4096):
            raise FlowError("invalid_input", "读取需 response_id、JSON Pointer path、非负字符 offset 和 1–4096 的 limit。")
        if response_id not in self.items:
            raise FlowError("response_expired", "结果不在本服务进程缓存中；请按领域 ID show/resume 重新读取，勿重复写操作。")
        self.items.move_to_end(response_id)
        value = self.items[response_id][0]
        if path:
            if not path.startswith("/"):
                raise FlowError("invalid_input", "path 为空或以 / 开头的 JSON Pointer；~1 表示 /，~0 表示 ~。")
            for component in path[1:].split("/"):
                if "~" in component.replace("~0", "").replace("~1", ""):
                    raise FlowError("invalid_input", "JSON Pointer 转义无效。")
                component = component.replace("~1", "/").replace("~0", "~")
                try:
                    if isinstance(value, list):
                        if not component.isascii() or not component.isdecimal() or str(int(component)) != component:
                            raise ValueError("array index")
                        index = int(component)
                        if index >= len(value):
                            raise IndexError("array index")
                        value = value[index]
                    elif isinstance(value, dict):
                        value = value[component]
                    else:
                        raise ValueError("scalar")
                except (KeyError, IndexError, ValueError) as exc:
                    raise FlowError("content_not_found", "该缓存结果中没有此 JSON Pointer。") from exc
        text = value if isinstance(value, str) else encode(value)
        if offset > len(text):
            raise FlowError("invalid_input", "offset 超出内容字符范围。")
        base = {"responseId": response_id, "path": path, "format": "text" if isinstance(value, str) else "json",
                "scope": "captured_result_not_live", "applicability": "not_recomputed",
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "totalCharacters": len(text),
                "offset": offset, "offsetUnit": "unicode_code_points", "startLine": text.count("\n", 0, offset) + 1,
                "startsMidLine": offset > 0 and text[offset - 1] != "\n"}
        def page(count):
            end = offset + count
            return {**base, "text": text[offset:end], "nextOffset": end if end < len(text) else None,
                    "complete": end == len(text)}
        low, high = 0, min(limit, len(text) - offset)
        if len(encode(page(0)).encode("utf-8")) > INLINE_BYTES:
            raise FlowError("invalid_input", "path 元数据超出内联限制，请选择更短的父级 Pointer。")
        while low < high:
            middle = (low + high + 1) // 2
            if len(encode(page(middle)).encode("utf-8")) <= INLINE_BYTES:
                low = middle
            else:
                high = middle - 1
        if low == 0 and offset < len(text):
            raise FlowError("invalid_input", "path 元数据未留出内容空间，请选择更短的父级 Pointer。")
        return page(low)
