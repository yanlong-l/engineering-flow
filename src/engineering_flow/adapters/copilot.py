"""按已安装运行时生成绑定单一工作区的本地 Agent Plugins 1.0 目录。"""

import json
import os
import shutil
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

from engineering_flow import __version__
from engineering_flow.core.diagnostics import diagnose
from engineering_flow.core.errors import FlowError
from engineering_flow.core.snapshots import canonical, digest
from engineering_flow.core.workspace import inspect_workspace


PACKAGE_FILES = ("plugin.json", "mcp.json", "com.github.copilot/agents/engineering-flow.agent.md",
                 "skills/document-handoff/SKILL.md", "skills/verify-review/SKILL.md")


def build_plugin(workspace: Path, destination: Path) -> dict:
    diagnostic = diagnose(workspace)
    if not diagnostic["mcpReady"]:
        raise FlowError("plugin_unavailable", "工作区或固定 MCP 依赖不可用；请先运行 doctor。")
    root = diagnostic["workspace"]
    destination = destination.absolute()
    temporary = None
    try:
        if destination.exists() or destination.is_symlink():
            raise OSError("目标已存在；请使用新目录，避免覆盖已注册插件")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".ef-plugin-", dir=destination.parent))

        def copy_resource(source, target):
            target.mkdir()
            for item in source.iterdir():
                if item.is_dir():
                    copy_resource(item, target / item.name)
                else:
                    data = item.read_bytes()
                    if item.name.endswith(".md"):
                        data = data.replace(b"@BOUND_WORKSPACE@", root["root"].encode("utf-8"))
                    (target / item.name).write_bytes(data)

        copy_resource(files("engineering_flow").joinpath("resources/copilot"), temporary / "package")
        package = temporary / "package"
        manifest = json.loads((package / "plugin.json").read_bytes())
        manifest["version"] = __version__.replace(".dev", "-dev.")
        (package / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n")
        config = {"mcpServers": {"engineering-flow": {
            "command": sys.executable,
            "args": ["-I", "-m", "engineering_flow.adapters.mcp", "--workspace", root["root"],
                     "--expected-project-id", root["projectId"], "--expected-workspace-id", root["workspaceId"],
                     "--expected-version", __version__, "--expected-environment", sys.prefix],
        }}}
        (package / "mcp.json").write_text(json.dumps(config, ensure_ascii=True, indent=2) + "\n")
        binding = {"schemaVersion": 2, "version": __version__, "python": sys.executable, "environment": sys.prefix,
                   **{key: root[key] for key in ("root", "projectId", "workspaceId")},
                   "hostValidation": "not_observed", "hooks": "not_enabled",
                   "files": {name: digest((package / name).read_bytes()) for name in PACKAGE_FILES}}
        binding["integrity"] = digest(canonical(binding))
        (package / "binding.json").write_text(json.dumps(binding, ensure_ascii=True, indent=2) + "\n")
        os.rename(package, destination)
        return {"directory": str(destination), "binding": binding,
                "next": "使用生成该包的 CLI 执行 plugin inspect PATH，再在 VS Code 的 Chat: Install Plugin from Source 选择目录；新建 Copilot 会话选择 Engineering Flow。",
                "limitations": ["插件绑定一个本机工作区及当前 Python 路径；移动/重建环境后须重新生成。",
                                "生成不等于宿主已装载或工具已调用；没有安装或修改 VS Code 设置。",
                                "不启用 Hooks，使用显式 checkpoint/check/review/handoff。"]}
    except (OSError, ValueError) as exc:
        raise FlowError("plugin_export", f"插件未生成：{exc}") from exc
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)


