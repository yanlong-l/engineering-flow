"""按项目 argv 真实执行检查，保留历史结果并计算当前适用性。"""

import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .config import snapshot_config
from .errors import FlowError
from .evidence import output, seal
from .records import text, validate_id
from .snapshots import Capture, capture_snapshot
from .tasks import TaskService, _now

MAX_OUTPUT_BYTES = 4 * 1024 * 1024  # 每个流；超限为执行错误，保留前缀。
EXECUTION_LIMITATIONS = [
    "在当前工作区执行，前后快照相同也不能排除执行期间短暂修改后恢复；未做隔离执行。",
    "只验证声明的输入范围；忽略文件、依赖、PATH 和外部环境可能影响结果。",
    "passed 仅表示配置命令正常退出且退出码为 0；测试数量和断言由项目命令负责。",
    "继承执行器环境，不保存环境变量；仅记录 Python、平台及实际 argv/cwd。",
]


def applicability(run: dict, current: dict) -> str:
    if run["status"] == "running" or run["snapshotAfterId"] is None:
        return "unknown"
    return "current" if run["snapshotId"] == run["snapshotAfterId"] == current["id"] else "stale"


def check_results(store, task: dict, capture: Capture, *, history: list[dict] | None = None) -> dict:
    definitions = snapshot_config(capture.document, capture.blobs)["checks"]
    history = store.evidence("check_runs", task_id=task["id"]) if history is None else history
    latest = {run["check"]["id"]: run for run in history}
    checks = []
    for definition in definitions:
        run = latest.get(definition["id"])
        state = applicability(run, capture.document) if run else "unknown"
        checks.append({"check": definition, "runId": run["id"] if run else None,
                       "status": run["status"] if run else "not_run", "applicability": state,
                       "verified": bool(run and run["status"] == "passed" and state == "current")})
    required = [item for item in checks if item["check"]["required"]]
    return {"checks": checks, "requiredChecksPassed": bool(required) and all(item["verified"] for item in required),
            "history": [{"runId": r["id"], "checkId": r["check"]["id"], "status": r["status"],
                         "applicability": applicability(r, capture.document)} for r in history],
            "limitations": list(EXECUTION_LIMITATIONS)}


