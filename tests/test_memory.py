"""固定来源样例验证记忆状态、检索遗漏、隔离与中断安全；不依赖模型自评。"""

import json
import os
import shutil
import sqlite3
from contextlib import closing
from copy import deepcopy
from unittest.mock import patch

from engineering_flow.core.errors import FlowError
from engineering_flow.core.evidence import seal
from engineering_flow.core.feedback import ConfirmationPort, ConsentReceipt, FeedbackService
from engineering_flow.core.memory import MemoryService, context_bytes
from engineering_flow.core.store import TaskStore
from engineering_flow.core.tasks import TaskService

from support import GitFixture


class TestConsent(ConfirmationPort):
    """自动化夹具不代表用户已确认。"""
    def request(self, opinion):
        return ConsentReceipt(opinion["integrity"], {"source": "interactive_terminal", "uid": os.getuid(),
            "account": "automated-memory-test", "tty": "/dev/test", "assurance": "local_session_not_identity_verified"})


class MemoryTests(GitFixture):
    def proposal(self, **changes):
        value = {"content": "队列使用 request_id 复用批次；此处为候选解释。", "kind": "design_decision",
            "scope": {"kind": "paths", "paths": ["tracked.txt"], "modules": ["queue"]},
            "keywords": ["request_id", "retry"],
            "sources": [{"kind": "code", "file": "tracked.txt", "layer": "worktree", "startLine": 1, "endLine": 1}]}
        value.update(changes)
        return value

    def propose(self, task=None, **changes):
        task = task or self.start()["task"]
        return MemoryService(self.root).propose(task["id"], self.proposal(**changes))

    def approve(self, memory, decision="approve"):
        review = self.cli("review", "build", memory["taskId"])["review"]
        opinion = self.cli("review", "record", review["id"], "--decision", decision, "--comment", "自动化夹具评审，不是真实用户批准",
                           "--memory", memory["id"])["record"]
        return FeedbackService(self.root).confirm(opinion["id"], authority=TestConsent())["record"]

    def test_cli_proposal_restart_and_resume_keep_provenance_and_candidate_state(self):
        task = self.start()["task"]
        path = self.root.parent / "proposal.json"
        path.write_text(json.dumps(self.proposal(), ensure_ascii=False))
        result = self.cli("memory", "propose", task["id"], "--input", str(path))
        memory = result["memory"]
        self.assertEqual(memory["origin"], "caller")
        self.assertEqual(result["state"]["confirmationStatus"], "proposed")
        self.assertEqual(result["state"]["applicability"], "current")
        self.assertFalse(result["state"]["eligibleAsCurrentBackground"])
        self.assertIsNone(result["state"]["confirmation"])
        self.assertEqual(self.cli("memory", "show", memory["id"]), result)
        item = self.cli("task", "resume", task["id"])["memoryContext"]["selected"][0]
        self.assertEqual(item["id"], memory["id"])
        self.assertEqual(item["sources"][0]["origin"], "program_observation")
        command = item["sources"][0]["readCommand"]
        self.assertEqual(self.cli(*command)["content"]["data"], "baseline\n")

    def test_proposal_cannot_self_confirm_or_claim_identity_and_needs_real_sources(self):
        task = self.start()["task"]
        invalid = [dict(self.proposal(), confirmed=True), dict(self.proposal(), origin="human"),
                   self.proposal(sources=[]), self.proposal(sources=[{"kind": "pr", "id": "123"}]),
                   self.proposal(scope={"kind": "paths", "paths": ["../outside"], "modules": []})]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(FlowError) as error:
                MemoryService(self.root).propose(task["id"], value)
            self.assertEqual(error.exception.code, "invalid_input")
        self.assertEqual(self.cli("task", "resume", task["id"])["memoryContext"]["selected"], [])

    def test_missing_binary_index_and_out_of_range_sources_are_checked_against_saved_bytes(self):
        (self.root / "binary.dat").write_bytes(b"\xff\x00")
        (self.root / "nul.txt").write_bytes(b"text\x00data\n")
        task = self.start()["task"]
        for file, start, end in [("missing.txt", 1, 1), ("tracked.txt", 1, 2), ("binary.dat", 1, 1), ("nul.txt", 1, 1)]:
            with self.subTest(file=file), self.assertRaises(FlowError):
                self.propose(task, sources=[{"kind": "code", "file": file, "layer": "worktree", "startLine": start, "endLine": end}])
        memory = self.propose(task, sources=[{"kind": "code", "file": "tracked.txt", "layer": "index", "startLine": 1, "endLine": 1}])
        self.assertEqual(memory["sources"][0]["layer"], "index")
        self.assertEqual(TaskStore(self.database).memory_documents("memories"), [memory["memory"]])

    def test_any_declared_input_or_task_revision_change_requires_revalidation(self):
        memory = self.propose()["memory"]
        original = self.cli("memory", "show", memory["id"])["memory"]
        (self.root / "other.txt").write_text("unrelated but conservatively invalidates\n")
        state = self.cli("memory", "show", memory["id"])["state"]
        self.assertEqual(state["applicability"], "needs_revalidation")
        self.assertIn("snapshot_changed", state["reasons"])
        (self.root / "other.txt").unlink()
        self.cli("task", "checkpoint", memory["taskId"], "--expected-revision", "1", "--progress", "new context")
        state = self.cli("memory", "show", memory["id"])["state"]
        self.assertIn("task_revision_changed", state["reasons"])
        self.assertEqual(self.cli("memory", "show", memory["id"])["memory"], original)

    def test_memory_confirmation_is_explicit_scoped_and_not_a_check_or_task_approval(self):
        result = self.propose()
        memory = result["memory"]
        review = self.cli("review", "build", memory["taskId"])["review"]
        opinion = self.cli("review", "record", review["id"], "--decision", "approve", "--comment", "候选待确认", "--memory", memory["id"])["record"]
        self.assertEqual(opinion["schemaVersion"], 2)
        self.assertEqual(opinion["scope"]["kind"], "memories")
        self.assertEqual(opinion["scope"]["memories"], [memory])
        self.assertEqual(self.cli("memory", "show", memory["id"])["state"]["confirmationStatus"], "proposed")
        self.assertEqual(self.cli("review", "confirm", opinion["id"], code=1)["code"], "confirmation_source")
        confirmed = FeedbackService(self.root).confirm(opinion["id"], authority=TestConsent())["record"]
        state = self.cli("memory", "show", memory["id"])["state"]
        self.assertEqual(state["confirmationStatus"], "confirmed")
        self.assertTrue(state["eligibleAsCurrentBackground"])
        self.assertEqual(state["confirmation"]["eventId"], confirmed["id"])
        resumed = self.cli("task", "resume", memory["taskId"])
        self.assertFalse(resumed["verification"]["requiredChecksPassed"])
        self.assertEqual([s["scope"]["kind"] for s in resumed["reviewFeedback"]["confirmedScopes"]], ["memories"])
        self.cli("review", "record", review["id"], "--decision", "approve", "--comment", "bad scope", "--memory", memory["id"], "--file", "tracked.txt", code=1)

    def test_deleted_confirmed_source_keeps_history_but_is_not_current_background(self):
        memory = self.propose()["memory"]
        confirmation = self.approve(memory)
        (self.root / "tracked.txt").unlink()
        result = self.cli("memory", "show", memory["id"])
        self.assertEqual(result["state"]["confirmationStatus"], "confirmed")
        self.assertEqual(result["state"]["confirmation"]["eventId"], confirmation["id"])
        self.assertEqual(result["state"]["applicability"], "needs_revalidation")
        self.assertFalse(result["state"]["eligibleAsCurrentBackground"])
        self.assertEqual(self.cli(*result["sources"][0]["readCommand"])["content"]["data"], "baseline\n")
        newer = self.cli("review", "build", memory["taskId"])["review"]
        self.assertEqual(self.cli("review", "record", newer["id"], "--decision", "approve", "--comment", "cannot silently revalidate", "--memory", memory["id"], code=1)["code"], "memory_stale")

    def test_task_approval_does_not_implicitly_confirm_any_memory(self):
        memory = self.propose()["memory"]
        review = self.cli("review", "build", memory["taskId"])["review"]
        opinion = FeedbackService(self.root).record(review["id"], decision="approve", comment="task only")["record"]
        FeedbackService(self.root).confirm(opinion["id"], authority=TestConsent())
        self.assertEqual(self.cli("memory", "show", memory["id"])["state"]["confirmationStatus"], "proposed")

    def test_later_single_memory_decision_overrides_only_that_part_of_a_bundle(self):
        first = self.propose()["memory"]
        task = self.cli("task", "resume", first["taskId"])["task"]
        second = self.propose(task, content="第二条独立候选")["memory"]
        review = self.cli("review", "build", task["id"])["review"]
        opinion = FeedbackService(self.root).record(review["id"], decision="approve", comment="bundle fixture",
                                                   memory_ids=[first["id"], second["id"]])["record"]
        original = FeedbackService(self.root).confirm(opinion["id"], authority=TestConsent())["record"]
        self.approve(first, "request_changes")
        resumed = self.cli("task", "resume", task["id"])
        scopes = resumed["reviewFeedback"]["confirmedScopes"]
        decisions = {s["scope"]["memories"][0]["id"]: s["decision"] for s in scopes}
        self.assertEqual(decisions, {first["id"]: "request_changes", second["id"]: "approve"})
        state = next(s for s in resumed["reviewFeedback"]["states"] if s["eventId"] == original["id"])
        self.assertEqual(state["effectiveMemoryIds"], [second["id"]])
        self.assertEqual(self.cli("memory", "show", first["id"])["state"]["confirmationStatus"], "rejected")
        self.assertEqual(self.cli("memory", "show", second["id"])["state"]["confirmationStatus"], "confirmed")

    def test_latest_scoped_confirmation_can_reject_and_exclude_candidate(self):
        memory = self.propose()["memory"]
        self.approve(memory)
        self.approve(memory, "request_changes")
        state = self.cli("memory", "show", memory["id"])["state"]
        self.assertEqual(state["confirmationStatus"], "rejected")
        context = self.cli("memory", "context", memory["taskId"])
        self.assertEqual(context["selected"], [])
        self.assertEqual(context["excluded"][0]["reason"], "rejected")

    def test_conflicting_decisions_keep_sources_and_do_not_merge_into_rules(self):
        first = self.propose()["memory"]
        task = self.cli("task", "resume", first["taskId"])["task"]
        second = self.propose(task, content="重试必须拒绝已有 request_id；与另一候选相矛盾。")["memory"]
        self.approve(first)
        self.approve(second)
        self.cli("memory", "relate", first["id"], "--relation", "conflicts_with", "--other", second["id"], "--reason", "固定矛盾样例")
        context = self.cli("memory", "context", first["taskId"])
        self.assertEqual(len(context["selected"]), 2)
        for item in context["selected"]:
            self.assertTrue(item["state"]["hasActiveConflict"])
            self.assertFalse(item["state"]["eligibleAsCurrentBackground"])
            self.assertEqual(len(item["sources"]), 1)
        self.assertEqual(len(context["relations"]), 1)

    def test_proposed_replacement_does_not_hide_old_rule_and_confirmed_replacement_is_traceable(self):
        old = self.propose()["memory"]
        task = self.cli("task", "resume", old["taskId"])["task"]
        self.approve(old)
        new = self.propose(task, content="新候选保留明确条件，不自动合并旧结论。")["memory"]
        self.cli("memory", "relate", new["id"], "--relation", "supersedes", "--other", old["id"], "--reason", "替代草稿")
        self.assertEqual(self.cli("memory", "show", old["id"])["state"]["applicability"], "current")
        self.assertTrue(self.cli("memory", "show", old["id"])["state"]["hasActiveConflict"])
        self.approve(new)
        context = self.cli("memory", "context", old["taskId"])
        self.assertEqual([i["id"] for i in context["selected"]], [new["id"]])
        self.assertEqual(context["excluded"][0]["reason"], "superseded")
        self.assertEqual(self.cli("memory", "show", old["id"])["state"]["supersededBy"], [new["id"]])
        self.approve(new, "request_changes")
        # 撤回新结论也不能悄悄复活已被替代的旧规则。
        self.assertEqual(self.cli("memory", "context", old["taskId"])["selected"], [])
        self.cli("memory", "relate", new["id"], "--relation", "archive", "--reason", "显式归档")
        self.assertEqual(self.cli("memory", "context", old["taskId"])["selected"], [])

    def test_cycles_and_self_relations_are_rejected_without_saving(self):
        first = self.propose()["memory"]
        task = self.cli("task", "resume", first["taskId"])["task"]
        second = self.propose(task)["memory"]
        self.cli("memory", "relate", first["id"], "--relation", "supersedes", "--other", second["id"], "--reason", "one direction")
        for left, right in [(second["id"], first["id"]), (first["id"], first["id"])]:
            self.cli("memory", "relate", left, "--relation", "supersedes", "--other", right, "--reason", "invalid cycle", code=1)
        self.assertEqual(len(TaskStore(self.database).memory_documents("memory_events")), 1)

    def test_task_paths_modules_keywords_and_project_scope_choose_relevant_records(self):
        (self.root / "other.txt").write_text("other module\n")
        first_task = self.start()["task"]
        specific = self.propose(first_task)["memory"]
        project = self.propose(first_task, content="全项目限制", scope={"kind": "project", "paths": [], "modules": []}, keywords=[])["memory"]
        next_task = self.cli("task", "start", "--goal", "unrelated-goal", "--accept", "unrelated-check")["task"]
        base = self.cli("memory", "context", next_task["id"])
        self.assertEqual([i["id"] for i in base["selected"]], [project["id"]])
        self.assertEqual(next(e["reason"] for e in base["excluded"] if e["id"] == specific["id"]), "unrelated")
        for args, expected in [(('--path', 'tracked.txt'), 'path'), (('--module', 'QUEUE'), 'module'), (('--query', 'request_id'), 'keyword')]:
            with self.subTest(args=args):
                item = next(i for i in self.cli("memory", "context", next_task["id"], *args)["selected"] if i["id"] == specific["id"])
                self.assertIn(expected, item["matches"])
        linked = self.cli("task", "start", "--goal", "different", "--accept", "different", "--file", "tracked.txt")["memoryContext"]
        self.assertIn(specific["id"], [i["id"] for i in linked["selected"]])

    def test_budget_exact_utf8_boundary_and_all_omissions_have_read_references(self):
        memory = self.propose()["memory"]
        full = self.cli("memory", "context", memory["taskId"])
        size = len(context_bytes(full["selected"]))
        self.assertEqual(full["usedBytes"], size)
        self.assertLess(size, len(json.dumps(full["selected"], ensure_ascii=True).encode()))
        exact = self.cli("memory", "context", memory["taskId"], "--budget-bytes", str(size))
        self.assertEqual(exact["selected"], full["selected"])
        limited = self.cli("memory", "context", memory["taskId"], "--budget-bytes", str(size - 1))
        self.assertFalse(limited["complete"])
        self.assertEqual(limited["selected"], [])
        self.assertEqual(limited["usedBytes"], 2)
        self.assertEqual(limited["excluded"][0]["reason"], "budget")
        self.assertEqual(self.cli(*limited["excluded"][0]["readCommand"])["memory"], memory)
        self.cli("memory", "context", memory["taskId"], "--budget-bytes", "1", code=1)
        self.cli("memory", "context", memory["taskId"], "--path", "../outside", code=1)

    def test_budget_can_skip_large_record_and_include_a_later_small_one(self):
        task = self.start()["task"]
        big = self.propose(task, content="large " * 1000)["memory"]
        small = self.propose(task, content="小候选")["memory"]
        full = self.cli("memory", "context", task["id"], "--budget-bytes", "65536")
        small_item = next(i for i in full["selected"] if i["id"] == small["id"])
        budget = len(context_bytes([small_item]))
        limited = self.cli("memory", "context", task["id"], "--budget-bytes", str(budget))
        self.assertEqual([i["id"] for i in limited["selected"]], [small["id"]])
        self.assertEqual(limited["excluded"][0]["id"], big["id"])

    def test_failed_check_and_ai_explanation_sources_keep_their_actual_origins(self):
        config = {"schemaVersion": 1, "checks": [{"id": "fail", "required": True,
            "argv": ["{python}", "-c", "raise SystemExit(1)"]}]}
        (self.root / ".engineering-flow.json").write_text(json.dumps(config))
        task = self.start()["task"]
        from engineering_flow.core.checks import CheckService
        run = CheckService(self.root).run(task["id"], "fail")["run"]
        review = self.cli("review", "build", task["id"])["review"]
        reference = {k: v for k, v in self.proposal()["sources"][0].items() if k != "kind"}
        explanation = FeedbackService(self.root).explain(review["id"], {"summary": "AI 推断未确认", "behaviors": [{"title": "重试", "description": "待核对", "acceptanceCriteria": [1], "references": [reference]}]})
        sources = [{"kind": "check", "id": run["id"]}, {"kind": "review_event", "id": explanation["record"]["id"]}]
        result = self.propose(task, sources=sources)
        self.assertEqual([s["origin"] for s in result["sources"]], ["runner", "ai"])
        self.assertEqual(result["sources"][0]["status"], "failed")
        self.assertEqual(result["state"]["confirmationStatus"], "proposed")
        self.assertFalse(self.cli("task", "resume", task["id"])["verification"]["requiredChecksPassed"])

    def test_branch_mismatch_is_excluded_and_cannot_be_read_or_implicitly_resumed(self):
        memory = self.propose()["memory"]
        self.git("checkout", "--quiet", "-b", "other-branch")
        other = self.start()["task"]
        context = self.cli("memory", "context", other["id"])
        self.assertEqual(context["selected"], [])
        self.assertEqual(context["excluded"], [{"id": memory["id"], "reason": "branch_mismatch", "readCommand": ["memory", "show", memory["id"]]}])
        self.assertEqual(self.cli("memory", "show", memory["id"], code=1)["code"], "workspace_mismatch")
        self.assertEqual(self.cli("memory", "context", memory["taskId"], code=1)["code"], "workspace_mismatch")

    def test_copied_database_in_same_branch_worktree_cannot_supply_memory(self):
        memory = self.propose()["memory"]
        other = self.root.parent / "other-worktree"
        self.git("worktree", "add", "--quiet", "--force", str(other), "main")
        (other / ".engineering-flow").mkdir()
        shutil.copyfile(self.database, other / ".engineering-flow/state.sqlite3")
        self.assertEqual(self.cli("memory", "show", memory["id"], workspace=other, code=1)["code"], "workspace_mismatch")

    def test_corrupt_record_missing_source_and_snapshot_damage_fail_closed(self):
        memory = self.propose()["memory"]
        broken = deepcopy(memory)
        broken["proposal"]["content"] = "unsealed edit"
        self.execute_sql("UPDATE memories SET document=? WHERE id=?", (json.dumps(broken), memory["id"]))
        self.assertEqual(self.cli("task", "resume", memory["taskId"], code=1)["code"], "invalid_memory")
        broken = deepcopy(memory)
        broken["proposal"]["sources"][0]["endLine"] = 999
        self.execute_sql("UPDATE memories SET document=? WHERE id=?", (json.dumps(seal(broken)), memory["id"]))
        self.assertEqual(self.cli("memory", "show", memory["id"], code=1)["code"], "invalid_memory")
        self.execute_sql("UPDATE memories SET document=? WHERE id=?", (json.dumps(memory), memory["id"]))
        self.execute_sql("DELETE FROM snapshots WHERE id=?", (memory["snapshotId"],))
        self.assertEqual(self.cli("memory", "show", memory["id"], code=1)["code"], "invalid_snapshot")

    def test_review_cannot_confirm_different_memory_payload_even_with_resealed_event(self):
        memory = self.propose()["memory"]
        review = self.cli("review", "build", memory["taskId"])["review"]
        opinion = FeedbackService(self.root).record(review["id"], decision="approve", comment="scope fixture", memory_ids=[memory["id"]])["record"]
        opinion["scope"]["memories"][0]["proposal"]["content"] = "changed inside opinion"
        seal(opinion["scope"]["memories"][0]);seal(opinion)
        self.execute_sql("UPDATE review_events SET document=? WHERE id=?", (json.dumps(opinion), opinion["id"]))
        self.assertEqual(self.cli("review", "confirm", opinion["id"], code=1)["code"], "invalid_evidence")

    def test_v4_read_keeps_schema_and_first_write_preserves_old_json(self):
        task = self.start()["task"]
        before = self.rows()
        self.execute_sql("DROP TABLE memories")
        self.execute_sql("DROP TABLE memory_events")
        self.execute_sql("DROP TABLE document_proposals")
        self.execute_sql("PRAGMA user_version=4")
        self.assertEqual(self.cli("task", "resume", task["id"])["memoryContext"]["selected"], [])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
        self.propose(task)
        self.assertEqual(self.rows(), before)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)

    def test_migration_failure_rolls_back_new_memory_and_blob_transaction(self):
        task = self.start()["task"]
        self.execute_sql("DROP TABLE memories")
        self.execute_sql("DROP TABLE memory_events")
        self.execute_sql("DROP TABLE document_proposals")
        self.execute_sql("PRAGMA user_version=4")
        original = sqlite3.connect
        def denied(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and name == "memory_events" else sqlite3.SQLITE_OK)
            return connection
        with patch("engineering_flow.core.store.sqlite3.connect", side_effect=denied), self.assertRaises(FlowError) as error:
            self.propose(task)
        self.assertEqual(error.exception.code, "storage_error")
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='memories'").fetchone())

    def test_revision_race_prevents_memory_save_and_keeps_previous_revision(self):
        task = self.start()["task"]
        original = TaskStore.save_memory
        def race(store, kind, document, **kwargs):
            TaskService(self.root).checkpoint(task["id"], expected_revision=1, progress="changed before memory write")
            return original(store, kind, document, **kwargs)
        with patch.object(TaskStore, "save_memory", race), self.assertRaises(FlowError) as error:
            self.propose(task)
        self.assertEqual(error.exception.code, "revision_conflict")
        self.assertEqual(TaskStore(self.database).memory_documents("memories"), [])

    def test_storage_abort_rolls_back_new_snapshot_and_memory_together(self):
        task = self.start()["task"]
        with closing(sqlite3.connect(self.database)) as connection:
            before = {t: connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("snapshots", "blobs", "memories")}
        self.execute_sql("CREATE TRIGGER abort_memory AFTER INSERT ON memories BEGIN SELECT RAISE(ABORT, 'test memory interruption'); END")
        (self.root / "tracked.txt").write_text("new snapshot before aborted insert\n")
        with self.assertRaises(FlowError) as error:
            self.propose(task)
        self.assertEqual(error.exception.code, "storage_error")
        with closing(sqlite3.connect(self.database)) as connection:
            after = {t: connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
            self.assertEqual(after, before)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.cli("task", "resume", task["id"])["task"], task)

    def test_running_check_and_another_tasks_evidence_cannot_be_memory_sources(self):
        from engineering_flow.core.checks import CheckService
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "checks": [
            {"id": "pass", "required": True, "argv": ["{python}", "-c", "pass"]}]}))
        task = self.start()["task"]
        run = CheckService(self.root).run(task["id"], "pass")["run"]
        other = self.start()["task"]
        with self.assertRaises(FlowError):
            self.propose(other, sources=[{"kind": "check", "id": run["id"]}])
        run.update(status="running", endedAt=None, snapshotAfterId=None, exitCode=None, failure=None)
        self.execute_sql("UPDATE check_runs SET document=? WHERE id=?", (json.dumps(seal(run)), run["id"]))
        with self.assertRaises(FlowError):
            self.propose(task, sources=[{"kind": "check", "id": run["id"]}])
        self.assertEqual(TaskStore(self.database).memory_documents("memories"), [])

    def test_memory_content_and_sources_are_safely_rendered_in_review_material(self):
        from pathlib import Path
        from test_review_m2 import Document
        memory = self.propose(content="<script>window.memoryInjected=1</script>\n候选含完整条件。")["memory"]
        self.approve(memory)
        result = self.cli("review", "build", memory["taskId"])
        source = Path(result["htmlPath"]).read_text()
        self.assertIn("范围：记忆：", source)
        self.assertIn("&lt;script&gt;window.memoryInjected=1&lt;/script&gt;", source)
        self.assertNotIn("script", Document(source).tags)
        self.assertEqual(Document(source).events, [])
        self.assertTrue(self.cli("review", "show", result["review"]["id"])["currentReviewFeedback"]["confirmedScopes"])
