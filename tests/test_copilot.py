"""独立 stdio SDK 客户端与 CLI 交叉验证；不将模拟客户端称为 Copilot。"""

import asyncio
import importlib.metadata
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from support import GitFixture
from engineering_flow.core.diagnostics import diagnose
from engineering_flow.core.workspace import inspect_workspace

try:
    MCP_AVAILABLE = importlib.metadata.version("mcp") == "2.3.0"
except importlib.metadata.PackageNotFoundError:
    MCP_AVAILABLE = False


class DiagnosticsTests(GitFixture):
    def test_diagnostic_does_not_execute_or_create_state_or_claim_host(self):
        result = self.cli("doctor")
        self.assertTrue(result["cliReady"])
        self.assertEqual(result["checks"]["execution"], "not_run")
        self.assertEqual(result["host"]["pluginLoading"], "not_observed")
        self.assertEqual(result["host"]["hooks"], "not_enabled")
        self.assertEqual(result["voice"]["modelExecution"], "not_observed")
        self.assertIn("no_required_checks", [i["code"] for i in result["issues"]])
        self.assertFalse(self.database.exists())

    def test_missing_sdk_preserves_cli_and_plugin_does_not_claim_ready(self):
        with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
            result = diagnose(self.root)
        self.assertTrue(result["cliReady"])
        self.assertFalse(result["mcpReady"])
        self.assertIn("mcp_unavailable", [i["code"] for i in result["issues"]])
        result = self.start()
        self.assertEqual(result["task"]["revision"], 1)

    def test_invalid_configuration_and_missing_inputs_are_diagnosed(self):
        (self.root / ".engineering-flow.json").write_text('{"schemaVersion":1,"checks":[{"id":"fake","required":false,"argv":[]}]}')
        result = diagnose(self.root)
        self.assertFalse(result["cliReady"])
        self.assertIn("invalid_config", [i["code"] for i in result["issues"]])
        self.assertFalse(self.database.exists())
        (self.root / ".engineering-flow.json").write_text('{"schemaVersion":1,"additionalInputs":["absent"]}')
        self.assertIn("missing_input", [i["code"] for i in diagnose(self.root)["issues"]])


