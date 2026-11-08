"""M5 构造试点；只操作新建目录，通过独立 CLI 进程收集证据，不调用模型。"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4


PROJECT = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Page(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.tags, self.events, self.links, self.ids = [], [], [], []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for name, value in attrs:
            if name.startswith("on"):
                self.events.append(name)
            if name in ("href", "src"):
                self.links.append(value)
            if name == "id":
                self.ids.append(value)


class Pilot:
    def __init__(self, output):
        # 拒绝覆盖，失败时保留现场；不复用或清理用户已有仓库。
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.repo = self.output / "repo"
        self.repo.mkdir()
        self.commands, self.observations = [], []
        self.started = time.monotonic()
        self.manifest = {"schemaVersion": 1, "kind": "constructed_python_pilot",
                         "startedAt": datetime.now(timezone.utc).isoformat(),
                         "status": "running", "humanApproval": "not_observed",
                         "humanSemanticReview": "not_observed", "teamBenefit": "not_measured",
                         "runtime": {"python": sys.version, "executable": sys.executable,
                                     "platform": platform.platform()},
                         "commands": self.commands, "observations": self.observations}
        shutil.copy2(__file__, self.output / "run_pilot.py")
        inputs = [Path(__file__), *sorted((PROJECT / "examples/batch-queue").iterdir())]
        self.manifest["inputFiles"] = {str(p.relative_to(PROJECT)): sha(p.read_bytes()) for p in inputs if p.is_file()}
        self.save()

    def save(self):
        self.manifest["elapsedSeconds"] = round(time.monotonic() - self.started, 3)
        write_json(self.output / "pilot.json", self.manifest)

    def require(self, condition, description):
        self.observations.append({"description": description, "passed": bool(condition),
                                  "afterCommand": len(self.commands)})
        self.save()
        if not condition:
            raise RuntimeError(description)

    def command(self, name, argv, *, expected=0, cwd=None):
        started = time.monotonic()
        # 不采集环境变量；禁用 fixture 的外部 Git hooks/签名和继承的 Git 重定向。
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        execution_error = None
        try:
            result = subprocess.run(argv, cwd=cwd or self.repo, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            execution_error = f"{type(exc).__name__}: {exc}"
            result = subprocess.CompletedProcess(argv, None, getattr(exc, "stdout", None) or b"",
                                                 getattr(exc, "stderr", None) or b"")
        stem = f"{len(self.commands) + 1:02}-{name}"
        raw_files = {}
        for stream in ("stdout", "stderr"):
            raw = getattr(result, stream)
            filename = f"{stem}.{stream}"
            (self.output / filename).write_bytes(raw)
            raw_files[stream] = {"path": filename, "sha256": sha(raw), "bytes": len(raw)}
        self.commands.append({"name": name, "argv": list(map(str, argv)),
                              "cwd": str(cwd or self.repo), "exitCode": result.returncode,
                              "expectedExitCode": expected,
                              "executionError": execution_error,
                              "elapsedSeconds": round(time.monotonic() - started, 3), **raw_files})
        self.save()
        if result.returncode != expected:
            raise RuntimeError(f"{name}: exit={result.returncode}, expected={expected}; see {stem}.stderr")
        return result

    def git(self, *args):
        return self.command("git-" + args[0], ["git", "-c", "user.name=EF Pilot",
                            "-c", "user.email=ef-pilot@example.invalid", "-c", "commit.gpgsign=false",
                            "-c", "core.hooksPath=/dev/null", *args])

    def cli(self, name, *args, expected=0):
        result = self.command(name, [sys.executable, "-I", "-m", "engineering_flow",
                                    "--workspace", str(self.repo), *args], expected=expected)
        return json.loads(result.stderr if expected == 1 else result.stdout)

    def input(self, name, value):
        path = self.output / f"{name}.json"
        write_json(path, value)
        return str(path)

    def run(self):
        example = PROJECT / "examples/batch-queue"
        identity = self.command("product-identity", [sys.executable, "-I", "-c",
            "import hashlib,json,pathlib,engineering_flow; "
            "p=pathlib.Path(engineering_flow.__file__).parent; "
            "print(json.dumps({'version':engineering_flow.__version__, 'packagePath':str(p), "
            "'files':{str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() "
            "for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}}))"])
        self.manifest["productIdentity"] = json.loads(identity.stdout)
        for path in example.iterdir():
            if path.is_file():
                shutil.copy2(path, self.repo / path.name)
        # 预置缺陷明确标识，修复内容来自现有正确示例，不声称模型发现了未知缺陷。
        shutil.copy2(example / "buggy_queue.py", self.repo / "batch_queue.py")
        (self.repo / "NOTES.md").write_text("构造仓库基线。\n", encoding="utf-8")
        config = json.loads((self.repo / ".engineering-flow.json").read_text())
        config["checks"] += [
            {"id": "missing-command", "required": False, "argv": [str(self.repo / "absent-command")]},
            {"id": "timeout", "required": False, "argv": ["{python}", "-c", "import time; print('started', flush=True); time.sleep(5)"], "timeoutSeconds": 0.1},
            {"id": "log-text", "required": False, "argv": ["{python}", "-c", "print('<script>window.pilot=1</script>')"]},
            {"id": "unrun", "required": False, "argv": ["{python}", "-c", "print('not executed')"]},
        ]
        write_json(self.repo / ".engineering-flow.json", config)
        self.git("init", "--quiet", "-b", "main")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Constructed pilot baseline with intentional defect")
        (self.repo / "NOTES.md").write_text("开始前暂存改动。\n", encoding="utf-8")
        self.git("add", "NOTES.md")
        (self.repo / "NOTES.md").write_text("开始前暂存改动。\n另有未暂存内容。\n", encoding="utf-8")
        doctor = self.cli("doctor", "doctor")
        self.require(doctor["cliReady"], "CLI 诊断可用，不要求 Hooks 或模型服务")
        self.manifest["productVersion"] = doctor["version"]
        start = self.cli("start", "task", "start", "--goal", "构造试点：批量任务重试复用原批次",
                         "--accept", "相同标识与列表复用；不同列表拒绝；重开及同机并发保持一致",
                         "--file", "batch_queue.py", "--progress", "调用者声称检查通过；尚无执行记录",
                         "--issue", "未覆盖真实分布式服务、设备调度及网络超时")
        task = start["task"]; task_id = task["id"]
        self.manifest["taskId"] = task_id
        self.require(bool(task["startingWorkspace"]["observedChanges"]) and
                     all(c["ownership"] == "pre_existing_unknown" for c in task["startingWorkspace"]["observedChanges"]),
                     "启动前已有暂存/未暂存改动保持归属未知")
        self.require(not start["verification"]["requiredChecksPassed"], "调用者通过声明不能填补未运行检查")
        unrun = self.cli("unrun-review", "review", "build", task_id)
        self.require(any(c["status"] == "not_run" and c["check"]["required"] for c in unrun["review"]["verification"]["checks"]),
                     "材料显示必需项未运行")
        failed = self.cli("intentional-defect", "check", "run", task_id, "idempotency", expected=3)
        self.require(failed["run"]["status"] == "failed" and "FAILED" in failed["run"]["stderr"]["data"],
                     "预置重复请求缺陷产生真实断言失败")
        shutil.copy2(example / "batch_queue.py", self.repo / "batch_queue.py")
        saved = self.cli("repair-checkpoint", "task", "checkpoint", task_id, "--expected-revision", "1",
                         "--progress", "以现有正确示例替换构造缺陷；需要重新执行四个行为案例")
        self.require(saved["task"]["revision"] == 2 and saved["currentWorkspace"]["head"] == task["startingWorkspace"]["head"],
                     "HEAD 不变时修复仍改变快照，checkpoint 保存修订")
        passed = self.cli("repaired-check", "check", "run", task_id, "idempotency")
        self.require(passed["run"]["status"] == "passed" and passed["applicability"] == "current"
                     and "Ran 4 tests" in passed["run"]["stderr"]["data"], "修复后四个真实行为检查 passed/current")
        for check in ("missing-command", "timeout"):
            error = self.cli(check, "check", "run", task_id, check, expected=3)
            self.require(error["run"]["status"] == "error", f"{check} 保留执行错误")
        self.cli("log-text", "check", "run", task_id, "log-text")
        self.cli("known-bug", "check", "run", task_id, "known-bug", expected=3)
        self.cli("skip-required", "check", "skip", task_id, "idempotency", "--reason", "构造暂缓：保留跳过事实")
        skipped = self.cli("resume-skipped", "task", "resume", task_id)
        self.require(not skipped["verification"]["requiredChecksPassed"], "最新必需项跳过覆盖旧通过且不满足要求")
        skip_review = self.cli("skipped-review", "review", "build", task_id)
        self.cli("rerun-required", "check", "run", task_id, "idempotency")
        current = self.cli("current-review", "review", "build", task_id)
        explanation = json.loads((example / "explanation.example.json").read_text())
        self.cli("explanation", "review", "explain", current["review"]["id"], "--input", self.input("explanation", explanation))
        opinion = self.cli("opinion", "review", "record", current["review"]["id"], "--decision", "request_changes",
                           "--comment", "构造意见：分布式服务仍需单独验收", "--file", "batch_queue.py")
        denied = self.cli("noninteractive-confirm", "review", "confirm", opinion["record"]["id"], expected=1)
        self.require(denied["error"]["code"] == "confirmation_source", "非交互调用不能直接写入人工确认")
        memory = self.cli("memory", "memory", "propose", task_id, "--input", str(self.repo / "memory.example.json"))
        contrary = json.loads((example / "memory.example.json").read_text())
        contrary["content"] = "构造相反候选：相同请求也应创建新批次；此说法故意与原候选冲突。"
        second = self.cli("contrary-memory", "memory", "propose", task_id, "--input", self.input("contrary-memory", contrary))
        self.cli("memory-conflict", "memory", "relate", memory["memory"]["id"], "--relation", "conflicts_with",
                 "--other", second["memory"]["id"], "--reason", "构造声明，非程序自动语义识别")
        context = self.cli("conflicting-context", "memory", "context", task_id, "--module", "queue")
        self.require(len(context["selected"]) == 2 and
                     all(m["state"]["hasActiveConflict"] and not m["state"]["eligibleAsCurrentBackground"] for m in context["selected"]),
                     "显式声明矛盾的两条候选保留来源，不合成当前规则")
        document = self.cli("document", "document", "propose", task_id, "--input", str(self.repo / "document.example.json"))
        original = document["document"]
        packet = self.cli("voice", "document", "voice", original["id"])
        self.require(packet["status"] == "loaded" and packet["modelExecution"] == "not_observed", "固定表达规则加载成功不表示模型已改写")
        rewrite = {"proposalIntegrity": packet["proposalIntegrity"], "moduleDigest": packet["moduleDigest"],
                   "rewritten": original["proposal"]["draft"].replace("请求内容不同时拒绝", "请求内容不同时接受")}
        rejected = self.cli("rejected-rewrite", "document", "rewrite", original["id"], "--input", self.input("bad-rewrite", rewrite))
        self.require(rejected["document"]["voice"]["status"] == "rejected" and rejected["document"]["after"] == original["after"],
                     "条件/否定被改写时拒绝候选并保留原稿")
        exported = self.cli("export-document", "document", "export", original["id"])
        self.require(not (self.repo / "MAINTENANCE.md").exists(), "建议、改写与导出没有静默覆盖目标文件")
        handoff = self.cli("handoff-before-edit", "task", "handoff", task_id)
        self.validate_material(handoff)
        self.validate_material(skip_review)
        old_html = Path(handoff["htmlPath"]).read_bytes()
        # 仅在构造仓库演示应用已知原稿；不将脚本行为伪装为真人批准。
        self.git("apply", "--check", exported["patchPath"])
        self.git("apply", exported["patchPath"])
        old = self.cli("stale-review", "review", "show", handoff["review"]["id"])
        self.require(old["applicability"] == "stale" and not old["currentVerification"]["requiredChecksPassed"]
                     and Path(handoff["htmlPath"]).read_bytes() == old_html, "应用文档后旧 Review 和检查失效，旧静态页不改写")
        outdated = self.cli("stale-memory", "memory", "show", memory["memory"]["id"])
        self.require(outdated["state"]["applicability"] == "needs_revalidation" and
                     not outdated["state"]["eligibleAsCurrentBackground"], "候选记忆在新快照不冒充当前规则")
        self.cli("document-checkpoint", "task", "checkpoint", task_id, "--expected-revision", "2",
                 "--progress", "构造脚本已应用原稿；旧建议与解释留在历史快照；下一次核对分布式限制")
        final_check = self.cli("final-check", "check", "run", task_id, "idempotency")
        final = self.cli("final-handoff", "task", "handoff", task_id)
        self.validate_material(final)
        resumed = self.cli("new-process-resume", "task", "resume", task_id)
        self.require(resumed["task"] == final["review"]["task"] and resumed["verification"]["requiredChecksPassed"],
                     "独立新进程恢复同一任务、进度与当前必需检查")
        self.require(final["review"]["humanConfirmation"] is None and
                     not any(e["eventType"] == "confirmation" for e in final["review"]["reviewRecords"]),
                     "全部试点步骤均未产生人工批准")
        self.require(all(s["applicability"] == "stale" for s in resumed["reviewFeedback"]["states"]),
                     "新快照不沿用旧解释和评审意见")
        self.git("switch", "--quiet", "-c", "other")
        wrong = self.cli("wrong-branch", "task", "resume", task_id, expected=1)
        self.require(wrong["error"]["code"] == "workspace_mismatch", "错误分支不能默默续接")
        self.git("switch", "--quiet", "main")
        with closing(sqlite3.connect(self.repo / ".engineering-flow/state.sqlite3")) as db:
            self.require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "试点数据库完整性检查通过")
        self.manifest.update(status="passed", finalReviewId=final["review"]["id"],
                             finalSnapshotId=final_check["run"]["snapshotAfterId"],
                             finalReviewPath=final["htmlPath"], finalTaskRevision=resumed["task"]["revision"])
        self.save()

    def validate_material(self, material):
        directory = Path(material["directory"])
        references = json.loads((directory / "references.json").read_text())
        self.require(bool(references) and all(sha((directory / ref["path"]).read_bytes()) == ref["sha256"] for ref in references),
                     "Review 文件/diff/日志原始引用摘要全部匹配")
        content = Path(material["htmlPath"]).read_text()
        page = Page(content)
        self.require("script" not in page.tags and not page.events and len(page.ids) == len(set(page.ids)),
                     "HTML 无脚本、事件属性或重复锚点")
        self.require("&lt;script&gt;window.pilot=1&lt;/script&gt;" in content, "真实日志中的脚本文本已转义展示")
        self.require(all(link[1:] in page.ids if link.startswith("#") else (directory / link).is_file()
                         for link in page.links), "页面链接指向存在的本地材料或精确锚点")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / ".local/pilot-runs" / uuid4().hex,
                        help="新的证据目录，拒绝覆盖；默认 .local/pilot-runs/随机 ID")
    args = parser.parse_args()
    pilot = Pilot(args.output)
    try:
        pilot.run()
    except Exception as exc:
        pilot.manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        pilot.save()
        print(json.dumps({"status": "failed", "evidence": str(pilot.output), "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "evidence": str(pilot.output), "taskId": pilot.manifest["taskId"],
                      "elapsedSeconds": pilot.manifest["elapsedSeconds"], "humanApproval": "not_observed"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
