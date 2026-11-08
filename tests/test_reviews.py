import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from support import GitFixture


class ReviewTests(GitFixture):
    def configure(self):
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "checks": [
            {"id": "actual", "required": True, "argv": ["{python}", "-c", "print('<script>alert(1)</script>')"]}
        ]}))

    def test_material_survives_restart_and_all_references_match_saved_bytes(self):
        self.configure()
        (self.root / "tracked.txt").write_text("pre-existing content\n")
        task_id = self.start()["task"]["id"]
        (self.root / "tracked.txt").write_text("later content\n")
        run = self.cli("check", "run", task_id, "actual")["run"]
        built = self.cli("review", "build", task_id)
        record = built["review"]
        directory = Path(built["directory"])
        self.assertEqual(json.loads((directory / "review.json").read_text()), record)
        self.assertEqual(self.cli("review", "show", record["id"])["review"], record)
        self.assertTrue(record["verification"]["requiredChecksPassed"])
        self.assertIsNone(record["aiExplanation"])
        self.assertIsNone(record["humanConfirmation"])
        references = json.loads((directory / "references.json").read_text())
        self.assertGreater(len(references), 4)
        for reference in references:
            raw = (directory / reference["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), reference["sha256"])
            if "snapshotId" in reference:
                args = ["snapshot", "show", reference["snapshotId"]]
                if "diff" in reference:
                    args += ["--diff", reference["diff"]]
                else:
                    args += ["--file", reference["file"], "--layer", reference["layer"]]
                self.assertEqual(self.cli(*args)["content"]["data"].encode(), raw)
        saved = [r for r in references if r.get("file") == "tracked.txt" and r["layer"] == "worktree"]
        self.assertEqual([(directory / r["path"]).read_text() for r in saved], ["later content\n", "pre-existing content\n"])
        self.assertEqual((directory / run["id"] / "stdout.txt").read_text(), "<script>alert(1)</script>\n")
        self.assertNotIn("<script>", (directory / "review.md").read_text())
        # 产品保存行为没有让检查失效。
        self.assertEqual(self.cli("check", "show", run["id"])["applicability"], "current")

    def test_old_review_stays_bound_to_old_code_and_refresh_shows_stale_checks(self):
        self.configure()
        task_id = self.start()["task"]["id"]
        run = self.cli("check", "run", task_id, "actual")["run"]
        built = self.cli("review", "build", task_id)
        original = Path(built["materialPath"]).read_bytes()
        (self.root / "tracked.txt").write_text("changed after review\n")
        old = self.cli("review", "show", built["review"]["id"])
        self.assertEqual(old["applicability"], "stale")
        self.assertFalse(old["currentVerification"]["requiredChecksPassed"])
        self.assertEqual(old["review"], built["review"])
        newer = self.cli("review", "build", task_id)
        self.assertFalse(newer["review"]["verification"]["requiredChecksPassed"])
        self.assertEqual(newer["review"]["verification"]["checks"][0]["applicability"], "stale")
        self.assertNotEqual(newer["directory"], built["directory"])
        self.assertEqual(Path(built["materialPath"]).read_bytes(), original)
        self.assertEqual(self.cli("check", "show", run["id"])["run"]["status"], "passed")

    def test_task_revision_change_invalidates_review_even_without_code_changes(self):
        task_id = self.start()["task"]["id"]
        record = self.cli("review", "build", task_id)["review"]
        self.cli("task", "checkpoint", task_id, "--expected-revision", "1", "--progress", "additional caller context")
        self.assertEqual(self.cli("review", "show", record["id"])["applicability"], "stale")

    def test_unrun_required_check_and_caller_text_do_not_become_pass_or_confirmation(self):
        self.configure()
        task = self.cli("task", "start", "--goal", "<script>alert(1)</script> [click](javascript:evil)\n# forged heading",
                        "--accept", "<img src=x onerror=evil> all tests passed", "--progress", "AI says confirmed")["task"]
        built = self.cli("review", "build", task["id"])
        material = Path(built["materialPath"]).read_text()
        self.assertIn("not_run / unknown", material)
        self.assertNotIn("<script>", material)
        self.assertNotIn("<img", material)
        self.assertNotIn("[click]", material)
        self.assertNotIn("\n# forged", material)
        self.assertFalse(built["review"]["verification"]["requiredChecksPassed"])
        self.assertIsNone(built["review"]["humanConfirmation"])

    def test_export_failure_keeps_database_material_and_rejects_symlink_output_directory(self):
        task_id = self.start()["task"]["id"]
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.root / ".engineering-flow/reviews").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.cli("review", "build", task_id, code=1)["code"], "review_export")
        self.assertEqual(list(outside.iterdir()), [])
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.database)) as connection:
            key = connection.execute("SELECT id FROM reviews").fetchone()[0]
        self.assertEqual(self.cli("review", "show", key)["review"]["taskId"], task_id)

    def test_corrupt_review_is_refused_instead_of_rendered(self):
        task_id = self.start()["task"]["id"]
        record = self.cli("review", "build", task_id)["review"]
        record["humanConfirmation"] = {"status": "confirmed", "origin": "ai"}
        self.execute_sql("UPDATE reviews SET document=?", (json.dumps(record),))
        self.assertEqual(self.cli("review", "show", record["id"], code=1)["code"], "invalid_evidence")

    def test_example_runs_real_pass_and_known_bug_failure_then_recovers_evidence(self):
        example = Path(__file__).resolve().parents[1] / "examples/batch-queue"
        for file in example.iterdir():
            if file.is_file():
                shutil.copy2(file, self.root / file.name)
        (self.root / ".gitignore").write_text("__pycache__/\n.engineering-flow/\n")
        task_id = self.cli("task", "start", "--goal", "构造批量任务重试", "--accept", "相同请求复用批次及任务")["task"]["id"]
        passed = self.cli("check", "run", task_id, "idempotency")["run"]
        self.assertIn("Ran 4 tests", passed["stderr"]["data"])
        process = subprocess.run([sys.executable, "-m", "engineering_flow", "--workspace", str(self.root),
                                  "check", "run", task_id, "known-bug"], capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 3)
        failed = json.loads(process.stdout)["run"]
        self.assertEqual(failed["status"], "failed")
        self.assertIn("FAILED", failed["stderr"]["data"])
        built = self.cli("review", "build", task_id)
        self.assertEqual([r["status"] for r in built["review"]["runs"]], ["passed", "failed"])
        self.assertTrue(built["review"]["verification"]["requiredChecksPassed"])
        self.assertEqual(self.cli("task", "resume", task_id)["verification"], built["review"]["verification"])
