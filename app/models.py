"""Pydantic models matching spec 04-data-model.md."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class SessionStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"
    ARCHIVED = "archived"


class ProcessIdentity(BaseModel):
    pid: int
    start_time_epoch: float


class Session(BaseModel):
    id: UUID
    status: SessionStatus
    title: str = ""
    prompt: str
    transcript_source: Literal["stream-json"] = "stream-json"
    mcp_config: dict[str, Any] = {}
    allowed_tools: list[str] = []
    denied_tools: list[str] = []
    user_selected_folders: list[str] = []
    outputs_dir: str
    cli_session_id: str | None = None
    error: str | None = None
    task_id: UUID | None = None
    init_step: str | None = None
    num_turns: int | None = None
    is_error: bool | None = None
    exit_code: int | None = None
    process_identity: ProcessIdentity | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None


class SessionEvent(BaseModel):
    id: int
    session_id: UUID
    seq: int
    event_type: Literal[
        "init", "message", "user", "tool_use", "tool_result",
        "result", "error", "close", "init_status", "raw",
    ]
    payload: dict[str, Any]
    created_at: datetime


class TaskStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    MISSED = "missed"
    QUEUED = "queued"


class ScheduledTask(BaseModel):
    id: UUID
    name: str
    cadence: Literal["hourly", "daily", "weekly", "weekdays", "manual"] | None = None
    cron_expr: str | None = None
    prompt: str
    allowed_tools: list[str] = []
    status: TaskStatus
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_session_id: UUID | None = None
    last_run_error: str | None = None
    created_at: datetime
    updated_at: datetime


class Artifact(BaseModel):
    id: UUID
    session_id: UUID
    name: str
    rel_path: str
    size_bytes: int
    current_version: int = 1
    content_hash: str
    created_at: datetime
    modified_at: datetime
    deleted_at: datetime | None = None


class ArtifactVersion(BaseModel):
    id: int
    artifact_id: UUID
    version: int
    stored_rel_path: str
    content_hash: str
    size_bytes: int
    created_at: datetime


class PermissionRecord(BaseModel):
    id: int
    session_id: UUID | None = None
    task_id: UUID | None = None
    tool_name: str
    decision: Literal["grant", "deny", "approve_future", "deleted_observed"]
    reason: str
    input: dict[str, Any] = {}
    consumed_by_session_id: UUID | None = None
    created_at: datetime