def inspect_plugin(workspace: Path, directory: Path) -> dict:
    """只读检查已生成包；不执行 mcp.json 中的命令，也不自动修复或注册。"""
    directory = directory.absolute()
    issues = []
    result = {"origin": "program_observation", "directory": str(directory), "ready": False,
              "hostValidation": "not_observed", "authentication": "not_provided", "issues": issues}
    try:
        if directory.is_symlink() or (directory / "binding.json").is_symlink():
            raise ValueError("插件目录及 binding.json 不能是符号链接")
        if (directory / "binding.json").stat().st_size > 65536:
            raise ValueError("binding.json 超出限制")
        binding = json.loads((directory / "binding.json").read_bytes())
        if binding.get("schemaVersion") == 1:
            result["binding"] = binding
            issues.append({"code": "legacy_binding", "message": "旧包没有运行时版本/环境与文件清单绑定，请使用正确 CLI 生成新目录。"})
            return result
        expected = {"schemaVersion", "version", "python", "environment", "root", "projectId", "workspaceId",
                    "hostValidation", "hooks", "files", "integrity"}
        if (set(binding) != expected or type(binding["schemaVersion"]) is not int or binding["schemaVersion"] != 2
                or binding["hostValidation"] != "not_observed" or binding["hooks"] != "not_enabled"
                or set(binding["files"]) != set(PACKAGE_FILES)
                or digest(canonical({k: v for k, v in binding.items() if k != "integrity"})) != binding["integrity"]):
            raise ValueError("绑定清单损坏或版本不支持")
        result["binding"] = binding
        expected_files = set(PACKAGE_FILES) | {"binding.json"}
        actual_files = set()
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError("插件目录不允许符号链接")
            if path.is_file():
                actual_files.add(path.relative_to(directory).as_posix())
        if actual_files != expected_files:
            raise ValueError("插件包含未声明或缺失的文件；Hooks/额外组件不能绕过生成清单")
        for name in PACKAGE_FILES:
            path = directory / name
            parents = path.relative_to(directory).parts
            current = directory
            for part in parents:
                current /= part
                if current.is_symlink():
                    raise ValueError("插件文件路径不允许符号链接")
            if path.stat().st_size > 1024 * 1024 or digest(path.read_bytes()) != binding["files"][name]:
                raise ValueError("插件文件与生成清单不一致：" + name)
        config = json.loads((directory / "mcp.json").read_bytes())
        expected_server = {"command": binding["python"], "args": ["-I", "-m", "engineering_flow.adapters.mcp",
            "--workspace", binding["root"], "--expected-project-id", binding["projectId"],
            "--expected-workspace-id", binding["workspaceId"], "--expected-version", binding["version"],
            "--expected-environment", binding["environment"]]}
        manifest = json.loads((directory / "plugin.json").read_bytes())
        if (config != {"mcpServers": {"engineering-flow": expected_server}}
                or manifest["name"] != "engineering-flow" or manifest["version"] != binding["version"].replace(".dev", "-dev.")):
            raise ValueError("MCP 启动参数或 manifest 与绑定不符")
        if not Path(binding["python"]).is_file() or not os.access(binding["python"], os.X_OK):
            issues.append({"code": "python_missing", "message": "绑定的 Python 不存在或不可执行；恢复原环境或生成新插件。"})
        if (binding["version"] != __version__ or Path(binding["environment"]).resolve() != Path(sys.prefix).resolve()
                or os.path.abspath(binding["python"]) != os.path.abspath(sys.executable)):
            issues.append({"code": "runtime_mismatch", "message": "当前 CLI 不是生成该插件的版本或 Python 环境；使用正确 CLI 核对，升级后需生成新目录。"})
        observed = inspect_workspace(workspace)
        if (binding["root"] != observed["root"] or any(binding[k] != observed[k] for k in ("projectId", "workspaceId"))):
            issues.append({"code": "workspace_mismatch", "message": "当前工作区与插件绑定不同；不要在错误窗口使用该包。"})
        diagnostic = diagnose(workspace)
        result["runtime"] = diagnostic["runtime"]
        result["mcp"] = diagnostic["mcp"]
        if not diagnostic["mcpReady"]:
            issues.append({"code": "mcp_unavailable", "message": "当前环境或配置不能使用 MCP，请运行 doctor。"})
        result["ready"] = not issues
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        issues.append({"code": "invalid_plugin", "message": f"无法核对插件：{exc}"})
        return result
    except FlowError as exc:
        issues.append({"code": exc.code, "message": str(exc)})
        return result
