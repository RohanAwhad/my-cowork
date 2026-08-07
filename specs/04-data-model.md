# 04 — Data Model

> Writer: W3 (data + interfaces + runtime) | Status: written — pending review
> Binding: glossary statuses, 02 §2 spawn template, 02 §7 concurrency, 03 §6 owned-by lines. Entity shapes are the contract for 05-interfaces and all PRDs.

## 1. Entities (pydantic models)

Seven entities. All field names are binding; JSON columns hold validated pydantic payloads, not free-form JSON.

### 1.1 `Session` — cloned from RE §2 session record (persist-before-spawn, `userSelectedFolders`, `cliSessionId` mapping, `error`)

```python
class SessionStatus(StrEnum):
    PENDING = "pending"; QUEUED = "queued"; RUNNING = "running"
    DONE = "done"; STOPPED = "stopped"; FAILED = "failed"; ARCHIVED = "archived"

class ProcessIdentity(BaseModel):          # PID-reuse guard (02 §7) [design decision]
    pid: int
    startTimeEpoch: float                  # process start time at spawn (ps -o lstart)

class Session(BaseModel):
    id: UUID                               # uuid4; no "local_" prefix [design decision — single user, no namespace; cliSessionId is the separate CLI mapping]
    status: SessionStatus
    title: str = ""                        # set at creation: first ~40 chars of prompt, truncated [invented] (P3-23)
    prompt: str                            # the user's message; v1 is single-turn — result = turn end, no further turns [design decision, RE §2 is multi-turn]
    transcriptSource: Literal["stream-json"]
    mcpConfig: dict[str, Any]              # resolved connector servers {name: {command, args, env}}; compiled by ConnectorRegistry (05 §1.8)
    allowedTools: list[str]                # effective allowlist at spawn (workspace ∪ user; exact merge rule → 07)
    deniedTools: list[str]                 # --disallowedTools; always binds (02 §2)
    userSelectedFolders: list[Path]        # FolderGrant folded in [design decision — pre-spawn UI state only, no runtime dialog (glossary); RE §2 stores them on the session record]
    outputsDir: Path                       # per-session outputs dir (04 §3)
    cliSessionId: str | None = None        # set on `init` event (RE session-lifecycle §6.2)
    error: str | None = None
    taskId: UUID | None = None             # non-null ⇔ scheduled run (per-run = own session, mission §3.2)
    initStep: str | None = None            # auth|skills|prompt|mcp_setup|query|complete (RE session-lifecycle §2, mapped in 05 §2.2) [design decision]
    numTurns: int | None = None            # from `result` event
    isError: bool | None = None            # from `result` event
    exitCode: int | None = None            # CLI exit code (0 = clean EOF)
    processIdentity: ProcessIdentity | None = None
    createdAt: datetime
    updatedAt: datetime
    startedAt: datetime | None = None
    endedAt: datetime | None = None
```
Justification: RE §2 — record persisted **before** spawn, first message buffered; RE §7 — transcript NOT in the record (Cowork keeps CLI jsonl; we keep `SessionEvent` rows, 04 §1.2).

### 1.2 `SessionEvent` — [design decision] transcript as rows, assembled from stream-json events

```python
class SessionEvent(BaseModel):
    id: int
    sessionId: UUID
    seq: int                               # monotonic per session; WS replay cursor (05 §1.1)
    eventType: Literal["init","message","user","tool_use","tool_result","result","error","close","init_status","raw"]
    payload: dict[str, Any]                # shape per 05 §2 mapping table
    createdAt: datetime
```
Justification: Cowork stores transcript in `.claude/projects/*.jsonl` (RE §7) and re-parses it; we assemble from the stream-json pipe instead — no jsonl re-parse (03 §6 line 81 → 05-interfaces; decision made in 05 §2.2). `SessionEvent` rows are the **primary** transcript store; the raw event log is retained in `transcript.jsonl` (04 §3) as the pre-assembly source (P3-20). Unmapped stream-json types are stored as `eventType="raw"` with the verbatim payload — the pipeline never raises on unknown events (P1-2).

### 1.3 `ScheduledTask` — cloned from RE §6 local `.claude/scheduled_tasks/<id>.json` store

