"""构造案例：仅本地 SQLite，不执行设备任务、不连接业务系统。"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path


class BatchQueue:
    def __init__(self, database: Path):
        self.database = database
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, cases TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL, case_name TEXT NOT NULL
                );
            """)

    def submit(self, request_id: str, cases: list[str]) -> dict:
        if not isinstance(request_id, str) or not request_id.strip() or not cases or any(not isinstance(c, str) or not c.strip() for c in cases):
            raise ValueError("request_id 和 cases 不能为空")
        encoded = json.dumps(cases, ensure_ascii=True)
        with closing(sqlite3.connect(self.database, timeout=5)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT id, cases FROM batches WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if existing[1] != encoded:
                    raise ValueError("同一 request_id 的 cases 不一致")
                batch_id = existing[0]
            else:
                batch_id = connection.execute("INSERT INTO batches (request_id, cases) VALUES (?, ?)", (request_id, encoded)).lastrowid
                connection.executemany("INSERT INTO jobs (batch_id, case_name) VALUES (?, ?)", ((batch_id, case) for case in cases))
            jobs = connection.execute("SELECT id, case_name FROM jobs WHERE batch_id=? ORDER BY id", (batch_id,)).fetchall()
            return {"batchId": batch_id, "jobs": [{"id": row[0], "case": row[1]} for row in jobs]}
