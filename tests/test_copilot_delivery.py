"""分页证据、版本绑定及只读安装诊断的实际边界。"""

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from engineering_flow.adapters.responses import INLINE_BYTES, ResponseStore, encode
from engineering_flow.core.errors import FlowError
import test_copilot as copilot_helpers

MCP_AVAILABLE = copilot_helpers.MCP_AVAILABLE


class ResponseTests(unittest.TestCase):
    def test_unicode_long_lines_and_controls_roundtrip_without_losing_bytes(self):
        store = ResponseStore()
        original = "条件：不能修改。🛠\n" * 1800 + "A" * 12000 + "\x00\t\r"
        raw = {"content": {"encoding": "utf-8", "sha256": hashlib.sha256(original.encode()).hexdigest(), "data": original},
               "snapshotId": "a" * 64, "file": "test.py", "layer": "worktree"}
        presented = store.present(raw)
        self.assertFalse(presented["presentation"]["complete"])
        self.assertLessEqual(len(encode(presented).encode()), INLINE_BYTES)
        offset, recovered = 0, ""
        while True:
            part = store.read(presented["presentation"]["responseId"], path="/content/data", offset=offset, limit=4096)
            self.assertLessEqual(len(encode(part).encode()), INLINE_BYTES)
            self.assertEqual(part["startLine"], original[:offset].count("\n") + 1)
            recovered += part["text"]
            if part["nextOffset"] is None:
                self.assertTrue(part["complete"])
                break
            self.assertGreater(part["nextOffset"], offset)
            offset = part["nextOffset"]
        self.assertEqual(original, recovered)
        self.assertEqual(part["sha256"], hashlib.sha256(recovered.encode()).hexdigest())

    def test_full_json_and_raw_rule_pointer_preserve_conditions_and_binding(self):
        store = ResponseStore()
        result = {"instructions": {"docs/regressions.md": "超过 10 秒才终止，未确认。\n" * 900},
                  "draft": "原稿", "proposalIntegrity": "p", "moduleDigest": "m", "modelExecution": "not_observed", "status": "loaded"}
        view = store.present(result);identifier = view["presentation"]["responseId"]
        self.assertEqual(view["rules"][0]["readPath"], "/instructions/docs~1regressions.md")
        first = store.read(identifier, path="/instructions/docs~1regressions.md")
        self.assertTrue(first["text"].startswith("超过 10 秒才终止，未确认。"))
        result["draft"] = "后来修改"
        self.assertEqual(store.read(identifier, path="/draft")["text"], "原稿")
        full, offset = "", 0
        while True:
            page = store.read(identifier, offset=offset)
            full += page["text"]
            if page["nextOffset"] is None:break
            offset = page["nextOffset"]
        self.assertEqual(json.loads(full)["draft"], "原稿")
        self.assertEqual(first["applicability"], "not_recomputed")

    def test_expiration_oversize_invalid_paths_and_empty_content_are_explicit(self):
        store = ResponseStore(capacity=25000, max_items=2)
        ids = [store.present({"text": str(i) * 7000})["presentation"]["responseId"] for i in range(3)]
        with self.assertRaises(FlowError) as expired:store.read(ids[0])
        self.assertEqual(expired.exception.code, "response_expired")
        for path in ("__class__", "/missing", "/~2", "/text/0"):
            with self.assertRaises(FlowError):store.read(ids[-1], path=path)
        for offset, limit in ((True, 1), (-1, 1), (0, 0), (0, 4097), (1000000, 2)):
            with self.assertRaises(FlowError):store.read(ids[-1], offset=offset, limit=limit)
        unavailable = store.present({"text": "x" * 30000})["presentation"]
        self.assertFalse(unavailable["complete"])
        self.assertIsNone(unavailable["read"])
        self.assertEqual(unavailable["unavailableReason"], "response_exceeds_cache_capacity")
        value = store.present({"padding": "x" * 7000, "empty": "", "array": ["value"]})
        identifier = value["presentation"]["responseId"]
        self.assertTrue(store.read(identifier, path="/empty")["complete"])
        self.assertEqual(store.read(identifier, path="/array/0")["text"], "value")
        for path in ("/array/-1", "/array/01", "/array/" + "9" * 1000):
            with self.assertRaises(FlowError):store.read(identifier, path=path)


