# 06 — Runtime

> Writer: W3 | Status: written — pending review
> Binding: 02 §6 fail fast, 02 §7 concurrency + boot reconcile, 03 §6 lines 77–84. One-active-session invariant, queue drain, PID-reuse guard, failure/timeout tables.

## 1. Process topology

```
uvicorn (1 Python process, asyncio single event loop)
├─ WorkspaceServer      HTTP+WS on 127.0.0.1:8765 (05 §1.1)
├─ SessionManager ──► RunnerAdapter ──► claude CLI subprocess   (1 per running session; queued = unspawned;
│                                          own process group, start_new_session=True, 05 §2.1)
├─ EventBus             in-process pub-sub (05 §1.5)
├─ PermissionGate       EventBus subscriber; no own process
├─ ArtifactWatcher      per live session: fs.watch(outputs_dir, non-recursive) (RE §5)
├─ SchedulerEngine      asyncio timer loop (tick every 15 s) + boot recovery
├─ ConnectorRegistry    config only
└─ Storage ──► aiosqlite connection ──► ~/.co-work/cowork.db (WAL)
```

- **aiosqlite** chosen (05 §1.9 [design decision]): the single connection runs on aiosqlite's internal background thread; no user-managed threads, no `run_in_executor` pools (03 §6 line 80). All writes serialize through that one connection (02 §7).
- No other threads in v1. The CLI subprocesses are supervised purely via asyncio pipes.

## 2. Lifecycle

### 2.1 Startup sequence

1. Load `Settings`; set `Settings.lastBootAt = now` (persisted, P1-3). `Storage.init` (open DB, `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`; migrate schema).
2. **Reconcile sessions** (02 §7, owned by 04/06):
   - every session left `running` → `RunnerAdapter.probe(identity)`; **PID-reuse guard**: a live PID whose start time differs from `proc_start_epoch` is a *different* process → treat as dead, do NOT kill it (02 §7); identity match → group-kill orphan, `running → failed` (`error="app restarted"`).
   - `queued` sessions WITH a task → run directly at boot (`queued → running` via the normal spawn path — the slot is free) (P1-6); `pending`/`queued` without a task → `failed` (`error="app restarted"`).
   - **Orphan rule (P1-4)**: `task.status=queued` with no `queued` session row → `queued → active`, `nextRunAt` recomputed.
3. **SchedulerEngine.recover_missed(now, last_boot=Settings.lastBootAt)** (02 §6, P1-3): active tasks with `nextRunAt` inside the down-window `(lastBootAt, now)` → `missed`; replay = **direct-create queued session** for the missed occurrence via the 04 §4.3 path — `tick` never selects `missed` tasks (P1-8); a replayed session starts **immediately** when the slot is free (the same `SessionManager.start_session` path as the drain — replayed runs must not sit queued behind a free slot, P2-3), else it queues and drains normally; which occurrences replay (coalescing) → **prd-scheduled-tasks**.
4. Start ArtifactWatcher (none yet — per-live-session only, RE §5) and the scheduler tick loop; start WorkspaceServer (bind 127.0.0.1:8765).
5. Port already in use → fail fast with a clear error (02 §6, 06 §4 row 8).

### 2.2 Shutdown sequence (SIGINT/SIGTERM handler)

1. Stop accepting new work: scheduler tick loop cancels; queued sessions → `failed` (`error="app shutting down"`).
2. Every running session → teardown protocol (05 §3.3) → `stopped`.
3. Flush aiosqlite (commit pending), close DB, exit 0. Audit rows are append-per-write (04 §3) — nothing to flush in practice.

### 2.3 Session lifecycle inside one run (persist-before-spawn, RE §2)

