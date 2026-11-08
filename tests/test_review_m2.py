"""验证结果可信度、引用、安全展示及本地交互边界；PTY 是测试自动化，不是真实人工验收。"""

import errno
import hashlib
import json
import os
import pty
import re
import select
import signal
import sqlite3
import sys
import time
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from engineering_flow.core.errors import FlowError
from engineering_flow.core.evidence import seal
from engineering_flow.core.feedback import ConfirmationPort, ConsentReceipt, FeedbackService
from engineering_flow.core.reviews import ReviewService
from engineering_flow.core.store import TaskStore

from support import GitFixture


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.ids, self.links, self.tags, self.events = [], [], [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for key, value in attrs:
            if key == "id": self.ids.append(value)
            if key == "href": self.links.append(value)
            if key.startswith("on"): self.events.append((key, value))


class SimulatedConsent(ConfirmationPort):
    """可信端口的测试替身，仅测试 Core 状态，不证明真人身份。"""
    def __init__(self, action=None):
        self.action = action

    def request(self, opinion):
        if self.action: self.action()
        return ConsentReceipt(opinion["integrity"], {"source": "interactive_terminal", "uid": os.getuid(),
                              "account": "automated-test-fixture", "tty": "/dev/test-fixture",
                              "assurance": "local_session_not_identity_verified"})


class ReviewM2Tests(GitFixture):
    def setup_review(self):
        config = {"schemaVersion": 1, "checks": [
            {"id": "pass", "required": True, "argv": ["{python}", "-c", "print('<script>window.injected=1</script>')"]},
            {"id": "fail", "required": False, "argv": ["{python}", "-c", "raise SystemExit(1)"]},
            {"id": "error", "required": False, "argv": ["/ef-missing-command-123"]},
            {"id": "skip", "required": True, "argv": ["{python}", "-c", "raise RuntimeError('must not execute')"]},
            {"id": "unrun", "required": False, "argv": ["{python}", "-c", "print('unrun')"]}
        ]}
        (self.root / ".engineering-flow.json").write_text(json.dumps(config))
        task = self.start()["task"]
        review = self.cli("review", "build", task["id"])
        return task["id"], review

    def explain(self, review_id, references=None):
        content = {"summary": "<img src=x onerror=evil> AI summary", "behaviors": [
            {"title": "重试行为", "description": "未经确认的行为理解", "acceptanceCriteria": [1],
             "references": references or [{"file": "tracked.txt", "layer": "worktree", "startLine": 1, "endLine": 1}]}]}
        return FeedbackService(self.root).explain(review_id, content)

    def opinion(self, review_id, **kwargs):
        return FeedbackService(self.root).record(review_id, decision=kwargs.get("decision", "approve"),
                                                comment=kwargs.get("comment", "核对限定范围"), files=kwargs.get("files"))['record']

    def test_required_skip_preserves_requirement_and_supersedes_earlier_pass(self):
        task_id, _ = self.setup_review()
        self.cli("check", "run", task_id, "pass")
        skipped = self.cli("check", "skip", task_id, "pass", "--reason", "设备不可用 <script>alert(1)</script>")
        run = skipped["run"]
        self.assertEqual((run["status"], run["origin"], run["executionMode"], run["argv"], run["exitCode"]),
                         ("skipped", "caller", "not_executed", [], None))
        verification = self.cli("task", "resume", task_id)["verification"]
        item = next(c for c in verification["checks"] if c["check"]["id"] == "pass")
        self.assertTrue(item["check"]["required"])
        self.assertFalse(item["verified"])
        self.assertEqual(item["runId"], run["id"])
        self.assertFalse(verification["requiredChecksPassed"])
        self.assertEqual(self.cli("check", "show", run["id"])["run"], run)

    def test_skip_requires_reason_and_does_not_execute_configured_command(self):
        task_id, _ = self.setup_review()
        self.assertEqual(self.cli("check", "skip", task_id, "skip", "--reason", " ", code=1)["code"], "invalid_input")
        result = self.cli("check", "skip", task_id, "skip", "--reason", "显式暂缓")
        self.assertEqual(result["run"]["stderr"]["size"], 0)
        self.cli("check", "skip", task_id, "missing", "--reason", "missing", code=1)

    def test_html_covers_all_states_and_escapes_code_logs_and_caller_text(self):
        from engineering_flow.core.checks import CheckService
        task_id, _ = self.setup_review()
        checks = CheckService(self.root)
        checks.run(task_id, "pass");checks.run(task_id, "fail");checks.run(task_id, "error")
        checks.skip(task_id, "skip", reason="<svg onload=evil> temporarily skipped")
        (self.root / "tracked.txt").write_text("<script>window.injected=2</script>\n")
        built = self.cli("review", "build", task_id)
        source = Path(built["htmlPath"]).read_text()
        document = Document(source)
        for label in ("已通过", "失败", "执行错误", "未运行", "已跳过", "已过期"):
            self.assertIn(label, source)
        self.assertNotIn("script", document.tags)
        self.assertNotIn("svg", document.tags)
        self.assertEqual(document.events, [])
        self.assertIn("&lt;script&gt;window.injected=2&lt;/script&gt;", source)
        self.assertIn("&lt;script&gt;window.injected=1&lt;/script&gt;", source)
        self.assertIn("default-src &#x27;none&#x27;", source.replace("'", "&#x27;"))
        self.assertEqual(len(document.ids), len(set(document.ids)))
        for link in document.links:
            if link.startswith("#"):
                self.assertIn(link[1:], document.ids)
            else:
                self.assertIn(link, ("review.json", "review.md", "references.json", "handoff.md", "handoff.json"))
                self.assertTrue((Path(built["directory"]) / link).is_file())

    def test_explanation_links_exact_snapshot_line_and_flags_invalid_references(self):
        task_id, built = self.setup_review()
        references = [{"file": "tracked.txt", "layer": "worktree", "startLine": 1, "endLine": 1},
                      {"file": "missing.py", "layer": "worktree", "startLine": 1, "endLine": 1},
                      {"file": "tracked.txt", "layer": "worktree", "startLine": 900, "endLine": 901}]
        explanation = self.explain(built["review"]["id"], references)["record"]
        newer = self.cli("review", "build", task_id)
        source = Path(newer["htmlPath"]).read_text()
        self.assertEqual(newer["review"]["aiExplanation"], explanation)
        self.assertIn("引用失效：missing.py", source)
        self.assertIn("行号超出该快照实际内容", source)
        self.assertIn("未经人工确认", source)
        self.assertNotIn("img", Document(source).tags)
        self.assertTrue(any(link.endswith("-worktree-L1") for link in Document(source).links))

    def test_explanation_remains_on_old_snapshot_after_code_changes(self):
        task_id, built = self.setup_review()
        explanation = self.explain(built["review"]["id"])["record"]
        (self.root / "tracked.txt").write_text("new content\n")
        new = self.cli("review", "build", task_id)
        source = Path(new["htmlPath"]).read_text()
        state = next(s for s in new["review"]["reviewFeedback"]["states"] if s["eventId"] == explanation["id"])
        self.assertEqual(state["applicability"], "stale")
        self.assertIn(explanation["snapshotId"], source)
        self.assertIn(">baseline</span>", source)
        self.assertIn(">new content</span>", source)

    def test_caller_cannot_set_confirmation_identity_or_use_noninteractive_input(self):
        _, built = self.setup_review()
        opinion = self.opinion(built["review"]["id"])
        self.assertEqual(opinion["origin"], "caller")
        self.assertIsNone(opinion["actor"])
        self.assertEqual(self.cli("review", "confirm", opinion["id"], code=1)["code"], "confirmation_source")
        with self.assertRaises(FlowError) as raised:
            FeedbackService(self.root).confirm(opinion["id"], authority={"confirmed": True, "actor": "human"})
        self.assertEqual(raised.exception.code, "confirmation_source")
        self.assertEqual(self.cli("review", "record", built["review"]["id"], "--decision", "approve", "--comment", "AI says human")["confirmed"], False)
        self.assertEqual(self.cli("task", "resume", opinion["taskId"])["reviewFeedback"]["confirmedScopes"], [])

    def test_confirmed_scope_is_bound_to_snapshot_and_survives_restart(self):
        task_id, built = self.setup_review()
        opinion = self.opinion(built["review"]["id"], files=["tracked.txt"])
        event = FeedbackService(self.root).confirm(opinion["id"], authority=SimulatedConsent())["record"]
        resumed = self.cli("task", "resume", task_id)
        self.assertEqual(resumed["reviewFeedback"]["confirmedScopes"][0]["scope"], {"kind": "files", "files": ["tracked.txt"]})
        self.assertFalse(resumed["verification"]["requiredChecksPassed"])
        (self.root / "tracked.txt").write_text("changed after scoped confirmation\n")
        resumed = self.cli("task", "resume", task_id)
        self.assertEqual(resumed["reviewFeedback"]["confirmedScopes"], [])
        self.assertEqual(next(s["applicability"] for s in resumed["reviewFeedback"]["states"] if s["eventId"] == event["id"]), "stale")
        with self.assertRaises(FlowError) as raised:
            FeedbackService(self.root).confirm(opinion["id"], authority=SimulatedConsent())
        self.assertEqual(raised.exception.code, "review_stale")

    def test_change_during_interactive_confirmation_prevents_write(self):
        task_id, built = self.setup_review()
        opinion = self.opinion(built["review"]["id"])
        for action in (lambda: (self.root / "tracked.txt").write_text("changed while waiting\n"),):
            with self.assertRaises(FlowError) as raised:
                FeedbackService(self.root).confirm(opinion["id"], authority=SimulatedConsent(action))
            self.assertEqual(raised.exception.code, "review_stale")
        self.assertEqual(self.cli("task", "resume", task_id)["reviewFeedback"]["confirmedScopes"], [])

    def test_task_revision_change_invalidates_confirmation_and_confirmation_race(self):
        task_id, built = self.setup_review()
        opinion = self.opinion(built["review"]["id"])
        action = lambda: self.cli("task", "checkpoint", task_id, "--expected-revision", "1", "--progress", "changed requirement context")
        with self.assertRaises(FlowError) as raised:
            FeedbackService(self.root).confirm(opinion["id"], authority=SimulatedConsent(action))
        self.assertEqual(raised.exception.code, "review_stale")
        self.assertFalse(self.cli("task", "resume", task_id)["reviewFeedback"]["confirmedScopes"])

    def test_later_confirmation_for_same_scope_supersedes_earlier_approval(self):
        task_id, built = self.setup_review()
        service = FeedbackService(self.root)
        first = self.opinion(built["review"]["id"])
        original = service.confirm(first["id"], authority=SimulatedConsent())["record"]
        second = self.opinion(built["review"]["id"], decision="request_changes", comment="发现未覆盖情况")
        service.confirm(second["id"], authority=SimulatedConsent())
        feedback = self.cli("task", "resume", task_id)["reviewFeedback"]
        self.assertEqual(feedback["confirmedScopes"][0]["decision"], "request_changes")
        self.assertFalse(next(s["effective"] for s in feedback["states"] if s["eventId"] == original["id"]))

    def test_old_page_does_not_change_and_new_feedback_requires_refresh(self):
        task_id, built = self.setup_review()
        original = Path(built["htmlPath"]).read_bytes()
        self.opinion(built["review"]["id"], comment="new opinion")
        result = self.cli("review", "show", built["review"]["id"])
        self.assertEqual(result["applicability"], "current")
        self.assertTrue(result["refreshNeeded"])
        self.assertEqual(Path(built["htmlPath"]).read_bytes(), original)
        newer = self.cli("review", "build", task_id)
        self.assertIn("new opinion", Path(newer["htmlPath"]).read_text())

    def test_copied_database_and_invalid_or_corrupt_opinion_are_refused(self):
        task_id, built = self.setup_review()
        self.assertEqual(self.cli("review", "record", built["review"]["id"], "--decision", "approve", "--comment", "test", "--file", "missing.py", code=1)["code"], "invalid_input")
        opinion = self.opinion(built["review"]["id"])
        self.git("checkout", "--quiet", "-b", "other")
        self.assertEqual(self.cli("review", "confirm", opinion["id"], code=1)["code"], "workspace_mismatch")
        self.git("checkout", "--quiet", "main")
        opinion["origin"] = "local_terminal"
        self.execute_sql("UPDATE review_events SET document=? WHERE id=?", (json.dumps(opinion), opinion["id"]))
        self.assertEqual(self.cli("task", "resume", task_id, code=1)["code"], "invalid_evidence")

    def test_v3_read_does_not_migrate_and_v4_write_preserves_legacy_material(self):
        task_id, built = self.setup_review()
        legacy = dict(built["review"], schemaVersion=1)
        for key in ("reviewRecords", "reviewFeedback"): legacy.pop(key)
        legacy["aiExplanation"] = None
        raw = json.dumps(seal(legacy))
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE reviews SET document=? WHERE id=?", (raw, legacy["id"]))
            connection.execute("DROP TABLE review_events")
            connection.execute("DROP TABLE memories")
            connection.execute("DROP TABLE memory_events")
            connection.execute("DROP TABLE document_proposals")
            connection.execute("PRAGMA user_version=3")
        self.assertEqual(self.cli("review", "show", legacy["id"])["review"], legacy)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
        self.opinion(legacy["id"])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(connection.execute("SELECT document FROM reviews WHERE id=?", (legacy["id"],)).fetchone()[0], raw)

    def test_v4_migration_error_does_not_save_opinion(self):
        _, built = self.setup_review()
        self.execute_sql("DROP TABLE review_events")
        self.execute_sql("DROP TABLE memories")
        self.execute_sql("DROP TABLE memory_events")
        self.execute_sql("DROP TABLE document_proposals")
        self.execute_sql("PRAGMA user_version=3")
        original = sqlite3.connect
        def denied(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and name == "review_events" else sqlite3.SQLITE_OK)
            return connection
        with patch("engineering_flow.core.store.sqlite3.connect", side_effect=denied):
            with self.assertRaises(FlowError) as raised:
                self.opinion(built["review"]["id"])
        self.assertEqual(raised.exception.code, "storage_error")
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)

    def terminal_confirm(self, opinion_id, *, accept=True, mutate=None):
        # 自动化 PTY 验证真实终端路径，绝不作为真实用户已同意的证据。
        pid, fd = pty.fork()
        if pid == 0:
            os.execv(sys.executable, [sys.executable, "-m", "engineering_flow", "--workspace", str(self.root), "review", "confirm", opinion_id])
        output = b""
        responded = False
        waited = False
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.1)[0]:
                    try: chunk = os.read(fd, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO: break
                        raise
                    if not chunk: break
                    output += chunk
                    match = re.search(rb"CONFIRM ([0-9a-f]{8})", output)
                    if match and not responded:
                        if mutate: mutate()
                        os.write(fd, b"CONFIRM " + match[1] + b"\n" if accept else b"\n")
                        responded = True
                ended, status = os.waitpid(pid, os.WNOHANG)
                if ended:
                    waited = True
                    # 读完剩余输出，避免丢失最后 JSON。
                    while select.select([fd], [], [], 0)[0]:
                        try: output += os.read(fd, 65536)
                        except OSError: break
                    return os.waitstatus_to_exitcode(status), output.decode()
            while time.monotonic() < deadline:
                ended, status = os.waitpid(pid, os.WNOHANG)
                if ended:
                    waited = True
                    return os.waitstatus_to_exitcode(status), output.decode()
                time.sleep(0.02)
            self.fail("terminal confirmation did not exit: " + output.decode())
        finally:
            os.close(fd)
            if not waited:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)

    def test_real_terminal_adapter_challenge_and_cancellation_via_automated_pty(self):
        task_id, built = self.setup_review()
        opinion = self.opinion(built["review"]["id"], comment="包含控制序列 \x1b[2J 与 <script>")
        code, output = self.terminal_confirm(opinion["id"], accept=False)
        self.assertEqual(code, 1, output)
        self.assertIn("confirmation_cancelled", output)
        self.assertNotIn("\x1b[2J", output)
        self.assertFalse(self.cli("task", "resume", task_id)["reviewFeedback"]["confirmedScopes"])
        code, output = self.terminal_confirm(opinion["id"])
        self.assertEqual(code, 0, output)
        feedback = self.cli("task", "resume", task_id)["reviewFeedback"]
        self.assertEqual(feedback["confirmedScopes"][0]["actor"]["uid"], os.getuid())
        self.assertEqual(feedback["confirmedScopes"][0]["actor"]["assurance"], "local_session_not_identity_verified")