```python
class TaskStatus(StrEnum):
    ACTIVE = "active"; PAUSED = "paused"; DISABLED = "disabled"
    MISSED = "missed"; QUEUED = "queued"    # queued = fired while any run slot is busy (interactive or scheduled; 06 §3 row 2)

class ScheduledTask(BaseModel):
    id: UUID
    name: str
    cadence: Literal["hourly","daily","weekly","weekdays","manual"] | None = None  # RE §6 cadence enum; manual = user-triggered ("run now")
    cronExpr: str | None = None            # croniter 5-field (custom); croniter justified in 05 §1.7 [invented dependency]
    prompt: str                            # run prompt; spawned per run as own session
    allowedTools: list[str]                # auto-approve policy → spawn --allowedTools under --permission-mode manual (RE §6 shouldAutoApprovePermission analog)
    status: TaskStatus
    nextRunAt: datetime | None = None      # None for manual cadence until fired; computed from cadence or cronExpr (05 §1.7)
    lastRunAt: datetime | None = None
    lastRunSessionId: UUID | None = None
    lastRunError: str | None = None        # mid-flight crash stub (03 §6 line 84; retry policy → prd-scheduled-tasks)
    createdAt: datetime
    updatedAt: datetime
```
Justification: RE §6 — local job store, auto-approve gate; [design decision] SQLite instead of JSON files; per-run = own session (mission §3.2). Exactly one of `cadence`/`cronExpr` is set (Storage-validated). Wall-clock semantics: stored/compared in UTC; DST/rollover policy (croniter is wall-clock) → prd-scheduled-tasks (P2-10).

### 1.4 `Artifact` + `ArtifactVersion` — cloned from RE §2 `fs_file_created` detection; versioning [design decision]

```python
class Artifact(BaseModel):
    id: UUID
    sessionId: UUID
    name: str
    relPath: str                           # path relative to session outputsDir
    sizeBytes: int
    currentVersion: int = 1
    contentHash: str                       # sha256 of latest version
    createdAt: datetime
    modifiedAt: datetime
    deletedAt: datetime | None = None

class ArtifactVersion(BaseModel):
    id: int
    artifactId: UUID
    version: int                           # 1..N
    storedRelPath: str                     # <sessions>/<id>/artifacts/<name>__v<N>_<hash8>.<ext> (04 §3)
    contentHash: str
    sizeBytes: int
    createdAt: datetime
```
Justification: detection semantics cloned from RE §1/§2 (`fs_file_created`/`fs_file_deleted`, non-recursive watch); Cowork versions server-side (RE §10) — v1 versions locally as `<name>__v<N>_<hash8>.<ext>`: the filename suffix is the **hash8** of the file content, the version timestamp is the `ArtifactVersion.createdAt` row time (not part of the filename) [design decision]; exact scheme resolved by prd-live-artifacts. Names are sanitized at `version_file`: `..` segments and `/` path separators in artifact names are rejected before any copy (P2-16).

### 1.5 `PermissionRecord` — cloned from RE §4 `audit.jsonl` (permission_request / permission_response trail)

```python
class PermissionRecord(BaseModel):
    id: int
    sessionId: UUID | None = None
    taskId: UUID | None = None
    toolName: str                          # mcp__<server>__<tool> or builtin name
    decision: Literal["grant","deny","approve_future","deleted_observed"]   # approve_future applies to next spawn only (mission §3.1); deleted_observed: watcher-sourced deletion (07 §4.1–4.2) — toolName="fs_delete", input={path}
    reason: str                            # e.g. "tool_use correlated against effective allowlist: not listed" (mission §5)
    input: dict[str, Any]                  # tool_use.input snapshot
    consumedBySessionId: UUID | None = None  # approve_future: which later session consumed it at spawn (P3-22)
    createdAt: datetime
```
Justification: RE §4 — full audit trail of every grant/deny/approval; [design decision] SQLite table (03 §3 Storage) + per-session `audit.jsonl` mirror (RE §7). The DB row is **authoritative**; the `audit.jsonl` mirror is best-effort, appended after commit — a divergence is resolved from the DB (P2-14). Denials are deterministic correlations, never `tool_result` string parsing (mission §5).

