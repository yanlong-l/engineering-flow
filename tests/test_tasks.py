"""在临时 Git 仓库与独立 CLI 进程中验证任务存取合同。"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


from support import GitFixture


class TaskCliTests(GitFixture):
    def test_create_checkpoint_and_new_process_resume_exact_record(self):
        initial = self.start()["task"]
        saved = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1",
                         "--progress", "完成存取；仍待下一轮快照验证\n保留换行与否定。",
                         "--goal", "保存后的目标", "--accept", "新的验收条件",
                         "--clear-issues")["task"]
        restored = self.cli("task", "resume", initial["id"])
        self.assertEqual(restored["task"], saved)
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["goal"], "保存后的目标")
        self.assertEqual(saved["acceptanceCriteria"], ["新的验收条件"])
        self.assertEqual(saved["unresolvedIssues"], [])
        self.assertEqual(saved["createdAt"], initial["createdAt"])
        self.assertEqual(saved["startingWorkspace"], initial["startingWorkspace"])
        self.assertEqual(json.loads(self.rows()[0][2]), initial)
        self.assertEqual(len(restored["limitations"]), 3)
        self.assertIsNotNone(saved["savedWorkspace"]["snapshotId"])
        self.assertEqual(restored["snapshotComparison"]["status"], "current")
        self.assertEqual(saved["inputOrigin"], "caller")
        self.assertNotIn("checks", saved)

    def test_checkpoint_preserves_omitted_fields(self):
        initial = self.start()["task"]
        saved = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1",
                         "--progress", "已保存")["task"]
        for key in ("goal", "acceptanceCriteria", "unresolvedIssues"):
            self.assertEqual(saved[key], initial[key])

    def test_existing_staged_unstaged_untracked_and_rename_are_observations(self):
        self.git("mv", "tracked.txt", "renamed.txt")
        (self.root / "renamed.txt").write_text("baseline\nunstaged\n")
        (self.root / "未追踪 name\n.txt").write_text("pre-existing\n")
        task = self.start()["task"]
        changes = task["startingWorkspace"]["observedChanges"]
        paths = {item["path"]: item for item in changes}
        self.assertEqual(paths["renamed.txt"]["originalPath"], "tracked.txt")
        self.assertEqual(paths["renamed.txt"]["status"], "RM")
        self.assertEqual(paths["未追踪 name\n.txt"]["status"], "??")
        self.assertTrue(all(item["ownership"] == "pre_existing_unknown" for item in changes))
        self.assertEqual((self.root / "renamed.txt").read_text(), "baseline\nunstaged\n")

    def test_own_state_is_excluded_even_without_gitignore(self):
        first = self.start()["task"]
        second = self.start()["task"]
        self.assertEqual(first["startingWorkspace"]["observedChanges"], [])
        self.assertEqual(second["startingWorkspace"]["observedChanges"], [])
        self.assertNotEqual(first["id"], second["id"])

    def test_later_edits_are_not_mislabeled_as_preexisting_or_authored_by_task(self):
        initial = self.start()["task"]
        (self.root / "later.txt").write_text("after task start")
        restored = self.cli("task", "resume", initial["id"])
        self.assertEqual(restored["task"]["startingWorkspace"]["observedChanges"], [])
        self.assertEqual(restored["currentWorkspace"]["observedChanges"][0]["ownership"], "unknown")
        saved = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "记录后续修改")
        self.assertEqual(saved["task"]["savedWorkspace"]["observedChanges"][0]["ownership"], "unknown")

    def test_subdirectory_uses_same_workspace_and_default_cwd(self):
        initial = self.start()["task"]
        subdirectory = self.root / "nested"
        subdirectory.mkdir()
        resumed = self.cli("task", "resume", initial["id"], cwd=subdirectory, workspace=False)
        self.assertEqual(resumed["task"], initial)
        self.assertEqual(resumed["currentWorkspace"]["root"], str(self.root.resolve()))

    def test_stale_revision_is_rejected_without_lost_update(self):
        initial = self.start()["task"]
        saved = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "first")["task"]
        error = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "stale", code=1)
        self.assertEqual(error["code"], "revision_conflict")
        self.assertEqual(self.cli("task", "resume", initial["id"])["task"], saved)
        self.assertEqual(len(self.rows()), 2)

    def test_missing_task_does_not_create_storage(self):
        error = self.cli("task", "resume", "a" * 32, code=1)
        self.assertEqual(error["code"], "task_not_found")
        self.assertFalse(self.database.parent.exists())

    def test_unknown_id_does_not_create_another_task(self):
        self.start()
        error = self.cli("task", "resume", "a" * 32, code=1)
        self.assertEqual(error["code"], "task_not_found")
        self.assertEqual(len(self.rows()), 1)

    def test_invalid_input_does_not_create_storage(self):
        for args in [("task", "start", "--goal", "  ", "--accept", "condition"),
                     ("task", "start", "--goal", "goal", "--accept", ""),
                     ("task", "resume", "../../other")]:
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args, code=1)["code"], "invalid_input")
        self.assertFalse(self.database.parent.exists())

    def test_non_git_workspace_is_diagnosed_without_writing(self):
        result = subprocess.run([sys.executable, "-m", "engineering_flow", "--workspace", self.temp.name,
                                 "task", "start", "--goal", "goal", "--accept", "condition"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "workspace_error")
        self.assertFalse((Path(self.temp.name) / ".engineering-flow").exists())

    def test_branch_change_refuses_resume_and_checkpoint(self):
        initial = self.start()["task"]
        self.git("switch", "--quiet", "-c", "another")
        for args in [("task", "resume", initial["id"]),
                     ("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "wrong branch")]:
            self.assertEqual(self.cli(*args, code=1)["code"], "workspace_mismatch")
        self.assertEqual(len(self.rows()), 1)

    def test_head_change_warns_without_fabricating_verification(self):
        initial = self.start()["task"]
        (self.root / "tracked.txt").write_text("new commit\n")
        self.git("commit", "--quiet", "-am", "changed")
        restored = self.cli("task", "resume", initial["id"])
        self.assertEqual(restored["task"], initial)
        self.assertEqual(len(restored["limitations"]), 3)
        self.assertNotEqual(restored["currentWorkspace"]["head"], initial["savedWorkspace"]["head"])

    def test_unborn_and_detached_head_are_recorded_explicitly(self):
        self.git("checkout", "--quiet", "--orphan", "unborn")
        unborn = self.start()["task"]["startingWorkspace"]
        self.assertEqual(unborn["branch"], "unborn")
        self.assertIsNone(unborn["head"])
        self.git("checkout", "--quiet", "--detach", "main")
        detached = self.start()["task"]["startingWorkspace"]
        self.assertIsNone(detached["branch"])
        self.assertIsNotNone(detached["head"])

    def test_inherited_git_environment_does_not_redirect_observation(self):
        environment = dict(os.environ, GIT_DIR="/nonexistent", GIT_WORK_TREE="/nonexistent")
        result = self.start(env=environment)
        self.assertEqual(result["task"]["startingWorkspace"]["root"], str(self.root.resolve()))

    def test_corrupt_json_returns_error_and_preserves_original_bytes(self):
        initial = self.start()["task"]
        self.execute_sql("UPDATE task_revisions SET document=?", ("{broken",))
        before = self.database.read_bytes()
        self.assertEqual(self.cli("task", "resume", initial["id"], code=1)["code"], "invalid_record")
        self.assertEqual(self.database.read_bytes(), before)

    def test_invalid_record_schema_and_fields_are_rejected(self):
        initial = self.start()["task"]
        invalid_records = [None, [], dict(initial, schemaVersion=99), dict(initial, revision=True),
                           dict(initial, acceptanceCriteria=[]), dict(initial, savedWorkspace={}),
                           dict(initial, inputOrigin="human_confirmed"), dict(initial, id="b" * 32)]
        for record in invalid_records:
            with self.subTest(record=record):
                self.execute_sql("UPDATE task_revisions SET document=?", (json.dumps(record),))
                self.assertEqual(self.cli("task", "resume", initial["id"], code=1)["code"], "invalid_record")

    def test_unknown_database_schema_is_not_reinitialized(self):
        initial = self.start()["task"]
        self.execute_sql("PRAGMA user_version=99")
        before = self.database.read_bytes()
        self.assertEqual(self.cli("task", "resume", initial["id"], code=1)["code"], "unsupported_schema")
        self.assertEqual(self.start(code=1)["code"], "unsupported_schema")
        self.assertEqual(self.database.read_bytes(), before)

    def test_corrupt_database_is_not_recreated(self):
        self.database.parent.mkdir()
        self.database.write_bytes(b"not a sqlite database")
        before = self.database.read_bytes()
        self.assertEqual(self.start(code=1)["code"], "storage_error")
        self.assertEqual(self.database.read_bytes(), before)

    def test_storage_path_failure_is_not_reported_as_success(self):
        self.database.parent.write_text("a file blocks the state directory")
        self.assertEqual(self.start(code=1)["code"], "storage_error")
        self.assertEqual(self.database.parent.read_text(), "a file blocks the state directory")


if __name__ == "__main__":
    unittest.main()
