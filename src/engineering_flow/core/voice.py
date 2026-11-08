"""固定 Markdown Skill 的显式加载与保护区比较；不运行模型或推断语义等价。"""

import json
import re
from importlib.resources import files

from .snapshots import digest

MODULE_DIGEST = "a0f56221f40cbca76ea1a9bbd78970aeebcebbda89d6e06854f1c0dab6ba50e5"


def load_module() -> dict:
    try:
        root = files("engineering_flow").joinpath("resources/engineer_voice")
        manifest_raw = root.joinpath("manifest.json").read_bytes()
        if digest(manifest_raw) != MODULE_DIGEST:
            raise ValueError("pinned manifest integrity")
        manifest = json.loads(manifest_raw)
        contents = {}
        for path, expected in manifest["files"].items():
            raw = root.joinpath(path).read_bytes()
            if digest(raw) != expected:
                raise ValueError("module integrity")
            contents[path] = raw.decode("utf-8")
        if "MIT License" not in contents["LICENSE"]:
            raise ValueError("license")
        return {"status": "loaded", "module": manifest, "moduleDigest": MODULE_DIGEST,
                "instructions": contents, "modelExecution": "not_observed"}
    except (OSError, ValueError, KeyError, UnicodeError) as exc:
        return {"status": "unavailable", "module": None, "moduleDigest": None, "instructions": {},
                "modelExecution": "not_observed", "reason": str(exc), "fallback": "保留原技术草稿，未做 engineer-voice 改写。"}


def protected_parts(value: str) -> list[str]:
    """保守识别 Markdown 保护区；未知语法可通过 protectedFacts 显式锁定。"""
    parts, prose = [], []
    fence = None
    block = []
    for line in value.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            block.append(line)
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not line[match.end():].strip():
                parts.append("".join(block)); block = []; fence = None
        elif match:
            fence = match[1]; block = [line]
        elif line.lstrip().startswith(("|", ">", "$ ")) or line.startswith(("    ", "\t")):
            parts.append(line)
        else:
            prose.append(line)
    if block:
        parts.append("".join(block))
    # 行内代码、链接、数字（含单位）、中英文直接引语逐字保护。
    pattern = r"(`+)[^`\n]*?\1|https?://[^\s<>\])]+|\d+(?:[.:-]\d+)*(?:\s*(?:%|ms|seconds?\b|minutes?\b|hours?\b|days?\b|MiB|GiB|KiB|MB|GB|KB|MHz|GHz|Hz|秒|分钟|天|次|字节|小时))?|“[^”\n]*”|「[^」\n]*」|\"[^\"\n]*\""
    parts.extend(m[0] for m in re.finditer(pattern, "".join(prose)))
    return parts


def compare_protected(original: str, rewritten: str, facts: list[str]) -> list[str]:
    issues = []
    if protected_parts(original) != protected_parts(rewritten):
        issues.append("protected_content_changed")
    if any(original.count(fact) != rewritten.count(fact) for fact in facts):
        issues.append("protected_fact_changed")
    # 只作保守的风险筛选；相同词序也可能改变主体/对象，不推导语义等价。
    markers = r"未确认|尚未|未验证|未复测|不能|无法|不建议|建议|必须|禁止|可能|计划|已经|仅|只|最多|至少|超过|达到|如果|除非|否则|仍|继续|恢复|未完成|未变化|不重试|不可见|为主|全部|所有|默认"
    if re.findall(markers, original) != re.findall(markers, rewritten):
        issues.append("semantic_markers_changed")
    return issues