@unittest.skipUnless(MCP_AVAILABLE, "安装 .[copilot] 后运行真实 stdio 集成测试")
class CopilotTests(GitFixture):
    def setUp(self):
        super().setUp()
        (self.root / ".gitignore").write_text('.engineering-flow/\n')
        (self.root / ".engineering-flow.json").write_text(json.dumps({"schemaVersion": 1, "checks": [
            {"id": "required", "required": True, "argv": ["{python}", "-c", "print('ACTUAL_CHECK')"]},
            {"id": "failure", "required": False, "argv": ["{python}", "-c", "import sys;print('ACTUAL_FAILURE');sys.exit(7)"]},
            {"id": "missing", "required": False, "argv": ["ef-this-command-does-not-exist"]},
        ]}))

    def session(self, callback, *, root=None, extra=()):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def run():
            with (Path(self.temp.name) / "mcp-stderr.txt").open("w+") as errors:
                async with stdio_client(StdioServerParameters(command=sys.executable, args=[
                    "-m", "engineering_flow.adapters.mcp", "--workspace", str(root or self.root), *extra],
                    cwd=self.temp.name), errlog=errors) as (reader, writer):
                    async with ClientSession(reader, writer) as client:
                        await client.initialize()
                        return await callback(client)
        return asyncio.run(run())

    async def call(self, client, group, action, *, error=False, **args):
        result = await client.call_tool("flow_" + group, {"action": action, "view": "full", **args})
        content = json.loads(result.content[0].text)
        self.assertEqual(result.is_error, error, content)
        self.assertIsNone(result.structured_content)
        return content

    def test_stdio_discovery_strict_parameters_and_no_confirmation_tool(self):
        async def scenario(client):
            tools = (await client.list_tools()).tools
            self.assertEqual({t.name for t in tools}, {"flow_" + g for g in ("task", "check", "review", "memory", "document", "snapshot", "doctor", "read")})
            for tool in tools:
                self.assertNotIn('"oneOf"', json.dumps(tool.input_schema))
            task_tool = next(t for t in tools if t.name == "flow_task")
            self.assertEqual(task_tool.input_schema["properties"]["action"]["enum"], ["start", "resume", "checkpoint", "handoff"])
            for group, action, args in [
                ("task", "start", {"goal": "x", "acceptance": ["y"], "confirmed": True}),
                ("task", "start", {"goal": "x", "acceptance": ["y"], "workspace": str(self.root)}),
                ("task", "checkpoint", {"task_id": "0" * 32, "expected_revision": True, "progress": "x"}),
                ("review", "confirm", {"opinion_id": "0" * 32}),
                ("check", "run", {"task_id": "0" * 32, "check_id": "required", "argv": ["echo", "fake"]}),
                ("doctor", "inspect", {"actor": "human"}),
                ("doctor", [], {}),
            ]:
                result = await self.call(client, group, action, error=True, **args)
                self.assertEqual(result["error"]["code"], "invalid_input")
            result = await client.call_tool("flow_confirm", {})
            self.assertTrue(result.is_error)
            invalid = await self.call(client, "document", "propose", error=True, task_id="0" * 32,
                proposal={"target": "NOTES.md", "mode": "generated", "draft": "candidate", "reason": "fixture", "sources": [
                    {"kind": "code", "file": "tracked.txt", "layer": "worktree", "startLine": 1, "endLine": 1}], "protectedFacts": []})
            self.assertIn("/proposal", invalid["error"]["message"])
            self.assertIn("region", invalid["error"]["message"])
            self.assertFalse(self.database.exists())
        self.session(scenario)

    def test_cli_and_mcp_share_revision_snapshot_and_stale_results(self):
        initial = self.start()["task"]
        async def scenario(client):
            result = await self.call(client, "task", "resume", task_id=initial["id"])
            self.assertEqual(result["task"], initial)
            updated = await self.call(client, "task", "checkpoint", task_id=initial["id"], expected_revision=1, progress="MCP 保存")
            self.assertEqual(updated["task"], self.cli("task", "resume", initial["id"])["task"])
            conflict = await self.call(client, "task", "checkpoint", error=True, task_id=initial["id"], expected_revision=1, progress="冲突")
            self.assertEqual(conflict["error"]["code"], "revision_conflict")
            run = await self.call(client, "check", "run", task_id=initial["id"], check_id="required")
            self.assertEqual(run["run"]["stdout"]["data"], "ACTUAL_CHECK\n")
            review = await self.call(client, "review", "build", task_id=initial["id"])
            (self.root / "tracked.txt").write_text("changed without commit\n")
            shown = await self.call(client, "check", "show", run_id=run["run"]["id"])
            self.assertEqual(shown["applicability"], "stale")
            resumed = self.cli("task", "resume", initial["id"])
            self.assertFalse(resumed["verification"]["requiredChecksPassed"])
            old = await self.call(client, "snapshot", "show", snapshot_id=initial["startingWorkspace"]["snapshotId"], file="tracked.txt")
            self.assertEqual(old["content"]["data"], "baseline\n")
            self.assertTrue(Path(review["directory"], "review.html").is_file())
        self.session(scenario)

    def test_actual_failure_error_and_skip_never_satisfy_required(self):
        async def scenario(client):
            task = (await self.call(client, "task", "start", goal="检查", acceptance=["真实结果"]))["task"]
            for check_id, status in (("failure", "failed"), ("missing", "error")):
                run = await self.call(client, "check", "run", error=True, task_id=task["id"], check_id=check_id)
                self.assertEqual(run["run"]["status"], status)
            await self.call(client, "check", "run", task_id=task["id"], check_id="required")
            skip = await self.call(client, "check", "skip", task_id=task["id"], check_id="required", reason="显式未执行")
            self.assertEqual(skip["run"]["status"], "skipped")
            result = await self.call(client, "task", "resume", task_id=task["id"])
            self.assertFalse(result["verification"]["requiredChecksPassed"])
            self.assertTrue(result["verification"]["checks"][0]["check"]["required"])
        self.session(scenario)

    def test_document_voice_rewrite_review_opinion_memory_and_handoff_remain_candidates(self):
        async def scenario(client):
            task = (await self.call(client, "task", "start", goal="文档", acceptance=["建议可追溯"]))["task"]
            source = {"kind": "code", "file": "tracked.txt", "layer": "worktree", "startLine": 1, "endLine": 1}
            proposal = {"target": "NOTES.md", "mode": "generated", "region": None,
                        "draft": "构造草稿：超过 10 秒后终止。仍需 Review。\n", "reason": "构造验收", "sources": [source], "protectedFacts": []}
            document = (await self.call(client, "document", "propose", task_id=task["id"], proposal=proposal))["document"]
            voice = await self.call(client, "document", "voice", document_id=document["id"])
            self.assertEqual(voice["status"], "loaded")
            self.assertEqual(voice["modelExecution"], "not_observed")
            rewrite = await self.call(client, "document", "rewrite", document_id=document["id"], content={
                "proposalIntegrity": voice["proposalIntegrity"], "moduleDigest": voice["moduleDigest"], "rewritten": "超过 11 秒后终止。仍需 Review。\n"})
            self.assertEqual(rewrite["document"]["voice"]["status"], "rejected")
            self.assertEqual(rewrite["document"]["after"], document["after"])
            review = await self.call(client, "review", "build", task_id=task["id"])
            review_id = review["review"]["id"]
            opinion = await self.call(client, "review", "record", review_id=review_id, decision="approve", comment="只是调用者意见", document_ids=[document["id"]])
            await self.call(client, "review", "explain", review_id=review_id, content={"summary": "AI 解释", "behaviors": [
                {"title": "构造行为", "description": "保留快照来源", "acceptanceCriteria": [1],
                 "references": [{k: v for k, v in source.items() if k != "kind"}]}]})
            memory = await self.call(client, "memory", "propose", task_id=task["id"], proposal={"content": "候选事实", "kind": "limitation", "scope": {"kind": "project", "paths": [], "modules": []}, "keywords": [], "sources": [source]})
            await self.call(client, "memory", "show", memory_id=memory["memory"]["id"])
            await self.call(client, "memory", "context", task_id=task["id"])
            await self.call(client, "memory", "relate", memory_id=memory["memory"]["id"], relation="archive", reason="测试归档")
            await self.call(client, "document", "export", document_id=document["id"])
            final = await self.call(client, "task", "handoff", task_id=task["id"])
            self.assertTrue(Path(final["directory"], "handoff.md").is_file())
            current = await self.call(client, "document", "show", document_id=document["id"])
            self.assertEqual(current["state"]["confirmationStatus"], "proposed")
            self.assertFalse((self.root / "NOTES.md").exists())
        self.session(scenario)

    def test_branch_and_worktree_mismatch_use_core_rules(self):
        task = self.start()["task"]
        async def scenario(client):
            self.git("switch", "--quiet", "-c", "other")
            error = await self.call(client, "task", "resume", task_id=task["id"], error=True)
            self.assertEqual(error["error"]["code"], "workspace_mismatch")
        self.session(scenario)
        from engineering_flow.adapters.mcp import create_server
        from engineering_flow.core.errors import FlowError
        with self.assertRaises(FlowError) as raised:
            create_server(self.root, expected_workspace_id="0" * 64)
        self.assertEqual(raised.exception.code, "workspace_mismatch")

    def test_cancelled_mcp_request_preserves_eventual_real_result(self):
        config = json.loads((self.root / ".engineering-flow.json").read_bytes())
        config["checks"] = [{"id": "bounded", "required": True, "timeoutSeconds": 3,
                             "argv": ["{python}", "-c", "import time;time.sleep(0.8);print('FINISHED_AFTER_CANCEL')"]}]
        (self.root / ".engineering-flow.json").write_text(json.dumps(config))
        task = self.start()["task"]

        async def scenario(client):
            request = asyncio.create_task(client.call_tool("flow_check", {"action": "run", "task_id": task["id"], "check_id": "bounded"}))
            running_id = None
            for _ in range(30):
                resumed = await asyncio.to_thread(self.cli, "task", "resume", task["id"])
                history = resumed["verification"]["history"]
                if history:
                    self.assertEqual(history[0]["status"], "running")
                    running_id = history[0]["runId"]
                    break
                await asyncio.sleep(0.02)
            self.assertIsNotNone(running_id)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            # MCP 会话仍能响应，正在执行的 Core 在有界时间内保存真实终态。
            await client.send_ping()
            for _ in range(30):
                shown = await asyncio.to_thread(self.cli, "check", "show", running_id)
                if shown["run"]["status"] != "running":
                    break
                await asyncio.sleep(0.05)
            self.assertEqual(shown["run"]["status"], "passed")
            self.assertEqual(shown["run"]["stdout"]["data"], "FINISHED_AFTER_CANCEL\n")
        self.session(scenario)

    def test_worktree_cannot_reuse_original_binding(self):
        other = Path(self.temp.name) / "other-worktree"
        self.git("worktree", "add", "--quiet", "-b", "other", str(other))
        from engineering_flow.adapters.mcp import create_server
        from engineering_flow.core.errors import FlowError
        binding = inspect_workspace(self.root)
        with self.assertRaises(FlowError) as raised:
            create_server(other, expected_project_id=binding["projectId"], expected_workspace_id=binding["workspaceId"])
        self.assertEqual(raised.exception.code, "workspace_mismatch")

    def test_plugin_export_binds_paths_preserves_existing_and_has_no_hooks(self):
        # 空格与中文路径通过 argv 数组保留，不依赖启动 cwd。
        target = Path(self.temp.name) / "插件 space"
        result = self.cli("plugin", "build", "--output", str(target))
        config = json.loads((target / "mcp.json").read_bytes())["mcpServers"]["engineering-flow"]
        self.assertEqual(config["command"], sys.executable)
        self.assertIn(str(self.root.resolve()), config["args"])
        self.assertIn(inspect_workspace(self.root)["workspaceId"], config["args"])
        self.assertEqual(result["binding"]["hostValidation"], "not_observed")
        self.assertFalse((target / "com.github.copilot/hooks").exists())
        agent = (target / "com.github.copilot/agents/engineering-flow.agent.md").read_text()
        self.assertIn(str(self.root.resolve()), agent)
        self.assertNotIn("@BOUND_WORKSPACE@", agent)
        before = (target / "mcp.json").read_bytes()
        self.assertEqual(self.cli("plugin", "build", "--output", str(target), code=1)["code"], "plugin_export")
        self.assertEqual((target / "mcp.json").read_bytes(), before)