### 1.6 `Connector` — [design decision] config-only registry; shape from RE §5 connector `{uuid,name,url,toolNames,isConnected}`

```python
class Connector(BaseModel):
    id: UUID
    name: str
    command: str                           # e.g. npx, uvx
    args: list[str]
    env: dict[str, str] = {}
    toolNames: list[str]                   # inventory CACHE of mcp__<server>__<tool> names (from CLI-side tools/list probe, prd-mcp-connectors); the per-tool policy matrix in connector_tools (04 §2) decides allow/ask/blocked — this list does not decide; default [] → unlisted tools are denied (P2-15)
    requiresOAuth: bool = False            # interactive-OAuth excluded from scheduled runs (02 §2; mcp PRD)
    oauthPreAuthDone: bool = False         # via `claude mcp login` outside sessions [design decision; mcp PRD]
    status: Literal["registered","disabled"] = "registered"
    createdAt: datetime
    updatedAt: datetime
```
Justification: no in-app MCP client (03 §3); connectors enter via CLI `--mcp-config`/`--strict-mcp-config` (02 §2). Pre-auth flow → prd-mcp-connectors.

### 1.7 `Settings` — [invented] key/value store, typed accessors

```python
class Settings(BaseModel):
    claudeVersionPin: str | None = None   # 02 §2 pinning; user override recorded in audit trail [design decision]
    serverPort: int = 8765                # 05 §1.1
    schedulerTickSeconds: int = 15
    spawnHealthTimeoutSeconds: int = 30
    runnerNoEventTimeoutMinutes: int = 10 # hung-runner watchdog (06 §4/§5) [invented]
    memoryEnabled: bool = True            # workspace memory carve-out (memory.md, 04 §3; 07 §5.3) [design decision; prd-memory]
    schedulerMaxConsecutiveFailures: int = 5  # task auto-disable threshold (04 §4.2) [invented]
    lastBootAt: datetime | None = None    # set at startup; missed-run down-window (P1-3) — server-only, excluded from the API view (05 §1.1, P3-1)
    logLevel: str = "INFO"                # LOGGING_LEVEL
```
Stored as `settings(key TEXT PK, value JSON)`. Justification: version pinning + runtime tuning knobs have no Cowork analog (Cowork pins at build time, RE §3).

## 2. SQLite schema

One database: `~/.co-work/cowork.db` (04 §3). WAL mode, foreign keys on, single writer = Storage (02 §7).

