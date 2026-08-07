# 05 — Interfaces

> Writer: W3 | Status: written — pending review
> Contracts (signatures, not implementations) for the ten components (glossary, binding). pydantic-friendly typed signatures. Exact merge rule for the effective allowlist → 07; WorkspaceServerToken → 07.

## 1. Interface contracts

Shared shapes (P3-23):

```python
class SessionSummary(BaseModel):           # workspace list rows
    id: UUID; status: SessionStatus; title: str; createdAt: datetime
    updatedAt: datetime; numTurns: int | None; isError: bool | None
    taskId: UUID | None; artifactCount: int = 0

class UserMessage(BaseModel):              # stdin NDJSON envelope (05 §3.1; RE session-lifecycle §1.4)
    type: Literal["user"] = "user"
    uuid: UUID
    session_id: str | None = None          # our session UUID until `init` binds cliSessionId
    message: dict[str, Any]                # {role:"user", content:[{type:"text","text":...}]}

class StreamJsonEvent(BaseModel):          # unwrapped stream-json event (05 §2.2)
    type: str                              # documented: system|assistant|user|tool_use|tool_result|result|error|stream_event; unknown → stored `raw`
    session_id: str | None = None
    payload: dict[str, Any] = {}
    raw: str | None = None                 # verbatim JSON line → transcript.jsonl (04 §3)
```

### 1.1 `WorkspaceServer` — FastAPI + websockets, 127.0.0.1 only (02 §4)

