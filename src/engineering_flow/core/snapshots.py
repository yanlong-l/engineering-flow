"""声明范围内的内容快照。连续两次读取一致仍不等于隔离或原子快照。"""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import FlowError
from .config import CONFIG, parse_config
from .paths import relative_path
from .workspace import GIT_PATHS, _git, inspect_workspace

MAX_FILES = 2000
MAX_BYTES = 64 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def fingerprint(document: dict) -> str:
    return digest(canonical({k: v for k, v in document.items() if k not in ("id", "capturedAt")}))


@dataclass
class Capture:
    workspace: dict
    document: dict
    blobs: dict[str, bytes]


def _read(root: Path, name: str) -> tuple[bytes, str] | None:
    """用 dir_fd/O_NOFOLLOW 逐级打开，避免符号链接把读取引到根目录外。"""
    relative_path(name)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = name.split("/")
        for part in parts[:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            os.close(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise FlowError("unsupported_input", f"快照只支持普通文件：{name}")
            raise FlowError("snapshot_limit", f"输入文件超出快照大小限制：{name}")
        with os.fdopen(descriptor, "rb") as stream:
            data = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
            identity = lambda s: (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)
            if identity(before) != identity(after):
                raise FlowError("snapshot_changed", "采集时文件发生变化；未保存，请停止修改后重试。")
            if len(data) > MAX_BYTES:
                raise FlowError("snapshot_limit", f"输入文件超出快照大小限制：{name}")
            return data, "100755" if before.st_mode & 0o111 else "100644"
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FlowError("unsupported_input", f"无法安全读取 {name}；符号链接、特殊文件或不可读路径不受支持。") from exc
    finally:
        os.close(directory)


def _config(root: Path) -> list[str]:
    contents = _read(root, CONFIG)
    return parse_config(contents[0] if contents else None)["additionalInputs"]


def _extra_files(root: Path, names: list[str]) -> set[str]:
    result = set()
    for name in names:
        # 不跟随任何路径分量中的符号链接。
        current = root
        for part in name.split("/"):
            current /= part
            if current.is_symlink():
                raise FlowError("unsupported_input", f"声明输入不支持符号链接：{name}")
        if not current.exists():
            raise FlowError("missing_input", f"声明的输入不存在：{name}")
        if current.is_dir():
            def walk_error(exc):
                raise FlowError("unsupported_input", f"无法枚举声明输入：{name}") from exc
            for directory, directories, files in os.walk(current, followlinks=False, onerror=walk_error):
                for child in directories:
                    nested = Path(directory) / child
                    relative_path(nested.relative_to(root).as_posix())
                    if nested.is_symlink():
                        raise FlowError("unsupported_input", f"声明输入包含符号链接目录：{name}")
                for file in files:
                    result.add(relative_path((Path(directory) / file).relative_to(root).as_posix()))
        else:
            result.add(name)
    return result


def _index(root: Path) -> dict[str, dict]:
    entries = {}
    for entry in _git(root, "ls-files", "--stage", "-z", "--", *GIT_PATHS).split(b"\0"):
        if not entry:
            continue
        info, name = entry.split(b"\t", 1)
        mode, object_id, stage = info.decode("ascii").split()
        if stage != "0" or mode not in ("100644", "100755"):
            raise FlowError("unsupported_input", "快照不支持未解决的合并、符号链接或 submodule。")
        entries[relative_path(os.fsdecode(name))] = {"mode": mode, "objectId": object_id}
    return entries


def _index_blobs(root: Path, entries: dict[str, dict]) -> dict[str, bytes]:
    try:
        return _read_index_blobs(root, entries)
    except (ValueError, IndexError) as exc:
        raise FlowError("snapshot_changed", "暂存区对象读取不完整或发生变化；未保存，请重试。") from exc


def _read_index_blobs(root: Path, entries: dict[str, dict]) -> dict[str, bytes]:
    identifiers = sorted({e["objectId"] for e in entries.values()})
    if not identifiers:
        return {}
    request = "".join(oid + "\n" for oid in identifiers).encode("ascii")
    info = _git(root, "cat-file", "--batch-check", input_data=request).splitlines()
    total = 0
    if len(info) != len(identifiers):
        raise ValueError("incomplete object list")
    for expected, line in zip(identifiers, info):
        oid, kind, size = line.split()
        if kind != b"blob" or oid.decode("ascii") != expected:
            raise FlowError("unsupported_input", "暂存区不是受支持的 blob。")
        total += int(size)
    if total > MAX_BYTES:
        raise FlowError("snapshot_limit", "暂存区内容超出 64 MiB 快照限制。")
    raw = _git(root, "cat-file", "--batch", input_data=request)
    offset = 0
    result = {}
    for expected in identifiers:
        end = raw.index(b"\n", offset)
        oid, kind, size = raw[offset:end].decode("ascii").split()
        if oid != expected or kind != "blob":
            raise FlowError("snapshot_changed", "读取暂存区对象失败，请重试。")
        offset = end + 1
        length = int(size)
        if len(raw) < offset + length + 1 or raw[offset + length:offset + length + 1] != b"\n":
            raise ValueError("truncated object")
        result[oid] = raw[offset:offset + length]
        offset += length + 1
    if offset != len(raw):
        raise ValueError("unexpected object data")
    return result


def _collect(path: Path) -> Capture:
    workspace = inspect_workspace(path)
    root = Path(workspace["root"])
    additional = _config(root)
    index = _index(root)
    names = set(index)
    if workspace["head"] is not None:
        for entry in _git(root, "ls-tree", "-r", "-z", "--full-tree", workspace["head"]).split(b"\0"):
            if entry:
                info, name = entry.split(b"\t", 1)
                if name == b".engineering-flow" or name.startswith(b".engineering-flow/"):
                    continue
                if info.split()[0] not in (b"100644", b"100755"):
                    raise FlowError("unsupported_input", "HEAD 包含不受支持的符号链接或 submodule。")
                names.add(relative_path(os.fsdecode(name)))
    names.update(relative_path(os.fsdecode(p)) for p in _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *GIT_PATHS).split(b"\0") if p)
    names.update(_extra_files(root, additional))
    if _read(root, CONFIG) is not None:
        names.add(CONFIG)
    if len(names) > MAX_FILES:
        raise FlowError("snapshot_limit", "输入超出 2000 个文件的快照限制。")
    ignored = sorted(name for p in _git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z", "--", *GIT_PATHS).split(b"\0")
                     if p and (name := os.fsdecode(p)).rstrip("/") != ".engineering-flow"
                     and not name.startswith(".engineering-flow/"))
    blobs = {}
    size = 0

    def put(data: bytes) -> str:
        nonlocal size
        key = digest(data)
        if key not in blobs:
            size += len(data)
            if size > MAX_BYTES:
                raise FlowError("snapshot_limit", "快照去重后的内容超出 64 MiB 限制。")
            blobs[key] = data
        return key

    index_blobs = _index_blobs(root, index)
    files = []
    for name in sorted(names):
        entry = {"path": name, "index": None, "worktree": {"kind": "missing"}}
        if name in index:
            entry["index"] = dict(index[name], blob=put(index_blobs[index[name]["objectId"]]))
        contents = _read(root, name)
        if contents is not None:
            data, mode = contents
            entry["worktree"] = {"kind": "file", "mode": mode, "blob": put(data), "size": len(data)}
        files.append(entry)
    diff_args = ("--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--no-renames", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/")
    staged = _git(root, "diff", "--cached", *diff_args, "--", *GIT_PATHS)
    unstaged = _git(root, "diff", *diff_args, "--", *GIT_PATHS)
    document = {
        "schemaVersion": 1, "origin": "program_observation", "projectId": workspace["projectId"],
        "workspaceId": workspace["workspaceId"], "branch": workspace["branch"], "head": workspace["head"],
        "scope": {"mode": "git-tracked-and-unignored-plus-declared", "additionalInputs": additional,
                  "configPath": CONFIG, "excludedPaths": [".git/", ".engineering-flow/"],
                  "ignoredPaths": ignored, "consistency": "two-consecutive-reads"},
        "files": files, "diffs": {"staged": put(staged), "unstaged": put(unstaged)},
    }
    document["id"] = fingerprint(document)
    document["capturedAt"] = datetime.now(timezone.utc).isoformat()
    final_workspace = inspect_workspace(root)
    if workspace != final_workspace:
        raise FlowError("snapshot_changed", "采集期间 Git 身份或状态变化；未保存，请重试。")
    workspace["snapshotId"] = document["id"]
    return Capture(workspace, document, blobs)


def capture_snapshot(path: Path) -> Capture:
    first = _collect(path)
    second = _collect(path)
    if first.document["id"] != second.document["id"]:
        raise FlowError("snapshot_changed", "连续两次内容采集不一致；未保存，请停止修改后重试。")
    return second


def blob_references(document: dict) -> set[str]:
    refs = set(document["diffs"].values())
    for entry in document["files"]:
        if entry["index"] is not None:
            refs.add(entry["index"]["blob"])
        if entry["worktree"]["kind"] == "file":
            refs.add(entry["worktree"]["blob"])
    return refs


def validate_snapshot(document: dict, snapshot_id: str) -> None:
    try:
        if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1 or document["origin"] != "program_observation":
            raise ValueError("schema or origin")
        if document["id"] != snapshot_id or fingerprint(document) != snapshot_id:
            raise ValueError("fingerprint mismatch")
        if datetime.fromisoformat(document["capturedAt"]).utcoffset() is None:
            raise ValueError("invalid timestamp")
        for key in ("projectId", "workspaceId"):
            if not isinstance(document[key], str) or len(document[key]) != 64:
                raise ValueError("invalid identity")
        if document["scope"]["mode"] != "git-tracked-and-unignored-plus-declared" or document["scope"]["consistency"] != "two-consecutive-reads":
            raise ValueError("invalid scope")
        if not isinstance(document["files"], list):
            raise ValueError("invalid manifest")
        seen = set()
        for entry in document["files"]:
            relative_path(entry["path"])
            if entry["path"] in seen:
                raise ValueError("duplicate path")
            seen.add(entry["path"])
            indexed, current = entry["index"], entry["worktree"]
            if indexed is not None:
                if indexed["mode"] not in ("100644", "100755") or not isinstance(indexed["objectId"], str):
                    raise ValueError("invalid index")
            if current["kind"] not in ("file", "missing"):
                raise ValueError("invalid file kind")
            if current["kind"] == "file" and (current["mode"] not in ("100644", "100755")
                    or type(current["size"]) is not int or current["size"] < 0):
                raise ValueError("invalid file")
        if set(document["diffs"]) != {"staged", "unstaged"}:
            raise ValueError("invalid diffs")
        if any(not isinstance(ref, str) or len(ref) != 64 or any(c not in "0123456789abcdef" for c in ref)
               for ref in blob_references(document)):
            raise ValueError("invalid blob reference")
    except (KeyError, TypeError, ValueError, FlowError, AttributeError) as exc:
        raise FlowError("invalid_snapshot", "快照损坏或指纹不符；未修改原记录。") from exc


def compare_snapshots(saved: dict | None, current: dict, related_files: list[str]) -> dict:
    if saved is None:
        return {"status": "unknown", "savedSnapshotId": None, "currentSnapshotId": current["id"], "changes": []}
    before = {entry["path"]: entry for entry in saved["files"]}
    after = {entry["path"]: entry for entry in current["files"]}
    def kind(name):
        if name not in after or (after[name]["worktree"]["kind"] == "missing"
                                and name in before and before[name]["worktree"]["kind"] == "file"):
            return "removed"
        if name not in before or (before[name]["worktree"]["kind"] == "missing" and after[name]["worktree"]["kind"] == "file"):
            return "added"
        return "modified"
    changes = [
        {"path": name, "kind": kind(name),
         "association": "explicitly_related" if name in related_files else "unknown", "ownership": "unknown"}
        for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)
    ]
    return {"status": "current" if saved["id"] == current["id"] else "stale",
            "savedSnapshotId": saved["id"], "currentSnapshotId": current["id"], "changes": changes}
