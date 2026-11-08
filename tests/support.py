from contextlib import closing
"""在临时 Git 仓库与独立 CLI 进程中验证任务存取合同。"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ef-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "--quiet", "-b", "main")
        (self.root / "tracked.txt").write_text("baseline\n")
        self.git("add", "tracked.txt")
        self.git("commit", "--quiet", "-m", "fixture")
        self.database = self.root / ".engineering-flow/state.sqlite3"

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.name=EF Test",
             "-c", "user.email=ef-test@example.invalid", "-c", "commit.gpgsign=false",
             "-c", "core.hooksPath=/dev/null", *args],
            check=True, capture_output=True,
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        )

    def cli(self, *args, code=0, cwd=None, workspace=True, env=None):
        command = [sys.executable, "-m", "engineering_flow"]
        if workspace:
            command += ["--workspace", str(self.root if workspace is True else workspace)]
        result = subprocess.run(command + list(args), capture_output=True, text=True,
                                cwd=cwd or self.temp.name, env=env, timeout=15)
        self.assertEqual(result.returncode, code, result.stderr)
        if code == 0:
            self.assertEqual(result.stderr, "")
            return json.loads(result.stdout)
        self.assertEqual(result.stdout, "")
        return json.loads(result.stderr)["error"]

    def start(self, **kwargs):
        return self.cli("task", "start", "--goal", "恢复中文任务 🛠",
                        "--accept", "新进程恢复内容一致", "--accept", "不声称检查已通过",
                        "--issue", "尚未验证快照", **kwargs)

    def rows(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            return connection.execute("SELECT task_id, revision, document FROM task_revisions ORDER BY revision").fetchall()

    def execute_sql(self, sql, parameters=()):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(sql, parameters)
