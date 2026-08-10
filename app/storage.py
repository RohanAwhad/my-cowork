"""SQLite storage layer with aiosqlite.

Provides CRUD operations for sessions, artifacts, and permission records.
Each public method is one transaction. Structured logging at entry/exit.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import aiosqlite
from loguru import logger

from app.models import (
    Artifact,
    PermissionRecord,
    ScheduledTask,
    Session,
    SessionStatus,
    TaskStatus,
)

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    prompt        TEXT NOT NULL,
    transcript_source TEXT NOT NULL DEFAULT 'stream-json',
    mcp_config    TEXT NOT NULL DEFAULT '{}',
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    denied_tools  TEXT NOT NULL DEFAULT '[]',
    user_selected_folders TEXT NOT NULL DEFAULT '[]',
    outputs_dir   TEXT NOT NULL,
    cli_session_id TEXT,
    error         TEXT,
    task_id       TEXT,
    init_step     TEXT,
    num_turns     INTEGER,
    is_error      INTEGER,
    exit_code     INTEGER,
    proc_pid      INTEGER,
    proc_start_epoch REAL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    started_at    TEXT,
    ended_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE TABLE IF NOT EXISTS session_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    seq        INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_session_seq ON session_events(session_id, seq);

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    cadence     TEXT,
    cron_expr   TEXT,
    prompt      TEXT NOT NULL,
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL,
    next_run_at TEXT,
    last_run_at TEXT,
    last_run_session_id TEXT,
    last_run_error TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON tasks(status, next_run_at);

CREATE TABLE IF NOT EXISTS artifacts (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    name        TEXT NOT NULL,
    rel_path    TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    deleted_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);

CREATE TABLE IF NOT EXISTS artifact_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    version     INTEGER NOT NULL,
    stored_rel_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (artifact_id, version)
);

CREATE TABLE IF NOT EXISTS permissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT REFERENCES sessions(id),
    task_id     TEXT,
    tool_name   TEXT NOT NULL,
    decision    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    input       TEXT NOT NULL DEFAULT '{}',
    consumed_by_session_id TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_permissions_session ON permissions(session_id, created_at);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def init_db(self) -> None:
        logger.info("init_db_started", db_path=self._db_path)
        self._db = await aiosqlite.connect(self._db_path, isolation_level=None)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        logger.info("init_db_completed", db_path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("storage_closed")

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Storage not initialized — call init_db() first"
        return self._db

    # --- Sessions ---

    async def create_session(self, session: Session) -> Session:
        logger.info("create_session", session_id=str(session.id))
        proc_pid = session.process_identity.pid if session.process_identity else None
        proc_start = session.process_identity.start_time_epoch if session.process_identity else None
        await self.db.execute(
            """INSERT INTO sessions (
                id, status, title, prompt, transcript_source,
                mcp_config, allowed_tools, denied_tools, user_selected_folders,
                outputs_dir, cli_session_id, error, task_id, init_step,
                num_turns, is_error, exit_code, proc_pid, proc_start_epoch,
                created_at, updated_at, started_at, ended_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(session.id), session.status.value, session.title, session.prompt,
                session.transcript_source,
                json.dumps(session.mcp_config), json.dumps(session.allowed_tools),
                json.dumps(session.denied_tools), json.dumps(session.user_selected_folders),
                session.outputs_dir, session.cli_session_id, session.error,
                str(session.task_id) if session.task_id else None, session.init_step,
                session.num_turns, int(session.is_error) if session.is_error is not None else None,
                session.exit_code, proc_pid, proc_start,
                session.created_at.isoformat(), session.updated_at.isoformat(),
                session.started_at.isoformat() if session.started_at else None,
                session.ended_at.isoformat() if session.ended_at else None,
            ),
        )
        await self.db.commit()
        logger.info("create_session_completed", session_id=str(session.id))
        return session

    async def get_session(self, session_id: UUID) -> Session | None:
        logger.debug("get_session", session_id=str(session_id))
        cursor = await self.db.execute("SELECT * FROM sessions WHERE id = ?", (str(session_id),))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_session(row)

    async def update_session_status(
        self,
        session_id: UUID,
        new_status: SessionStatus,
        *,
        error: str | None = None,
        ended_at: datetime | None = None,
    ) -> Session | None:
        logger.info("update_session_status", session_id=str(session_id), new_status=new_status.value)
        now = _now_iso()

        fields = ["status = ?", "updated_at = ?"]
        values: list[Any] = [new_status.value, now]
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if ended_at is not None:
            fields.append("ended_at = ?")
            values.append(ended_at.isoformat())
        if new_status == SessionStatus.RUNNING:
            fields.append("started_at = ?")
            values.append(now)

        values.append(str(session_id))
        set_clause = ", ".join(fields)

        if new_status == SessionStatus.RUNNING:
            await self.db.execute("BEGIN IMMEDIATE")
            cursor = await self.db.execute(
                f"UPDATE sessions SET {set_clause} WHERE id = ? "
                "AND NOT EXISTS(SELECT 1 FROM sessions WHERE status = ? AND id != ?)",
                values + [SessionStatus.RUNNING.value, str(session_id)],
            )
            if cursor.rowcount == 0:
                await self.db.execute("ROLLBACK")
                raise ValueError("Cannot transition to running: another session is already running")
            await self.db.execute("COMMIT")
        else:
            await self.db.execute(
                f"UPDATE sessions SET {set_clause} WHERE id = ?",
                values,
            )
            await self.db.commit()
        result = await self.get_session(session_id)
        logger.info("update_session_status_completed", session_id=str(session_id), new_status=new_status.value)
        return result

    async def list_sessions(self, status: SessionStatus | None = None) -> list[Session]:
        logger.debug("list_sessions", status=status.value if status else None)
        if status:
            cursor = await self.db.execute(
                "SELECT * FROM sessions WHERE status = ? ORDER BY created_at DESC", (status.value,)
            )
        else:
            cursor = await self.db.execute("SELECT * FROM sessions ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [_row_to_session(r) for r in rows]

    # --- Artifacts ---

    async def create_artifact(self, artifact: Artifact) -> Artifact:
        logger.info("create_artifact", artifact_id=str(artifact.id), session_id=str(artifact.session_id))
        await self.db.execute(
            """INSERT INTO artifacts (
                id, session_id, name, rel_path, size_bytes,
                current_version, content_hash, created_at, modified_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(artifact.id), str(artifact.session_id), artifact.name,
                artifact.rel_path, artifact.size_bytes, artifact.current_version,
                artifact.content_hash,
                artifact.created_at.isoformat(), artifact.modified_at.isoformat(),
                artifact.deleted_at.isoformat() if artifact.deleted_at else None,
            ),
        )
        await self.db.commit()
        logger.info("create_artifact_completed", artifact_id=str(artifact.id))
        return artifact

    async def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        logger.debug("get_artifact", artifact_id=str(artifact_id))
        cursor = await self.db.execute("SELECT * FROM artifacts WHERE id = ?", (str(artifact_id),))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_artifact(row)

    async def list_artifacts_by_session(self, session_id: UUID) -> list[Artifact]:
        logger.debug("list_artifacts_by_session", session_id=str(session_id))
        cursor = await self.db.execute(
            "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at", (str(session_id),)
        )
        rows = await cursor.fetchall()
        return [_row_to_artifact(r) for r in rows]

    # --- Permissions ---

    async def record_permission(self, record: PermissionRecord) -> PermissionRecord:
        logger.info(
            "record_permission",
            session_id=str(record.session_id) if record.session_id else None,
            tool_name=record.tool_name,
            decision=record.decision,
        )
        cursor = await self.db.execute(
            """INSERT INTO permissions (
                session_id, task_id, tool_name, decision, reason,
                input, consumed_by_session_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(record.session_id) if record.session_id else None,
                str(record.task_id) if record.task_id else None,
                record.tool_name, record.decision, record.reason,
                json.dumps(record.input),
                str(record.consumed_by_session_id) if record.consumed_by_session_id else None,
                record.created_at.isoformat(),
            ),
        )
        await self.db.commit()
        record_id = cursor.lastrowid
        logger.info("record_permission_completed", permission_id=record_id)
        return record.model_copy(update={"id": record_id})

    async def list_permissions_by_session(self, session_id: UUID) -> list[PermissionRecord]:
        logger.debug("list_permissions_by_session", session_id=str(session_id))
        cursor = await self.db.execute(
            "SELECT * FROM permissions WHERE session_id = ? ORDER BY created_at",
            (str(session_id),),
        )
        rows = await cursor.fetchall()
        return [_row_to_permission(r) for r in rows]

    # --- Tasks ---

    async def create_task(self, task: ScheduledTask) -> ScheduledTask:
        logger.info("create_task", task_id=str(task.id))
        await self.db.execute(
            """INSERT INTO tasks (
                id, name, cadence, cron_expr, prompt, allowed_tools,
                status, next_run_at, last_run_at, last_run_session_id,
                last_run_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(task.id), task.name, task.cadence, task.cron_expr,
                task.prompt, json.dumps(task.allowed_tools),
                task.status.value,
                task.next_run_at.isoformat() if task.next_run_at else None,
                task.last_run_at.isoformat() if task.last_run_at else None,
                str(task.last_run_session_id) if task.last_run_session_id else None,
                task.last_run_error,
                task.created_at.isoformat(), task.updated_at.isoformat(),
            ),
        )
        await self.db.commit()
        logger.info("create_task_completed", task_id=str(task.id))
        return task

    async def get_task(self, task_id: UUID) -> ScheduledTask | None:
        logger.debug("get_task", task_id=str(task_id))
        cursor = await self.db.execute("SELECT * FROM tasks WHERE id = ?", (str(task_id),))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_task(row)

    async def update_task(self, task_id: UUID, **fields: Any) -> ScheduledTask | None:
        logger.info("update_task", task_id=str(task_id), fields=list(fields.keys()))
        if not fields:
            return await self.get_task(task_id)

        set_parts: list[str] = []
        values: list[Any] = []
        for key, val in fields.items():
            if key == "status" and isinstance(val, TaskStatus):
                val = val.value
            elif key == "allowed_tools" and isinstance(val, list):
                val = json.dumps(val)
            elif key in ("next_run_at", "last_run_at") and isinstance(val, datetime):
                val = val.isoformat()
            elif key == "last_run_session_id" and val is not None:
                val = str(val)
            set_parts.append(f"{key} = ?")
            values.append(val)

        set_parts.append("updated_at = ?")
        values.append(_now_iso())
        values.append(str(task_id))

        await self.db.execute(
            f"UPDATE tasks SET {', '.join(set_parts)} WHERE id = ?",
            values,
        )
        await self.db.commit()
        result = await self.get_task(task_id)
        logger.info("update_task_completed", task_id=str(task_id))
        return result

    async def list_tasks(self, status: TaskStatus | None = None) -> list[ScheduledTask]:
        logger.debug("list_tasks", status=status.value if status else None)
        if status:
            cursor = await self.db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC", (status.value,)
            )
        else:
            cursor = await self.db.execute("SELECT * FROM tasks ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [_row_to_task(r) for r in rows]


def _row_to_session(row: aiosqlite.Row) -> Session:
    from app.models import ProcessIdentity

    proc_identity = None
    if row["proc_pid"] is not None:
        proc_identity = ProcessIdentity(pid=row["proc_pid"], start_time_epoch=row["proc_start_epoch"])

    return Session(
        id=UUID(row["id"]),
        status=SessionStatus(row["status"]),
        title=row["title"],
        prompt=row["prompt"],
        transcript_source=row["transcript_source"],
        mcp_config=json.loads(row["mcp_config"]),
        allowed_tools=json.loads(row["allowed_tools"]),
        denied_tools=json.loads(row["denied_tools"]),
        user_selected_folders=json.loads(row["user_selected_folders"]),
        outputs_dir=row["outputs_dir"],
        cli_session_id=row["cli_session_id"],
        error=row["error"],
        task_id=UUID(row["task_id"]) if row["task_id"] else None,
        init_step=row["init_step"],
        num_turns=row["num_turns"],
        is_error=bool(row["is_error"]) if row["is_error"] is not None else None,
        exit_code=row["exit_code"],
        process_identity=proc_identity,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
        ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
    )


def _row_to_artifact(row: aiosqlite.Row) -> Artifact:
    return Artifact(
        id=UUID(row["id"]),
        session_id=UUID(row["session_id"]),
        name=row["name"],
        rel_path=row["rel_path"],
        size_bytes=row["size_bytes"],
        current_version=row["current_version"],
        content_hash=row["content_hash"],
        created_at=datetime.fromisoformat(row["created_at"]),
        modified_at=datetime.fromisoformat(row["modified_at"]),
        deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
    )


def _row_to_permission(row: aiosqlite.Row) -> PermissionRecord:
    return PermissionRecord(
        id=row["id"],
        session_id=UUID(row["session_id"]) if row["session_id"] else None,
        task_id=UUID(row["task_id"]) if row["task_id"] else None,
        tool_name=row["tool_name"],
        decision=row["decision"],
        reason=row["reason"],
        input=json.loads(row["input"]),
        consumed_by_session_id=UUID(row["consumed_by_session_id"]) if row["consumed_by_session_id"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_task(row: aiosqlite.Row) -> ScheduledTask:
    return ScheduledTask(
        id=UUID(row["id"]),
        name=row["name"],
        cadence=row["cadence"],
        cron_expr=row["cron_expr"],
        prompt=row["prompt"],
        allowed_tools=json.loads(row["allowed_tools"]),
        status=TaskStatus(row["status"]),
        next_run_at=datetime.fromisoformat(row["next_run_at"]) if row["next_run_at"] else None,
        last_run_at=datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None,
        last_run_session_id=UUID(row["last_run_session_id"]) if row["last_run_session_id"] else None,
        last_run_error=row["last_run_error"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