```sql
PRAGMA journal_mode = WAL;      -- set at open; persists in -wal/-shm files
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE sessions (
  id            TEXT PRIMARY KEY,          -- uuid4
  status        TEXT NOT NULL,             -- pending|queued|running|done|stopped|failed|archived
  title         TEXT NOT NULL DEFAULT '',
  prompt        TEXT NOT NULL,
  transcript_source TEXT NOT NULL DEFAULT 'stream-json',
  mcp_config    TEXT NOT NULL DEFAULT '{}',-- JSON dict
  allowed_tools TEXT NOT NULL DEFAULT '[]',-- JSON list[str]
  denied_tools  TEXT NOT NULL DEFAULT '[]',
  user_selected_folders TEXT NOT NULL DEFAULT '[]', -- JSON list[str] (abs paths)
  outputs_dir   TEXT NOT NULL,
  cli_session_id TEXT,                     -- NULL until init event
  error         TEXT,
  task_id       TEXT REFERENCES tasks(id) ON DELETE SET NULL,  -- deleting a task never orphans sessions (P1-4)
  init_step     TEXT,
  num_turns     INTEGER,
  is_error      INTEGER,
  exit_code     INTEGER,
  proc_pid      INTEGER,
  proc_start_epoch REAL,
  created_at    TEXT NOT NULL,             -- ISO-8601 UTC
  updated_at    TEXT NOT NULL,
  started_at    TEXT,
  ended_at      TEXT
);
CREATE INDEX idx_sessions_status ON sessions(status);          -- sessions-by-status (UI list, queue drain)
CREATE INDEX idx_sessions_task  ON sessions(task_id);

CREATE TABLE session_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  seq        INTEGER NOT NULL,             -- monotonic per session
  event_type TEXT NOT NULL,                -- init|message|user|tool_use|tool_result|result|error|close|init_status|raw
  payload    TEXT NOT NULL,                -- JSON
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_events_session_seq ON session_events(session_id, seq);  -- transcript + WS replay

CREATE TABLE tasks (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  cadence     TEXT,                        -- hourly|daily|weekly|weekdays|manual (RE §6); NULL when cron_expr set
  cron_expr   TEXT,                        -- croniter 5-field; NULL when cadence set (exactly one set, Storage-validated)
  prompt      TEXT NOT NULL,
  allowed_tools TEXT NOT NULL DEFAULT '[]',
  status      TEXT NOT NULL,               -- active|paused|disabled|missed|queued
  next_run_at TEXT,                        -- NULL for manual cadence until fired
  last_run_at TEXT,
  last_run_session_id TEXT,
  last_run_error TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX idx_tasks_next_run ON tasks(status, next_run_at); -- tasks-by-next-run (scheduler tick)

CREATE TABLE artifacts (
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
CREATE INDEX idx_artifacts_session ON artifacts(session_id);   -- artifacts-by-session (workspace list)

CREATE TABLE artifact_versions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  version     INTEGER NOT NULL,
  stored_rel_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  size_bytes  INTEGER NOT NULL,
  created_at  TEXT NOT NULL,
  UNIQUE (artifact_id, version)
);

CREATE TABLE permissions (                  -- audit trail (03 §3); DB row authoritative + best-effort mirror to per-session audit.jsonl (P2-14)
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT REFERENCES sessions(id),
  task_id     TEXT REFERENCES tasks(id) ON DELETE SET NULL,   -- audit rows survive task deletion (P1-4)
  tool_name   TEXT NOT NULL,
  decision    TEXT NOT NULL,               -- grant|deny|approve_future|deleted_observed
  reason      TEXT NOT NULL,
  input       TEXT NOT NULL DEFAULT '{}',  -- JSON
  consumed_by_session_id TEXT,             -- approve_future: consuming session (P3-22)
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_permissions_session ON permissions(session_id, created_at);  -- audit-by-session

CREATE TABLE connectors (
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

CREATE TABLE connector_tools (              -- per-connector tool policy matrix (07; prd-mcp-connectors; 04 §1.6)
  connector_id TEXT NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
  tool_name    TEXT NOT NULL,               -- mcp__<server>__<tool>
  policy       TEXT NOT NULL CHECK (policy IN ('always','ask','blocked')),
  PRIMARY KEY (connector_id, tool_name)
);

CREATE TABLE settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,                -- JSON
  updated_at TEXT NOT NULL
);
```

Transaction boundaries (Storage, 05 §1.9): each public method = one transaction; a session status transition commits status + terminal fields + the triggering `session_events` row atomically. `transition(→ running)` validates the one-active invariant (no other `running` row exists) in the **same transaction** — no TOCTOU window (P1-5).

## 3. On-disk layout (outside SQLite)

Workspace data root: **`~/.co-work/`** [design decision]. Justification: Cowork nests `userData/local-agent-mode-sessions/<account>/<org>/` (RE §7) — v1 has no account/org (mission §2), so a flat dotdir in `$HOME`, sibling to `~/.claude` (user config, shared at spawn, 02 §2) keeps all app state in one discoverable place.

