"""SQLite storage layer — async wrapper over aiosqlite, single writer connection.

Spec refs: 04 §2 (DDL), 04 §4.1 (session state machine), 05 §1.9 (Storage interface).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import aiosqlite
from loguru import logger

from cowork.models import (
    Artifact,
    ArtifactVersion,
    Connector,
    ConnectorStatus,
    PermissionDecision,
    PermissionRecord,
    ScheduledTask,
    Session,
    SessionEvent,
    SessionEventType,
    SessionStatus,
    SessionSummary,
    TaskStatus,
)

_DDL = """\
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
  task_id       TEXT REFERENCES tasks(id) ON DELETE SET NULL,
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
CREATE INDEX IF NOT EXISTS idx_sessions_task  ON sessions(task_id);

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
  task_id     TEXT REFERENCES tasks(id) ON DELETE SET NULL,
  tool_name   TEXT NOT NULL,
  decision    TEXT NOT NULL,
  reason      TEXT NOT NULL,
  input       TEXT NOT NULL DEFAULT '{}',
  consumed_by_session_id TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_permissions_session ON permissions(session_id, created_at);

CREATE TABLE IF NOT EXISTS connectors (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  command      TEXT NOT NULL,
  args         TEXT NOT NULL DEFAULT '[]',
  env          TEXT NOT NULL DEFAULT '{}',
  tool_names   TEXT NOT NULL DEFAULT '[]',
  requires_oauth INTEGER NOT NULL DEFAULT 0,
  oauth_pre_auth_done INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'registered',
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connector_tools (
  connector_id TEXT NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
  tool_name    TEXT NOT NULL,
  policy       TEXT NOT NULL CHECK (policy IN ('always','ask','blocked')),
  PRIMARY KEY (connector_id, tool_name)
);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

_LEGAL_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.PENDING: {SessionStatus.QUEUED, SessionStatus.RUNNING, SessionStatus.FAILED},
    SessionStatus.QUEUED: {SessionStatus.RUNNING, SessionStatus.STOPPED, SessionStatus.FAILED},
    SessionStatus.RUNNING: {SessionStatus.DONE, SessionStatus.STOPPED, SessionStatus.FAILED},
    SessionStatus.DONE: {SessionStatus.ARCHIVED},
    SessionStatus.STOPPED: {SessionStatus.ARCHIVED},
    SessionStatus.FAILED: {SessionStatus.ARCHIVED},
    SessionStatus.ARCHIVED: set(),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    return datetime.fromisoformat(val)


def _str_uuid(u: UUID) -> str:
    return str(u)


def _parse_uuid(val: str | None) -> UUID | None:
    if val is None:
        return None
    return UUID(val)


class Storage:
    """Async SQLite storage — single writer connection."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._checkpoint_task: asyncio.Task[None] | None = None

    async def init(self) -> None:
        logger.debug("storage.init db_path={}", self._db_path)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        for stmt in _DDL.split(";"):
            stmt = stmt.strip()
            if stmt:
                await self._conn.execute(stmt)
        await self._conn.commit()
        if self._db_path != ":memory:":
            self._checkpoint_task = asyncio.create_task(self._wal_checkpoint_loop())
        logger.info("storage.init complete")

    async def close(self) -> None:
        logger.debug("storage.close")
        if self._checkpoint_task is not None:
            self._checkpoint_task.cancel()
            try:
                await self._checkpoint_task
            except asyncio.CancelledError:
                pass
            self._checkpoint_task = None
        if self._conn is not None:
            if self._db_path != ":memory:":
                await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._conn.close()
            self._conn = None
        logger.info("storage.close complete")

    async def _wal_checkpoint_loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            if self._conn is not None:
                await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                logger.debug("storage.wal_checkpoint done")

    @property
    def _db(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Storage.init() not called"
        return self._conn

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    async def insert_session(self, session: Session) -> Session:
        logger.debug("storage.insert_session id={}", session.id)
        now = _utcnow()
        session.updated_at = now
        pi = session.process_identity
        await self._db.execute(
            """INSERT INTO sessions (
                id, status, title, prompt, transcript_source, mcp_config,
                allowed_tools, denied_tools, user_selected_folders, outputs_dir,
                cli_session_id, error, task_id, init_step, num_turns, is_error,
                exit_code, proc_pid, proc_start_epoch, created_at, updated_at,
                started_at, ended_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _str_uuid(session.id),
                session.status.value,
                session.title,
                session.prompt,
                session.transcript_source,
                json.dumps(session.mcp_config),
                json.dumps(session.allowed_tools),
                json.dumps(session.denied_tools),
                json.dumps([str(p) for p in session.user_selected_folders]),
                str(session.outputs_dir),
                session.cli_session_id,
                session.error,
                _str_uuid(session.task_id) if session.task_id else None,
                session.init_step,
                session.num_turns,
                int(session.is_error) if session.is_error is not None else None,
                session.exit_code,
                pi.pid if pi else None,
                pi.start_time_epoch if pi else None,
                _iso(session.created_at),
                _iso(session.updated_at),
                _iso(session.started_at),
                _iso(session.ended_at),
            ),
        )
        await self._db.commit()
        logger.debug("storage.insert_session committed id={}", session.id)
        return session

    async def get_session(self, session_id: UUID) -> Session | None:
        logger.debug("storage.get_session id={}", session_id)
        cur = await self._db.execute(
            "SELECT * FROM sessions WHERE id = ?", (_str_uuid(session_id),)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    async def list_sessions(self) -> list[SessionSummary]:
        logger.debug("storage.list_sessions")
        cur = await self._db.execute(
            """SELECT s.id, s.status, s.title, s.created_at, s.updated_at,
                      s.num_turns, s.is_error, s.task_id,
                      (SELECT COUNT(*) FROM artifacts a WHERE a.session_id = s.id) AS artifact_count
               FROM sessions s ORDER BY s.created_at DESC"""
        )
        rows = await cur.fetchall()
        result: list[SessionSummary] = []
        for row in rows:
            result.append(
                SessionSummary(
                    id=UUID(row["id"]),
                    status=SessionStatus(row["status"]),
                    title=row["title"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    num_turns=row["num_turns"],
                    is_error=bool(row["is_error"]) if row["is_error"] is not None else None,
                    task_id=_parse_uuid(row["task_id"]),
                    artifact_count=row["artifact_count"],
                )
            )
        return result

    async def update_session(self, session_id: UUID, **fields: Any) -> Session:
        logger.debug("storage.update_session id={} fields={}", session_id, list(fields.keys()))
        fields["updated_at"] = _utcnow()

        set_clauses: list[str] = []
        values: list[Any] = []
        for key, val in fields.items():
            col = key
            if key == "process_identity" and val is not None:
                set_clauses.append("proc_pid = ?")
                values.append(val.pid)
                set_clauses.append("proc_start_epoch = ?")
                values.append(val.start_time_epoch)
                continue
            if key == "process_identity" and val is None:
                set_clauses.append("proc_pid = ?")
                values.append(None)
                set_clauses.append("proc_start_epoch = ?")
                values.append(None)
                continue
            if isinstance(val, datetime):
                values.append(_iso(val))
            elif isinstance(val, UUID):
                values.append(_str_uuid(val))
            elif isinstance(val, bool):
                values.append(int(val))
                col = key
            elif isinstance(val, (list, dict)):
                values.append(json.dumps(val))
            else:
                values.append(val)
            set_clauses.append(f"{col} = ?")

        values.append(_str_uuid(session_id))
        sql = f"UPDATE sessions SET {', '.join(set_clauses)} WHERE id = ?"
        await self._db.execute(sql, values)
        await self._db.commit()

        session = await self.get_session(session_id)
        assert session is not None
        return session

    async def transition(self, session_id: UUID, new_status: SessionStatus) -> Session:
        logger.debug("storage.transition id={} new_status={}", session_id, new_status)
        cur = await self._db.execute(
            "SELECT status FROM sessions WHERE id = ?", (_str_uuid(session_id),)
        )
        row = await cur.fetchone()
        if row is None:
            raise ValueError(f"Session {session_id} not found")

        current_status = SessionStatus(row["status"])
        allowed = _LEGAL_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Illegal transition: {current_status.value} -> {new_status.value}"
            )

        if new_status == SessionStatus.RUNNING:
            cnt_cur = await self._db.execute(
                "SELECT COUNT(*) AS cnt FROM sessions WHERE status = 'running' AND id != ?",
                (_str_uuid(session_id),),
            )
            cnt_row = await cnt_cur.fetchone()
            assert cnt_row is not None
            if cnt_row["cnt"] > 0:
                raise ValueError(
                    "One-active invariant violated: another session is already running"
                )

        now = _utcnow()
        started_at_clause = ""
        params: list[Any] = [new_status.value, _iso(now)]
        if new_status == SessionStatus.RUNNING:
            started_at_clause = ", started_at = ?"
            params.append(_iso(now))

        ended_at_clause = ""
        if new_status in (SessionStatus.DONE, SessionStatus.STOPPED, SessionStatus.FAILED):
            ended_at_clause = ", ended_at = ?"
            params.append(_iso(now))

        params.append(_str_uuid(session_id))
        await self._db.execute(
            f"UPDATE sessions SET status = ?, updated_at = ?{started_at_clause}{ended_at_clause} WHERE id = ?",
            params,
        )
        await self._db.commit()

        session = await self.get_session(session_id)
        assert session is not None
        logger.debug("storage.transition committed id={} status={}", session_id, new_status)
        return session

    async def reconcile_running(self, started_before: datetime) -> None:
        logger.debug("storage.reconcile_running cutoff={}", started_before)
        now = _utcnow()
        await self._db.execute(
            """UPDATE sessions SET status = 'failed', updated_at = ?, ended_at = ?
               WHERE status = 'running' AND started_at < ?""",
            (_iso(now), _iso(now), _iso(started_before)),
        )
        await self._db.commit()
        logger.debug("storage.reconcile_running done")

    # ------------------------------------------------------------------
    # Event operations
    # ------------------------------------------------------------------

    async def append_event(
        self, session_id: UUID, event_type: SessionEventType, payload: dict[str, Any]
    ) -> SessionEvent:
        logger.debug("storage.append_event session_id={} type={}", session_id, event_type)
        sid = _str_uuid(session_id)

        cur = await self._db.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM session_events WHERE session_id = ?",
            (sid,),
        )
        row = await cur.fetchone()
        assert row is not None
        next_seq: int = row["max_seq"] + 1

        now = _utcnow()
        await self._db.execute(
            """INSERT INTO session_events (session_id, seq, event_type, payload, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (sid, next_seq, event_type.value, json.dumps(payload), _iso(now)),
        )
        await self._db.commit()

        event = SessionEvent(
            session_id=session_id,
            seq=next_seq,
            event_type=event_type,
            payload=payload,
            created_at=now,
        )
        cur2 = await self._db.execute(
            "SELECT id FROM session_events WHERE session_id = ? AND seq = ?",
            (sid, next_seq),
        )
        id_row = await cur2.fetchone()
        if id_row is not None:
            event.id = id_row["id"]

        logger.debug("storage.append_event committed seq={}", next_seq)
        return event

    async def list_events(
        self, session_id: UUID, after_seq: int = 0
    ) -> list[SessionEvent]:
        logger.debug("storage.list_events session_id={} after_seq={}", session_id, after_seq)
        cur = await self._db.execute(
            """SELECT id, session_id, seq, event_type, payload, created_at
               FROM session_events
               WHERE session_id = ? AND seq > ?
               ORDER BY seq""",
            (_str_uuid(session_id), after_seq),
        )
        rows = await cur.fetchall()
        return [
            SessionEvent(
                id=r["id"],
                session_id=UUID(r["session_id"]),
                seq=r["seq"],
                event_type=SessionEventType(r["event_type"]),
                payload=json.loads(r["payload"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Task CRUD
    # ------------------------------------------------------------------

    async def insert_task(self, task: ScheduledTask) -> ScheduledTask:
        logger.debug("storage.insert_task id={}", task.id)
        now = _utcnow()
        task.updated_at = now
        await self._db.execute(
            """INSERT INTO tasks (
                id, name, cadence, cron_expr, prompt, allowed_tools, status,
                next_run_at, last_run_at, last_run_session_id, last_run_error,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _str_uuid(task.id),
                task.name,
                task.cadence,
                task.cron_expr,
                task.prompt,
                json.dumps(task.allowed_tools),
                task.status.value,
                _iso(task.next_run_at),
                _iso(task.last_run_at),
                _str_uuid(task.last_run_session_id) if task.last_run_session_id else None,
                task.last_run_error,
                _iso(task.created_at),
                _iso(task.updated_at),
            ),
        )
        await self._db.commit()
        logger.debug("storage.insert_task committed id={}", task.id)
        return task

    async def get_task(self, task_id: UUID) -> ScheduledTask | None:
        logger.debug("storage.get_task id={}", task_id)
        cur = await self._db.execute(
            "SELECT * FROM tasks WHERE id = ?", (_str_uuid(task_id),)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    async def update_task(self, task_id: UUID, **fields: Any) -> ScheduledTask:
        logger.debug("storage.update_task id={} fields={}", task_id, list(fields.keys()))
        fields["updated_at"] = _utcnow()

        set_clauses: list[str] = []
        values: list[Any] = []
        for key, val in fields.items():
            if isinstance(val, datetime):
                values.append(_iso(val))
            elif isinstance(val, UUID):
                values.append(_str_uuid(val))
            elif isinstance(val, (list, dict)):
                values.append(json.dumps(val))
            else:
                values.append(val)
            set_clauses.append(f"{key} = ?")

        values.append(_str_uuid(task_id))
        sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?"
        await self._db.execute(sql, values)
        await self._db.commit()

        task = await self.get_task(task_id)
        assert task is not None
        return task

    async def list_tasks(self) -> list[ScheduledTask]:
        logger.debug("storage.list_tasks")
        cur = await self._db.execute("SELECT * FROM tasks ORDER BY created_at DESC")
        rows = await cur.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def list_due(self, now: datetime) -> list[ScheduledTask]:
        logger.debug("storage.list_due now={}", now)
        cur = await self._db.execute(
            "SELECT * FROM tasks WHERE status = 'active' AND next_run_at <= ? ORDER BY next_run_at",
            (_iso(now),),
        )
        rows = await cur.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def set_task_status(self, task_id: UUID, new_status: TaskStatus) -> ScheduledTask:
        logger.debug("storage.set_task_status id={} status={}", task_id, new_status)
        now = _utcnow()
        await self._db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (new_status.value, _iso(now), _str_uuid(task_id)),
        )
        await self._db.commit()
        task = await self.get_task(task_id)
        assert task is not None
        return task

    # ------------------------------------------------------------------
    # Artifact operations
    # ------------------------------------------------------------------

    async def record_artifact(
        self,
        session_id: UUID,
        name: str,
        rel_path: str,
        content_hash: str,
        size_bytes: int,
        stored_rel_path: str,
    ) -> tuple[Artifact, ArtifactVersion]:
        logger.debug("storage.record_artifact session_id={} name={}", session_id, name)
        sid = _str_uuid(session_id)
        now = _utcnow()
        now_iso = _iso(now)
        assert now_iso is not None

        cur = await self._db.execute(
            "SELECT * FROM artifacts WHERE session_id = ? AND name = ?",
            (sid, name),
        )
        existing = await cur.fetchone()

        if existing is None:
            artifact_id = uuid4()
            aid = _str_uuid(artifact_id)
            version = 1
            await self._db.execute(
                """INSERT INTO artifacts (
                    id, session_id, name, rel_path, size_bytes, current_version,
                    content_hash, created_at, modified_at
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (aid, sid, name, rel_path, size_bytes, version, content_hash, now_iso, now_iso),
            )
        else:
            aid = existing["id"]
            artifact_id = UUID(aid)
            version = existing["current_version"] + 1
            await self._db.execute(
                """UPDATE artifacts SET current_version = ?, content_hash = ?,
                   size_bytes = ?, rel_path = ?, modified_at = ?
                   WHERE id = ?""",
                (version, content_hash, size_bytes, rel_path, now_iso, aid),
            )

        await self._db.execute(
            """INSERT INTO artifact_versions (
                artifact_id, version, stored_rel_path, content_hash, size_bytes, created_at
            ) VALUES (?,?,?,?,?,?)""",
            (aid, version, stored_rel_path, content_hash, size_bytes, now_iso),
        )
        await self._db.commit()

        artifact = await self.get_artifact(artifact_id)
        assert artifact is not None

        ver_cur = await self._db.execute(
            "SELECT * FROM artifact_versions WHERE artifact_id = ? AND version = ?",
            (aid, version),
        )
        ver_row = await ver_cur.fetchone()
        assert ver_row is not None
        art_version = ArtifactVersion(
            id=ver_row["id"],
            artifact_id=UUID(ver_row["artifact_id"]),
            version=ver_row["version"],
            stored_rel_path=ver_row["stored_rel_path"],
            content_hash=ver_row["content_hash"],
            size_bytes=ver_row["size_bytes"],
            created_at=datetime.fromisoformat(ver_row["created_at"]),
        )

        logger.debug("storage.record_artifact committed artifact_id={} version={}", artifact_id, version)
        return artifact, art_version

    async def list_artifacts(self, session_id: UUID) -> list[Artifact]:
        logger.debug("storage.list_artifacts session_id={}", session_id)
        cur = await self._db.execute(
            "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at",
            (_str_uuid(session_id),),
        )
        rows = await cur.fetchall()
        return [self._row_to_artifact(r) for r in rows]

    async def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        logger.debug("storage.get_artifact id={}", artifact_id)
        cur = await self._db.execute(
            "SELECT * FROM artifacts WHERE id = ?", (_str_uuid(artifact_id),)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_artifact(row)

    async def mark_artifact_deleted(self, artifact_id: UUID) -> None:
        logger.debug("storage.mark_artifact_deleted id={}", artifact_id)
        now_iso = _iso(_utcnow())
        await self._db.execute(
            "UPDATE artifacts SET deleted_at = ?, modified_at = ? WHERE id = ?",
            (now_iso, now_iso, _str_uuid(artifact_id)),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Permission operations
    # ------------------------------------------------------------------

    async def append_permission(
        self,
        session_id: UUID | None,
        task_id: UUID | None,
        tool_name: str,
        decision: PermissionDecision,
        reason: str,
        input_data: dict[str, Any],
    ) -> PermissionRecord:
        logger.debug("storage.append_permission tool={} decision={}", tool_name, decision)
        now = _utcnow()
        now_iso = _iso(now)
        assert now_iso is not None

        cur = await self._db.execute(
            """INSERT INTO permissions (
                session_id, task_id, tool_name, decision, reason, input, created_at
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                _str_uuid(session_id) if session_id else None,
                _str_uuid(task_id) if task_id else None,
                tool_name,
                decision.value,
                reason,
                json.dumps(input_data),
                now_iso,
            ),
        )
        await self._db.commit()

        rec = PermissionRecord(
            id=cur.lastrowid or 0,
            session_id=session_id,
            task_id=task_id,
            tool_name=tool_name,
            decision=decision,
            reason=reason,
            input=input_data,
            created_at=now,
        )
        logger.debug("storage.append_permission committed id={}", rec.id)
        return rec

    async def list_permissions(self, session_id: UUID) -> list[PermissionRecord]:
        logger.debug("storage.list_permissions session_id={}", session_id)
        cur = await self._db.execute(
            """SELECT id, session_id, task_id, tool_name, decision, reason,
                      input, consumed_by_session_id, created_at
               FROM permissions
               WHERE session_id = ?
               ORDER BY created_at""",
            (_str_uuid(session_id),),
        )
        rows = await cur.fetchall()
        return [
            PermissionRecord(
                id=r["id"],
                session_id=_parse_uuid(r["session_id"]),
                task_id=_parse_uuid(r["task_id"]),
                tool_name=r["tool_name"],
                decision=PermissionDecision(r["decision"]),
                reason=r["reason"],
                input=json.loads(r["input"]),
                consumed_by_session_id=_parse_uuid(r["consumed_by_session_id"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Connector CRUD
    # ------------------------------------------------------------------

    async def insert_connector(self, connector: Connector) -> Connector:
        logger.debug("storage.insert_connector id={}", connector.id)
        now = _utcnow()
        connector.updated_at = now
        await self._db.execute(
            """INSERT INTO connectors (
                id, name, command, args, env, tool_names, requires_oauth,
                oauth_pre_auth_done, status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _str_uuid(connector.id),
                connector.name,
                connector.command,
                json.dumps(connector.args),
                json.dumps(connector.env),
                json.dumps(connector.tool_names),
                int(connector.requires_oauth),
                int(connector.oauth_pre_auth_done),
                connector.status.value,
                _iso(connector.created_at),
                _iso(connector.updated_at),
            ),
        )
        await self._db.commit()
        logger.debug("storage.insert_connector committed id={}", connector.id)
        return connector

    async def get_connector(self, connector_id: UUID) -> Connector | None:
        logger.debug("storage.get_connector id={}", connector_id)
        cur = await self._db.execute(
            "SELECT * FROM connectors WHERE id = ?", (_str_uuid(connector_id),)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_connector(row)

    async def update_connector(self, connector_id: UUID, **fields: Any) -> Connector:
        logger.debug("storage.update_connector id={} fields={}", connector_id, list(fields.keys()))
        fields["updated_at"] = _utcnow()

        set_clauses: list[str] = []
        values: list[Any] = []
        for key, val in fields.items():
            if isinstance(val, datetime):
                values.append(_iso(val))
            elif isinstance(val, UUID):
                values.append(_str_uuid(val))
            elif isinstance(val, bool):
                values.append(int(val))
            elif isinstance(val, (list, dict)):
                values.append(json.dumps(val))
            else:
                values.append(val)
            set_clauses.append(f"{key} = ?")

        values.append(_str_uuid(connector_id))
        sql = f"UPDATE connectors SET {', '.join(set_clauses)} WHERE id = ?"
        await self._db.execute(sql, values)
        await self._db.commit()

        connector = await self.get_connector(connector_id)
        assert connector is not None
        return connector

    async def delete_connector(self, connector_id: UUID) -> None:
        logger.debug("storage.delete_connector id={}", connector_id)
        await self._db.execute(
            "DELETE FROM connectors WHERE id = ?", (_str_uuid(connector_id),)
        )
        await self._db.commit()
        logger.debug("storage.delete_connector committed id={}", connector_id)

    async def list_connectors(self) -> list[Connector]:
        logger.debug("storage.list_connectors")
        cur = await self._db.execute("SELECT * FROM connectors ORDER BY created_at")
        rows = await cur.fetchall()
        return [self._row_to_connector(r) for r in rows]

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        logger.debug("storage.get_setting key={}", key)
        cur = await self._db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        if row is None:
            return default
        return str(row["value"])

    async def set_setting(self, key: str, value: str) -> None:
        logger.debug("storage.set_setting key={}", key)
        now_iso = _iso(_utcnow())
        await self._db.execute(
            """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, value, now_iso),
        )
        await self._db.commit()
        logger.debug("storage.set_setting committed key={}", key)

    # ------------------------------------------------------------------
    # Row-to-model helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_session(row: Any) -> Session:
        from cowork.models import ProcessIdentity

        pi: ProcessIdentity | None = None
        if row["proc_pid"] is not None and row["proc_start_epoch"] is not None:
            pi = ProcessIdentity(pid=row["proc_pid"], start_time_epoch=row["proc_start_epoch"])

        return Session(
            id=UUID(row["id"]),
            status=SessionStatus(row["status"]),
            title=row["title"],
            prompt=row["prompt"],
            transcript_source=row["transcript_source"],
            mcp_config=json.loads(row["mcp_config"]),
            allowed_tools=json.loads(row["allowed_tools"]),
            denied_tools=json.loads(row["denied_tools"]),
            user_selected_folders=[
                __import__("pathlib").Path(p) for p in json.loads(row["user_selected_folders"])
            ],
            outputs_dir=__import__("pathlib").Path(row["outputs_dir"]),
            cli_session_id=row["cli_session_id"],
            error=row["error"],
            task_id=_parse_uuid(row["task_id"]),
            init_step=row["init_step"],
            num_turns=row["num_turns"],
            is_error=bool(row["is_error"]) if row["is_error"] is not None else None,
            exit_code=row["exit_code"],
            process_identity=pi,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=_parse_dt(row["started_at"]),
            ended_at=_parse_dt(row["ended_at"]),
        )

    @staticmethod
    def _row_to_task(row: Any) -> ScheduledTask:
        return ScheduledTask(
            id=UUID(row["id"]),
            name=row["name"],
            cadence=row["cadence"],
            cron_expr=row["cron_expr"],
            prompt=row["prompt"],
            allowed_tools=json.loads(row["allowed_tools"]),
            status=TaskStatus(row["status"]),
            next_run_at=_parse_dt(row["next_run_at"]),
            last_run_at=_parse_dt(row["last_run_at"]),
            last_run_session_id=_parse_uuid(row["last_run_session_id"]),
            last_run_error=row["last_run_error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_artifact(row: Any) -> Artifact:
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
            deleted_at=_parse_dt(row["deleted_at"]),
        )

    @staticmethod
    def _row_to_connector(row: Any) -> Connector:
        return Connector(
            id=UUID(row["id"]),
            name=row["name"],
            command=row["command"],
            args=json.loads(row["args"]),
            env=json.loads(row["env"]),
            tool_names=json.loads(row["tool_names"]),
            requires_oauth=bool(row["requires_oauth"]),
            oauth_pre_auth_done=bool(row["oauth_pre_auth_done"]),
            status=ConnectorStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