`create_session` (row written, status `pending`, outputsDir mkdir'd) → `start_session` → `RunnerAdapter.spawn` (first message buffered) → **flush the first message** → health check (probe, item 13): the first event is typically `init` (carries `session_id` + tools list); a non-`init` `system` keeps the health timer running; `pending→running` **requires `init`** (`cliSessionId` bound on `init`); an early `error` fails health immediately → events streamed/mapped/persisted (05 §2.2) → `result` (`num_turns`, `is_error`, `permission_denials[]` — consumed by PermissionGate, 05 §1.4) → `running→done` → process group teardown → queue drain notification (04 §4.3). Errors at any step (including spawn/health failure): fail the session, run the teardown group-kill (P1-7), never fail the app (02 §6, 03 §1).

### 2.4 Resume semantics (03 §6 line 81)

`--resume` is not in the v1 spawn template [design decision]. A `stopped`/`failed` session keeps its transcript + artifacts and is terminal until `archived`; the user starts a new session. RE §2's resume path (cliSessionId reuse) is dropped; headroom noted for a later phase.

## 3. Concurrency rules

| # | Rule | Enforcement |
|---|---|---|
| 1 | **One run slot** in v1 (02 §7): interactive and scheduled runs share it; scheduled runs are serialized, never overlapping | `SessionManager` is the gatekeeper (03 §6 note, 04 §4.3): `start_session` raises if `active_session()` exists; only SchedulerEngine may create `queued` sessions |
| 2 | Scheduled trigger while slot busy → **queue**, never skip/overlap [design decision] | slot busy = an interactive session **or another scheduled run** (scheduled-on-scheduled queueing; glossary defers here — P3-6): `task.status=queued` + `Session(status=queued)`; drain on `session.ended` (04 §4.2/§4.3); overlap policy detail → prd-scheduled-tasks |
| 3 | SQLite write serialization | Single aiosqlite connection; every write is a short transaction (05 §1.9); WAL for lock-free reads |
| 4 | EventBus delivery isolation | Per-subscriber asyncio tasks; raising subscriber detached after 3 failures (05 §1.5) |
| 5 | One tick at a time | Scheduler tick re-entrancy guarded by an asyncio lock (a slow tick never overlaps the next) [invented] |

## 4. Failure modes

| # | Failure | Behavior | Recovery | Owner |
|---|---|---|---|---|
| 1 | claude CLI crash (nonzero exit, no `result`) | `running→failed`; `error` = exit code + stderr tail; events/artifacts already persisted stay; interactive: no auto-retry | User starts a new session | SessionManager/RunnerAdapter |
| 2 | Runner EOF mid-turn (stdout closed, exit 0, no `result`) | Same as #1 (`error="unexpected EOF mid-turn"`) | Same | RunnerAdapter |
| 3 | Spawn failure / health-check timeout (no first event in 30 s) | `pending→failed`; stderr tail in `error`; teardown protocol group-kills the spawned CLI (P1-7) | None (fail fast, 02 §6); user retries | SessionManager |
| 4 | Hung runner (no events, no `result`) | no-event watchdog: `Settings.runnerNoEventTimeoutMinutes` (default 10 [invented], P2-13) → `running→failed` (`error="no events for N min"`) + teardown group-kill | None; user retries; scheduled occurrence handled per 04 §4.2 (not re-fired) | SessionManager (watchdog owned by 06) |
| 5 | Auth expiry / network death mid-run (`error` event or exit) | `running→failed`; `error` categorized `auth_error`/`network_error` (RE session-lifecycle §6.2) | User re-authenticates the CLI (it owns auth, 02 §1); new session | RunnerAdapter/SessionManager |
| 6 | App killed (SIGKILL/power loss) | Sessions left `running`; WAL keeps DB consistent; audit rows durable (append-per-write) | Boot reconcile 2.1 step 2 (PID liveness + reuse guard + orphan group-kill) | Runtime (06) |
| 7 | SQLite locked / busy beyond 5 s | `busy_timeout=5000` → Storage raises; exception surfaces (fail fast, 02 §6) | Restart app; single-connection design makes contention unlikely | Storage |
| 8 | Port 8765 in use | Startup fails fast with clear error message (02 §6) | User frees port or sets `Settings.serverPort` | WorkspaceServer |
| 9 | Watcher fs error (outputsDir deleted mid-session) | `ArtifactWatcher` logs error, stops watching that dir; session continues; versioned artifacts remain | User restores dir; new session re-watches | ArtifactWatcher |
| 10 | Disk full (ENOSPC) on outputs/artifacts/audit | ArtifactWatcher: version copy skipped + logged, session continues; Storage writes raising ENOSPC → exception surfaces (fail fast, 02 §6) | User frees space; skipped files never versioned — transcript notes the gap | ArtifactWatcher/Storage |
| 11 | **Scheduled run mid-flight crash** (03 §6 line 84) | Session → `failed`; task stays `active` (neither `missed` nor re-fired); `lastRunError` + `lastRunSessionId` recorded; `nextRunAt` unchanged | **Stub for prd-scheduled-tasks**: retry count/backoff/notification policy TBD; mechanism (what state to read) is defined in 04 §1.3 | prd-scheduled-tasks |
| 12 | PID reuse during reconcile | Identity (pid + start time) mismatch → treat as dead, never kill the unrelated process (02 §7) | N/A — guard is the recovery | Runtime (06) |
| 13 | CLI binary missing / untested version | `pending→failed`, `error="claude binary not found"` / version-pin violation (02 §2) | User installs/pins version in Settings; override recorded in audit | SessionManager |
| 14 | Background task spawn inside runner | Blocked by env `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` + PreToolUse Task hook (03 §6 line 82; hook file → 07) | N/A | Runtime/07 |
| 15 | PreToolUse hooks missing / hook errors | Spawn proceeds allowlist-only — hook errors are non-blocking by CLI design (probe); no session impact; denials then come only from the spawn-time allowlist | N/A (hook files owned by 07) | 07 |
| 16 | Artifact transaction failure (`record_artifact_detection` raises) | Session continues; the artifact is skipped + logged (fail-contained at the boundary, 02 §6) | File is never versioned; user can re-trigger by re-touching the file | ArtifactWatcher/Storage |

## 5. Timeouts

| # | Timeout | Value | Semantics | Source |
|---|---|---|---|---|
| 1 | Spawn health check | 30 s (`Settings.spawnHealthTimeoutSeconds`) | spawn → flush first message → first event is typically `init` (session_id + tools list); non-`init` `system` keeps the timer running; `pending→running` requires `init`; early `error` fails health (probe, item 13); timeout → `pending→failed` + teardown group-kill (02 §2 no handshake) | [invented] |
| 2 | stdin EOF grace | 5 s | wait for clean exit before SIGTERM (05 §3.3) | [invented] |
| 3 | SIGTERM grace | 3 s | then SIGKILL (process group) | [invented] |
| 4 | Permission notice TTL | none | report-only channel; no blocking dialog, no timeout-deny (glossary superseded term) | [design decision] |
| 5 | WS client disconnect | none on sessions | sessions are app-owned, not connection-owned; after reconnect the UI must re-sync via HTTP GET (`events?after_seq=`, `/api/sessions`) (P3-24) | [design decision] |
| 6 | Task run max duration | **none in v1** | scheduled runs may exceed any bound (beyond the no-event watchdog, row 6b); any wall-clock cap → prd-scheduled-tasks | [invented — flag] |
| 6b | Runner no-event watchdog | 10 min (`Settings.runnerNoEventTimeoutMinutes`) | no events + no `result` → `running→failed` + teardown (06 §4 row 4) | [invented] (P2-13) |
| 7 | Scheduler tick interval | 15 s (`Settings.schedulerTickSeconds`) | `nextRunAt <= now` check granularity; 1-min cron precision is plenty | [invented] |
| 8 | MCP tool timeout | 30 s | `MCP_TOOL_TIMEOUT=30000` in runner env (RE §2, symbol-map §4) | cloned RE §2 |
| 9 | Idle-session timeout | none | Cowork's 5-min idle check is telemetry-only (RE session-lifecycle §8.3) — dropped | [design decision] |
| 10 | Queue wait | unbounded | a queued scheduled run waits until the slot frees; user can cancel (04 §4.3) | [design decision] |

## 6. Runner hardening (03 §6 line 82)

Spawn env (every run): `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, `MCP_TOOL_TIMEOUT=30000`, shared user `CLAUDE_CONFIG_DIR` (02 §2 — never isolated). PreToolUse Task hook (`matcher: Task`) blocks `run_in_background` by printing the probe-verified stdout contract `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny"}}` (02 §2, 07 §5.3/§7). The hook is the single static script `~/.co-work/hooks/pre-tool-use.sh` (04 §3), installed once with user consent — no per-session hook files (mechanism → 07 §5.3). The folder-grant **PreToolUse path-filter hook** (the spawn-cwd hard boundary, 02 §2) is owned by 07-security + prd-local-files — it must not be homeless (P3-26).

## 7. Handoff summary (runtime-owned)

- SchedulerEngine → SessionManager: direct call for queue drain + tick (03 §6 line 83, kept) and `sched.notice` publish for UI.
- SessionManager → RunnerAdapter: `spawn(spec)` / `handle.stop()` — the only process-control surface.
- SessionManager → Storage: `transition()` + `append_event()` in one transaction.
- PermissionGate → Storage: `append_permission` (row + audit.jsonl).
- Boot: reconcile (2.1) runs before scheduler recovery (2.1 step 3) — recovered tasks must never observe a phantom `running` session occupying the slot.
