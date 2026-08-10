"""PermissionGate — spawn-time policy enforcement, folder grant validation, and audit.

Spec refs: 05 §1.4 (interface), 07 §2.2 (merge algorithm), 07 §3 (PermissionGate),
           07 §4 (audit trail), 07 §5 (folder grants).
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger

from cowork import config
from cowork.models import (
    EffectivePolicy,
    PermissionDecision,
    PermissionRecord,
    Session,
)
from cowork.storage import Storage


def resolve_policy(session: Session) -> EffectivePolicy:
    """Compute effective allowlist: denied-wins, default-deny for unlisted.

    Per 07 §2.2: allowed = workspace allowed, denied = workspace denied.
    Any tool in both → denied wins.
    """
    allowed = set(session.allowed_tools)
    denied = set(session.denied_tools)
    allowed -= denied
    return EffectivePolicy(allowed=allowed, denied=denied)


def decide(tool_name: str, policy: EffectivePolicy) -> PermissionDecision:
    """Pure function: tool_name vs policy → GRANT or DENY."""
    return policy.decide(tool_name)


async def record(
    storage: Storage,
    session_id: UUID | None,
    task_id: UUID | None,
    tool_name: str,
    decision: PermissionDecision,
    reason: str,
    input_data: dict[str, Any],
) -> PermissionRecord:
    """Insert DB row (authoritative) + best-effort audit.jsonl mirror."""
    rec = await storage.append_permission(
        session_id=session_id,
        task_id=task_id,
        tool_name=tool_name,
        decision=decision,
        reason=reason,
        input_data=input_data,
    )

    if session_id is not None:
        _mirror_to_audit_jsonl(session_id, rec)

    return rec


def _mirror_to_audit_jsonl(session_id: UUID, rec: PermissionRecord) -> None:
    """Best-effort append to audit.jsonl — catch and log IO errors."""
    audit_file = config.audit_path(str(session_id))
    line = json.dumps(
        {
            "id": rec.id,
            "session_id": str(rec.session_id) if rec.session_id else None,
            "task_id": str(rec.task_id) if rec.task_id else None,
            "tool_name": rec.tool_name,
            "decision": rec.decision.value,
            "reason": rec.reason,
            "input": rec.input,
            "created_at": rec.created_at.isoformat(),
        },
        separators=(",", ":"),
    )
    try:
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        with audit_file.open("a") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.warning("audit.jsonl mirror failed session_id={}: {}", session_id, exc)


def validate_grant(path: Path) -> None:
    """Folder grant validation per 07 §5.

    Raises ValueError for:
    - Non-absolute paths
    - Paths resolving outside $HOME
    - Paths equal to $HOME (too broad)
    - Paths inside ~/.co-work/ EXCEPT ~/.co-work/memory.md
    """
    if not path.is_absolute():
        raise ValueError(f"Grant path must be absolute: {path}")

    home = Path.home()
    resolved = path.resolve()
    home_resolved = home.resolve()

    if not _is_relative_to(resolved, home_resolved):
        raise ValueError(f"Grant path must be under $HOME: {path}")

    if resolved == home_resolved:
        raise ValueError(f"Cannot grant $HOME itself: {path}")

    data_root_resolved = config.DATA_ROOT.resolve()
    memory_resolved = config.MEMORY_PATH.resolve()

    if _is_relative_to(resolved, data_root_resolved) and resolved != memory_resolved:
        raise ValueError(f"Cannot grant app-owned path (except memory.md): {path}")


def _is_relative_to(child: Path, parent: Path) -> bool:
    """Check if child is equal to or under parent."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def generate_policy_file(session_id: UUID, policy: EffectivePolicy) -> Path:
    """Write policy.json to session dir, mode 0o600. Returns the path."""
    policy_file = config.policy_path(str(session_id))
    policy_file.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(
        {
            "sessionId": str(session_id),
            "allowed": sorted(policy.allowed),
            "denied": sorted(policy.denied),
        },
        indent=2,
    )

    policy_file.write_text(content)
    policy_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    logger.debug("policy_file written session_id={} path={}", session_id, policy_file)
    return policy_file


async def consume_approve_future(
    storage: Storage,
    session_id: UUID,
    tool_name: str,
) -> PermissionRecord | None:
    """Find an unconsumed approve_future for tool_name, mark it consumed.

    Only for interactive sessions (task_id is None on the record).
    Returns the consumed record, or None if not found.
    """
    records = await storage.list_permissions(session_id)
    for rec in records:
        if (
            rec.decision == PermissionDecision.APPROVE_FUTURE
            and rec.tool_name == tool_name
            and rec.consumed_by_session_id is None
            and rec.task_id is None
        ):
            await _mark_consumed(storage, rec.id, session_id)
            rec.consumed_by_session_id = session_id
            return rec
    return None


async def _mark_consumed(storage: Storage, record_id: int, consuming_session_id: UUID) -> None:
    """Mark a permission record as consumed by a session."""
    db = storage._db  # noqa: SLF001
    await db.execute(
        "UPDATE permissions SET consumed_by_session_id = ? WHERE id = ?",
        (str(consuming_session_id), record_id),
    )
    await db.commit()


async def ingest_hook_decisions(storage: Storage, session_id: UUID) -> None:
    """Read hook-decisions.jsonl, create PermissionRecord rows.

    Best-effort: log errors and continue on parse failures.
    """
    hook_file = config.hook_decisions_path(str(session_id))
    if not hook_file.exists():
        logger.debug("no hook-decisions.jsonl for session_id={}", session_id)
        return

    logger.debug("ingesting hook-decisions session_id={}", session_id)
    try:
        lines = hook_file.read_text().splitlines()
    except OSError as exc:
        logger.warning("failed to read hook-decisions.jsonl session_id={}: {}", session_id, exc)
        return

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            tool_name = data.get("tool_name", data.get("toolName", "unknown"))
            decision_str = data.get("decision", "deny")
            decision = PermissionDecision(decision_str)
            reason = data.get("reason", "hook decision")
            input_data: dict[str, Any] = data.get("input", {})

            await storage.append_permission(
                session_id=session_id,
                task_id=None,
                tool_name=tool_name,
                decision=decision,
                reason=reason,
                input_data=input_data,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning(
                "hook-decisions.jsonl parse error session_id={} line={}: {}",
                session_id,
                i,
                exc,
            )
