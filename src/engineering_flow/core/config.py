"""从快照中的配置读取项目检查；不读取个人偏好或接受执行结论。"""

import json
import math
import re

from .errors import FlowError
from .paths import relative_path

CONFIG = ".engineering-flow.json"
CHECK_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}\Z")


def parse_config(data: bytes | None) -> dict:
    if data is None:
        return {"schemaVersion": 1, "additionalInputs": [], "checks": []}
    try:
        value = json.loads(data)
        if (not isinstance(value, dict) or set(value) - {"schemaVersion", "additionalInputs", "checks"}
                or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1):
            raise ValueError("schema or fields")
        additional = value.get("additionalInputs", [])
        if not isinstance(additional, list):
            raise ValueError("additionalInputs")
        additional = sorted(set(relative_path(p) for p in additional))
        checks, seen = [], set()
        if not isinstance(value.get("checks", []), list):
            raise ValueError("checks")
        for item in value.get("checks", []):
            if (not isinstance(item, dict) or set(item) - {"id", "argv", "cwd", "required", "timeoutSeconds"}
                    or not isinstance(item["id"], str) or not CHECK_ID.fullmatch(item["id"])
                    or item["id"] in seen or type(item["required"]) is not bool
                    or not isinstance(item["argv"], list) or not item["argv"]
                    or any(not isinstance(a, str) or "\0" in a for a in item["argv"])
                    or not item["argv"][0].strip()):
                raise ValueError("check definition")
            cwd = item.get("cwd", ".")
            if cwd != ".":
                relative_path(cwd)
            timeout = item.get("timeoutSeconds", 60)
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0.1 <= timeout <= 3600:
                raise ValueError("timeoutSeconds")
            checks.append({"id": item["id"], "argv": item["argv"], "cwd": cwd,
                           "required": item["required"], "timeoutSeconds": timeout})
            seen.add(item["id"])
        return {"schemaVersion": 1, "additionalInputs": additional, "checks": checks}
    except (ValueError, KeyError, TypeError, FlowError) as exc:
        raise FlowError("invalid_config", f"{CONFIG} 配置无效；检查需唯一 id、argv、布尔 required、仓库内 cwd 和 0.1–3600 秒 timeoutSeconds。") from exc


def snapshot_config(document: dict, blobs: dict[str, bytes]) -> dict:
    entry = next((e for e in document["files"] if e["path"] == CONFIG), None)
    current = entry["worktree"] if entry else {}
    return parse_config(blobs[current["blob"]] if current.get("kind") == "file" else None)
