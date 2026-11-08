"""可选的本地 stdio MCP 适配器，无网络监听或人工确认工具。"""

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

from engineering_flow import __version__
from engineering_flow.core.diagnostics import MCP_VERSION
from engineering_flow.core.errors import FlowError
from engineering_flow.core.workspace import inspect_workspace


def create_server(workspace: Path, *, expected_project_id=None, expected_workspace_id=None):
    import anyio
    import jsonschema
    from mcp import types
    from mcp.server.lowlevel import Server
    from .operations import DESCRIPTIONS, OPERATIONS, dispatch, tool_schema
    from .responses import ResponseStore, encode

    # 启动后固定根目录，工具不能另传工作区，也不依赖宿主启动 cwd。
    binding = inspect_workspace(workspace)
    if ((expected_project_id is not None and binding["projectId"] != expected_project_id)
            or (expected_workspace_id is not None and binding["workspaceId"] != expected_workspace_id)):
        raise FlowError("workspace_mismatch", "插件绑定的项目或工作区身份已变化；请核对路径后重新生成插件。")
    root = Path(binding["root"])
    schemas = {"flow_" + group: tool_schema(group) for group in OPERATIONS}
    schemas["flow_read"] = {"type": "object", "properties": {
        "response_id": {"type": "string"}, "path": {"type": "string", "default": ""},
        "offset": {"type": "integer", "minimum": 0, "default": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 4096, "default": 2000}},
        "required": ["response_id"], "additionalProperties": False}
    responses = ResponseStore()
    lock = anyio.Lock()

    async def listing(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(
            name=name, description=("读取 presentation.responseId 对应的完整结果。path 是 JSON Pointer，如 /instructions/SKILL.md、/draft、/run/stdout/data；字符串按原文分页，无 JSON 转义长行。按 nextOffset 连续读取直到 null，offset 单位为 Unicode 字符。结果只属于当前 MCP 进程，重启/淘汰后按领域 ID 重新 show/resume，不要重试写操作。缓存是捕获时状态，不重新判断适用性。" if name == "flow_read" else DESCRIPTIONS[name.removeprefix("flow_")]), inputSchema=schema,
            annotations=types.ToolAnnotations(readOnlyHint=name in ("flow_snapshot", "flow_doctor", "flow_read"),
                                             openWorldHint=name == "flow_check"),
        ) for name, schema in schemas.items()])

    async def call(ctx, params):
        try:
            schema = schemas.get(params.name)
            if schema is None:
                raise FlowError("invalid_input", "未知工具；此服务没有人工确认或任意命令入口。")
            arguments = params.arguments or {}
            try:
                # 按 action 验证对应分支，保留具体字段错误，避免只返回整个 oneOf 不匹配。
                selected_action = arguments.get("action") if isinstance(arguments, dict) else None
                action_schema = OPERATIONS.get(params.name.removeprefix("flow_"), {}).get(selected_action) if isinstance(selected_action, str) else None
                chosen = ({**action_schema, "properties": {"action": {"const": arguments["action"]}, "view": schema["properties"]["view"], **action_schema["properties"]},
                           "required": ["action", *action_schema["required"]]} if action_schema else schema)
                jsonschema.Draft202012Validator(chosen).validate(arguments)
            except jsonschema.ValidationError as exc:
                location = "/" + "/".join(str(p) for p in exc.absolute_path)
                detail = exc.message if exc.validator in ("required", "additionalProperties") else f"不符合 {exc.validator} 约束"
                raise FlowError("invalid_input", f"工具参数 {location}：{detail}。请按对应 action 的 schema 传参。") from exc
            action = arguments.get("action")
            values = {k: v for k, v in arguments.items() if k not in ("action", "view")}
            # 单个服务串行操作。取消请求不丢弃已开始的真实结果；检查仍受 Core 超时约束。
            async with lock:
                with anyio.CancelScope(shield=True):
                    def invoke():
                        if importlib.metadata.version("engineering-flow") != __version__:
                            raise FlowError("runtime_changed", "运行时安装版本已变化，请停止并重新加载插件服务，勿继续旧会话写入。")
                        observed = inspect_workspace(root)
                        if any(observed[k] != binding[k] for k in ("projectId", "workspaceId")):
                            raise FlowError("workspace_mismatch", "运行中的插件绑定身份已变化，未执行操作。")
                        if params.name == "flow_read":
                            return responses.read(**values)
                        return dispatch(root, params.name.removeprefix("flow_"), action, values)
                    result = await anyio.to_thread.run_sync(invoke)
            failed = (params.name == "flow_check" and action == "run" and
                      (result["run"]["status"] != "passed" or result["applicability"] != "current"))
            # 一个可解析的 JSON 文本，避免 Copilot 把 text 和 structuredContent 重复展开。
            # 分行后，宿主将长结果落到临时文件时也能按实际行读取。
            presented = result if params.name == "flow_read" else responses.present(result, full=arguments.get("view") == "full")
            return types.CallToolResult(content=[types.TextContent(type="text", text=encode(presented))],
                                        isError=failed)
        except FlowError as exc:
            result = {"error": {"code": exc.code, "message": str(exc)}}
        except Exception:
            # 不把未捕获异常、库错误或内部路径堆栈伪装成产品成功。
            result = {"error": {"code": "adapter_error", "message": "MCP 适配器执行失败；请使用 CLI 核对已持久化状态，勿假定操作未发生。"}}
        return types.CallToolResult(content=[types.TextContent(type="text", text=encode(responses.present(result)))],
                                    isError=True)

    server = Server("Engineering Flow", version=__version__, on_list_tools=listing, on_call_tool=call,
                    instructions=f"Bound workspace: {root}. Use only for this workspace. No human confirmation tool. Hooks disabled; explicit checkpoint required. Default responses are bounded summaries when presentation.complete=false; use flow_read with response_id and JSON Pointer path, following nextOffset until null. Read strings as raw pages, not host temporary files. Cached results describe capture time; resume/show recomputes applicability.")
    server.middleware = []  # 不启用 SDK 默认 OTel；产品不采集完整对话或上传运行记录。
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Engineering Flow 本地 stdio MCP；固定工作区，不监听网络")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--expected-project-id")
    parser.add_argument("--expected-workspace-id")
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-environment")
    args = parser.parse_args(argv)
    try:
        if (args.expected_project_id or args.expected_workspace_id) and (not args.expected_version or not args.expected_environment):
            raise FlowError("plugin_rebuild_required", "旧插件缺少版本/环境绑定；请在正确运行时生成新目录并重新注册。")
        if args.expected_version and args.expected_version != __version__:
            raise FlowError("runtime_mismatch", "插件声明的产品版本与当前安装不同，请重新生成插件或恢复原运行时版本。")
        if args.expected_environment and Path(args.expected_environment).resolve() != Path(sys.prefix).resolve():
            raise FlowError("runtime_mismatch", "当前 Python 环境与插件绑定不同，请使用正确环境生成插件。")
        try:
            version = importlib.metadata.version("mcp")
        except importlib.metadata.PackageNotFoundError:
            version = None
        if version != MCP_VERSION:
            raise FlowError("mcp_unavailable", "请安装 engineering-flow[copilot]；MCP 仅支持 mcp==2.3.0，CLI 仍可独立使用。")
        import anyio
        from mcp.server.stdio import stdio_server
        server = create_server(args.workspace, expected_project_id=args.expected_project_id,
                               expected_workspace_id=args.expected_workspace_id)

        async def run():
            async with stdio_server() as (reader, writer):
                await server.run(reader, writer, server.create_initialization_options())
        anyio.run(run)
        return 0
    except FlowError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