```
~/.co-work/                        # created by SessionManager at startup
  cowork.db (+ -wal, -shm)         # SQLite; created by Storage
  memory.md                        # workspace memory root (global read/write memory, prd-memory; carve-out 07 §5.3) [design decision]
  server-token                     # WorkspaceServerToken, chmod 0600, written once at first run; regeneration = delete the file (lifecycle owned by 07 §6.2)
  hooks/pre-tool-use.sh            # static PreToolUse hook script, installed once with user consent (02 §2; 07 §5.3, prd-local-files §3.3)
  sessions/<id>/                   # per-session dir; mirrors Cowork <sessionId>/ dirs (RE §7)
    outputs/                       # outputs dir — created by SessionManager BEFORE spawn (RE §2 persistence-before-spawn)
    artifacts/                     # versioned copies (<name>__v<N>_<hash8>.<ext>); created by ArtifactWatcher
    audit.jsonl                    # best-effort human-readable audit mirror (RE §7; one JSON object per PermissionRecord; DB row is authoritative, appended after commit, P2-14; 50 MB cap, then refuse-write+log [design decision])
    transcript.jsonl               # raw stream-json event log (pre-assembly source; 05 §2) [design decision]
    policy.json                    # per-session spawn-time policy file, chmod 0600, written by PermissionGate per spawn, deleted at session end — NOT with the session dir (dirs persist until archive); path unified with 07 §5.3 [design decision]
    hook-decisions.jsonl           # append-only hook decision log (hook script appends one JSON object per decision, prd-local-files §2.5/§3.3; ingested into PermissionRecord at session close, prd-memory D6)
  tmp/mcp-config-<sessionid>.json  # compiled per-session --mcp-config (02 §2); created by ConnectorRegistry, deleted on session end
```

Creation owners: SessionManager → root, `sessions/<id>/`, `outputs/` (mkdir recursive, pre-spawn), `memory.md`; ArtifactWatcher → `artifacts/`; Storage → `cowork.db`, `audit.jsonl`, `transcript.jsonl`; ConnectorRegistry → `tmp/`; PermissionGate → `sessions/<id>/policy.json` (per spawn, deleted at session end) + `sessions/<id>/hook-decisions.jsonl` (ingested at session close); WorkspaceServer → `server-token` (0600, first-run write; regeneration via deletion, 07 §6.2); install-once with consent → `hooks/pre-tool-use.sh` (07 §5.3).

Outputs location: per-session `sessions/<id>/outputs`, **not** the shared-cwd pattern (`~/Documents/Claude/outputs`, RE session-lifecycle §7.6) [design decision] — keeps outputs colocated with the session and trivially watchable; the shared-cwd variant adds nothing for a single user.

## 4. State machines

### 4.1 Session.status — transitions, triggers, actors

| From | To | Trigger | Actor |
|---|---|---|---|
| pending | queued | scheduled trigger fires while a run slot is busy — one-active rule (02 §7) | SchedulerEngine |
| pending | running | spawn → flush first message → `init` event within timeout (binds cliSessionId; a non-`init` `system` keeps the timer, probe) (P1-1, 02 §2) | SessionManager (via RunnerAdapter) |
| pending | failed | pre-spawn error (settings/connector resolution) | SessionManager |
| pending | failed | spawn error, binary missing, or health-check timeout — teardown group-kill applies on this path (P1-7) | SessionManager |
| pending | failed | boot reconcile: app died while pending (P3-2) | Runtime (boot) |
| queued | running | slot free: active session ended + queue drain (04 §4.3) | SchedulerEngine → SessionManager |
| queued | running | boot reconcile: app died while queued, slot free at boot → run directly (P1-6) | Runtime (boot) |
| queued | stopped | user cancels the queued run | WorkspaceServer → SessionManager |
| queued | failed | graceful app shutdown (06 §2.2) | Runtime (shutdown) |
| queued | failed | boot reconcile: queued session with no task row (orphan, P3-2) | Runtime (boot) |
| queued | failed | drain failure: `start_session` raises — task returns to `active`, retried at the next scheduled occurrence (P2-2) | SchedulerEngine |
| running | done | `result` event received (num_turns, is_error) | RunnerAdapter → SessionManager |
| running | stopped | user stop; teardown protocol completed (02 §2) | WorkspaceServer → SessionManager |
| running | stopped | graceful app shutdown teardown (06 §2.2) | Runtime (shutdown) |
| running | failed | runner crash / EOF mid-turn / `error` event / watchdog no-event timeout (06 §4) | RunnerAdapter → SessionManager |
| done | archived | user archives | WorkspaceServer → SessionManager |
| stopped | archived | user archives | WorkspaceServer → SessionManager |
| failed | archived | user archives | WorkspaceServer → SessionManager |

