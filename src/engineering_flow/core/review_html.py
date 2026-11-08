"""固定、无脚本的本地 HTML；所有动态文本转义，链接只指向已验证的内部锚点。"""

import base64
import html
import json

from .evidence import output_bytes, snapshot_references
from .snapshots import digest

STYLE = """
:root{color-scheme:light;--ink:#182332;--muted:#5e6b7a;--line:#dce3eb;--blue:#1856a5;--bg:#f3f6fa}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
a{color:var(--blue);text-underline-offset:3px}a:focus-visible,summary:focus-visible{outline:3px solid #edac31;outline-offset:4px}
header{background:#142b43;color:#fff;padding:30px max(28px,calc((100% - 1300px)/2));border-bottom:5px solid #41b5ad}.brand{font-size:13px;letter-spacing:.1em;color:#a8dedd}h1{font-size:28px;line-height:1.35;margin:10px 0 14px;font-weight:650}h2{font-size:21px;margin:0 0 18px}h3{font-size:17px;margin:20px 0 10px}.meta{color:#c3d3e1;font-size:13px;overflow-wrap:anywhere}
.layout{max-width:1360px;margin:auto;padding:28px;display:grid;grid-template-columns:180px minmax(0,1fr);gap:28px}nav{position:sticky;top:24px;align-self:start}nav a{display:block;padding:10px 14px;text-decoration:none;border-left:2px solid var(--line);color:var(--muted)}nav a:hover{border-color:var(--blue);color:var(--blue);background:white}
main{min-width:0}section{background:white;border:1px solid var(--line);border-radius:10px;padding:26px;margin-bottom:22px;scroll-margin-top:24px}.notice{padding:15px 18px;border-left:4px solid #b67c16;background:#fff7e6;border-radius:5px;margin-bottom:22px}.muted{color:var(--muted)}.small{font-size:13px}.text{white-space:pre-wrap;overflow-wrap:anywhere}.source{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}.pill{display:inline-block;font-size:12px;line-height:1.7;font-weight:650;border:1px solid #ced7e4;border-radius:5px;padding:2px 8px;background:#eef2f6;color:#4a586b;margin:2px 4px 2px 0}.passed,.current{color:#186347;background:#edf8f1;border-color:#c0deca}.failed,.error,.invalid{color:#a43131;background:#fff0ef;border-color:#edc3bf}.stale,.skipped{color:#825a0b;background:#fff5dc;border-color:#ead5a1}.not_run,.unknown,.running{color:#566376;background:#eef1f6}
.check,.event,.behavior{border:1px solid var(--line);border-radius:7px;padding:17px;margin:13px 0}.check-head{display:flex;gap:12px;justify-content:space-between;align-items:baseline;flex-wrap:wrap}.check h3{margin:0}.facts{display:grid;grid-template-columns:120px minmax(0,1fr);gap:5px 12px;font-size:13px;margin:16px 0}.facts dt{color:var(--muted)}.facts dd{margin:0;overflow-wrap:anywhere}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86em;overflow-wrap:anywhere}
pre{background:#f6f8fb;border:1px solid var(--line);border-radius:5px;padding:14px;overflow:auto;max-height:480px;font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;tab-size:4}pre.code{padding:10px 0;counter-reset:line}.code .line{display:block;min-height:1.65em;padding:0 16px 0 64px;position:relative;white-space:pre}.line:before{content:attr(data-line);position:absolute;left:0;width:48px;text-align:right;color:#778598;user-select:none}.line:target{background:#fff0ba;outline:1px solid #e4c36a}summary{cursor:pointer;overflow-wrap:anywhere;font-weight:550;padding:10px 0}details{border-top:1px solid var(--line);margin-top:10px}.snapshot-id{font:12px ui-monospace,monospace;overflow-wrap:anywhere}.links a{margin-right:12px}.empty{padding:16px;background:#f6f8fb;border-radius:6px;color:var(--muted)}ul{padding-left:22px}.invalid-ref{display:block;color:#a43131;margin:8px 0}.scope{color:#5e6b7a;font-size:13px}.footer{font-size:12px;color:var(--muted);padding:8px 0 28px}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:9px;border-bottom:1px solid var(--line)}
@media(max-width:800px){.layout{display:block;padding:16px}nav{position:static;display:flex;overflow:auto;margin-bottom:18px}nav a{white-space:nowrap;padding:8px 12px}header{padding:22px}h1{font-size:23px}section{padding:18px}.facts{grid-template-columns:90px 1fr}}
"""
LABELS = {"passed": "已通过", "failed": "失败", "error": "执行错误", "not_run": "未运行", "skipped": "已跳过", "stale": "已过期", "current": "生成时适用", "unknown": "适用性未知", "running": "运行中"}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def badge(value: str) -> str:
    return f'<span class="pill {esc(value)}">{esc(LABELS.get(value, value))}</span>'


