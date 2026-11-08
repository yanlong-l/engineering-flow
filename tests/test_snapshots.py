from contextlib import closing
import base64
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

from engineering_flow.core import snapshots
from engineering_flow.core.errors import FlowError
from engineering_flow.core.tasks import TaskService

from support import GitFixture


class SnapshotTests(GitFixture):
    def test_head_unchanged_content_changes_are_stale_and_saved_content_survives(self):
        initial = self.start()["task"]
        (self.root / "tracked.txt").write_text("after start\n")
        restored = self.cli("task", "resume", initial["id"])
        self.assertEqual(restored["currentWorkspace"]["head"], initial["savedWorkspace"]["head"])
        self.assertEqual(restored["snapshotComparison"]["status"], "stale")
        self.assertEqual(restored["snapshotComparison"]["changes"][0]["path"], "tracked.txt")
        old = self.cli("snapshot", "show", initial["savedWorkspace"]["snapshotId"], "--file", "tracked.txt")
        self.assertEqual(old["content"]["data"], "baseline\n")
        self.assertEqual(self.cli("task", "resume", initial["id"])["task"], initial)

    def test_index_only_changes_are_captured_separately_from_worktree(self):
        initial = self.start()["task"]
        (self.root / "tracked.txt").write_text("staged version\n")
        self.git("add", "tracked.txt")
        (self.root / "tracked.txt").write_text("baseline\n")
        saved = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "保存两个层次")
        snapshot_id = saved["task"]["savedWorkspace"]["snapshotId"]
        self.assertNotEqual(snapshot_id, initial["savedWorkspace"]["snapshotId"])
        self.assertEqual(self.cli("snapshot", "show", snapshot_id, "--file", "tracked.txt", "--layer", "index")["content"]["data"], "staged version\n")
        self.assertEqual(self.cli("snapshot", "show", snapshot_id, "--file", "tracked.txt")["content"]["data"], "baseline\n")
        self.assertIn("+staged version", self.cli("snapshot", "show", snapshot_id, "--diff", "staged")["content"]["data"])

    def test_preexisting_and_later_changes_in_one_file_keep_evidence_and_unknown_ownership(self):
        (self.root / "tracked.txt").write_text("baseline\npreexisting\n")
        task = self.cli("task", "start", "--goal", "混合改动", "--accept", "保留已有内容", "--file", "tracked.txt")["task"]
        baseline_id = task["startingWorkspace"]["snapshotId"]
        (self.root / "tracked.txt").write_text("baseline\npreexisting\nlater unknown author\n")
        result = self.cli("task", "resume", task["id"])
        change = result["changesSinceStart"]["changes"][0]
        self.assertEqual(change["association"], "explicitly_related")
        self.assertEqual(change["ownership"], "unknown")
        self.assertEqual(self.cli("snapshot", "show", baseline_id, "--file", "tracked.txt")["content"]["data"], "baseline\npreexisting\n")
        diff = self.cli("snapshot", "show", baseline_id, "--diff", "unstaged")["content"]["data"]
        self.assertIn("+preexisting", diff)
        self.assertNotIn("later unknown author", diff)
        saved = self.cli("task", "checkpoint", task["id"], "--expected-revision", "1", "--progress", "保存")
        self.assertEqual(saved["task"]["startingWorkspace"], task["startingWorkspace"])
        self.assertEqual(saved["snapshotComparison"]["status"], "current")
        self.assertEqual(saved["changesSinceStart"]["status"], "stale")

    def test_untracked_bytes_change_even_when_status_and_head_do_not(self):
        target = self.root / "new.txt"
        target.write_text("one")
        initial = self.start()
        target.write_text("two")
        restored = self.cli("task", "resume", initial["task"]["id"])
        self.assertEqual(restored["currentWorkspace"]["observedChanges"], initial["currentWorkspace"]["observedChanges"])
        self.assertEqual(restored["snapshotComparison"]["status"], "stale")

    def test_deleted_and_renamed_files_preserve_starting_contents(self):
        task = self.start()["task"]
        self.git("mv", "tracked.txt", "renamed.txt")
        result = self.cli("task", "resume", task["id"])
        files = {entry["path"]: entry for entry in result["currentSnapshot"]["files"]}
        self.assertEqual(files["tracked.txt"]["worktree"]["kind"], "missing")
        self.assertEqual(files["renamed.txt"]["worktree"]["kind"], "file")
        self.assertEqual(result["snapshotComparison"]["status"], "stale")
        self.assertEqual(self.cli("snapshot", "show", task["startingWorkspace"]["snapshotId"], "--file", "tracked.txt")["content"]["data"], "baseline\n")

    def test_binary_contents_roundtrip_and_executable_mode_changes_fingerprint(self):
        data = b"\x00\xffbinary\n"
        (self.root / "binary.dat").write_bytes(data)
        task = self.start()["task"]
        content = self.cli("snapshot", "show", task["savedWorkspace"]["snapshotId"], "--file", "binary.dat")["content"]
        self.assertEqual(content["encoding"], "base64")
        self.assertEqual(base64.b64decode(content["data"]), data)
        os.chmod(self.root / "tracked.txt", 0o755)
        self.assertEqual(self.cli("task", "resume", task["id"])["snapshotComparison"]["status"], "stale")

    def test_ignored_scope_is_visible_and_explicit_additional_inputs_are_captured(self):
        (self.root / ".gitignore").write_text("ignored.py\ntracked.txt\n")
        (self.root / "ignored.py").write_text("one\n")
        initial = self.start()
        self.assertIn("ignored.py", initial["currentSnapshot"]["scope"]["ignoredPaths"])
        self.assertIn("tracked.txt", [e["path"] for e in initial["currentSnapshot"]["files"]])
        (self.root / "ignored.py").write_text("two\n")
        self.assertEqual(self.cli("task", "resume", initial["task"]["id"])["snapshotComparison"]["status"], "current")
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "additionalInputs": ["ignored.py"]}))
        included = self.start()["task"]
        old = self.cli("snapshot", "show", included["savedWorkspace"]["snapshotId"], "--file", "ignored.py")
        self.assertEqual(old["content"]["data"], "two\n")
        (self.root / "ignored.py").write_text("three\n")
        self.assertEqual(self.cli("task", "resume", included["id"])["snapshotComparison"]["status"], "stale")

    def test_declared_directory_includes_ignored_children(self):
        (self.root / ".gitignore").write_text("inputs/\n")
        (self.root / "inputs").mkdir()
        (self.root / "inputs/data.txt").write_text("declared")
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "additionalInputs": ["inputs"]}))
        result = self.start()
        self.assertIn("inputs/data.txt", [e["path"] for e in result["currentSnapshot"]["files"]])

    def test_product_records_and_logs_do_not_change_input_fingerprint(self):
        initial = self.start()["task"]
        (self.root / ".engineering-flow/log.txt").write_text("generated output")
        saved = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "only progress")
        self.assertEqual(saved["task"]["savedWorkspace"]["snapshotId"], initial["savedWorkspace"]["snapshotId"])
        self.assertEqual(saved["snapshotComparison"]["status"], "current")

    def test_ignored_product_directory_does_not_invalidate_new_task(self):
        (self.root / ".gitignore").write_text(".engineering-flow/\n")
        nested = self.root / "nested/.engineering-flow"
        nested.mkdir(parents=True)
        (nested / "input.txt").write_text("ignored project input, not root product state")
        (self.root / "nested/source.py").write_text("project input\n")
        initial = self.start()
        resumed = self.cli("task", "resume", initial["task"]["id"])
        self.assertEqual(resumed["snapshotComparison"]["status"], "current")
        self.assertEqual(initial["currentSnapshot"]["id"], resumed["currentSnapshot"]["id"])
        self.assertNotIn(".engineering-flow/", resumed["currentSnapshot"]["scope"]["ignoredPaths"])
        self.assertIn("nested/.engineering-flow/", resumed["currentSnapshot"]["scope"]["ignoredPaths"])

    def test_escape_paths_and_invalid_configuration_are_rejected_before_writes(self):
        for path in ("../outside", "/absolute", ".git/config", ".engineering-flow/state.sqlite3", "nested/../escape"):
            with self.subTest(path=path):
                (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "additionalInputs": [path]}))
                self.assertEqual(self.start(code=1)["code"], "invalid_config")
                self.assertFalse(self.database.exists())
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "additionalInputs": ["missing.txt"]}))
        self.assertEqual(self.start(code=1)["code"], "missing_input")

    def test_symbolic_file_and_declared_symbolic_directory_are_not_followed(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("outside contents")
        (self.root / "link.txt").symlink_to(outside)
        self.assertEqual(self.start(code=1)["code"], "unsupported_input")
        self.assertFalse(self.database.exists())
        (self.root / "link.txt").unlink()
        (self.root / "external").symlink_to(outside.parent, target_is_directory=True)
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "additionalInputs": ["external"]}))
        self.assertEqual(self.start(code=1)["code"], "unsupported_input")
        self.assertEqual(outside.read_text(), "outside contents")

    def test_submodule_is_explicitly_unsupported(self):
        head = self.git("rev-parse", "HEAD").stdout.decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{head},vendor")
        self.assertEqual(self.start(code=1)["code"], "unsupported_input")
        self.assertFalse(self.database.exists())

    def test_special_file_is_rejected_without_blocking(self):
        os.mkfifo(self.root / "pipe")
        # Git 不枚举 FIFO；显式声明后也必须报错而非阻塞读取。
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "additionalInputs": ["pipe"]}))
        self.assertEqual(self.start(code=1)["code"], "unsupported_input")
        self.assertFalse(self.database.exists())

    def test_size_and_count_limits_fail_without_incomplete_saved_snapshot(self):
        with patch.object(snapshots, "MAX_FILES", 0):
            with self.assertRaises(FlowError) as raised:
                TaskService(self.root).start(goal="limit", acceptance=["error"])
            self.assertEqual(raised.exception.code, "snapshot_limit")
        with (self.root / "large.bin").open("wb") as stream:
            stream.truncate(snapshots.MAX_BYTES + 1)
        self.assertEqual(self.start(code=1)["code"], "snapshot_limit")
        self.assertFalse(self.database.exists())

    def test_concurrent_content_mutation_is_detected_before_checkpoint(self):
        initial = self.start()["task"]
        collect = snapshots._collect
        calls = 0
        def mutate(path):
            nonlocal calls
            result = collect(path)
            calls += 1
            if calls == 1:
                (self.root / "tracked.txt").write_text("concurrently changed\n")
            return result
        with patch.object(snapshots, "_collect", side_effect=mutate):
            with self.assertRaises(FlowError) as raised:
                TaskService(self.root).checkpoint(initial["id"], expected_revision=1, progress="must not save")
        self.assertEqual(raised.exception.code, "snapshot_changed")
        self.assertEqual(len(self.rows()), 1)

    def test_damaged_blob_blocks_resume_and_checkpoint_without_rewriting_history(self):
        initial = self.start()["task"]
        self.execute_sql("UPDATE blobs SET content=?", (b"tampered",))
        before = self.database.read_bytes()
        for args in [("task", "resume", initial["id"]),
                     ("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "bad")]:
            self.assertEqual(self.cli(*args, code=1)["code"], "invalid_snapshot")
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(len(self.rows()), 1)

    def test_missing_snapshot_and_corrupt_manifest_are_errors(self):
        initial = self.start()["task"]
        self.execute_sql("UPDATE snapshots SET document=?", ("{broken",))
        self.assertEqual(self.cli("task", "resume", initial["id"], code=1)["code"], "invalid_snapshot")
        self.execute_sql("DELETE FROM snapshots")
        self.assertEqual(self.cli("task", "resume", initial["id"], code=1)["code"], "invalid_snapshot")

    def test_related_paths_are_explicit_associations_and_can_be_cleared(self):
        initial = self.cli("task", "start", "--goal", "related", "--accept", "preserve", "--file", "tracked.txt")["task"]
        self.assertEqual(initial["relatedFiles"], ["tracked.txt"])
        saved = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "clear", "--clear-files")
        self.assertEqual(saved["task"]["relatedFiles"], [])
        self.assertEqual(self.cli("snapshot", "show", initial["savedWorkspace"]["snapshotId"], "--file", "../escape", code=1)["code"], "invalid_input")

    def test_v1_read_is_unchanged_and_write_migrates_without_fabricating_baseline(self):
        initial = self.start()["task"]
        legacy = dict(initial, schemaVersion=1)
        legacy.pop("relatedFiles")
        legacy["startingWorkspace"] = dict(initial["startingWorkspace"], snapshotId=None)
        legacy["savedWorkspace"] = dict(initial["savedWorkspace"], snapshotId=None)
        original = json.dumps(legacy)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE task_revisions SET document=?", (original,))
            connection.execute("DROP TABLE snapshots")
            connection.execute("DROP TABLE blobs")
            connection.execute("DROP TABLE check_runs")
            connection.execute("DROP TABLE reviews")
            connection.execute("DROP TABLE review_events")
            connection.execute("DROP TABLE memories")
            connection.execute("DROP TABLE memory_events")
            connection.execute("DROP TABLE document_proposals")
            connection.execute("PRAGMA user_version=1")
        before = self.database.read_bytes()
        restored = self.cli("task", "resume", initial["id"])
        self.assertEqual(restored["task"], legacy)
        self.assertEqual(restored["snapshotComparison"]["status"], "unknown")
        self.assertEqual(self.database.read_bytes(), before)
        saved = self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "v2")
        self.assertEqual(saved["task"]["schemaVersion"], 2)
        self.assertIsNone(saved["task"]["startingWorkspace"]["snapshotId"])
        self.assertEqual(saved["changesSinceStart"]["status"], "unknown")
        self.assertEqual(saved["snapshotComparison"]["status"], "current")
        self.assertEqual(self.rows()[0][2], original)
        self.assertEqual(self.cli("task", "resume", initial["id"])["task"], saved["task"])
