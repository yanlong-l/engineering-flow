from contextlib import closing
import shutil
import sqlite3
import subprocess

from support import GitFixture


class IsolationTests(GitFixture):
    def copy_store(self, destination):
        target = destination / ".engineering-flow/state.sqlite3"
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as source, closing(sqlite3.connect(target)) as sink:
            source.backup(sink)
        return target

    def test_different_worktree_has_no_task_and_copied_database_is_rejected(self):
        initial = self.start()["task"]
        other = self.root.parent / "repo-other"
        self.git("worktree", "add", "--quiet", "-b", "other", str(other))
        self.assertEqual(self.cli("task", "resume", initial["id"], workspace=other, code=1)["code"], "task_not_found")
        target = self.copy_store(other)
        before = target.read_bytes()
        self.assertEqual(self.cli("task", "resume", initial["id"], workspace=other, code=1)["code"], "workspace_mismatch")
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self.cli("snapshot", "show", initial["savedWorkspace"]["snapshotId"], workspace=other, code=1)["code"], "workspace_mismatch")

    def test_same_branch_name_worktrees_have_distinct_identities(self):
        first = self.start()["task"]
        other = self.root.parent / "repo-similar"
        self.git("worktree", "add", "--quiet", "--force", str(other), "main")
        second = self.start(workspace=other)["task"]
        a, b = first["savedWorkspace"], second["savedWorkspace"]
        self.assertEqual(a["branch"], b["branch"])
        self.assertEqual(a["projectId"], b["projectId"])
        self.assertNotEqual(a["workspaceId"], b["workspaceId"])
        self.assertNotEqual(a["snapshotId"], b["snapshotId"])
        self.copy_store(other)
        self.assertEqual(self.cli("task", "resume", first["id"], workspace=other, code=1)["code"], "workspace_mismatch")

    def test_same_remote_clones_are_not_the_same_local_project(self):
        self.git("remote", "add", "origin", "https://example.invalid/shared.git")
        initial = self.start()["task"]
        other = self.root.parent / "clone"
        subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(self.root), str(other)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(other), "remote", "set-url", "origin", "https://example.invalid/shared.git"], check=True)
        second = self.start(workspace=other)["task"]
        self.assertNotEqual(initial["savedWorkspace"]["projectId"], second["savedWorkspace"]["projectId"])
        self.copy_store(other)
        self.assertEqual(self.cli("task", "resume", initial["id"], workspace=other, code=1)["code"], "workspace_mismatch")

    def test_canonical_symlink_alias_can_resume_same_workspace(self):
        initial = self.start()["task"]
        alias = self.root.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.cli("task", "resume", initial["id"], workspace=alias)["task"], initial)

    def test_moving_checkout_does_not_silently_adopt_old_identity(self):
        initial = self.start()["task"]
        other = self.root.parent / "moved"
        shutil.copytree(self.root, other)
        self.assertEqual(self.cli("task", "resume", initial["id"], workspace=other, code=1)["code"], "workspace_mismatch")

    def test_detached_head_switch_to_other_commit_is_rejected(self):
        first = self.git("rev-parse", "HEAD").stdout.decode().strip()
        (self.root / "tracked.txt").write_text("second commit\n")
        self.git("commit", "--quiet", "-am", "second")
        second = self.git("rev-parse", "HEAD").stdout.decode().strip()
        self.git("checkout", "--quiet", "--detach", first)
        initial = self.start()["task"]
        self.git("checkout", "--quiet", "--detach", second)
        self.assertEqual(self.cli("task", "resume", initial["id"], code=1)["code"], "workspace_mismatch")

    def test_state_directory_or_database_symlink_is_rejected(self):
        outside = self.root.parent / "outside-state"
        outside.mkdir()
        self.database.parent.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.start(code=1)["code"], "storage_path")
        self.assertEqual(list(outside.iterdir()), [])
        self.database.parent.unlink()
        self.database.parent.mkdir()
        external_db = outside / "state.sqlite3"
        external_db.write_bytes(b"untouched")
        self.database.symlink_to(external_db)
        self.assertEqual(self.start(code=1)["code"], "storage_path")
        self.assertEqual(external_db.read_bytes(), b"untouched")