class CheckService(TaskService):
    def skip(self, task_id: str, check_id: str, *, reason: str) -> dict:
        text(reason, "跳过原因")
        task, capture = self._resume(task_id)
        self._result(task, capture)
        definition = next((c for c in snapshot_config(capture.document, capture.blobs)["checks"] if c["id"] == check_id), None)
        if definition is None:
            raise FlowError("check_not_found", "项目配置中不存在该检查 ID。")
        now = _now()
        record = {"schemaVersion": 2, "id": uuid4().hex, "taskId": task_id, "taskRevision": task["revision"],
                  "projectId": capture.workspace["projectId"], "workspaceId": capture.workspace["workspaceId"],
                  "origin": "caller", "check": definition, "argv": [], "cwd": str(Path(capture.workspace["root"]) / definition["cwd"]),
                  "snapshotId": capture.document["id"], "snapshotAfterId": capture.document["id"], "executionMode": "not_executed",
                  "startedAt": now, "endedAt": now, "status": "skipped", "reason": reason,
                  "exitCode": None, "failure": None, "stdout": output(b""), "stderr": output(b""), "environment": {},
                  "limitations": ["调用者显式记录跳过；命令没有执行，必需检查仍未满足。"]}
        self._store(capture.workspace).save_evidence("check_runs", seal(record), captures=[capture])
        return {"run": record, "applicability": "current"}

    @staticmethod
    def _cwd(root: Path, relative: str) -> Path:
        directory = root
        if relative != ".":
            for part in relative.split("/"):
                directory /= part
                if directory.is_symlink():
                    raise OSError("检查 cwd 不支持符号链接")
        if not directory.is_dir() or not directory.resolve().is_relative_to(root.resolve()):
            raise OSError("检查 cwd 不存在或越界")
        return directory

    @staticmethod
    def _kill(process) -> None:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

    def run(self, task_id: str, check_id: str) -> dict:
        task, before = self._resume(task_id)
        self._result(task, before)  # 检查旧引用；损坏时不能继续生成可信结论。
        checks = snapshot_config(before.document, before.blobs)["checks"]
        definition = next((c for c in checks if c["id"] == check_id), None)
        if definition is None:
            raise FlowError("check_not_found", "项目配置中不存在该检查 ID；未执行命令。")
        argv = [sys.executable if a == "{python}" else a for a in definition["argv"]]
        root = Path(before.workspace["root"])
        record = {"schemaVersion": 1, "id": uuid4().hex, "taskId": task_id, "taskRevision": task["revision"],
                  "projectId": before.workspace["projectId"], "workspaceId": before.workspace["workspaceId"],
                  "origin": "runner", "check": deepcopy(definition), "argv": argv, "cwd": str(root / definition["cwd"]),
                  "snapshotId": before.document["id"], "snapshotAfterId": None, "executionMode": "workspace",
                  "startedAt": _now(), "endedAt": None, "status": "running", "exitCode": None, "failure": None,
                  "stdout": output(b""), "stderr": output(b""),
                  "environment": {"python": sys.version, "pythonExecutable": sys.executable, "platform": platform.platform()},
                  "limitations": list(EXECUTION_LIMITATIONS)}
        store = self._store(before.workspace)
        store.save_evidence("check_runs", seal(record), captures=[before])
        process, after, failure = None, None, None
        previous_handler = None
        if threading.current_thread() is threading.main_thread():
            previous_handler = signal.getsignal(signal.SIGTERM)
            def interrupted(signum, frame):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, interrupted)
        try:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                try:
                    cwd = self._cwd(root, definition["cwd"])
                    process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                               start_new_session=True)
                    deadline = time.monotonic() + definition["timeoutSeconds"]
                    while True:
                        code = process.poll()
                        if max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size) > MAX_OUTPUT_BYTES:
                            failure = {"kind": "output_limit", "message": "输出超过每个流 4 MiB 限制，已终止命令。"}
                            break
                        if code is not None:
                            break
                        if time.monotonic() >= deadline:
                            failure = {"kind": "timeout", "message": "命令超过配置的时间限制，已终止进程组。"}
                            break
                        time.sleep(0.02)
                except OSError as exc:
                    failure = {"kind": "launch", "message": str(exc)}
                except KeyboardInterrupt:
                    failure = {"kind": "interrupted", "message": "执行器被中断，未确认检查完成。"}
                finally:
                    self._kill(process)
                record["exitCode"] = process.returncode if process else None
                for key, stream in (("stdout", stdout), ("stderr", stderr)):
                    stream.seek(0)
                    data = stream.read(MAX_OUTPUT_BYTES + 1)
                    record[key] = output(data[:MAX_OUTPUT_BYTES], truncated=len(data) > MAX_OUTPUT_BYTES)
                    if len(data) > MAX_OUTPUT_BYTES and failure is None:
                        failure = {"kind": "output_limit", "message": "输出被截断，不能标为通过。"}
        except OSError as exc:
            failure = {"kind": "output_capture", "message": str(exc)}
        finally:
            if previous_handler is not None:
                signal.signal(signal.SIGTERM, previous_handler)
        record["endedAt"] = _now()
        try:
            after = capture_snapshot(root)
            record["snapshotAfterId"] = after.document["id"]
        except FlowError as exc:
            failure = {"kind": "post_snapshot", "code": exc.code, "message": str(exc), "executionFailure": failure}
        if failure is None and record["exitCode"] is not None and record["exitCode"] < 0:
            failure = {"kind": "signal", "message": f"命令被信号 {-record['exitCode']} 终止。"}
        record["failure"] = failure
        record["status"] = "error" if failure else "passed" if record["exitCode"] == 0 else "failed"
        store.save_evidence("check_runs", seal(record), captures=[after] if after else [], finishing=True)
        # 这里的适用性只针对结束时快照；get/resume 会重新采集后再计算。
        return {"run": record, "applicability": applicability(record, after.document) if after else "unknown"}

    def get(self, run_id: str) -> dict:
        validate_id(run_id)
        from .workspace import inspect_workspace
        workspace = inspect_workspace(self.workspace_path)
        store = self._store(workspace)
        rows = store.evidence("check_runs", evidence_id=run_id)
        if not rows:
            raise FlowError("check_not_found", "找不到该检查运行。")
        record = rows[0]
        task, capture = self._resume(record["taskId"])
        self._result(task, capture)
        return {"run": record, "applicability": applicability(record, capture.document), "currentSnapshotId": capture.document["id"]}