from support import GitFixture
class DeliveryTests(GitFixture):
    session = copilot_helpers.CopilotTests.session
    call = copilot_helpers.CopilotTests.call

    def setUp(self):
        super().setUp()
        (self.root / ".gitignore").write_text(".engineering-flow/\n")

    @unittest.skipUnless(MCP_AVAILABLE, "需要 .[copilot]")
    def test_default_summary_read_and_stale_observation_share_core(self):
        async def scenario(client):
            result = await client.call_tool("flow_task", {"action": "start", "goal": "大目标" * 3000, "acceptance": ["原文不丢失"]})
            view = json.loads(result.content[0].text)
            self.assertFalse(result.is_error)
            self.assertLessEqual(len(result.content[0].text.encode()), INLINE_BYTES)
            identifier = view["presentation"]["responseId"];task_id = view["task"]["id"]
            read = await client.call_tool("flow_read", {"response_id": identifier, "path": "/snapshotComparison/status"})
            self.assertEqual(json.loads(read.content[0].text)["text"], "current")
            (self.root / "tracked.txt").write_text("changed\n")
            latest = await self.call(client, "task", "resume", task_id=task_id)
            self.assertEqual(latest["snapshotComparison"]["status"], "stale")
            old = await client.call_tool("flow_read", {"response_id": identifier, "path": "/snapshotComparison/status"})
            self.assertEqual(json.loads(old.content[0].text)["scope"], "captured_result_not_live")
            self.assertEqual(json.loads(old.content[0].text)["text"], "current")
            bad = await client.call_tool("flow_read", {"response_id": identifier, "path": "/task/confirmed"})
            self.assertTrue(bad.is_error)
        self.session(scenario)

    @unittest.skipUnless(MCP_AVAILABLE, "需要 .[copilot]")
    def test_failed_long_output_preserves_failure_and_complete_log_reference(self):
        config = {"schemaVersion": 1, "checks": [{"id": "long", "required": True,
            "argv": ["{python}", "-c", "import sys;print('FAIL_CONDITION' * 1500);sys.exit(9)"]}]}
        (self.root / ".engineering-flow.json").write_text(json.dumps(config))
        task = self.start()["task"]
        async def scenario(client):
            result = await client.call_tool("flow_check", {"action": "run", "task_id": task["id"], "check_id": "long"})
            value = json.loads(result.content[0].text)
            self.assertTrue(result.is_error)
            self.assertEqual(value["run"]["status"], "failed")
            self.assertEqual(value["run"]["exitCode"], 9)
            page = await client.call_tool("flow_read", {"response_id": value["presentation"]["responseId"], "path": "/run/stdout/data"})
            self.assertTrue(json.loads(page.content[0].text)["text"].startswith("FAIL_CONDITION"))
            self.assertFalse(self.cli("task", "resume", task["id"])["verification"]["requiredChecksPassed"])
        self.session(scenario)

    @unittest.skipUnless(MCP_AVAILABLE, "需要 .[copilot]")
    def test_plugin_inspection_detects_modified_assets_wrong_runtime_and_workspace(self):
        directory = Path(self.temp.name) / "plugin"
        self.cli("plugin", "build", "--output", str(directory))
        self.assertTrue(self.cli("plugin", "inspect", str(directory))["ready"])
        from engineering_flow.adapters.copilot import inspect_plugin
        from unittest.mock import patch
        with patch("engineering_flow.adapters.copilot.__version__", "0.0.0"):
            self.assertIn("runtime_mismatch", [i["code"] for i in inspect_plugin(self.root, directory)["issues"]])
        hook = directory / "com.github.copilot/hooks/hooks.json"
        hook.parent.mkdir()
        hook.write_text('{"hooks":{}}')
        self.assertIn("invalid_plugin", [i["code"] for i in inspect_plugin(self.root, directory)["issues"]])
        hook.unlink()
        other = Path(self.temp.name) / "worktree"
        self.git("worktree", "add", "--quiet", "-b", "other", str(other))
        self.assertIn("workspace_mismatch", [i["code"] for i in inspect_plugin(other, directory)["issues"]])
        (directory / "skills/verify-review/SKILL.md").write_text("corrupted")
        self.assertIn("invalid_plugin", [i["code"] for i in inspect_plugin(self.root, directory)["issues"]])

    def test_pinned_launcher_refuses_legacy_version_and_environment(self):
        from engineering_flow.core.workspace import inspect_workspace
        identity = inspect_workspace(self.root)
        for extra, error in ((["--expected-workspace-id", identity["workspaceId"]], "plugin_rebuild_required"),
                             (["--expected-version", "0.0.0"], "runtime_mismatch"),
                             (["--expected-environment", str(self.root)], "runtime_mismatch")):
            result = subprocess.run([sys.executable, "-m", "engineering_flow.adapters.mcp", "--workspace", str(self.root), *extra], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stderr)["error"]["code"], error)
            self.assertEqual(result.stdout, "")
        self.assertFalse(self.database.exists())

    def test_legacy_missing_and_symbolic_packages_are_diagnosed_without_execution(self):
        from engineering_flow.adapters.copilot import inspect_plugin
        directory = Path(self.temp.name) / "legacy"
        directory.mkdir()
        (directory / "binding.json").write_text('{"schemaVersion":1,"python":"/untrusted/never-execute"}')
        self.assertEqual(inspect_plugin(self.root, directory)["issues"][0]["code"], "legacy_binding")
        self.assertEqual(inspect_plugin(self.root, directory / "absent")["issues"][0]["code"], "invalid_plugin")
        linked = Path(self.temp.name) / "linked"
        linked.symlink_to(directory, target_is_directory=True)
        self.assertEqual(inspect_plugin(self.root, linked)["issues"][0]["code"], "invalid_plugin")
        self.assertFalse(self.database.exists())

    @unittest.skipUnless(MCP_AVAILABLE, "需要可选 SDK 元数据")
    def test_broken_sdk_is_unavailable_even_with_matching_version(self):
        from engineering_flow.core.diagnostics import diagnose
        from unittest.mock import patch
        import importlib
        original = importlib.import_module
        def fail_sdk(name, *args, **kwargs):
            if name == "mcp.server.lowlevel":raise ImportError("fixture")
            return original(name, *args, **kwargs)
        with patch("engineering_flow.core.diagnostics.importlib.import_module", side_effect=fail_sdk):
            result = diagnose(self.root)
        self.assertTrue(result["cliReady"])
        self.assertFalse(result["mcpReady"])
        self.assertEqual(result["mcp"]["importError"], "ImportError")
