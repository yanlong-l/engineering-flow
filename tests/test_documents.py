"""真实临时 Git/CLI 验证文档保护、来源、过期、确认及 Skill 降级。"""

import json
import shutil
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from engineering_flow.core.document_records import GENERATED
from engineering_flow.core.documents import DocumentService
from engineering_flow.core.errors import FlowError
from engineering_flow.core.evidence import seal
from engineering_flow.core.feedback import FeedbackService
from engineering_flow.core.store import TaskStore
from engineering_flow.core.tasks import TaskService
from engineering_flow.core.voice import compare_protected, load_module
from support import GitFixture
from test_memory import TestConsent


class DocumentTests(GitFixture):
    def setUp(self):
        super().setUp()
        (self.root / "guide.md").write_bytes("# 人工维护\r\n\r\n原说明。\r\n".encode())
        self.service = DocumentService(self.root)

    def proposal(self, **changes):
        value = {"target": "guide.md", "mode": "manual", "region": None, "draft": "请求最多重试 2 次。认证失败不重试。\n",
                 "reason": "补充重试限制，仍需核对实现。", "protectedFacts": ["最多重试 2 次", "认证失败不重试"],
                 "sources": [{"kind": "code", "file": "tracked.txt", "layer": "worktree", "startLine": 1, "endLine": 1}]}
        value.update(changes)
        return value

    def propose(self, task=None, **changes):
        task = task or self.start()["task"]
        return self.service.propose(task["id"], self.proposal(**changes))

    def rewrite(self, document, rewritten):
        packet = self.service.voice(document["id"])
        return self.service.rewrite(document["id"], {"proposalIntegrity": packet["proposalIntegrity"], "moduleDigest": packet["moduleDigest"], "rewritten": rewritten})

    def confirm(self, documents, decision="approve"):
        review = self.cli("review", "build", documents[0]["taskId"])["review"]
        opinion = FeedbackService(self.root).record(review["id"], decision=decision, comment="自动化夹具，不代表真人批准", document_ids=[d["id"] for d in documents])["record"]
        return FeedbackService(self.root).confirm(opinion["id"], authority=TestConsent())["record"]

    def test_cli_proposal_export_restart_and_handoff_never_overwrite_manual_document(self):
        task = self.start()["task"]
        original = (self.root / "guide.md").read_bytes()
        source = Path(self.temp.name) / "input.json"
        source.write_text(json.dumps(self.proposal()))
        proposed = self.cli("document", "propose", task["id"], "--input", str(source))
        document = proposed["document"]
        self.assertEqual(proposed["state"]["confirmationStatus"], "proposed")
        self.assertEqual(proposed["sources"][0]["origin"], "program_observation")
        exported = self.cli("document", "export", document["id"])
        self.assertEqual(Path(exported["directory"], "before.md").read_bytes(), original)
        self.assertEqual(self.cli("document", "export", document["id"])["directory"], exported["directory"])
        self.assertEqual(self.cli("document", "show", document["id"])["document"], document)
        self.assertEqual((self.root / "guide.md").read_bytes(), original)
        handoff = self.cli("task", "handoff", task["id"])
        material = json.loads(Path(handoff["directory"], "handoff.json").read_text())
        self.assertEqual(material["completion"], "not_asserted")
        self.assertEqual(material["documents"]["records"], [document])
        self.assertFalse(material["verification"]["requiredChecksPassed"])
        self.assertTrue(Path(handoff["handoffPath"]).exists())

    def test_mixed_only_replaces_unique_region_and_preserves_outside_bytes(self):
        before = "人工开头。\r\n<!-- engineering-flow:usage:start -->\r\n旧说明\r\n<!-- engineering-flow:usage:end -->\r\n人工结尾。\r\n"
        (self.root / "guide.md").write_bytes(before.encode())
        document = self.propose(mode="mixed", region="usage")["document"]
        self.assertTrue(document["after"].startswith(before[:before.index("旧说明") - 2]))
        self.assertTrue(document["after"].endswith("<!-- engineering-flow:usage:end -->\r\n人工结尾。\r\n"))
        self.assertEqual((self.root / "guide.md").read_bytes(), before.encode())

    def test_missing_reversed_duplicate_or_nested_markers_are_rejected(self):
        for value in ("no markers", "<!-- engineering-flow:x:end -->\n<!-- engineering-flow:x:start -->",
                      "<!-- engineering-flow:x:start --><!-- engineering-flow:x:start --><!-- engineering-flow:x:end -->",
                      "<!-- engineering-flow:x:start --><!-- engineering-flow:y:start --><!-- engineering-flow:x:end -->"):
            (self.root / "guide.md").write_text(value)
            with self.assertRaises(FlowError):
                self.propose(mode="mixed", region="x")

    def test_generated_only_accepts_new_target_or_explicit_generated_marker(self):
        with self.assertRaises(FlowError):
            self.propose(mode="generated")
        fresh = self.propose(mode="generated", target="new.md")["document"]
        self.assertIsNone(fresh["before"])
        self.assertTrue(fresh["after"].startswith(GENERATED))
        self.assertFalse((self.root / "new.md").exists())
        (self.root / "guide.md").write_text(GENERATED + "旧生成内容\n")
        self.assertTrue(self.propose(mode="generated")["document"]["after"].startswith(GENERATED))

    def test_paths_ignored_existing_binary_targets_and_fake_confirmation_are_rejected(self):
        (self.root / ".gitignore").write_text("hidden.md\n")
        (self.root / "hidden.md").write_text("not in snapshot")
        for changes in ({"target": "../out.md"}, {"target": "/tmp/out.md"}, {"target": "guide\n.md"},
                        {"target": "hidden.md", "mode": "generated"}, {"confirmed": True}, {"protectedFacts": ["not in draft"]}):
            with self.assertRaises(FlowError):
                self.propose(**changes)
        (self.root / "hidden.md").unlink()
        with self.assertRaises(FlowError):
            self.propose(target="hidden.md", mode="generated")
        with self.assertRaises(FlowError):
            self.propose(target="tracked.txt/new.md", mode="generated")
        (self.root / "guide.md").write_bytes(b"\xff")
        with self.assertRaises(FlowError):
            self.propose()

    def test_source_failures_wrong_task_and_missing_lines_cannot_be_saved(self):
        task = self.start()["task"]
        for source in ({"kind": "code", "file": "tracked.txt", "layer": "worktree", "startLine": 1, "endLine": 2},
                       {"kind": "code", "file": "missing.py", "layer": "worktree", "startLine": 1, "endLine": 1},
                       {"kind": "check", "id": "a" * 32}):
            with self.assertRaises(FlowError):
                self.propose(task, sources=[source])
        self.assertEqual(TaskStore(self.database).documents(task_id=task["id"]), [])

    def test_pinned_module_is_explicit_and_unchanged_draft_is_valid_candidate(self):
        document = self.propose()["document"]
        self.assertEqual(document["voice"]["status"], "not_requested")
        packet = self.cli("document", "voice", document["id"])
        self.assertEqual(packet["status"], "loaded")
        self.assertEqual(packet["module"]["commit"], "8dcf520fb3974e9711cf193ca78a9839a7fce5f0")
        self.assertIn("MIT License", packet["instructions"]["LICENSE"])
        self.assertEqual(packet["modelExecution"], "not_observed")
        rewritten = self.rewrite(document, document["proposal"]["draft"])
        self.assertEqual(rewritten["document"]["voice"]["status"], "protected_checks_passed")
        self.assertEqual(rewritten["state"]["confirmationStatus"], "proposed")
        self.assertEqual(self.service.get(document["id"])["document"], document)

    def test_missing_or_corrupt_module_keeps_original_draft_and_record(self):
        document = self.propose()["document"]
        with patch("engineering_flow.core.voice.files", side_effect=FileNotFoundError("fixture missing")):
            self.assertEqual(self.service.voice(document["id"])["status"], "unavailable")
            result = self.service.rewrite(document["id"], {})
            self.assertEqual(result["rewrite"]["status"], "unavailable")
            self.assertEqual(result["document"], document)
        self.assertEqual(len(TaskStore(self.database).documents(task_id=document["taskId"])), 1)
        fake = Path(self.temp.name) / "fake-package/resources/engineer_voice"
        fake.mkdir(parents=True)
        (fake / "manifest.json").write_text(json.dumps({"files": {"LICENSE": "0" * 64}}))
        (fake / "LICENSE").write_text("changed")
        with patch("engineering_flow.core.voice.files", return_value=fake.parent.parent):
            self.assertEqual(load_module()["status"], "unavailable")

    def test_risky_rewrite_preserves_original_and_rejects_unbound_or_self_reported_result(self):
        document = self.propose()["document"]
        result = self.rewrite(document, "请求必须重试 3 次。认证失败仍重试。\n")
        self.assertEqual(result["document"]["voice"]["status"], "rejected")
        self.assertEqual(result["document"]["after"], document["after"])
        self.assertIn("protected_fact_changed", result["document"]["voice"]["issues"])
        for content in ({"proposalIntegrity": "0" * 64, "moduleDigest": "0" * 64, "rewritten": "arbitrary"}, {"confirmed": True}):
            with self.assertRaises(FlowError):
                self.service.rewrite(document["id"], content)

    def test_fixed_upstream_semantic_regressions_reject_condition_negation_scope_and_strength_changes(self):
        cases = json.loads((Path(__file__).parent / "fixtures/voice_regressions.json").read_text())
        task = self.start()["task"]
        for case in cases:
            with self.subTest(case["id"]):
                self.assertEqual(compare_protected(case["draft"], case["acceptable"], case["facts"]), [])
                document = self.propose(task, draft=case["draft"], protectedFacts=case["facts"])["document"]
                self.assertEqual(self.rewrite(document, case["acceptable"])["document"]["voice"]["status"], "protected_checks_passed")
                rejected = self.rewrite(document, case["rejected"])["document"]
                self.assertEqual(rejected["voice"]["status"], "rejected")
                self.assertEqual(rejected["after"], document["after"])

    def test_code_commands_tables_quotes_urls_and_numeric_units_are_protected(self):
        original = '建议最多重试 2 次，间隔 5 秒。\n`AUTH_FAILED`\n```sh\necho "$TOKEN"\n```\n|状态|说明|\n|---|---|\n|frozen|暂停|\n> 原话\nhttps://example.invalid/api\n'
        for before, after in (("2 次", "3 次"), ("5 秒", "5 分钟"), ("AUTH_FAILED", "AUTH_OK"), ("echo", "eval"),
                              ("frozen", "active"), ("原话", "改话"), ("/api", "/new")):
            self.assertTrue(compare_protected(original, original.replace(before, after), ["建议"]))

    def test_sensitive_markers_are_checked_even_without_explicit_facts(self):
        for original, rewritten in (("不能据此确认已检查。", "尚未检查。"), ("超过 8%", "达到 8%"),
                                    ("建议重试。", "必须重试。"), ("可能支持。", "已经支持。"),
                                    ("如果失败则恢复。", "失败后继续。")):
            self.assertIn("semantic_markers_changed", compare_protected(original, rewritten, []))

    def test_task_and_file_approval_do_not_confirm_document_and_group_replacement_is_per_item(self):
        first = self.propose()["document"]
        second = self.propose({"id": first["taskId"]}, reason="另一份建议")["document"]
        review = self.cli("review", "build", first["taskId"])["review"]
        opinion = FeedbackService(self.root).record(review["id"], decision="approve", comment="task fixture")["record"]
        FeedbackService(self.root).confirm(opinion["id"], authority=TestConsent())
        self.assertEqual(self.service.get(first["id"])["state"]["confirmationStatus"], "proposed")
        self.confirm([first, second])
        self.confirm([first], "request_changes")
        self.assertEqual(self.service.get(first["id"])["state"]["confirmationStatus"], "rejected")
        self.assertEqual(self.service.get(second["id"])["state"]["confirmationStatus"], "confirmed")
        self.assertFalse(self.cli("task", "resume", first["taskId"])["verification"]["requiredChecksPassed"])
        material = self.cli("review", "build", first["taskId"])
        html = Path(material["htmlPath"]).read_text()
        self.assertIn("当前有效的文档建议确认：" + first["id"], html)
        self.assertIn("当前有效的文档建议确认：" + second["id"], html)

    def test_opinion_is_not_confirmation_and_changed_code_invalidates_old_confirmation(self):
        document = self.propose()["document"]
        review = self.cli("review", "build", document["taskId"])["review"]
        self.cli("review", "record", review["id"], "--document", document["id"], "--decision", "approve", "--comment", "caller only")
        self.assertEqual(self.service.get(document["id"])["state"]["confirmationStatus"], "proposed")
        self.confirm([document])
        (self.root / "tracked.txt").unlink()
        state = self.service.get(document["id"])["state"]
        self.assertEqual(state["confirmationStatus"], "confirmed")
        self.assertEqual(state["applicability"], "needs_revalidation")
        self.assertEqual(self.service.get(document["id"])["document"], document)
        self.assertTrue(self.cli("review", "show", review["id"])["refreshNeeded"])
        with self.assertRaises(FlowError):
            self.rewrite(document, document["proposal"]["draft"])

    def test_revision_change_and_application_require_new_snapshot_checks(self):
        document = self.propose()["document"]
        TaskService(self.root).checkpoint(document["taskId"], expected_revision=1, progress="新修订")
        self.assertIn("task_revision_changed", self.service.get(document["id"])["state"]["reasons"])
        (self.root / "guide.md").write_text(document["after"])
        self.assertIn("snapshot_changed", self.service.get(document["id"])["state"]["reasons"])

    def test_branch_and_copied_worktree_do_not_share_document_scope(self):
        document = self.propose()["document"]
        self.git("checkout", "--quiet", "-b", "other")
        self.assertEqual(self.cli("document", "show", document["id"], code=1)["code"], "workspace_mismatch")
        other = self.root.parent / "other-worktree"
        self.git("worktree", "add", "--quiet", "--force", str(other), "main")
        (other / ".engineering-flow").mkdir()
        shutil.copyfile(self.database, other / ".engineering-flow/state.sqlite3")
        self.assertEqual(self.cli("document", "show", document["id"], workspace=other, code=1)["code"], "workspace_mismatch")

    def test_tampered_document_and_review_payload_fail_closed(self):
        document = self.propose()["document"]
        broken = deepcopy(document); broken["before"] = "fake"; seal(broken)
        self.execute_sql("UPDATE document_proposals SET document=?", (json.dumps(broken),))
        self.assertEqual(self.cli("document", "show", document["id"], code=1)["code"], "invalid_document")
        self.execute_sql("UPDATE document_proposals SET document=?", (json.dumps(document),))
        review = self.cli("review", "build", document["taskId"])["review"]
        opinion = FeedbackService(self.root).record(review["id"], decision="approve", comment="fixture", document_ids=[document["id"]])["record"]
        opinion["scope"]["documents"][0]["proposal"]["reason"] = "forged reason";seal(opinion["scope"]["documents"][0]);seal(opinion)
        self.execute_sql("UPDATE review_events SET document=? WHERE id=?", (json.dumps(opinion), opinion["id"]))
        self.assertEqual(self.cli("review", "confirm", opinion["id"], code=1)["code"], "invalid_evidence")

    def test_v5_read_is_unchanged_and_write_migrates_preserving_task_json(self):
        task = self.start()["task"]; before = self.rows()
        self.execute_sql("DROP TABLE document_proposals");self.execute_sql("PRAGMA user_version=5")
        self.assertEqual(self.cli("task", "resume", task["id"])["documents"]["records"], [])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
        self.propose(task)
        self.assertEqual(self.rows(), before)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)

    def test_migration_denied_or_insert_aborted_rolls_back_everything(self):
        task = self.start()["task"]
        self.execute_sql("DROP TABLE document_proposals");self.execute_sql("PRAGMA user_version=5")
        original = sqlite3.connect
        def denied(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and name == "document_proposals" else sqlite3.SQLITE_OK)
            return connection
        with patch("engineering_flow.core.store.sqlite3.connect", side_effect=denied), self.assertRaises(FlowError):
            self.propose(task)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
        self.propose(task)
        with closing(sqlite3.connect(self.database)) as connection:
            before = {t: connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("snapshots", "blobs", "document_proposals")}
        self.execute_sql("CREATE TRIGGER abort_document AFTER INSERT ON document_proposals BEGIN SELECT RAISE(ABORT, 'fixture interruption'); END")
        (self.root / "tracked.txt").write_text("new snapshot")
        with self.assertRaises(FlowError):
            self.propose(task)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual({t: connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}, before)

    def test_revision_race_during_save_does_not_create_document(self):
        task = self.start()["task"];original = TaskStore.save_document
        def race(store, document, **kwargs):
            TaskService(self.root).checkpoint(task["id"], expected_revision=1, progress="race fixture")
            return original(store, document, **kwargs)
        with patch.object(TaskStore, "save_document", race), self.assertRaises(FlowError) as error:
            self.propose(task)
        self.assertEqual(error.exception.code, "revision_conflict")
        self.assertEqual(TaskStore(self.database).documents(task_id=task["id"]), [])

    def test_document_refresh_html_escaping_and_real_code_links(self):
        from test_review_m2 import Document
        task = self.start()["task"]
        old = self.cli("review", "build", task["id"])
        proposed = self.propose(task, draft="<script>window.documentInjected=1</script>", protectedFacts=[])["document"]
        self.assertTrue(self.cli("review", "show", old["review"]["id"])["refreshNeeded"])
        material = self.cli("review", "build", task["id"])
        self.assertFalse(self.cli("review", "show", material["review"]["id"])["refreshNeeded"])
        html = Path(material["htmlPath"]).read_text();parsed = Document(html)
        self.assertNotIn("script", parsed.tags)
        self.assertEqual(parsed.events, [])
        self.assertIn("&lt;script&gt;window.documentInjected=1&lt;/script&gt;", html)
        self.assertIn(proposed["snapshotId"], html)
        self.assertIn("tracked.txt", html)

    def test_no_final_newline_patch_can_be_applied_to_exact_original(self):
        import subprocess
        (self.root / "guide.md").write_text("old without newline")
        document = self.propose(draft="new without newline", protectedFacts=[])["document"]
        exported = self.service.export(document["id"])
        result = subprocess.run(["git", "-C", str(self.root), "apply", "--check", exported["patchPath"]], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