def raw_text(data: bytes) -> str:
    try:
        value = data.decode("utf-8")
        return "".join(c if c in "\n\t" or ord(c) >= 32 else f"\\x{ord(c):02x}" for c in value)
    except UnicodeDecodeError:
        return "二进制内容（base64）：\n" + base64.b64encode(data).decode("ascii")


def file_anchor(snapshot_id: str, file: str, layer: str) -> str:
    return f"s-{snapshot_id}-f-{digest(file.encode('utf-8'))}-{layer}"


def reference_link(reference: dict, snapshot_id: str, snapshots: dict) -> str:
    snapshot, blobs = snapshots[snapshot_id]
    entry = next((e for e in snapshot["files"] if e["path"] == reference["file"]), None)
    value = entry[reference["layer"]] if entry else None
    label = f"{reference['file']} · {reference['layer']}:{reference['startLine']}–{reference['endLine']}"
    reason = None
    if value is None or "blob" not in value:
        reason = "文件或指定内容层不存在"
    else:
        try:
            lines = blobs[value["blob"]].decode("utf-8").splitlines()
            if reference["endLine"] > len(lines):
                reason = "行号超出该快照实际内容"
        except UnicodeDecodeError:
            reason = "二进制内容没有文本行号"
    if reason:
        return f'<span class="invalid-ref">引用失效：{esc(label)}（{esc(reason)}）；未替换为其他位置。</span>'
    target = file_anchor(snapshot_id, reference["file"], reference["layer"]) + f"-L{reference['startLine']}"
    return f'<a href="#{target}">{esc(label)}</a>'


