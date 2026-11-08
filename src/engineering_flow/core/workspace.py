"""Git 身份与状态观察；内容快照由 snapshots 模块采集。"""

import hashlib
import os
import subprocess
from pathlib import Path

from .errors import FlowError


GIT_PATHS = (".", ":(top,exclude).engineering-flow")


def _git(path: Path, *args: str, allowed: tuple[int, ...] = (0,), input_data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(path), "-c", "core.fsmonitor=false", *args],
            input=input_data, capture_output=True, timeout=10,
            # 避免继承外部 Git 上下文，把另一仓库误当当前工作区。
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FlowError("workspace_error", f"无法执行 Git 工作区观察：{exc}") from exc
    if result.returncode not in allowed:
        raise FlowError("workspace_error", "无法读取 Git 工作区；请指定有效的非裸仓库路径。")
    return result.stdout


def _identity(*paths: str) -> str:
    return hashlib.sha256(os.fsencode("\0".join(paths))).hexdigest()


def inspect_workspace(path: Path) -> dict:
    root = Path(os.fsdecode(_git(path, "rev-parse", "--show-toplevel")).removesuffix("\n")).resolve()
    git_dir = Path(os.fsdecode(_git(root, "rev-parse", "--absolute-git-dir")).removesuffix("\n")).resolve()
    common = Path(os.fsdecode(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).removesuffix("\n")).resolve()
    branch = os.fsdecode(_git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1))).rstrip("\n") or None
    head = os.fsdecode(_git(root, "rev-parse", "--verify", "HEAD", allowed=(0, 128))).strip() or None
    entries = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                   "--", *GIT_PATHS).split(b"\0")
    changes = []
    index = 0
    while index < len(entries) and entries[index]:
        entry = entries[index]
        status = entry[:2].decode("ascii")
        change = {"status": status, "path": os.fsdecode(entry[3:]), "ownership": "unknown"}
        if "R" in status or "C" in status:
            index += 1
            change["originalPath"] = os.fsdecode(entries[index])
        changes.append(change)
        index += 1
    return {
        "projectId": _identity(str(common)),
        "workspaceId": _identity(str(root), str(git_dir)),
        "root": str(root), "gitDir": str(git_dir), "gitCommonDir": str(common),
        "branch": branch, "head": head, "observedChanges": changes,
        "origin": "program_observation", "snapshotId": None,
    }
