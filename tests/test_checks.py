import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from unittest.mock import patch

from engineering_flow.core.checks import CheckService
from engineering_flow.core.errors import FlowError
from engineering_flow.core.store import TaskStore

from support import GitFixture


class CheckTests(GitFixture):
    def configure(self, *checks):
        definitions = []
        for item in checks:
            definitions.append(dict({"id": "unit", "required": True, "argv": ["{python}", "-c", "print('actual output')"], "timeoutSeconds": 5}, **item))
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "checks": definitions}))

    def run_check(self, task_id, check="unit", code=0):
        process = subprocess.run([sys.executable, "-m", "engineering_flow", "--workspace", str(self.root),
                                  "check", "run", task_id, check], capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, code, process.stderr + process.stdout)
        self.assertEqual(process.stderr, "")
        return json.loads(process.stdout)

    def test_real_pass_persists_in_new_process_without_changing_task_revision(self):
        (self.root / "subdir").mkdir()
        self.configure({"cwd": "subdir", "argv": ["{python}", "-c", "import os,sys; print(os.getcwd()); print('stderr',file=sys.stderr)"]})
        started = self.start()
        self.assertEqual(started["verification"]["checks"][0]["status"], "not_run")
        self.assertFalse(started["verification"]["requiredChecksPassed"])
        result = self.run_check(started["task"]["id"])
        run = result["run"]
        self.assertEqual((run["status"], result["applicability"], run["exitCode"]), ("passed", "current", 0))
        self.assertEqual(run["snapshotId"], run["snapshotAfterId"])
        self.assertEqual(run["argv"][0], sys.executable)
        self.assertEqual(run["stdout"]["data"].strip(), str((self.root / "subdir").resolve()))
        self.assertEqual(run["stderr"]["data"], "stderr\n")
        self.assertEqual(run["origin"], "runner")
        self.assertEqual(self.cli("check", "show", run["id"])["run"], run)
        resumed = self.cli("task", "resume", started["task"]["id"])
        self.assertEqual(resumed["task"], started["task"])
        self.assertTrue(resumed["verification"]["requiredChecksPassed"])
        self.assertEqual(len(self.rows()), 1)

    def test_nonzero_exit_is_failed_and_newer_failure_supersedes_pass(self):
        self.configure({"argv": ["{python}", "-c", "from pathlib import Path; import sys; p=Path('.engineering-flow/once'); existed=p.exists(); p.touch(); print('assertion output'); sys.exit(7 if existed else 0)"]})
        task_id = self.start()["task"]["id"]
        self.run_check(task_id)
        failed = self.run_check(task_id, code=3)["run"]
        self.assertEqual((failed["status"], failed["exitCode"], failed["failure"]), ("failed", 7, None))
        resumed = self.cli("task", "resume", task_id)["verification"]
        self.assertFalse(resumed["requiredChecksPassed"])
        self.assertEqual(resumed["checks"][0]["runId"], failed["id"])
        self.assertEqual([r["status"] for r in resumed["history"]], ["passed", "failed"])

    def test_command_not_found_is_launch_error_with_raw_message(self):
        self.configure({"argv": ["/ef-missing-command-123456"]})
        run = self.run_check(self.start()["task"]["id"], code=3)["run"]
        self.assertEqual((run["status"], run["exitCode"], run["failure"]["kind"]), ("error", None, "launch"))
        self.assertIn("ef-missing-command", run["failure"]["message"])

    def test_timeout_terminates_process_group_and_keeps_partial_output(self):
        self.configure({"timeoutSeconds": 0.2, "argv": ["{python}", "-u", "-c", "import time; print('started'); time.sleep(30)"]})
        result = self.run_check(self.start()["task"]["id"], code=3)
        self.assertEqual(result["run"]["failure"]["kind"], "timeout")
        self.assertEqual(result["run"]["stdout"]["data"], "started\n")
        self.assertLess(result["run"]["exitCode"], 0)

    def test_binary_output_roundtrips_and_argv_does_not_use_shell(self):
        self.configure({"argv": ["{python}", "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\x00'); print(sys.argv[1],file=sys.stderr)", "$(touch injected); <script>"]})
        run = self.run_check(self.start()["task"]["id"])["run"]
        self.assertEqual(run["stdout"]["encoding"], "base64")
        self.assertEqual(run["stdout"]["data"], "/wA=")
        self.assertIn("$(touch injected)", run["stderr"]["data"])
        self.assertFalse((self.root / "injected").exists())

    def test_output_limit_is_error_even_when_process_exits_zero(self):
        self.configure({"argv": ["{python}", "-c", "import sys; sys.stdout.write('x'*100000)"]})
        task_id = self.start()["task"]["id"]
        with patch("engineering_flow.core.checks.MAX_OUTPUT_BYTES", 1024):
            run = CheckService(self.root).run(task_id, "unit")["run"]
        self.assertEqual((run["status"], run["failure"]["kind"]), ("error", "output_limit"))
        self.assertEqual(run["stdout"]["size"], 1024)
        self.assertTrue(run["stdout"]["truncated"])

    def test_run_mutating_source_is_historical_pass_but_stale(self):
        self.configure({"argv": ["{python}", "-c", "from pathlib import Path; Path('tracked.txt').write_text('changed by check')"]})
        result = self.run_check(self.start()["task"]["id"], code=3)
        self.assertEqual((result["run"]["status"], result["applicability"]), ("passed", "stale"))
        self.assertNotEqual(result["run"]["snapshotId"], result["run"]["snapshotAfterId"])
        self.assertFalse(self.cli("task", "resume", result["run"]["taskId"])["verification"]["requiredChecksPassed"])

    def test_post_snapshot_error_is_saved_and_never_passed(self):
        self.configure({"argv": ["{python}", "-c", "from pathlib import Path; Path('tracked.txt').unlink(); Path('tracked.txt').symlink_to('/dev/null')"]})
        result = self.run_check(self.start()["task"]["id"], code=3)
        self.assertEqual(result["run"]["failure"]["kind"], "post_snapshot")
        self.assertEqual((result["run"]["status"], result["applicability"]), ("error", "unknown"))
        (self.root / "tracked.txt").unlink()
        (self.root / "tracked.txt").write_text("baseline\n")
        self.assertEqual(self.cli("check", "show", result["run"]["id"])["applicability"], "unknown")

    def test_uncommitted_source_or_config_change_invalidates_pass(self):
        self.configure({})
        task_id = self.start()["task"]["id"]
        run = self.run_check(task_id)["run"]
        head = self.git("rev-parse", "HEAD").stdout
        (self.root / "tracked.txt").write_text("edited after pass\n")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, head)
        self.assertEqual(self.cli("check", "show", run["id"])["applicability"], "stale")
        (self.root / "tracked.txt").write_text("baseline\n")
        self.configure({"required": False})
        resumed = self.cli("task", "resume", task_id)["verification"]
        self.assertEqual(resumed["checks"][0]["applicability"], "stale")
        self.assertFalse(resumed["requiredChecksPassed"])

    def test_optional_pass_does_not_satisfy_unrun_required_check(self):
        self.configure({}, {"id": "optional", "required": False})
        task_id = self.start()["task"]["id"]
        self.run_check(task_id, "optional")
        self.assertFalse(self.cli("task", "resume", task_id)["verification"]["requiredChecksPassed"])
        self.cli("check", "run", task_id, "missing", code=1)
        rejected = subprocess.run([sys.executable, "-m", "engineering_flow", "--workspace", str(self.root),
                                   "check", "run", task_id, "unit", "--status", "passed"], capture_output=True)
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(rejected.stdout, b"")

    def test_no_checks_cannot_imply_verification(self):
        result = self.start()
        self.assertEqual(result["verification"]["checks"], [])
        self.assertFalse(result["verification"]["requiredChecksPassed"])

    def test_invalid_config_and_escaped_or_symlink_cwd_are_rejected(self):
        for changes in ({"cwd": "../escape"}, {"required": "false"}, {"argv": "echo ok"}, {"timeoutSeconds": True}):
            self.configure(changes)
            self.assertEqual(self.start(code=1)["code"], "invalid_config")
        (self.root / ".gitignore").write_text("outside\n")
        (self.root / "outside").symlink_to(self.temp.name, target_is_directory=True)
        self.configure({"cwd": "outside"})
        run = self.run_check(self.start()["task"]["id"], code=3)["run"]
        self.assertEqual(run["failure"]["kind"], "launch")

    def test_branch_mismatch_and_corrupt_output_are_not_accepted(self):
        self.configure({})
        run = self.run_check(self.start()["task"]["id"])["run"]
        self.git("checkout", "--quiet", "-b", "other")
        self.assertEqual(self.cli("check", "show", run["id"], code=1)["code"], "workspace_mismatch")
        self.git("checkout", "--quiet", "main")
        run["stdout"]["data"] = "fake passing text"
        self.execute_sql("UPDATE check_runs SET document=?", (json.dumps(run),))
        self.assertEqual(self.cli("task", "resume", run["taskId"], code=1)["code"], "invalid_evidence")

    def test_sigterm_records_interruption_and_sigkill_leaves_unknown_running(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            self.configure({"argv": ["{python}", "-u", "-c", "from pathlib import Path; import os,time; Path('.engineering-flow/child.pid').write_text(str(os.getpid())); print('ready'); time.sleep(30)"]})
            task_id = self.start()["task"]["id"]
            marker = self.root / ".engineering-flow/child.pid"
            marker.unlink(missing_ok=True)
            process = subprocess.Popen([sys.executable, "-m", "engineering_flow", "--workspace", str(self.root), "check", "run", task_id, "unit"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.addCleanup(lambda p=process: p.kill() if p.poll() is None else None)
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            child = int(marker.read_text())
            try:
                process.send_signal(sig)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(stderr, b"")
                verification = self.cli("task", "resume", task_id)["verification"]
                self.assertFalse(verification["requiredChecksPassed"])
                if sig == signal.SIGTERM:
                    result = json.loads(stdout)
                    self.assertEqual(result["run"]["failure"]["kind"], "interrupted")
                    self.assertEqual(process.returncode, 3)
                else:
                    self.assertEqual(verification["checks"][0]["status"], "running")
                    self.assertEqual(verification["checks"][0]["applicability"], "unknown")
            finally:
                try:
                    os.killpg(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_v2_read_preserves_bytes_and_write_upgrades_evidence_tables(self):
        task = self.start()["task"]
        before = self.rows()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("DROP TABLE check_runs")
            connection.execute("DROP TABLE reviews")
            connection.execute("DROP TABLE review_events")
            connection.execute("DROP TABLE memories")
            connection.execute("DROP TABLE memory_events")
            connection.execute("DROP TABLE document_proposals")
            connection.execute("PRAGMA user_version=2")
        self.assertEqual(self.cli("task", "resume", task["id"])["task"], task)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
        self.cli("task", "checkpoint", task["id"], "--expected-revision", "1", "--progress", "upgrade")
        self.assertEqual(self.rows()[0], before[0])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)

    def test_evidence_migration_failure_rolls_back_before_command_runs(self):
        self.configure({"argv": ["{python}", "-c", "from pathlib import Path; Path('must-not-exist').touch()"]})
        task_id = self.start()["task"]["id"]
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("DROP TABLE check_runs")
            connection.execute("DROP TABLE reviews")
            connection.execute("DROP TABLE review_events")
            connection.execute("DROP TABLE memories")
            connection.execute("DROP TABLE memory_events")
            connection.execute("DROP TABLE document_proposals")
            connection.execute("PRAGMA user_version=2")
        original = sqlite3.connect
        def denied(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and name == "reviews" else sqlite3.SQLITE_OK)
            return connection
        with patch("engineering_flow.core.store.sqlite3.connect", side_effect=denied):
            with self.assertRaises(FlowError) as raised:
                CheckService(self.root).run(task_id, "unit")
        self.assertEqual(raised.exception.code, "storage_error")
        self.assertFalse((self.root / "must-not-exist").exists())
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='check_runs'").fetchone())

    def test_finish_storage_failure_cannot_leave_a_passed_record(self):
        self.configure({})
        task_id = self.start()["task"]["id"]
        original = TaskStore.save_evidence
        def fail_finish(store, kind, document, **kwargs):
            if kwargs.get("finishing"):
                raise FlowError("storage_full", "injected finish write failure")
            return original(store, kind, document, **kwargs)
        with patch.object(TaskStore, "save_evidence", fail_finish):
            with self.assertRaises(FlowError) as raised:
                CheckService(self.root).run(task_id, "unit")
        self.assertEqual(raised.exception.code, "storage_full")
        result = self.cli("task", "resume", task_id)["verification"]
        self.assertEqual((result["checks"][0]["status"], result["checks"][0]["applicability"]), ("running", "unknown"))
        self.assertFalse(result["requiredChecksPassed"])

    def test_copied_database_does_not_expose_check_as_current_in_other_worktree(self):
        import shutil
        self.configure({})
        run = self.run_check(self.start()["task"]["id"])["run"]
        other = self.root.parent / "other-worktree"
        self.git("worktree", "add", "--quiet", "-b", "other", str(other))
        (other / ".engineering-flow").mkdir()
        shutil.copy2(self.database, other / ".engineering-flow/state.sqlite3")
        self.assertEqual(self.cli("check", "show", run["id"], workspace=other, code=1)["code"], "workspace_mismatch")
