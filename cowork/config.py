"""Data root and path configuration — 04 §3 on-disk layout."""

from pathlib import Path

DATA_ROOT = Path.home() / ".co-work"

DB_PATH = DATA_ROOT / "cowork.db"
MEMORY_PATH = DATA_ROOT / "memory.md"
SERVER_TOKEN_PATH = DATA_ROOT / "server-token"

HOOKS_DIR = DATA_ROOT / "hooks"
HOOK_SCRIPT_PATH = HOOKS_DIR / "pre-tool-use.sh"

SESSIONS_DIR = DATA_ROOT / "sessions"
TMP_DIR = DATA_ROOT / "tmp"

MEMORY_SIZE_CAP_BYTES = 64 * 1024


def session_dir(session_id: str) -> Path:
    return SESSIONS_DIR / session_id


def outputs_dir(session_id: str) -> Path:
    return session_dir(session_id) / "outputs"


def artifacts_dir(session_id: str) -> Path:
    return session_dir(session_id) / "artifacts"


def transcript_path(session_id: str) -> Path:
    return session_dir(session_id) / "transcript.jsonl"


def audit_path(session_id: str) -> Path:
    return session_dir(session_id) / "audit.jsonl"


def policy_path(session_id: str) -> Path:
    return session_dir(session_id) / "policy.json"


def hook_decisions_path(session_id: str) -> Path:
    return session_dir(session_id) / "hook-decisions.jsonl"


def mcp_config_path(session_id: str) -> Path:
    return TMP_DIR / f"mcp-config-{session_id}.json"