Rules: no transition outside the glossary chain `pending → queued → running → done | stopped | failed | archived`; Storage rejects illegal transitions with an exception (fail fast, 02 §6), and `transition(→ running)` additionally rejects when another `running` row exists — same transaction (P1-5). `archived` is terminal. Stopped sessions are NOT resumable in v1 — `--resume` is not in the spawn template [design decision] (03 §6 line 81); transcript and artifacts persist.

### 4.2 Task.status — transitions, triggers, actors

| From | To | Trigger | Actor |
|---|---|---|---|
| active | queued | trigger fired while a run slot is busy (02 §7 conflict policy) | SchedulerEngine |
| active | missed | trigger fired while app was down (detected at boot from the down-window `(lastBootAt, now)`) | SchedulerEngine (boot) |
| active | paused | user pauses | WorkspaceServer → SchedulerEngine |
| active | disabled | user disables | WorkspaceServer → SchedulerEngine |
| active | disabled | auto-disable: `Settings.schedulerMaxConsecutiveFailures` consecutive failed runs (session `failed` incl. mid-flight crash and drain failure; a `done` resets) | SchedulerEngine |
| paused | active | user resumes | WorkspaceServer → SchedulerEngine |
| disabled | active | user enables | WorkspaceServer → SchedulerEngine |
| queued | active | queued run actually started (its session entered `running`) | SchedulerEngine |
| queued | paused | user pauses the task; the queued session (if any) continues to drain — pause affects future runs only (prd-scheduled-tasks §4.1) | WorkspaceServer → SchedulerEngine |
| queued | disabled | user disables the queued run | WorkspaceServer → SchedulerEngine |
| missed | queued | replay due at boot — direct-create queued session (P1-8); `tick` never selects `missed` tasks | SchedulerEngine (boot) |
| missed | active | replay skipped; next occurrence recomputed (`croniter.next`) | SchedulerEngine (boot) |

**Boot rule (binding, P1-4/P1-6):** `task.status=queued` with a live `queued` session row → that session runs directly at boot (`queued → running`, slot is free); `task.status=queued` with **no** queued session (orphan from a crash between the two writes of 04 §4.3 step 1) → `queued → active`, `nextRunAt` recomputed.

Missed-run replay policy (which occurrences replay, coalescing) is owned by prd-scheduled-tasks; 04/06 define the trigger mechanism only (03 §6 line 78). A run that crashed mid-flight leaves the task `active` — it is neither `missed` nor re-fired (03 §6 line 84; `lastRunError` records it; retry policy → prd-scheduled-tasks).

### 4.3 Queued-session handoff (SchedulerEngine ⇄ SessionManager)

1. Tick fires; due task; slot busy → SchedulerEngine writes the `Session(status=queued, taskId=task.id)` row **FIRST**, then sets `task.status=queued` (P1-4 write order — a crash between the two writes leaves `task=queued` with no session; resolved at boot, §4.2), publishes `sched.notice(action="queued")` (05 §1.5), and re-arms a drain attempt immediately — a session may have ended during the enqueue (P1-5).
2. Active session ends → SessionManager publishes `session.ended` on EventBus (05 §1.5).
3. SchedulerEngine drains queue: oldest queued task+session → publishes `sched.notice(action="drained")` (P3-4) → `SessionManager.start_session(session_id)` → session transitions `queued → running` (pending-path spawn); task → `active` with `nextRunAt = croniter.next(now)`.
4. Drain failure (P1-5/P2-2): `start_session` raises (invariant/race) → the queued session transitions `queued → failed` (`error="drain failed"`), task returns to `active` with `nextRunAt` recomputed to the next occurrence — retried only via the normal schedule, never a stranded `queued` row and never re-armed on the next tick (04 §4.1).
5. User cancels a queued session → `queued → stopped`; task → `active`, next run recomputed.
6. Invariant (02 §7): SessionManager is the gatekeeper (03 §6 note) — only SchedulerEngine may create `queued` sessions, and only SessionManager may move a session to `running`; one run slot total in v1 (interactive and scheduled runs share it; scheduled runs are serialized). An interactive start while queued sessions exist is **allowed** — interactive sessions preempt the queue; the queued session stays `queued` and drains afterward. The check is not only at `start_session` entry: `Storage.transition(→ running)` rejects inside the same transaction if another `running` row exists (P1-5) — no TOCTOU window.
