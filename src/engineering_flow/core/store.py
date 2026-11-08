"""任务、内容快照与 blob 在同一 SQLite 事务中提交。"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .errors import FlowError
from .records import validate_record
from .snapshots import Capture, blob_references, digest, validate_snapshot

STORE_VERSION = 6


class TaskStore:
    def __init__(self, path: Path, *, timeout: float = 5):
        self.path = path
        self.timeout = timeout

    @contextmanager
    def _connection(self, *, create: bool = False):
        connection = None
        try:
            if self.path.parent.is_symlink() or self.path.is_symlink():
                raise FlowError("storage_path", "存储目录或数据库不能是符号链接。")
            if create:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            if not create and not self.path.is_file():
                raise FlowError("task_not_found", "尚无任务存储；请先创建任务。")
            uri = self.path.resolve().as_uri() + ("?mode=rwc" if create else "?mode=rw")
            connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=self.timeout)
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE" if create else "BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4, 5, STORE_VERSION):
                raise FlowError("unsupported_schema", f"不支持存储 schema {version}；未修改原记录。")
            if version == 0:
                if not create or connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise FlowError("unsupported_schema", "未知数据库结构；拒绝初始化或覆盖。")
                connection.execute(
                    "CREATE TABLE task_revisions (task_id TEXT NOT NULL, revision INTEGER NOT NULL "
                    "CHECK(revision > 0), document TEXT NOT NULL, PRIMARY KEY(task_id, revision))"
                )
            if create and version < 2:
                # v1 -> v2 只增加表；旧 document 原样保留。DDL 与首条写入同事务。
                connection.execute("CREATE TABLE snapshots (id TEXT PRIMARY KEY, document TEXT NOT NULL)")
                connection.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, content BLOB NOT NULL)")
            if create and version < 3:
                connection.execute("CREATE TABLE check_runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, document TEXT NOT NULL)")
                connection.execute("CREATE TABLE reviews (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, document TEXT NOT NULL)")
            if create and version < 4:
                connection.execute("CREATE TABLE review_events (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, document TEXT NOT NULL)")
            if create and version < 5:
                connection.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, document TEXT NOT NULL)")
                connection.execute("CREATE TABLE memory_events (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, document TEXT NOT NULL)")
            if create and version < 6:
                connection.execute("CREATE TABLE document_proposals (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, document TEXT NOT NULL)")
                connection.execute(f"PRAGMA user_version={STORE_VERSION}")
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError) as exc:
            primary = getattr(exc, "sqlite_errorcode", 0) & 0xff
            code = {sqlite3.SQLITE_BUSY: "storage_busy", sqlite3.SQLITE_LOCKED: "storage_busy",
                    sqlite3.SQLITE_FULL: "storage_full", sqlite3.SQLITE_READONLY: "storage_readonly"}.get(primary, "storage_error")
            raise FlowError(code, f"任务存储读写失败，未确认保存成功：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()  # 回滚未提交的事务；失败不返回保存成功。

    @staticmethod
    def _decode(document: str, code: str) -> dict:
        try:
            return json.loads(document)
        except (ValueError, TypeError) as exc:
            raise FlowError(code, "存储 JSON 损坏；未修改原记录。") from exc

    def load(self, task_id: str) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT revision, document FROM task_revisions WHERE task_id=? ORDER BY revision DESC LIMIT 1", (task_id,)
            ).fetchone()
            if row is None:
                raise FlowError("task_not_found", "找不到该任务；请核对任务 ID 与工作区。")
            record = self._decode(row[1], "invalid_record")
            validate_record(record)
            if record["id"] != task_id or record["revision"] != row[0]:
                raise FlowError("invalid_record", "任务 ID 或修订号与存储索引不符。")
            return record

    @staticmethod
    def _read_snapshot(connection, snapshot_id: str) -> tuple[dict, dict[str, bytes]]:
        row = connection.execute("SELECT document FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise FlowError("invalid_snapshot", "任务引用的快照缺失；未自动回退或伪造当前状态。")
        document = TaskStore._decode(row[0], "invalid_snapshot")
        validate_snapshot(document, snapshot_id)
        blobs = {}
        for ref in blob_references(document):
            data = connection.execute("SELECT content FROM blobs WHERE id=?", (ref,)).fetchone()
            if data is None or not isinstance(data[0], bytes) or digest(data[0]) != ref:
                raise FlowError("invalid_snapshot", "快照内容缺失或摘要不符；未修改原记录。")
            blobs[ref] = data[0]
        for entry in document["files"]:
            current = entry["worktree"]
            if current["kind"] == "file" and len(blobs[current["blob"]]) != current["size"]:
                raise FlowError("invalid_snapshot", "快照文件长度与内容不符。")
        return document, blobs

    def load_snapshot(self, snapshot_id: str) -> tuple[dict, dict[str, bytes]]:
        with self._connection() as connection:
            return self._read_snapshot(connection, snapshot_id)

    @staticmethod
    def _memory_links(connection, document: dict, kind: str) -> None:
        from .memory_records import code_content, validate_memory
        snapshot, blobs = TaskStore._read_snapshot(connection, document["snapshotId"])
        row = connection.execute("SELECT document FROM task_revisions WHERE task_id=? AND revision=?",
                                 (document["taskId"], document["taskRevision"])).fetchone()
        if row is None:
            raise FlowError("invalid_memory", "记忆的任务修订缺失。")
        task = TaskStore._decode(row[0], "invalid_record")
        validate_record(task)
        if any(snapshot[k] != document[k] or task["savedWorkspace"][k] != document[k] for k in ("projectId", "workspaceId")):
            raise FlowError("invalid_memory", "记忆与来源工作区不符。")
        if (snapshot["branch"] != task["savedWorkspace"]["branch"] or
                snapshot["branch"] is None and snapshot["head"] != task["savedWorkspace"]["head"]):
            raise FlowError("invalid_memory", "记忆与任务分支不符。")
        if kind == "memories":
            from .evidence import validate_evidence
            try:
                for path in document["proposal"]["scope"]["paths"]:
                    if not any(e["path"] == path or e["path"].startswith(path + "/") for e in snapshot["files"]):
                        raise ValueError("scope path missing")
                for source in document["proposal"]["sources"]:
                    if source["kind"] == "code":
                        code_content(source, snapshot, blobs)
                        continue
                    table = "check_runs" if source["kind"] == "check" else "review_events"
                    row = connection.execute(f"SELECT document FROM {table} WHERE id=?", (source["id"],)).fetchone()
                    if row is None:
                        raise ValueError("missing source")
                    evidence = TaskStore._decode(row[0], "invalid_evidence")
                    validate_evidence(evidence, table)
                    if any(evidence[k] != document[k] for k in ("taskId", "projectId", "workspaceId", "snapshotId")):
                        raise ValueError("source scope")
                    if table == "check_runs" and evidence["status"] == "running":
                        raise ValueError("source not immutable yet")
                    TaskStore._event_links(connection, evidence, table)
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                raise FlowError("invalid_memory", "记忆必须引用同任务快照的实际文本行或已保存的终态证据。") from exc
        else:
            for key in ("memoryId", "otherId"):
                if document[key] is None:
                    continue
                row = connection.execute("SELECT document FROM memories WHERE id=?", (document[key],)).fetchone()
                if row is None:
                    raise FlowError("invalid_memory", "关系引用的记忆缺失。")
                memory = TaskStore._decode(row[0], "invalid_memory")
                validate_memory(memory, "memories")
                source, _ = TaskStore._read_snapshot(connection, memory["snapshotId"])
                if any(memory[k] != document[k] for k in ("projectId", "workspaceId")) or source["branch"] != snapshot["branch"]:
                    raise FlowError("invalid_memory", "不能跨工作区或分支关联记忆。")
                if key == "memoryId" and memory["taskId"] != document["taskId"]:
                    raise FlowError("invalid_memory", "关系不属于该记忆的任务。")
            if document["eventType"] == "supersedes":
                edges = {}
                for raw, in connection.execute("SELECT document FROM memory_events"):
                    event = TaskStore._decode(raw, "invalid_memory")
                    validate_memory(event, "memory_events")
                    if event["eventType"] == "supersedes":
                        edges.setdefault(event["memoryId"], set()).add(event["otherId"])
                pending, seen = [document["otherId"]], set()
                while pending:
                    key = pending.pop()
                    if key == document["memoryId"]:
                        raise FlowError("invalid_memory", "记忆替代关系不能循环。")
                    if key not in seen:
                        seen.add(key)
                        pending.extend(edges.get(key, ()))

    def memory_documents(self, kind: str) -> list[dict]:
        from .memory_records import validate_memory
        if kind not in ("memories", "memory_events"):
            raise ValueError("unsupported memory table")
        with self._connection() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] < 5:
                return []
            result = []
            for key, owner, raw in connection.execute(f"SELECT id, task_id, document FROM {kind} ORDER BY rowid").fetchall():
                document = self._decode(raw, "invalid_memory")
                validate_memory(document, kind)
                if document["id"] != key or document["taskId"] != owner:
                    raise FlowError("invalid_memory", "记忆 ID 或任务与存储索引不符。")
                self._memory_links(connection, document, kind)
                result.append(document)
            return result

    def save_memory(self, kind: str, document: dict, *, capture: Capture) -> None:
        from .memory_records import validate_memory
        validate_memory(document, kind)
        with self._connection(create=True) as connection:
            row = connection.execute("SELECT MAX(revision) FROM task_revisions WHERE task_id=?", (document["taskId"],)).fetchone()
            if row[0] != document["taskRevision"]:
                raise FlowError("revision_conflict", "保存记忆期间任务修订变化；请重新续接。")
            if capture.document["id"] != document["snapshotId"]:
                raise FlowError("invalid_memory", "记忆与保存快照不符。")
            self._save_capture(connection, capture)
            self._memory_links(connection, document, kind)
            connection.execute(f"INSERT INTO {kind} VALUES (?, ?, ?)",
                               (document["id"], document["taskId"], json.dumps(document, ensure_ascii=True)))

    @staticmethod
    def _document_links(connection, document: dict) -> None:
        from .document_records import before_content, source_proposal, validate_document
        validate_document(document)
        # 文档与记忆共享实际来源和任务/分支边界，不复制 runner/Review 的状态逻辑。
        TaskStore._memory_links(connection, dict(document, proposal=source_proposal(document["proposal"])), "memories")
        snapshot, blobs = TaskStore._read_snapshot(connection, document["snapshotId"])
        try:
            if before_content(document["proposal"], snapshot, blobs) != document["before"]:
                raise ValueError("target differs from snapshot")
        except (ValueError, UnicodeError) as exc:
            raise FlowError("invalid_document", "文档原文与所绑定快照不符。") from exc
        parent_id = document["voice"]["parentId"]
        if parent_id:
            row = connection.execute("SELECT document FROM document_proposals WHERE id=?", (parent_id,)).fetchone()
            parent = TaskStore._decode(row[0], "invalid_document") if row else None
            if parent is None:
                raise FlowError("invalid_document", "改写的原建议缺失。")
            validate_document(parent)
            if (parent["integrity"] != document["voice"]["parentIntegrity"] or parent["voice"]["status"] != "not_requested"
                    or any(parent[k] != document[k] for k in ("taskId", "taskRevision", "projectId", "workspaceId", "snapshotId", "proposal", "before"))):
                raise FlowError("invalid_document", "改写未绑定原草稿、快照和任务修订。")

    def documents(self, *, task_id: str | None = None, document_id: str | None = None) -> list[dict]:
        with self._connection() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] < 6:
                return []
            field, value = ("id", document_id) if document_id else ("task_id", task_id)
            result = []
            for key, owner, raw in connection.execute(f"SELECT id, task_id, document FROM document_proposals WHERE {field}=? ORDER BY rowid", (value,)).fetchall():
                document = self._decode(raw, "invalid_document")
                self._document_links(connection, document)
                if document["id"] != key or document["taskId"] != owner:
                    raise FlowError("invalid_document", "文档建议与存储索引不符。")
                result.append(document)
            return result

    def save_document(self, document: dict, *, capture: Capture) -> None:
        from .document_records import validate_document
        validate_document(document)
        with self._connection(create=True) as connection:
            revision = connection.execute("SELECT MAX(revision) FROM task_revisions WHERE task_id=?", (document["taskId"],)).fetchone()[0]
            if revision != document["taskRevision"]:
                raise FlowError("revision_conflict", "保存文档建议期间任务修订变化。")
            if capture.document["id"] != document["snapshotId"]:
                raise FlowError("invalid_document", "文档建议与保存快照不符。")
            self._save_capture(connection, capture)
            self._document_links(connection, document)
            connection.execute("INSERT INTO document_proposals VALUES (?, ?, ?)",
                               (document["id"], document["taskId"], json.dumps(document, ensure_ascii=True)))

    @staticmethod
    def _save_capture(connection, capture: Capture) -> None:
        validate_snapshot(capture.document, capture.document["id"])
        refs = blob_references(capture.document)
        if refs != set(capture.blobs) or any(digest(data) != ref for ref, data in capture.blobs.items()):
            raise FlowError("invalid_snapshot", "待保存内容与快照引用不符。")
        existing = connection.execute("SELECT 1 FROM snapshots WHERE id=?", (capture.document["id"],)).fetchone()
        if existing:
            TaskStore._read_snapshot(connection, capture.document["id"])
            return
        for ref, data in capture.blobs.items():
            old = connection.execute("SELECT content FROM blobs WHERE id=?", (ref,)).fetchone()
            if old is not None and old[0] != data:
                raise FlowError("invalid_snapshot", "已有内容摘要不符；拒绝覆盖。")
            connection.execute("INSERT OR IGNORE INTO blobs VALUES (?, ?)", (ref, data))
        connection.execute("INSERT INTO snapshots VALUES (?, ?)",
                           (capture.document["id"], json.dumps(capture.document, ensure_ascii=True)))

    def evidence(self, kind: str, *, task_id: str | None = None, evidence_id: str | None = None) -> list[dict]:
        if kind not in ("check_runs", "reviews", "review_events"):
            raise ValueError("unsupported evidence table")
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version < (4 if kind == "review_events" else 3):
                return []
            field, value = ("id", evidence_id) if evidence_id is not None else ("task_id", task_id)
            rows = connection.execute(f"SELECT id, task_id, document FROM {kind} WHERE {field}=? ORDER BY rowid", (value,)).fetchall()
            result = []
            from .evidence import snapshot_references, validate_evidence
            for key, owner, raw in rows:
                document = self._decode(raw, "invalid_evidence")
                validate_evidence(document, kind)
                if document["id"] != key or document["taskId"] != owner:
                    raise FlowError("invalid_evidence", "证据 ID 或任务与存储索引不符。")
                self._event_links(connection, document, kind)
                for ref in snapshot_references(document, kind):
                    snapshot, _ = self._read_snapshot(connection, ref)
                    if any(snapshot[k] != document[k] for k in ("projectId", "workspaceId")):
                        raise FlowError("invalid_evidence", "证据与快照身份不符。")
                result.append(document)
            return result

    @staticmethod
    def _event_links(connection, document: dict, kind: str) -> None:
        if kind != "review_events":
            return
        from .evidence import validate_evidence
        row = connection.execute("SELECT document FROM reviews WHERE id=?", (document["reviewId"],)).fetchone()
        if row is None:
            raise FlowError("invalid_evidence", "评审引用的材料缺失。")
        review = TaskStore._decode(row[0], "invalid_evidence")
        validate_evidence(review, "reviews")
        if (any(review[k] != document[k] for k in ("taskId", "snapshotId", "projectId", "workspaceId"))
                or review["task"]["revision"] != document["taskRevision"]):
            raise FlowError("invalid_evidence", "评审与材料范围不符。")
        if document["eventType"] != "explanation" and document["scope"]["kind"] == "memories":
            for memory in document["scope"]["memories"]:
                row = connection.execute("SELECT document FROM memories WHERE id=?", (memory["id"],)).fetchone()
                if row is None or TaskStore._decode(row[0], "invalid_memory") != memory:
                    raise FlowError("invalid_evidence", "评审绑定的记忆内容与原记录不符。")
        if document["eventType"] != "explanation" and document["scope"]["kind"] == "documents":
            for item in document["scope"]["documents"]:
                row = connection.execute("SELECT document FROM document_proposals WHERE id=?", (item["id"],)).fetchone()
                if row is None or TaskStore._decode(row[0], "invalid_document") != item:
                    raise FlowError("invalid_evidence", "评审绑定的文档建议与原记录不符。")
                TaskStore._document_links(connection, item)
        if document["eventType"] == "confirmation":
            row = connection.execute("SELECT document FROM review_events WHERE id=?", (document["opinionId"],)).fetchone()
            if row is None:
                raise FlowError("invalid_evidence", "确认引用的意见缺失。")
            opinion = TaskStore._decode(row[0], "invalid_evidence")
            validate_evidence(opinion, "review_events")
            if (opinion["eventType"] != "opinion" or document["opinionIntegrity"] != opinion["integrity"]
                    or any(opinion[k] != document[k] for k in ("taskId", "reviewId", "snapshotId", "scope", "decision", "comment"))):
                raise FlowError("invalid_evidence", "确认与原意见不符。")

    def save_evidence(self, kind: str, document: dict, *, captures: list[Capture], finishing: bool = False) -> None:
        from .evidence import snapshot_references, validate_evidence
        validate_evidence(document, kind)
        with self._connection(create=True) as connection:
            for capture in captures:
                self._save_capture(connection, capture)
            for ref in snapshot_references(document, kind):
                snapshot, _ = self._read_snapshot(connection, ref)
                if any(snapshot[k] != document[k] for k in ("projectId", "workspaceId")):
                    raise FlowError("invalid_evidence", "待保存证据和快照身份不符。")
            row = connection.execute("SELECT document FROM task_revisions WHERE task_id=? ORDER BY revision DESC LIMIT 1",
                                     (document["taskId"],)).fetchone()
            if row is None:
                raise FlowError("task_not_found", "证据对应的任务不存在。")
            task = self._decode(row[0], "invalid_record")
            validate_record(task)
            if any(task["savedWorkspace"][k] != document[k] for k in ("projectId", "workspaceId")):
                raise FlowError("workspace_mismatch", "证据不属于任务工作区。")
            self._event_links(connection, document, kind)
            if kind == "review_events" and document["eventType"] == "confirmation" and task["revision"] != document["taskRevision"]:
                raise FlowError("review_stale", "确认期间任务修订已改变，未保存确认。")
            raw = json.dumps(document, ensure_ascii=True)
            if finishing:
                row = connection.execute("SELECT document FROM check_runs WHERE id=?", (document["id"],)).fetchone()
                if row is None:
                    raise FlowError("invalid_evidence", "缺失检查开始记录。")
                previous = self._decode(row[0], "invalid_evidence")
                validate_evidence(previous, "check_runs")
                immutable = ("id", "taskId", "taskRevision", "projectId", "workspaceId", "check", "argv", "cwd", "snapshotId", "startedAt", "environment", "executionMode")
                if (previous["status"] != "running" or document["status"] == "running"
                        or any(previous[k] != document[k] for k in immutable)):
                    raise FlowError("invalid_evidence", "检查结果不能覆盖历史或改变执行依据。")
                connection.execute("UPDATE check_runs SET document=? WHERE id=?", (raw, document["id"]))
            else:
                connection.execute(f"INSERT INTO {kind} VALUES (?, ?, ?)", (document["id"], document["taskId"], raw))

    def append(self, record: dict, *, expected_revision: int, capture: Capture) -> None:
        validate_record(record)
        validate_snapshot(capture.document, capture.document["id"])
        if record["savedWorkspace"] != capture.workspace or record["savedWorkspace"]["snapshotId"] != capture.document["id"]:
            raise FlowError("invalid_snapshot", "任务与待保存快照不匹配。")
        refs = blob_references(capture.document)
        if refs != set(capture.blobs) or any(digest(data) != ref for ref, data in capture.blobs.items()):
            raise FlowError("invalid_snapshot", "待保存内容与快照引用不符。")
        with self._connection(create=True) as connection:
            current = connection.execute(
                "SELECT MAX(revision) FROM task_revisions WHERE task_id=?", (record["id"],)
            ).fetchone()[0] or 0
            if current != expected_revision or record["revision"] != current + 1:
                raise FlowError("revision_conflict", f"任务已是修订 {current}；请重新 resume 后再保存。")
            self._save_capture(connection, capture)
            for key in ("startingWorkspace", "savedWorkspace"):
                ref = record[key]["snapshotId"]
                if ref is not None:
                    document, _ = self._read_snapshot(connection, ref)
                    if any(document[k] != record[key][k] for k in ("projectId", "workspaceId", "branch", "head")):
                        raise FlowError("invalid_snapshot", "快照身份与任务工作区不符。")
            connection.execute("INSERT INTO task_revisions VALUES (?, ?, ?)",
                               (record["id"], record["revision"], json.dumps(record, ensure_ascii=True)))
