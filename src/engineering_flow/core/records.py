"""版本化任务记录校验；v1 可读，后续 checkpoint 追加 v2。"""

import re
from datetime import datetime

from .errors import FlowError
from .paths import relative_path

SCHEMA_VERSION = 2
TASK_ID = re.compile(r"[0-9a-f]{32}\Z")
SNAPSHOT_ID = re.compile(r"[0-9a-f]{64}\Z")


def validate_id(task_id: str) -> None:
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise FlowError("invalid_input", "任务 ID 必须是 start 返回的 32 位十六进制 ID。")


def text(value: object, label: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise FlowError("invalid_input", f"{label}必须是{'字符串' if allow_empty else '非空字符串'}。")


def texts(value: object, label: str, *, nonempty: bool = False) -> None:
    if not isinstance(value, list) or (nonempty and not value):
        raise FlowError("invalid_input", f"{label}必须是{'非空' if nonempty else ''}字符串列表。")
    for item in value:
        text(item, label)


def _workspace(value: dict) -> None:
    for key in ("projectId", "workspaceId", "root", "gitDir", "gitCommonDir"):
        text(value[key], key)
    for key in ("branch", "head"):
        if value[key] is not None:
            text(value[key], key)
    snapshot_id = value["snapshotId"]
    if value["origin"] != "program_observation" or (snapshot_id is not None and (
            not isinstance(snapshot_id, str) or not SNAPSHOT_ID.fullmatch(snapshot_id))):
        raise ValueError("unsupported workspace observation")
    if not isinstance(value["observedChanges"], list):
        raise ValueError("invalid changes")
    for change in value["observedChanges"]:
        text(change["path"], "path")
        if not isinstance(change["status"], str) or len(change["status"]) != 2:
            raise ValueError("invalid status")
        if change["ownership"] not in ("unknown", "pre_existing_unknown"):
            raise ValueError("invalid ownership")
        if "originalPath" in change:
            text(change["originalPath"], "originalPath")


def validate_record(record: dict) -> None:
    try:
        version = record["schemaVersion"]
        if type(version) is not int or version not in (1, SCHEMA_VERSION):
            raise ValueError("unsupported task schema")
        validate_id(record["id"])
        if type(record["revision"]) is not int or record["revision"] < 1:
            raise ValueError("invalid revision")
        text(record["goal"], "目标")
        texts(record["acceptanceCriteria"], "验收条件", nonempty=True)
        text(record["progress"], "进度", allow_empty=True)
        texts(record["unresolvedIssues"], "未决事项")
        if record["status"] != "active" or record["inputOrigin"] != "caller":
            raise ValueError("unsupported task state or origin")
        for key in ("createdAt", "updatedAt"):
            if datetime.fromisoformat(record[key]).utcoffset() is None:
                raise ValueError("timestamp must have timezone")
        _workspace(record["startingWorkspace"])
        _workspace(record["savedWorkspace"])
        if version == 1:
            if any(record[key]["snapshotId"] is not None for key in ("startingWorkspace", "savedWorkspace")):
                raise ValueError("v1 cannot claim a snapshot")
        else:
            if record["savedWorkspace"]["snapshotId"] is None:
                raise ValueError("v2 requires saved snapshot")
            texts(record["relatedFiles"], "关联文件")
            for path in record["relatedFiles"]:
                relative_path(path)
    except (KeyError, TypeError, ValueError, FlowError) as exc:
        raise FlowError("invalid_record", "任务记录损坏或 schema 不受支持；未修改原记录。") from exc
