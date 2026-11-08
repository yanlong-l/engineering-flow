"""仓库相对路径边界；拒绝把状态目录和 Git 元数据当输入。"""

from .errors import FlowError


def relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value or "\0" in value
            or any(part in ("", ".", "..", ".git") for part in value.split("/"))
            or value.split("/")[0] == ".engineering-flow"):
        raise FlowError("invalid_input", "输入必须是规范的仓库相对路径，且不能引用 Git 元数据或产品状态目录。")
    return value
