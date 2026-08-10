"""Pydantic entity models — all 7 entities from spec 04 §1 plus helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SessionStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    MISSED = "missed"
    QUEUED = "queued"


class PermissionDecision(StrEnum):
    GRANT = "grant"
    DENY = "deny"
    APPROVE_FUTURE = "approve_future"
    DELETED_OBSERVED = "deleted_observed"


class ConnectorStatus(StrEnum):
    REGISTERED = "registered"
    DISABLED = "disabled"


class SessionEventType(StrEnum):
    INIT = "init"
    MESSAGE = "message"
    USER = "user"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    RESULT = "result"
    ERROR = "error"
    CLOSE = "close"
    INIT_STATUS = "init_status"
    RAW = "raw"


# ---------------------------------------------------------------------------
# Helper models
# ---------------------------------------------------------------------------

class ProcessIdentity(BaseModel):
    """PID-reuse guard — 02 §7."""
    pid: int
    start_time_epoch: float


class SpawnSpec(BaseModel):
    """RunnerAdapter spawn parameters — 05 §2.1."""
    session_id: UUID
    prompt: str
    cwd: Path
    folder_grants: list[Path] = Field(default_factory=list)
    permission_mode: Literal["manual"] = "manual"
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    add_dirs: list[Path] = Field(default_factory=list)
    mcp_config_path: Path | None = None
    strict_mcp_config: bool = False
    append_system_prompt: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class EffectivePolicy(BaseModel):
    """Spawn-time resolved permission policy — 07 §2.2."""
    allowed: set[str] = Field(default_factory=set)
    denied: set[str] = Field(default_factory=set)

    def decide(self, tool_name: str) -> PermissionDecision:
        if tool_name in self.denied:
            return PermissionDecision.DENY
        if tool_name in self.allowed:
            return PermissionDecision.GRANT
        return PermissionDecision.DENY


class StreamJsonEvent(BaseModel):
    """Unwrapped stream-json event — 05 §2.2."""
    type: str
    session_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    raw: str | None = None


class UserMessage(BaseModel):
    """NDJSON stdin envelope — 05 §3.1."""
    type: Literal["user"] = "user"
    uuid: UUID = Field(default_factory=uuid4)
    session_id: str | None = None
    message: dict[str, Any] = Field(default_factory=dict)


class SessionCreate(BaseModel):
    """API input for creating sessions — 05 §1.1."""
    prompt: str
    folder_grants: list[Path] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)


class SessionSummary(BaseModel):
    """Workspace list rows — 05 §1.1."""
    id: UUID
    status: SessionStatus
    title: str
    created_at: datetime
    updated_at: datetime
    num_turns: int | None = None
    is_error: bool | None = None
    task_id: UUID | None = None
    artifact_count: int = 0


class MemorySnapshot(BaseModel):
    """Workspace memory state."""
    content: str
    size_bytes: int
    modified_at: datetime


# ---------------------------------------------------------------------------
# Entity 1: Session — 04 §1.1
# ---------------------------------------------------------------------------

class Session(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    status: SessionStatus = SessionStatus.PENDING
    title: str = ""
    prompt: str
    transcript_source: Literal["stream-json"] = "stream-json"
    mcp_config: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    user_selected_folders: list[Path] = Field(default_factory=list)
    outputs_dir: Path = Path()
    cli_session_id: str | None = None
    error: str | None = None
    task_id: UUID | None = None
    init_step: str | None = None
    num_turns: int | None = None
    is_error: bool | None = None
    exit_code: int | None = None
    process_identity: ProcessIdentity | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    ended_at: datetime | None = None


# ---------------------------------------------------------------------------
# Entity 2: SessionEvent — 04 §1.2
# ---------------------------------------------------------------------------

class SessionEvent(BaseModel):
    id: int = 0
    session_id: UUID
    seq: int
    event_type: SessionEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Entity 3: ScheduledTask — 04 §1.3
# ---------------------------------------------------------------------------

class ScheduledTask(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    cadence: Literal["hourly", "daily", "weekly", "weekdays", "manual"] | None = None
    cron_expr: str | None = None
    prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.ACTIVE
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_session_id: UUID | None = None
    last_run_error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Entity 4: Artifact — 04 §1.4
# ---------------------------------------------------------------------------

class Artifact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    name: str
    rel_path: str
    size_bytes: int
    current_version: int = 1
    content_hash: str
    created_at: datetime = Field(default_factory=_utcnow)
    modified_at: datetime = Field(default_factory=_utcnow)
    deleted_at: datetime | None = None


# ---------------------------------------------------------------------------
# Entity 5: ArtifactVersion — 04 §1.4
# ---------------------------------------------------------------------------

class ArtifactVersion(BaseModel):
    id: int = 0
    artifact_id: UUID
    version: int
    stored_rel_path: str
    content_hash: str
    size_bytes: int
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Entity 6: PermissionRecord — 04 §1.5
# ---------------------------------------------------------------------------

class PermissionRecord(BaseModel):
    id: int = 0
    session_id: UUID | None = None
    task_id: UUID | None = None
    tool_name: str
    decision: PermissionDecision
    reason: str
    input: dict[str, Any] = Field(default_factory=dict)
    consumed_by_session_id: UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Entity 7: Connector — 04 §1.6
# ---------------------------------------------------------------------------

class Connector(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    tool_names: list[str] = Field(default_factory=list)
    requires_oauth: bool = False
    oauth_pre_auth_done: bool = False
    status: ConnectorStatus = ConnectorStatus.REGISTERED
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Entity 8: Settings — 04 §1.7
# ---------------------------------------------------------------------------

class Settings(BaseModel):
    claude_version_pin: str | None = None
    server_port: int = 8765
    scheduler_tick_seconds: int = 15
    spawn_health_timeout_seconds: int = 30
    runner_no_event_timeout_minutes: int = 10
    memory_enabled: bool = True
    scheduler_max_consecutive_failures: int = 5
    last_boot_at: datetime | None = None
    log_level: str = "INFO"