Binds `127.0.0.1:<Settings.serverPort>` (default **8765** [design decision — Cowork's dev WS relay uses `ws://localhost:8765`, RE §5; single port serves HTTP + WS]). Token/origin checks → 07.

**HTTP routes** (client → server commands; JSON in/out, pydantic-validated):

| Route | Method | In | Out |
|---|---|---|---|
| `/` | GET | — | static workspace UI (no build step, 02 §5) |
| `/api/sessions` | GET | `?status=` | `list[SessionSummary]` |
| `/api/sessions` | POST | `SessionCreate{prompt, folderGrants: list[Path], allowedTools?, deniedTools?}` | `Session` (created, `pending`) |
| `/api/sessions/{id}/stop` | POST | — | `Session` |
| `/api/sessions/{id}/archive` | POST | — | `Session` |
| `/api/sessions/{id}/transcript` | GET | — | `list[SessionEvent]` (by seq) |
| `/api/sessions/{id}/events` | GET | `?after_seq=` | `list[SessionEvent]` — WS replay cursor |
| `/api/tasks` | GET/POST | `TaskCreate{name, cadence?, cronExpr?, prompt, allowedTools}` | `list[ScheduledTask]` / `ScheduledTask` |
| `/api/tasks/{id}` | PATCH/DELETE | `TaskPatch{status?, cadence?, cronExpr?, prompt?, allowedTools?}` | `ScheduledTask` |
| `/api/tasks/{id}/run` | POST | — | `ScheduledTask` (P2-1 — manual trigger / run-now: fires via the 04 §4.3 path — direct start if the slot is free, else queued) |
| `/api/connectors` | GET/POST | `ConnectorCreate{name, command, args, env, requiresOAuth?}` | `list[Connector]` / `Connector` |
| `/api/connectors/{id}` | DELETE | — | — |
| `/api/connectors/{id}/refresh` | POST | — | `Connector` (re-runs the tools/list probe; `probeError` set on failure) |
| `/api/connectors/{id}/tools` | PUT | `list[{toolName, policy: always\|ask\|blocked}]` | `Connector` (writes the connector_tools matrix, 04 §2) |
| `/api/artifacts` | GET | `?session_id=` | `list[Artifact]` (+ versions) |
| `/api/permissions` | GET | `?session_id=` | `list[PermissionRecord]` |
| `/api/settings` | GET/PUT | — | `Settings` |
| `/api/memory` | GET/PUT | `{text: str}` | `{text: str}` (workspace memory root `memory.md`, 04 §3; gated by `Settings.memoryEnabled`) |

`GET /previews/{session_id}/{artifact_id}/v{N}` — artifact content (browser-native embeds, 02 §5).

Cadence↔cron conversion (P2-1, 1:1 for fixed cadences): `hourly = 0 * * * *`, `daily = 0 0 * * *`, `weekly = 0 0 * * 0`, `weekdays = 0 0 * * 1-5`; `manual` means run-now only (`nextRunAt=None`, fires via `/api/tasks/{id}/run`).

`Settings.lastBootAt` is server-only (P3-1): excluded from the GET/PUT `/api/settings` view so round-trips cannot clobber it.

**WS `/ws`** (server → client event stream only; all commands over HTTP [design decision — pure event channel, trivially reconnectable]). Initial message set:

| Message | Payload | Source (EventBus topic) |
|---|---|---|
| `session.started` | `{sessionId}` | SESSION |
| `session.init_status` | `{sessionId, step}` — steps `auth→skills→prompt→mcp_setup→query→complete` (RE session-lifecycle §2) [design decision mapping] | SESSION |
| `session.event` | `{sessionId, seq, eventType, payload}` — stream relay (05 §2) | SESSION |
| `session.updated` | `{sessionId, status}` | SESSION |
| `session.ended` | `{sessionId, status, reason}` | SESSION |
| `session.archived` | `{sessionId}` | SESSION |
| `artifact.created` / `artifact.updated` / `artifact.deleted` | `{artifact}` / `{artifact, version}` / `{artifactId}` | ARTIFACT |
| `permission.notice` | `{sessionId, toolName, decision, reason}` — report-only (glossary) | PERMISSION |
| `task.created` / `task.updated` / `task.deleted` | `{task}` | SCHEDULER |
| `sched.notice` | `{taskId, action}` — `queued\|drained\|missed\|started` (started = direct-start scheduled run, P3-25) | SCHEDULER |
| `connector.updated` | `{connector, probeError: str \| None = None}` | CONNECTOR |

WS client disconnect does not affect sessions (06 §5); reconnect replays via `GET /api/sessions/{id}/events?after_seq=`. Subscriber isolation: a dead WS connection is dropped, never fed back into the bus (1.5).

### 1.2 `SessionManager` — lifecycle policy owner (03 §3)

```python
def create_session(create: SessionCreate, task_id: UUID | None = None) -> Session  # persist BEFORE spawn (RE §2); status=pending
def start_session(session_id: UUID) -> Session     # gatekeeper of one-active invariant (02 §7); final authority is Storage.transition (P1-5)
def stop_session(session_id: UUID) -> None                 # teardown protocol (05 §3.3)
def archive_session(session_id: UUID) -> None              # terminal
def active_session() -> Session | None                     # queried by SchedulerEngine (04 §4.3)
def get_session(session_id: UUID) -> Session
def list_sessions(status: SessionStatus | None = None) -> list[Session]
# internal event handlers (called by RunnerAdapter):
def _on_init(s: Session, cli_session_id: str) -> None      # session.cliSessionId = ...; publish session.started + init_status complete
def _on_stream_event(s: Session, ev: StreamJsonEvent) -> None  # map+persist SessionEvent (05 §2.2); publish session.event
def _on_result(s: Session, num_turns: int, is_error: bool) -> None  # running→done; publish session.ended
def _on_error(s: Session, err: str) -> None                # running→failed; publish session.ended
def _on_close(s: Session, exit_code: int) -> None          # process exit observed; final flush
```
Publishes on `Topic.SESSION`; persists via `Storage` (session row + events in one transaction per event batch). Stop/archive/ended also trigger queue drain via SchedulerEngine's EventBus subscription (04 §4.3).

No `send_message` (P2-11): v1 is single-turn — the first message is the only message (flushed post-spawn, P1-1); `result` = turn end, no further turns [design decision, RE §2 is multi-turn]. Cowork's hot-path `sendMessage` (RE §6.1) is out of scope.

### 1.3 `RunnerAdapter` — process mechanics owner; sole kernel abstraction (02 §2)

```python
def spawn(spec: SpawnSpec) -> RunnerHandle
class RunnerHandle:
    async def send(self, msg: UserMessage) -> None        # NDJSON on stdin
    async def close_input(self) -> None                   # stdin EOF (02 §2 teardown start)
    async def stop(self) -> None                          # EOF → SIGTERM → SIGKILL, process GROUP (05 §3.3)
    def events(self) -> AsyncIterator[StreamJsonEvent]    # parsed stdout NDJSON
    def stderr(self) -> AsyncIterator[str]                # tail captured for session.error
    @property def pid(self) -> int
    @property def identity(self) -> ProcessIdentity       # (pid, start_time_epoch) — PID-reuse guard (02 §7)
def resolve_claude_binary() -> Path                       # ~/.claude/local/claude, then PATH (02 §3)
def process_group_kill(identity: ProcessIdentity, signal: int) -> None
def probe(identity: ProcessIdentity) -> bool              # liveness for boot reconcile (02 §7)
```
Assembles the binding spawn args from `SpawnSpec` (02 §2 template; 05 §2). Ownership split (03 §3): SessionManager decides *when*; RunnerAdapter decides *how*.

### 1.4 `PermissionGate` — spawn-time policy; fail-closed (02 §6, glossary)

```python
class EffectivePolicy(BaseModel):
    allowed: set[str]          # workspace ∪ user settings (exact merge rule → 07)
    denied: set[str]           # --disallowedTools; always binds (02 §2)
    permission_mode: Literal["manual"] = "manual"
def resolve_policy(session: Session, settings: Settings) -> EffectivePolicy   # called at spawn by SessionManager
def decide(tool_use: ToolUseEvent, policy: EffectivePolicy) -> Decision       # Allow | Deny(reason)
def record(decision: Decision, session: Session, tool_use: ToolUseEvent) -> None  # PermissionRecord via Storage + audit.jsonl mirror
def on_event(ev: SessionEvent) -> None   # EventBus subscriber: correlates tool_use events vs policy (mission §5)
```
Denial observation (03 §4d): the gate subscribes to `Topic.SESSION`; on each `tool_use` event it applies `decide()` — deterministic correlation against the effective allowlist, **never** `tool_result` string parsing (mission §5). `deny` → record + publish `permission.notice`; `approve_future` (recorded only — no mid-run channel, glossary) updates `allowed` for the **next** spawn. The CLI also auto-denies unallowed tools; that `tool_result` is stored as an event but is not the decision source. Probe (item 12): the final `result` event additionally carries `permission_denials[]` — the gate MAY consume both `tool_result` content-agnostically and `permission_denials`; both are event-derived structures, never parsed text.

### 1.5 `EventBus` — in-process asyncio pub-sub (03 §3, §6 line 83)

```python
class Topic(StrEnum):
    SESSION = "session"; ARTIFACT = "artifact"; PERMISSION = "permission"
    SCHEDULER = "scheduler"; CONNECTOR = "connector"
def publish(topic: Topic, payload: dict) -> None
def subscribe(topic: Topic, handler: Callable[[dict], Awaitable[None]]) -> Subscription
def unsubscribe(sub: Subscription) -> None
```
**Publisher/subscriber matrix** (seeded from Cowork events, symbol-map §3a / session-lifecycle §6.2):

| Topic | Publishers | Subscribers |
|---|---|---|
| SESSION (`session.started`, `init_status`, `event`, `updated`, `ended`, `archived`) | SessionManager (Cowork `message`, `session_updated`, `close`, `archived`, `initialization_status` analog) | WorkspaceServer (WS push), PermissionGate (tool_use correlation), SchedulerEngine (drain on `session.ended`) |
| ARTIFACT (`artifact.created/updated/deleted`) | ArtifactWatcher (Cowork `fs_file_created/deleted` analog) | WorkspaceServer |
| PERMISSION (`permission.notice`) | PermissionGate | WorkspaceServer |
| SCHEDULER (`sched.notice`, `task.*`) | SchedulerEngine | WorkspaceServer |
| CONNECTOR (`connector.updated`) | ConnectorRegistry | WorkspaceServer |

Subscriber isolation rule (03 §6 line 83): every subscription runs in its own asyncio task; a raising handler is logged (loguru, `LOGGING_LEVEL`) and the subscription is detached after 3 consecutive failures [invented]; `publish()` never raises to the publisher. Tick path note (03 §6 line 83, kept): SchedulerEngine publishes `sched.notice` **and** calls `SessionManager` directly — the direct call is intentional (drain must not depend on bus delivery).

### 1.6 `ArtifactWatcher` — detection semantics cloned from RE §5 (`FileSystemWatcher`)

```python
def watch(session_id: UUID, outputs_dir: Path) -> None   # non-recursive, dotfiles skipped, initial scan (RE session-lifecycle §5)
def stop_watching(session_id: UUID) -> None              # on result/stop: final scan + version pass, then drop all fs events (P2-12 — the CLI may write between `result` and kill)
def version_file(artifact: Artifact, fs_path: Path) -> ArtifactVersion  # copy → artifacts/<name>__v<N>_<hash8>.<ext> (hash8 content suffix; version timestamp = row createdAt, 04 §1.4); rejects `..` and `/` in names (P2-16)
```
On fs event → `existsSync`-style recheck (RE §5): created/modified → version + persist + publish `artifact.created/updated`; gone → `deletedAt` + publish `artifact.deleted`.

Deletion audit scope (RESOLVED → 07 §4.1): 01 §5.4 and the glossary require *every grant, deny, approval, and deletion decision* to be captured, so watcher-sourced deletions count toward `PermissionRecord`s as `decision="deleted_observed"` (toolName `fs_delete`, input `{path}`). Final call was made in 07-security-permissions.md §4.1 (03 §6 line 85); the literal extension landed in 04 §1.5.

### 1.7 `SchedulerEngine` — local cron (RE §6 adapted)

```python
def create_task(spec: TaskCreate) -> ScheduledTask          # nextRunAt from cadence (hourly/daily/weekly/weekdays) or croniter(cronExpr).next(now); manual → None (P2-10)
def trigger_task(id: UUID) -> ScheduledTask                 # manual cadence / "run now" (POST /api/tasks/{id}/run, 05 §1.1): fires via the 04 §4.3 path — direct start if the slot is free, else queued [invented]
def update_task(id: UUID, patch: TaskPatch) -> ScheduledTask
def delete_task(id: UUID) -> None
def list_tasks() -> list[ScheduledTask]
def tick(now: datetime) -> list[UUID]                        # due = active and nextRunAt <= now (index tasks(status,next_run_at)); missed tasks are never selected here (P1-8)
def recover_missed(now: datetime, last_boot: datetime) -> None  # boot (P1-3): active tasks with nextRunAt in (last_boot, now) → missed; replay = direct-create queued session via the 04 §4.3 path — tick never selects missed tasks (P1-8); a replayed session starts IMMEDIATELY when the slot is free (same start path as the drain, P2-3), else it queues normally; which occurrences replay (coalescing) → prd-scheduled-tasks
def _on_session_ended(ev: dict) -> None                      # EventBus subscriber: queue drain (04 §4.3)
```
Conflict rule (02 §7): due task + `SessionManager.active_session() is not None` → task `queued` + queued session (04 §4.3); the enqueue re-arms a drain attempt (a session may have ended mid-enqueue, P1-5); drain failure (`start_session` raises) → queued session → `failed`, task → `active`, retried at the next scheduled occurrence (P2-2). Scheduled runs never overlap (serialized behind the single slot) and never wait on a dialog — unallowed tools auto-denied at spawn. Tick loop: `asyncio` timer at `Settings.schedulerTickSeconds` (default 15 [invented]). Dependency: `croniter` — justified: sole cron-expression parser for `next()`; no framework [design decision].

### 1.8 `ConnectorRegistry` — config store + per-session `--mcp-config` compiler (03 §3)

```python
def list_connectors() -> list[Connector]
def add_connector(spec: ConnectorCreate) -> Connector
def remove_connector(id: UUID) -> None
def compile_mcp_config(session: Session) -> Path | None      # writes ~/.co-work/tmp/mcp-config-<id>.json; None if no connectors
def tool_names(connector: Connector) -> list[str]            # feeds EffectivePolicy.allowed (mcp__<server>__<tool>)
def eligible_for_scheduled(c: Connector) -> bool             # not requiresOAuth or oauthPreAuthDone (02 §2)
```
Interactive-OAuth connectors are excluded from scheduled runs (02 §2) — pre-auth via `claude mcp login` outside sessions [design decision]; flow owned by prd-mcp-connectors. `--strict-mcp-config` is passed whenever a compiled file exists (02 §2). Tool inventory (P2-15): the `Connector.toolNames` acquisition mechanism (CLI-side `tools/list` probe before spawn, or `claude mcp` inspection) is owned by prd-mcp-connectors; until populated the default is `[]` and unlisted tools are denied at spawn.

### 1.9 `Storage` — SQLite layer, single writer owner (02 §7)

Async wrapper: **aiosqlite** [design decision — one background thread, non-blocking event loop, same transaction semantics as sqlite3; `run_in_executor` rejected: no thread pool to size, no cross-connection state to marshal]. Single connection for all writes (06 §3).

```python
async def init() -> None                          # open DB, PRAGMA WAL/foreign_keys/busy_timeout, migrate schema
async def close() -> None
# sessions
async def insert_session(s: Session) -> None
async def update_session(s: Session) -> None
async def transition(session_id: UUID, from_status: SessionStatus, to_status: SessionStatus, **fields) -> None  # rejects illegal transitions (04 §4.1); to `running` also rejected if another `running` row exists — same transaction, no TOCTOU (P1-5)
async def get_session(id: UUID) -> Session
async def list_sessions(status: SessionStatus | None = None) -> list[Session]
async def reconcile_running(started_before: datetime) -> list[Session]   # boot reconcile (06 §2)
# events
async def append_event(session_id: UUID, ev: SessionEvent) -> int        # returns seq; same txn as transition
async def list_events(session_id: UUID, after_seq: int = 0) -> list[SessionEvent]
# tasks
async def insert_task / update_task / get_task / list_tasks / list_due(now) / set_status(...)
# artifacts
async def insert_artifact / add_version / update_artifact / list_artifacts(session_id)
async def record_artifact_detection(session_id: UUID, artifact: Artifact, version: ArtifactVersion | None = None) -> Artifact  # insert_artifact + add_version + update_artifact in ONE transaction (05 §1.9 txn rule); version=None ⇒ deletion-only update; shape consumed by prd-live-artifacts §3.3
# audit
async def append_permission(rec: PermissionRecord) -> None              # DB row authoritative, committed first; audit.jsonl mirror appended best-effort after commit (P2-14)
async def list_permissions(session_id: UUID | None) -> list[PermissionRecord]
# connectors / settings
async def insert_connector / list_connectors / delete_connector / get_setting(key) / set_setting(key, value)
```
Transaction boundaries: one public method = one transaction; `transition()` + `append_event()` commit atomically; the `audit.jsonl` mirror append is best-effort post-commit (P2-14).

### 1.10 `Auth` — no-op (glossary, mission §2)

```python
def check_token(token: str | None) -> bool   # stub: always True; replaced by WorkspaceServerToken scheme → 07
def origin_allowed(origin: str | None) -> bool  # strict Origin check for WS → 07
```

## 2. Spawn contract

### 2.1 `SpawnSpec` — exact fields; args assembled by RunnerAdapter from the binding template (02 §2)

```python
class SpawnSpec(BaseModel):
    command: Path                        # resolve_claude_binary() result
    args: list[str]                      # -p --verbose --output-format stream-json --input-format stream-json
    permission_mode: Literal["manual"] = "manual"
    allowed_tools: list[str]             # --allowedTools <csv> (EffectivePolicy.allowed; task policy for scheduled runs, RE §6)
    denied_tools: list[str]              # --disallowedTools <csv> — always binds (02 §2)
    add_dirs: list[Path]                 # --add-dir per folder grant (02 §2); MAY include the workspace memory parent (~/.co-work) via the memory carve-out (07 §5.3) [design decision]
    mcp_config: Path | None              # --mcp-config <file>; + --strict-mcp-config when present
    cwd: Path                            # spawn cwd confinement [design decision]: first granted folder, else outputsDir
    env: dict[str, str]                  # CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 (03 §6 line 82); MCP_TOOL_TIMEOUT=30000 (RE §2); COWORK_SESSION_ID=<session uuid>; COWORK_POLICY_FILE=<compiled policy path>; NO isolated CLAUDE_CONFIG_DIR (02 §2)
    first_message: UserMessage           # buffered pre-spawn, flushed post-spawn (RE §2)
    append_system_prompt: str | None = None  # appended to the CLI system prompt per session (memory instructions, prd-memory) [design decision]
    health_timeout_s: float = 30.0       # 02 §2 no-handshake health check
    process_group: bool = True           # start_new_session=True — teardown kills the GROUP (03 §6 line 82)
```

### 2.2 Runner-side event contract — consumed stream-json types → `SessionEvent` rows

Top-level `stream_event` wrapper (verbose mode) is unwrapped; the inner event is authoritative [design decision]. Mapping (transcript assembly owned here, 03 §6 line 81 — assembled from the pipe, not CLI jsonl re-parse [design decision] vs RE §7):

| stream-json type | SessionEvent.eventType | Session fields / payload |
|---|---|---|
| `system` (subtype `init`) | `init` | `cliSessionId`, `slashCommands` → payload `{session_id, slash_commands, mcp_servers: [{name, status: connected\|failed}]}` (probe-verified on claude 2.1.220; prd-mcp-connectors §3.6 observes it at the health check); health-check success |
| `system` (other) | `message` | payload `{kind:"system", content}` |
| `assistant` | `message` | payload `{kind:"assistant", content}` (text/thinking blocks) |
| `assistant` w/ `tool_use` block | `tool_use` | payload `{id, name, input}` — the only decision source for PermissionGate (05 §1.4) |
| `user` (echo) | `message` | payload `{kind:"user", content}` (P1-2 — the CLI echoes user messages on stdout; previously unmapped) |
| `tool_result` | `tool_result` | payload `{tool_use_id, is_error, content}` — stored, never parsed for decisions |
| `result` | `result` | `session.numTurns/isError`; payload `{num_turns, is_error, permission_denials?}` (probe — denied tools surface deterministically here; 05 §1.4); triggers `running→done` |
| `error` | `error` | `session.error`; triggers `running→failed` |
| (exit) | `close` | `session.exitCode`; flush |
| (internal — SessionManager) | `init_status` | payload `{step}` — spawn-phase marker (05 §1.1), not a stream-json event (P3-5) |

`init_status` rows carry Cowork's initialization steps `auth→skills→prompt→mcp_setup→query→complete` (RE session-lifecycle §2), mapped to our phases [design decision]: auth=settings/connector resolution, skills=no-op (no skills sync in v1), prompt=spec build, mcp_setup=`--mcp-config` compile, query=spawn, complete=first event. Every event row is also appended raw to `sessions/<id>/transcript.jsonl` (04 §3). Unknown stream-json types are stored as `SessionEvent(eventType="raw")` with the verbatim payload — the pipeline never raises on unmapped events (P1-2).

## 3. Message flow

### 3.1 Stdin NDJSON shapes (`--input-format stream-json`)

```json
{"type":"user","uuid":"<uuid>","session_id":"<cliSessionId or None>","message":{"role":"user","content":[{"type":"text","text":"<prompt>"}]}}
```
Envelope cloned from RE session-lifecycle §1.4/§6.1 (uuid, session_id envelope, content blocks). v1 is single-turn: the first message is the only message (flushed post-spawn, P1-1); `result` = turn end, no further turns [design decision, RE §2 is multi-turn]. `session_id` in the envelope is our session UUID string until `init` returns the real CLI id [design decision].

### 3.2 Health check

No handshake (02 §2), but ordering matters (P1-1): the CLI gates `init` on the first stdin message — spawn, **flush the first message**, then await events within `health_timeout_s` (30 s default, 06 §5). Probe (item 13): the first event is typically `init` (carries `session_id` + tools list); a non-`init` `system` keeps the health timer running; `pending→running` **requires `init`** (it binds `cliSessionId`); an early `error` (startup auth/network failure) fails the health check immediately instead of waiting out the timeout (P3-3). Timeout → `pending→failed` with the buffered stderr tail in `session.error`; the teardown protocol (05 §3.3, process-group kill) runs on this failure path too (P1-7). Garbage on stdout (non-NDJSON) is `cli_stdout_pollution`-style failure [design decision, RE session-lifecycle §6.2 error categories].

### 3.3 Teardown protocol (binding, 02 §2 + 03 §6 line 82)

1. `close_input()` (stdin EOF — clean exit in `-p` mode, verified 02 §2); wait ≤ 5 s for exit.
2. SIGTERM to the **process group** (negative pid of the `start_new_session` group leader); wait ≤ 3 s.
3. SIGKILL to the process group.
4. Record `exitCode`; `running→stopped|failed` accordingly. Group kill applies to EVERY exit path — user stop, natural end, runner crash, and spawn/health-check failures (P1-7) — so orphan `claude` processes are impossible by construction for spawned processes; belt-and-braces: boot reconcile still scans (02 §7, 06 §2).
Runner env always includes `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`; a PreToolUse Task hook blocking `run_in_background` is required (03 §6 line 82; hook file authored by 07). `MCP_TOOL_TIMEOUT=30000` (RE §2).
