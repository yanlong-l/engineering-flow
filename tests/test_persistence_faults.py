from contextlib import closing
import json
import selectors
import sqlite3
import subprocess
import sys
from copy import deepcopy
from unittest.mock import patch

from engineering_flow.core.errors import FlowError
from engineering_flow.core.snapshots import capture_snapshot
from engineering_flow.core.store import TaskStore

from support import GitFixture


class PersistenceFaultTests(GitFixture):
    def worker(self, script, *args):
        process = subprocess.Popen([sys.executable, "-u", "-c", script, *map(str, args)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        self.addCleanup(cleanup)
        return process

    def ready(self, process):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=10), "worker did not reach transaction boundary")
        self.assertEqual(process.stdout.readline().strip(), "READY", "worker failed before boundary")

    def candidate(self, initial):
        capture = capture_snapshot(self.root)
        record = deepcopy(initial)
        record.update(revision=2, progress="candidate", savedWorkspace=capture.workspace)
        return record, capture

    def counts(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in ("task_revisions", "snapshots", "blobs"))

    def test_two_processes_compete_for_same_revision_without_lost_update(self):
        initial = self.start()["task"]
        script = '''
import json, sys
from pathlib import Path
from engineering_flow.core.tasks import TaskService
from engineering_flow.core.errors import FlowError
service = TaskService(Path(sys.argv[1]))
record, capture = service._resume(sys.argv[2])
record.update(revision=2, progress=sys.argv[3], savedWorkspace=capture.workspace)
print('READY', flush=True)
sys.stdin.readline()
try:
    service._store(capture.workspace).append(record, expected_revision=1, capture=capture)
    print(json.dumps({'saved': sys.argv[3]}))
except FlowError as exc:
    print(json.dumps({'error': exc.code}))
    sys.exit(1)
'''
        workers = [self.worker(script, self.root, initial["id"], f"writer-{index}") for index in range(2)]
        for process in workers:
            self.ready(process)
        for process in workers:
            process.stdin.write("go\n")
            process.stdin.flush()
        results = []
        for process in workers:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(stderr, "")
            results.append((process.returncode, json.loads(stdout)))
        self.assertEqual(sorted(code for code, _ in results), [0, 1])
        self.assertEqual(next(value["error"] for code, value in results if code), "revision_conflict")
        winner = next(value["saved"] for code, value in results if not code)
        restored = self.cli("task", "resume", initial["id"])["task"]
        self.assertEqual(restored["revision"], 2)
        self.assertEqual(restored["progress"], winner)
        self.assertEqual(len(self.rows()), 2)

    def test_kill_after_blobs_and_snapshot_before_task_commit_recovers_last_revision(self):
        initial = self.start()["task"]
        before = self.counts()
        (self.root / "tracked.txt").write_text("pending content with new snapshot\n")
        script = '''
import sqlite3, sys
from pathlib import Path
from engineering_flow.core.tasks import TaskService
service = TaskService(Path(sys.argv[1]))
record, capture = service._resume(sys.argv[2])
record.update(revision=2, progress='must roll back', savedWorkspace=capture.workspace)
original = sqlite3.connect
def connect(*args, **kwargs):
    connection = original(*args, **kwargs)
    def trace(statement):
        if statement.startswith('INSERT INTO task_revisions'):
            print('READY', flush=True)
            sys.stdin.readline()
    connection.set_trace_callback(trace)
    return connection
sqlite3.connect = connect
service._store(capture.workspace).append(record, expected_revision=1, capture=capture)
'''
        process = self.worker(script, self.root, initial["id"])
        self.ready(process)
        process.kill()
        process.communicate(timeout=10)
        self.assertLess(process.returncode, 0)
        restored = self.cli("task", "resume", initial["id"])
        self.assertEqual(restored["task"], initial)
        self.assertEqual(restored["snapshotComparison"]["status"], "stale")
        self.assertEqual(self.counts(), before)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "retry")["task"]["revision"], 2)

    def test_real_lock_timeout_is_diagnosed_then_retry_succeeds(self):
        initial = self.start()["task"]
        record, capture = self.candidate(initial)
        process = self.worker('''
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1], isolation_level=None)
connection.execute('BEGIN IMMEDIATE')
print('READY', flush=True)
sys.stdin.readline()
connection.close()
''', self.database)
        self.ready(process)
        with self.assertRaises(FlowError) as raised:
            TaskStore(self.database, timeout=0.05).append(record, expected_revision=1, capture=capture)
        self.assertEqual(raised.exception.code, "storage_busy")
        process.communicate(input="release\n", timeout=10)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "retry")["task"]["revision"], 2)

    def test_sqlite_page_limit_full_rolls_back_all_new_objects(self):
        initial = self.start()["task"]
        before = self.counts()
        (self.root / "large.txt").write_text("large data\n" * 30000)
        record, capture = self.candidate(initial)
        original = sqlite3.connect
        def limited(*args, **kwargs):
            connection = original(*args, **kwargs)
            pages = connection.execute("PRAGMA page_count").fetchone()[0]
            connection.execute(f"PRAGMA max_page_count={pages}")
            return connection
        with patch("engineering_flow.core.store.sqlite3.connect", side_effect=limited):
            with self.assertRaises(FlowError) as raised:
                TaskStore(self.database).append(record, expected_revision=1, capture=capture)
        self.assertEqual(raised.exception.code, "storage_full")
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.cli("task", "resume", initial["id"])["task"], initial)

    def test_readonly_connection_is_not_reported_as_success(self):
        initial = self.start()["task"]
        record, capture = self.candidate(initial)
        original = sqlite3.connect
        def readonly(database_uri, **kwargs):
            return original(database_uri.replace("mode=rwc", "mode=ro"), **kwargs)
        with patch("engineering_flow.core.store.sqlite3.connect", side_effect=readonly):
            with self.assertRaises(FlowError) as raised:
                TaskStore(self.database).append(record, expected_revision=1, capture=capture)
        self.assertEqual(raised.exception.code, "storage_readonly")
        self.assertEqual(len(self.rows()), 1)

    def test_partial_schema_migration_failure_rolls_back_tables_and_version(self):
        initial = self.start()["task"]
        legacy = dict(initial, schemaVersion=1)
        legacy.pop("relatedFiles")
        legacy["startingWorkspace"] = dict(initial["startingWorkspace"], snapshotId=None)
        legacy["savedWorkspace"] = dict(initial["savedWorkspace"], snapshotId=None)
        raw = json.dumps(legacy)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE task_revisions SET document=?", (raw,))
            connection.execute("DROP TABLE snapshots")
            connection.execute("DROP TABLE blobs")
            connection.execute("DROP TABLE check_runs")
            connection.execute("DROP TABLE reviews")
            connection.execute("DROP TABLE review_events")
            connection.execute("DROP TABLE memories")
            connection.execute("DROP TABLE memory_events")
            connection.execute("DROP TABLE document_proposals")
            connection.execute("PRAGMA user_version=1")
        record, capture = self.candidate(legacy)
        record.update(schemaVersion=2, relatedFiles=[])
        original = sqlite3.connect
        def denied(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY
                                      if action == sqlite3.SQLITE_CREATE_TABLE and name == "blobs" else sqlite3.SQLITE_OK)
            return connection
        with patch("engineering_flow.core.store.sqlite3.connect", side_effect=denied):
            with self.assertRaises(FlowError) as raised:
                TaskStore(self.database).append(record, expected_revision=1, capture=capture)
        self.assertEqual(raised.exception.code, "storage_error")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("task_revisions",)])
        self.assertEqual(self.rows()[0][2], raw)
        self.assertEqual(self.cli("task", "checkpoint", initial["id"], "--expected-revision", "1", "--progress", "retry")["task"]["revision"], 2)
