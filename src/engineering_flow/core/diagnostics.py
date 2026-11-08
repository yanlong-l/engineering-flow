"""只读程序观察；不运行项目命令或从本机安装推断宿主可用。"""

import importlib.metadata
import importlib
import platform
import sqlite3
import sys
from pathlib import Path

from engineering_flow import __version__
from .config import snapshot_config
from .errors import FlowError
from .snapshots import capture_snapshot
from .voice import load_module

MCP_VERSION = "2.3.0"


def diagnose(workspace: Path) -> dict:
    issues = []
    result = {"origin": "program_observation", "version": __version__,
              "runtime": {"python": platform.python_version(), "executable": sys.executable,
                          "platform": platform.platform(), "sqlite": sqlite3.sqlite_version},
              "host": {"pluginLoading": "not_observed", "toolInvocation": "not_observed",
                       "hooks": "not_enabled", "modelRewrite": "not_observed"},
              "fallback": "显式 CLI 支持保存、检查、Review、文档与交接；人工确认须操作者在独立终端运行。"}
    try:
        installed = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        installed = None
    importable, import_error = False, None
    if installed == MCP_VERSION:
        try:
            importlib.import_module("mcp.server.lowlevel")
            importable = True
        except Exception as exc:
            import_error = type(exc).__name__
    result["mcp"] = {"installed": installed, "required": MCP_VERSION, "importable": importable,
                     "available": installed == MCP_VERSION and importable, "importError": import_error}
    if not result["mcp"]["available"]:
        issues.append({"code": "mcp_unavailable", "message": "Copilot/MCP 需安装 engineering-flow[copilot]，固定 mcp==2.3.0；CLI 仍可使用。"})
    try:
        capture = capture_snapshot(workspace)
        config = snapshot_config(capture.document, capture.blobs)
        result["workspace"] = capture.workspace
        result["snapshotId"] = capture.document["id"]
        result["config"] = config
        result["checks"] = {"configured": [c["id"] for c in config["checks"]],
                            "required": [c["id"] for c in config["checks"] if c["required"]],
                            "execution": "not_run"}
        if not any(c["required"] for c in config["checks"]):
            issues.append({"code": "no_required_checks", "message": "未配置必需检查；不能产生全部必需检查已通过的结论。"})
    except FlowError as exc:
        issues.append({"code": exc.code, "message": str(exc)})
    module = load_module()
    # 诊断不把整个规则包复制到输出，loaded 也不等于宿主执行。
    result["voice"] = {k: module[k] for k in ("status", "module", "moduleDigest", "modelExecution", "reason") if k in module}
    if module["status"] != "loaded":
        issues.append({"code": "voice_unavailable", "message": "固定表达模块不可用；保留原技术草稿。"})
    result["issues"] = issues
    result["cliReady"] = "snapshotId" in result
    result["mcpReady"] = result["cliReady"] and result["mcp"]["available"]
    return result