def render_review(record: dict, store) -> str:
    snapshots = {ref: store.load_snapshot(ref) for ref in sorted(snapshot_references(record, "reviews"))}
    task = record["task"]
    feedback = record.get("reviewFeedback", {"records": [], "states": [], "confirmedScopes": []})
    states = {s["eventId"]: s["applicability"] for s in feedback["states"]}
    out = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
           '<meta name="referrer" content="no-referrer"><title>Engineering Flow · Review</title>', f'<style>{STYLE}</style></head><body>',
           f'<header><div class="brand">ENGINEERING FLOW / REVIEW</div><h1>{esc(task["goal"])}</h1>',
           f'<div class="meta">生成时间 {esc(record["createdAt"])} · 任务修订 {task["revision"]}<br>快照 {record["snapshotId"]}</div></header>',
           '<div class="layout"><nav aria-label="Review 导航"><a href="#overview">需求与范围</a><a href="#behavior">行为与阅读路线</a><a href="#checks">检查结果</a><a href="#feedback">评审与确认</a><a href="#documents">文档与交接</a><a href="#code">代码与 diff</a><a href="#limitations">限制与交接</a></nav><main>',
           '<div class="notice" role="note"><strong>生成时快照 · 静态材料</strong><br>本页不实时监测代码或新评审。修改后用 <code>review show</code> 查询适用性，<code>review build</code> 生成新页面；旧页保留历史内容。</div>',
           '<section id="overview"><div class="source">调用者输入 / 需求</div><h2>需求与范围</h2><ol>']
    out += [f'<li class="text">{esc(c)}</li>' for c in task["acceptanceCriteria"]]
    out += ['</ol><h3>进度与待判断事项</h3>', f'<p class="text">{esc(task["progress"] or "未记录进度。")}</p><ul>']
    out += [f'<li class="text">{esc(c)}</li>' for c in task["unresolvedIssues"]] or ['<li>未记录未决事项；不代表不存在风险。</li>']
    out += ['</ul><p class="muted small">启动前已有改动与后续内容分别保留。文件关联只表达任务范围，修改作者保持未知。</p></section>',
            '<section id="behavior"><div class="source">AI 解释 / 未经人工确认</div><h2>行为与阅读路线</h2>']
    explanation = record.get("aiExplanation")
    relevant = set(task.get("relatedFiles", [])) | {c["path"] for c in record["changesSinceStart"]["changes"]}
    documents = record.get("documents", {"records": [], "states": []})
    for document in documents["records"]:
        relevant.add(document["proposal"]["target"])
        relevant.update(s["file"] for s in document["proposal"]["sources"] if s["kind"] == "code")
    for event in feedback["records"]:
        if event["eventType"] == "explanation":
            for behavior in event["content"]["behaviors"]:
                relevant.update(r["file"] for r in behavior["references"])
        else:
            relevant.update(event["scope"]["files"])
    if explanation:
        out += [badge(states[explanation["id"]]), f'<p class="text">{esc(explanation["content"]["summary"])}</p>']
        for behavior in explanation["content"]["behaviors"]:
            out += [f'<article class="behavior"><h3>{esc(behavior["title"])}</h3><p class="scope">验收条件 {esc(", ".join(map(str, behavior["acceptanceCriteria"])))}</p>',
                    f'<p class="text">{esc(behavior["description"])}</p><p class="snapshot-id">解释绑定快照 {explanation["snapshotId"]}</p><ol>']
            out += [f'<li>{reference_link(ref, explanation["snapshotId"], snapshots)}</li>' for ref in behavior["references"]]
            out += ['</ol></article>']
    else:
        out += ['<p class="empty">尚未提供 AI 行为解释。下方代码、diff 和检查结果来自程序观察。</p>']
    out += ['</section><section id="checks"><div class="source">程序观察 / 检查证据</div><h2>检查结果</h2>',
            '<p>必需检查均满足：<strong>' + ('是（生成时）' if record["verification"]["requiredChecksPassed"] else '否') + '</strong>。自动检查与人工评审分别记录。</p>']
    runs = {r["id"]: r for r in record["runs"]}
    for item in record["verification"]["checks"]:
        definition = item["check"]
        run = runs.get(item["runId"])
        out += [f'<article class="check"><div class="check-head"><h3>{esc(definition["id"])}</h3><div>{badge(item["status"])}{badge(item["applicability"])}</div></div>',
                f'<p class="scope">{"必需检查" if definition["required"] else "可选检查"} · 项目配置保留</p>']
        if run:
            out += [f'<p class="small">运行 <a href="#run-{run["id"]}">{run["id"]}</a> · 历史状态 {esc(run["status"])}</p>']
            if run["status"] == "skipped":
                out += [f'<p class="text">跳过原因（调用者输入）：{esc(run["reason"])}</p><p>命令没有执行；跳过不满足必需项。</p>']
        else:
            out += ['<p class="muted">没有实际运行记录，不能以解释或进度替代。</p>']
        out += [f'<details><summary>项目配置的 argv</summary><pre>{esc(json.dumps(definition["argv"], ensure_ascii=False))}</pre></details></article>']
    if not record["verification"]["checks"]:
        out += ['<p class="empty">未配置检查，没有可核验的通过结论。</p>']
    out += ['<h3>全部运行记录</h3>']
    for state in record["verification"]["history"]:
        run = runs[state["runId"]]
        out += [f'<details id="run-{run["id"]}"><summary>{esc(run["check"]["id"])} · {esc(LABELS[run["status"]])} / {esc(LABELS[state["applicability"]])}</summary>',
                f'<p>{badge(run["status"])}{badge(state["applicability"])}</p><dl class="facts">']
        for label, value in (("运行 ID", run["id"]), ("开始 / 结束", f'{run["startedAt"]} / {run["endedAt"]}'), ("执行模式", run["executionMode"]),
                             ("实际 argv", json.dumps(run["argv"], ensure_ascii=False)), ("工作目录", run["cwd"]), ("退出码", run["exitCode"])):
            out += [f'<dt>{label}</dt><dd>{esc(value)}</dd>']
        for label, ref in (("执行前快照", run["snapshotId"]), ("执行后快照", run["snapshotAfterId"])):
            out += [f'<dt>{label}</dt><dd>' + (f'<a href="#snapshot-{ref}">{ref}</a>' if ref else '缺失，适用性未知') + '</dd>']
        out += ['</dl>']
        if run.get("reason"):
            out += [f'<p class="text">跳过原因：{esc(run["reason"])}</p>']
        if run["failure"]:
            out += [f'<pre>{esc(json.dumps(run["failure"], ensure_ascii=False, indent=2))}</pre>']
        for stream in ("stdout", "stderr"):
            value = run[stream]
            out += [f'<h4>{stream} · {value["size"]} bytes{" · 已截断" if value["truncated"] else ""}</h4>',
                    f'<p class="snapshot-id">SHA-256 {value["sha256"]}</p><pre>{esc(raw_text(output_bytes(value)) or "（空）")}</pre>']
        out += ['</details>']
    out += ['</section><section id="feedback"><div class="source">调用者意见 / 本地终端确认</div><h2>评审与确认</h2>',
            '<p class="muted small">意见与确认分开保存。确认仅覆盖列出的范围，不替代检查；终端账号与交互来源不构成身份认证。</p>']
    opinions = [e for e in feedback["records"] if e["eventType"] != "explanation"]
    for event in opinions:
        confirmed = event["eventType"] == "confirmation"
        scope = event["scope"]
        label = ("整个任务" if scope["kind"] == "task" else
                 "文档建议：" + ", ".join(d["id"] for d in scope["documents"]) if scope["kind"] == "documents" else
                 "记忆：" + ", ".join(m["id"] for m in scope["memories"]) if scope["kind"] == "memories" else ", ".join(scope["files"]))
        out += [f'<article class="event"><strong>{"终端确认记录" if confirmed else "调用者意见 · 尚未确认"}</strong> {badge(states[event["id"]])}',
                f'<p class="scope">范围：{esc(label)} · 决定：{esc(event["decision"])}</p>',
                f'<p class="text">{esc(event["comment"])}</p><p class="snapshot-id">{event["snapshotId"]} · 任务修订 {event["taskRevision"]}</p>']
        if scope["kind"] == "memories":
            out += [f'<pre>{esc(json.dumps(scope["memories"], ensure_ascii=False, indent=2))}</pre>']
        if scope["kind"] == "documents":
            out += [f'<pre>{esc(json.dumps(scope["documents"], ensure_ascii=False, indent=2))}</pre>']
        if confirmed:
            actor = event["actor"]
            state = next(s for s in feedback["states"] if s["eventId"] == event["id"])
            effective = state.get("effective", False)
            out += [f'<p class="scope">{"当前范围记录" if effective else "历史记录：已过期或被后续同范围确认替代"}</p>']
            if scope["kind"] == "memories":
                out += [f'<p class="scope">当前有效的记忆确认：{esc(", ".join(state.get("effectiveMemoryIds", [])) or "无")}</p>']
            if scope["kind"] == "documents":
                out += [f'<p class="scope">当前有效的文档建议确认：{esc(", ".join(state.get("effectiveDocumentIds", [])) or "无")}</p>']
            out += [f'<p class="small">本机账号 {esc(actor["account"])} (uid={actor["uid"]}) · {esc(actor["tty"])} · {esc(event["createdAt"])}</p>']
        out += ['</article>']
    if not opinions:
        out += ['<p class="empty">未记录评审意见或终端确认。</p>']
    out += ['</section><section id="documents"><div class="source">调用者候选 / 文档维护</div><h2>文档修改建议与交接</h2>',
            '<p>建议未写入工作区。保护内容检查不能证明语义等价；批准建议不替代应用后快照上的检查与评审。</p>']
    document_states = {s["id"]: s for s in documents["states"]}
    for document in documents["records"]:
        proposal, state = document["proposal"], document_states[document["id"]]
        out += [f'<article id="document-{document["id"]}"><h3>{esc(proposal["target"])} · {esc(proposal["mode"])}</h3>',
                f'<p>{esc(state["confirmationStatus"])} / {esc(state["applicability"])} · engineer-voice：{esc(document["voice"]["status"])}</p>',
                f'<p class="text">{esc(proposal["reason"])}</p><p class="snapshot-id">{document["snapshotId"]} · 任务修订 {document["taskRevision"]}</p>',
                f'<details><summary>修改建议 diff</summary><pre>{esc(document["patch"])}</pre></details>',
                f'<details><summary>完整原文、技术草稿、改写与来源</summary><pre>{esc(json.dumps(document, ensure_ascii=False, indent=2))}</pre></details><ul>']
        for source in proposal["sources"]:
            if source["kind"] == "code":
                out += [f'<li>{reference_link({k: v for k, v in source.items() if k != "kind"}, document["snapshotId"], snapshots)}</li>']
            else:
                out += [f'<li>{esc(source["kind"])} · {esc(source["id"])}</li>']
        out += ['</ul></article>']
    if "handoff" in record:
        out += ['<p class="links"><a href="handoff.md">交接说明</a><a href="handoff.json">完整交接状态与来源</a></p>']
    out += ['</section><section id="code"><div class="source">程序观察 / 持久化快照</div><h2>代码与 diff</h2>']
    for ref, (snapshot, blobs) in snapshots.items():
        label = '生成时快照' if ref == record["snapshotId"] else '任务启动快照' if ref == task["startingWorkspace"]["snapshotId"] else '历史证据快照'
        out += [f'<article id="snapshot-{ref}"><h3>{label}</h3><p class="snapshot-id">{ref}</p>',
                f'<p class="scope">分支 {esc(snapshot["branch"])} · HEAD {esc(snapshot["head"])} · ignoredPaths {esc(json.dumps(snapshot["scope"]["ignoredPaths"], ensure_ascii=False))}</p>']
        for layer, blob in snapshot["diffs"].items():
            out += [f'<details><summary>{layer} diff · {esc(blob[:12])}</summary><pre>{esc(raw_text(blobs[blob]) or "（无差异）")}</pre></details>']
        for entry in snapshot["files"]:
            if entry["path"] not in relevant:
                continue
            for layer in ("worktree", "index"):
                value = entry[layer]
                anchor = file_anchor(ref, entry["path"], layer)
                out += [f'<details id="{anchor}"><summary>{esc(entry["path"])} · {layer}</summary>']
                if value is None or "blob" not in value:
                    out += ['<p class="invalid-ref">该快照中无内容（缺失或删除），未替换为当前文件。</p>']
                else:
                    data = blobs[value["blob"]]
                    out += [f'<p class="snapshot-id">SHA-256 {value["blob"]}</p><pre class="code">']
                    try:
                        code_lines = [raw_text(line.encode("utf-8")) for line in data.decode("utf-8").splitlines()]
                    except UnicodeDecodeError:
                        code_lines = [raw_text(data)]
                    for number, line in enumerate(code_lines, start=1):
                        out += [f'<span class="line" id="{anchor}-L{number}" data-line="{number}">{esc(line)}</span>']
                    out += ['</pre>']
                out += ['</details>']
        out += ['</article>']
    out += ['</section><section id="limitations"><div class="source">范围与交接</div><h2>限制与交接</h2><ul>']
    out += [f'<li class="text">{esc(value)}</li>' for value in record["limitations"]]
    out += ['</ul><p class="links"><a href="review.json">结构化材料</a><a href="review.md">Markdown</a><a href="references.json">原始引用清单</a></p></section>',
            '<div class="footer">Engineering Flow · 本地生成，无外部资源或页面写入通道。</div></main></div></body></html>']
    return "\n".join(out)
