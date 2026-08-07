# PRD — Scheduled Tasks

> Writer: W4c (prd-scheduled-tasks) | Status: written — pending review
> Binding: 02 §6 (fail fast, crash-recoverable scheduler), 02 §7 (one-active-session invariant, boot reconcile), 03 §6 lines 77–84 (conflict policy, mid-flight crash), 04 §1.3 (`ScheduledTask` shape), 04 §4.2 (`Task.status` machine + boot rule), 04 §4.3 (queued-session handoff), 05 §1.1 (task routes + cadence↔cron), 05 §1.5 (`sched.notice`), 05 §1.7 (`SchedulerEngine` contract), 06 §2.1 (boot reconcile order), 06 §4 row 11 (mid-flight crash stub), 06 §5 rows 6b/7 (watchdog, tick interval).

## 1. Current Behavior (evidence)

- **Claude Cowork (cloud)**: scheduled tasks run on a cloud cron — they fire even with the app closed, computer asleep, or no device online; each run is its own Cowork session; cadence is limited to hourly/daily/weekly/weekdays/manual with no arbitrary cron; tasks cannot be tied to local folders (RESEARCH §2). The July 2026 pivot moved execution server-side; the desktop bundle's local execution path is separate (RE §6 — server sync unverified, local file trigger exists).
- **Cowork (local, RE §6)**: tasks persist as `.claude/scheduled_tasks/<id>.json`; creation is renderer-only via `CoworkScheduledTasks`/`CCDScheduledTasks` EIPC (`createScheduledTask`, `updateScheduledTask`, `updateScheduledTaskStatus`, `removeApprovedPermission`, `getAllScheduledTasks`, `getSessionsForScheduledTask`, `onScheduledTaskEvent` — RE §5 `CoworkScheduledTasks`/`CCDScheduledTasks` method tables; bundle_eipc_surface.txt); runs get auto-approved tools through the `shouldAutoApprovePermission(scheduledTaskId, …)` gate (RE §6).
- **Kimi Work**: local cron engine — the app must be open; missed triggers (sleep/shutdown) are **never replayed**; hard task quotas (Free 2 … Ultra 25, over-limit saves inactive) (RESEARCH §2). Underlying kimi-code kernel: per-session cron, deterministic jitter (recurring ≤10% of period, cap 15 min forward), **coalescing** (missed fires delivered once with `coalescedCount`), 7-day stale auto-expire, 1 s polling (RESEARCH §2). OpenClaw adds production hardening: **auto-disable after 10 consecutive run failures or 3 schedule errors** (RESEARCH §2).
- **Pre-decided in our specs**: SQLite task store with `Task.status = active|paused|disabled|missed|queued` (04 §1.3); exactly one of `cadence`/`cronExpr` (Storage-validated); queued sessions via the 04 §4.3 handoff; boot-time missed-run recovery with replay-only-latest-missed coalescing direction (02 §6, 06 §2.1 step 3); mid-flight crash leaves the task `active`, neither `missed` nor re-fired (03 §6 line 84); auto-approve resolved at spawn (`--allowedTools` under `--permission-mode manual`, never `bypassPermissions`) (02 §2, RE §6); one run slot shared by interactive and scheduled runs, scheduled runs serialized (02 §7, 06 §3).

## 2. Desired Behavior

**User story**: "As a user I schedule a daily task, it runs while my machine is on, and I can see results; if the app was down at trigger time, the missed run is replayed at boot."

**Numbered flow** (tick path; boot path in steps 8–9):

1. **Create** — user creates a task via `POST /api/tasks` with `cadence` **or** `cronExpr` (exactly one, Storage-validated), a prompt, and the auto-approve policy (`allowedTools`). `SchedulerEngine.create_task` computes `nextRunAt = croniter(cron).next(now_local)` (cadence converted 1:1 to cron, 05 §1.1) and persists via `Storage.insert_task`. `manual` cadence → `nextRunAt = None` (fires only via `POST /api/tasks/{id}/run`).
2. **Tick** — `SchedulerEngine` polls at `Settings.schedulerTickSeconds` (default 15, 06 §5 row 7); due predicate = `status == active and nextRunAt <= now` (05 §1.7); one tick at a time (asyncio lock, 06 §3 row 5). There is no per-task timer and no sleep-until in v1 — a fixed-interval poll is the only wakeup mechanism `[design decision]`.
3. **Due?** — `tick(now)` selects due tasks ordered by `nextRunAt` (index `tasks(status, next_run_at)`); `missed` tasks are never selected here (P1-8).
4. **Slot free?** — if `SessionManager.active_session() is None`: **direct start** — `SchedulerEngine` publishes `sched.notice(action="started")` (P3-25), then calls `SessionManager.start_session` on a `pending` session created with `taskId` (04 §4.3 step 6: only SchedulerEngine creates scheduled sessions). If busy (interactive **or** another scheduled run, 06 §3 row 2): **queue** via the 04 §4.3 handoff — session row (`status=queued`, `taskId`) written FIRST, then `task.status=queued` (P1-4 write order), `sched.notice(action="queued")`, re-arm a drain attempt immediately (P1-5).
5. **Session pipeline** — the run enters the standard pipeline: `RunnerAdapter.spawn` with the task's auto-approve policy (02 §2 template), health check, event streaming, artifacts detected by `ArtifactWatcher` (mission §3.2). One scheduled run never waits on a dialog: unlisted tools are auto-denied inside the CLI (02 §7).
6. **Result** — `result` event → `running→done`; `task.lastRunAt`, `lastRunSessionId`, `lastRunError=None` updated; consecutive-failure counter resets (§3.7).
7. **Recompute** — the basis depends on how the run was triggered `[design decision]`:
   - **Direct-start paths** (tick direct start with a free slot; manual run-now): `nextRunAt = croniter.next(now)` — the generic rule (04 §4.3 step 3 analog).
   - **Replay paths** (missed-run replay at boot — direct start or queued — including that session when it drains): `nextRunAt = croniter.next(latest_missed_occurrence_local)` — grid-preserving, one occurrence per down-window (coalescing). **Replay overrides the generic direct-start/drain rule**: 04 §4.3 step 3's `croniter.next(now)` does not apply to replay sessions.
   - **Edge (replay)**: if the grid has advanced past the occurrence following the latest missed one (the replay sat queued past the next grid point), `nextRunAt` advances to the first grid point strictly after `now` — `nextRunAt` is never past-due.
   - **Edge (normal queued)**: a queue longer than one period (e.g. daily task queued behind a 26-hour interactive session) skips the occurrence that elapsed during the queue — the task was `queued`, not `missed`, so no replay.
8. **Boot replay** — `SchedulerEngine.recover_missed(now, last_boot=Settings.lastBootAt)` runs after session reconcile (06 §2.1 step 3): active tasks with `nextRunAt` inside the down-window `(lastBootAt, now)` → `missed`, `sched.notice(action="missed")`, then **exactly one replay** — the latest missed occurrence — via the 04 §4.3 path; **direct start when the slot is free** (P2-3), else queue and drain normally. Coalescing: occurrences older than the latest missed one are dropped (06 §2.1, RESEARCH §2 — kimi coalescing, openwork replay-only-latest-missed) `[design decision]`. The replay run recomputes `nextRunAt` at its start (boot direct-start or drain) per the step-7 replay rule — grid-preserving, never past-due. If the user pauses/disables the task before boot recovery completes, the replay is skipped and `nextRunAt` is recomputed — the task stays in its user-set state (04 §4.2 `missed → active` applies only when still active; a paused/disabled task lands `missed → paused`/`missed → disabled`, no reactivation).
9. **Watchdog** — a run that emits no events for `Settings.runnerNoEventTimeoutMinutes` (default 10, 06 §5 row 6b) → `running→failed` + teardown group-kill (06 §4 row 4); the task stays `active`, `nextRunAt` unchanged, failure counter increments, next scheduled occurrence proceeds.

### 2.1 Decision summary (review aid)

| Decision | Choice | Evidence / citation |
|---|---|---|
| DST / `nextRunAt` | UTC storage, wall-clock croniter computation; gap advances, overlap fires once | 04 §1.3 P2-10; croniter wall-clock semantics `[design decision]` |
| Missed coalescing | replay latest occurrence only, once per down-window | RESEARCH §2 (kimi coalescing, openwork replay-only-latest-missed) `[design decision]` |
| Grid preservation | replay paths recompute `nextRunAt` from the latest missed occurrence — overriding the generic direct-start/drain rule (04 §4.3 step 3); never past-due | `[design decision]` |
| Auto-disable | 5 consecutive failed runs, derived from session rows, `Settings` override | RESEARCH §2 (OpenClaw: 10) `[design decision]` |
| Schedule when queued past a period | occurrence elapsed during the queue is skipped, never replayed | `[design decision]` |
| No sleep-until, no jitter, no stale expiry | fixed 15 s poll; kimi jitter/stale dropped | RESEARCH §2 `[design decision]` |
| No task quotas | single user, no tiers | RESEARCH §2 (kimi quotas) — not adopted `[design decision]` |
| `--allowedTools` under `--permission-mode manual`, never `bypassPermissions` | binding 02 §2, RE §4/§6 | — |

## 3. I/O Contracts

### 3.1 `ScheduledTask` entity (binding shape, 04 §1.3)

```python
class TaskStatus(StrEnum):
    ACTIVE = "active"; PAUSED = "paused"; DISABLED = "disabled"
    MISSED = "missed"; QUEUED = "queued"    # queued = fired while any run slot is busy (04 §1.3)

class ScheduledTask(BaseModel):
    id: UUID
    name: str
    cadence: Literal["hourly","daily","weekly","weekdays","manual"] | None = None
    cronExpr: str | None = None            # croniter 5-field; exactly one of cadence/cronExpr (Storage-validated)
    prompt: str
    allowedTools: list[str]                # auto-approve policy → spawn --allowedTools (RE §6)
    status: TaskStatus
    nextRunAt: datetime | None = None      # UTC storage; None for manual until fired (04 §1.3)
    lastRunAt: datetime | None = None
    lastRunSessionId: UUID | None = None
    lastRunError: str | None = None
    createdAt: datetime
    updatedAt: datetime
```

Cadence↔cronExpr 1:1 (05 §1.1, binding): `hourly = 0 * * * *`, `daily = 0 0 * * *`, `weekly = 0 0 * * 0`, `weekdays = 0 0 * * 1-5`; `manual` → `nextRunAt=None`, fires only via run-now. Validation at create/update (fail fast, 02 §6): exactly one of `cadence`/`cronExpr`; `cronExpr` must parse via croniter; `prompt` non-empty; `allowedTools` entries must not name tools of connectors excluded from scheduled runs (05 §1.8) `[design decision]`. Rejected `cronExpr` examples: 6-field with seconds, ranges out of bounds — croniter raises at parse.

### 3.2 API surface (05 §1.1, binding)

| Route | Behavior |
|---|---|
| `POST /api/tasks` | `TaskCreate{name, cadence?, cronExpr?, prompt, allowedTools}` → create + compute `nextRunAt`; `task.created` on SCHEDULER topic |
| `GET /api/tasks` | list all tasks |
| `PATCH /api/tasks/{id}` | `TaskPatch{status?, cadence?, cronExpr?, prompt?, allowedTools?}` — status transitions per 04 §4.2 (`active↔paused`, `active↔disabled`); cadence/cron change recomputes `nextRunAt`; `task.updated` |
| `DELETE /api/tasks/{id}` | cancels any queued session for the task (`queued→stopped`, 04 §4.3 step 5) then deletes the row; running sessions unaffected (`task_id` SET NULL, sessions survive — P1-4); `task.deleted` |
| `POST /api/tasks/{id}/run` | manual trigger ("run now", P2-1): fires via the 04 §4.3 path — direct start if slot free, else queued; **always recomputes** `nextRunAt = croniter.next(now)` (step-7 direct-start basis) `[design decision]`; overdue edge: a cadence/cron task that is past-due at run-now skips the elapsed occurrence — it is never replayed and never marked `missed`; for `manual`-cadence tasks `lastRunAt`/`lastRunSessionId` update and `nextRunAt` stays `None` (no schedule) |

`SchedulerEngine` owns task CRUD — never `SessionManager` (03 §4b). All `sched.notice`/`task.*` events publish on `Topic.SCHEDULER` → `WorkspaceServer` WS push (05 §1.5); subscriber isolation rules apply (a raising handler never kills the bus, 05 §1.5).

### 3.3 Tick computation and `nextRunAt` semantics

- **Storage/compare in UTC, compute in local wall-clock** (04 §1.3 P2-10) `[design decision]`: `nextRunAt` is persisted as ISO-8601 UTC; the croniter `next()` computation takes the local wall-clock time (system tz) and its result is converted to UTC for storage. The tick predicate `nextRunAt <= now` compares UTC instants — unaffected by tz changes.
- **DST policy (decided here)** `[design decision]`: croniter is wall-clock; we accept wall-clock scheduling with documented, deterministic behavior:
  - **Spring-forward gap** (nonexistent local time, e.g. 02:30 on the day clocks advance): croniter advances to the next valid time; the task fires then, and `nextRunAt` is recomputed from that actual fire time — the schedule resumes its normal grid the following period.
  - **Fall-back overlap** (ambiguous local time, e.g. 01:30 occurring twice): the task fires **once**, at the first pass of the ambiguous hour; recomputation from the fire time skips the second pass.
  - Both behaviors are deterministic under injected clocks; the test plan (§5) covers both transitions.
- **Tick loop**: fixed-interval poll (`Settings.schedulerTickSeconds`, default 15); 1-min cron precision is plenty (06 §5 row 7). Due selection is `status=active AND nextRunAt <= now`, ordered by `nextRunAt`. A task whose due time fell inside a tick gap (long tick, suspended laptop) still fires — `<= now` catches it on the next tick `[design decision]` (RESEARCH §2 — kimi polling model; we diverge from kimi by *replaying* rather than dropping, 02 §6).

### 3.4 Replay policy (missed runs)

- **One replay, latest occurrence only** `[design decision]` (RESEARCH §2 — kimi coalescing delivers missed fires once; openwork replays only the latest missed; we choose the openwork variant because each run is a session — multiple backfilled sessions have no utility for a single user).
- Trigger: boot only, via `recover_missed(now, lastBootAt)` (06 §2.1 step 3). Runtime ticks never create replays; the `Task.status=missed` row is transient — boot marks it and immediately enqueues the replay session (`missed → queued`, 04 §4.2), or skips the replay if the user paused/disabled the task meanwhile — the task stays in its user-set state (`missed → active` only when still active; `missed → paused`/`missed → disabled` otherwise, no reactivation).
- A `queued`/`missed` task with no queued session row at boot (orphan from a crash between the two writes of 04 §4.3 step 1) → `queued → active`, `nextRunAt` recomputed (04 §4.2 boot rule, P1-4).
- Replay sessions carry the same auto-approve policy and spawn-time gates as regular runs; nothing about the run itself differs (06 §2.1 — replayed runs must not sit queued behind a free slot, P2-3).
- Kimi's 7-day stale expiry is NOT adopted `[design decision]`: local-first means the task is owned by the machine; a week of down-time replays as exactly one run at the next boot, bounded by coalescing, so expiry adds no safety.

### 3.5 Mid-flight crash (03 §6 line 84)

Runner dies mid-run (crash, EOF mid-turn, watchdog, `error` event) → session `running→failed` (06 §4 rows 1–5); **the task is not re-fired and not marked `missed`** — it stays `active` with `nextRunAt` unchanged; `lastRunError` + `lastRunSessionId` record the failure; the next scheduled occurrence proceeds (04 §4.2, 06 §4 row 11). No retry-with-backoff in v1 (§6).

### 3.6 Auto-approve policy (binding, 02 §2/§7, RE §6)

- The task's `allowedTools` is the auto-approve policy: at spawn it is merged into the effective allowlist (`EffectivePolicy.allowed` = workspace policy ∪ user settings ∪ task `allowedTools`; exact merge rule → 07) and passed as `--allowedTools` under `--permission-mode manual` — **never** `bypassPermissions` (02 §2; Cowork's `sessionBypassPermissionsMode` is never enabled, RE §4).
- Unlisted tools are auto-denied by the CLI inside the run (`tool_result`); `PermissionGate` correlates the `tool_use` event against the policy (deterministic, never `tool_result` parsing — mission §5), records the denial in the audit trail (`PermissionRecord.decision="deny"`, `taskId` set), and publishes `permission.notice` → workspace. There is no mid-run approval channel and no timeout-deny (glossary).
- Connector tools: a task's `allowedTools` may name `mcp__<server>__<tool>`; the compiled `--mcp-config` for a scheduled run excludes interactive-OAuth connectors that are not pre-authenticated (`ConnectorRegistry.eligible_for_scheduled` = not `requiresOAuth` or `oauthPreAuthDone`, 02 §2, 05 §1.8). Naming a tool of an ineligible connector is rejected at task create/update `[design decision]` — fail fast at the boundary rather than an un-explained spawn-time denial.
- `manual` cadence tasks obey the same policy; there is no "ask me" mode for scheduled runs in v1.
- **Ask tools** (e.g. ask-user-question): auto-allowed in scheduled runs **iff** named in the task's `allowedTools` (07 §2.4 ask-tool line, parallel amendment); unlisted ask tools are auto-denied like any unlisted tool — a scheduled run never blocks on an unattended dialog (02 §7).
- **Probe note** (verification target): with the task allowlist applied, allowlisted tools produce **zero permission events** in the stream (verified in `-p` mode, 02 §6); an unlisted tool is auto-denied inside the CLI — the denial arrives as `tool_result` (plus CLI permission-denial diagnostics where emitted), and the audit decision is the **deterministic correlation of the `tool_use` event against the effective allowlist** (mission §5) — never `tool_result` string parsing.

### 3.7 Consecutive-failure counter → auto-disable

- **Threshold: 5 consecutive failed runs** `[design decision]` (RESEARCH §2 — OpenClaw auto-disables after 10 consecutive run failures; we pick 5: a week-day task failing daily disables within a week, faster than OpenClaw's fortnight, without being trigger-happy on transient network/auth failures).
- Override: `Settings.schedulerMaxConsecutiveFailures` (int, default 5, `[invented]`; typed accessor landed in 04 §1.7) — the `settings` table is key/value (04 §2), no schema change.
- Counting `[design decision]`: derived, no new column — count consecutive sessions for `taskId` whose terminal status is `failed`, ordered by `ended_at` desc (terminal time: a queued session created before a later direct-run can end after it — `ended_at` is the accurate ordering, though the serialized single slot makes divergence unlikely). Streak-breakers (never failures): any run ending `done`; `running→stopped` (user stop mid-run); `queued→stopped` (cancel, 04 §4.3 step 5). Included: pre-spawn failures (binary missing, health-check timeout, drain failure P2-2), watchdog kills, and mid-run crashes (03 §6 line 84). **Manual runs count equally** — a `manual`-cadence task auto-disables after N consecutive failed manual runs; the counter is per-task, not per-trigger-type `[design decision]`.
- On threshold: `task.status = disabled` (the `active → disabled` auto-disable row landed in 04 §4.2; referenced here), `lastRunError = "auto-disabled: N consecutive failed runs"`, `task.updated` published. The task stays `disabled` until the user explicitly enables it (`disabled → active`, 04 §4.2). No auto-re-enable, no silent retry.

### 3.8 Event surface (05 §1.5 binding)

`Topic.SCHEDULER` payloads: `task.created|task.updated|task.deleted` → `{task}`; `sched.notice` → `{taskId, action}` with `action ∈ queued|drained|missed|started` — emitted at: enqueue (queued), drain begin (drained, 04 §4.3 step 3), boot mark (missed), direct start (started, P3-25). No notice for auto-disable — the `task.updated` payload carries `status="disabled"` + `lastRunError`; the workspace renders the disable reason from `lastRunError`.

`Session.taskId` correlation (04 §1.1, binding): non-null ⇔ scheduled run; the workspace renders scheduled runs with the owning task's name; `GET /api/tasks/{id}` results surface `lastRunSessionId` so the user navigates session → artifacts (mission §3.2: results visible).

## 4. Component Touchpoints

| Component | Role |
|---|---|
| `SchedulerEngine` | Task CRUD (05 §1.7); 15 s tick; 04 §4.3 handoff (write order, drain re-arm, drain-failure → task `active` + recompute, P2-2); `recover_missed` at boot; `sched.notice`/`task.*` publishes; consecutive-failure counter derivation |
| `SessionManager` | One-active-slot gatekeeper (02 §7): `start_session` raises if busy; only SchedulerEngine creates scheduled sessions; `session.ended` → drain trigger (05 §1.5) |
| `RunnerAdapter` | Spawn with task policy → `SpawnSpec.allowed_tools` (05 §2.1); teardown group-kill on every exit path (05 §3.3) |
| `PermissionGate` | `resolve_policy` at spawn (task `allowedTools` ∪ workspace ∪ user); denial correlation + `permission.notice` + audit rows with `taskId` (05 §1.4) |
| `ConnectorRegistry` | `eligible_for_scheduled` gate on the compiled `--mcp-config` for scheduled runs (05 §1.8) |
| `Storage` | Task rows + `next_run_at` index; `transition` with one-active invariant (no TOCTOU, P1-5); `ON DELETE SET NULL` on `sessions.task_id` and `permissions.task_id` (04 §2) |
| `WorkspaceServer` | `/api/tasks*` routes; WS `sched.notice`/`task.*` push (05 §1.1) |
| `EventBus` | SCHEDULER topic publishers/subscribers matrix (05 §1.5); tick path direct-call to SessionManager is intentional (03 §6 line 83) |
| Runtime (boot) | Reconcile running sessions FIRST, then `recover_missed` — recovered runs never observe a phantom `running` session (06 §2.1, §7) |

### 4.1 Handoff contracts (who calls whom, in order)

- **Tick (direct)**: `SchedulerEngine.tick(now)` → `Storage.list_due(now)` → per due task: `SessionManager.create_session(task_id=…)` (`pending`) → publish `sched.notice(started)` → `SessionManager.start_session(id)` → (spawn path, 05 §2.1). Failure at `start_session` (invariant/race) → session `pending→failed` (`error="start failed"`), task → `active` with `nextRunAt` recomputed — same drain-failure rule as 04 §4.3 step 4 (P2-2).
- **Tick (queued)**: `Storage.insert_session(status=queued, task_id)` → `Storage.set_status(task, queued)` → publish `sched.notice(queued)` → re-arm drain attempt (P1-5).
- **Drain** (on `session.ended` or re-arm): oldest `queued` task+session → publish `sched.notice(drained)` → `SessionManager.start_session(id)` → on success task → `active` + `nextRunAt` recompute (04 §4.3 step 3; **replay sessions** recompute per the step-7 replay rule — `croniter.next(latest_missed_occurrence_local)`, overriding step 3); on raise → queued session → `failed` (`error="drain failed"`), task → `active` + recompute (P2-2) — never re-armed on the next tick, never a stranded `queued` row.
- **Boot** (06 §2.1 order, binding): (1) reconcile sessions (PID liveness, reuse guard, orphan group-kill, `running→failed`) — this frees the slot; (2) orphan task rule (`task=queued` with no `queued` session → `active` + recompute, P1-4); (3) `recover_missed` (replay policy, §3.4 of this doc); (4) start the tick loop. Step order is enforced: recovery must never observe a phantom `running` session (06 §7).
- **User actions**: `PATCH status=paused|disabled` does **not** stop an already-queued session — the queued run continues to drain and completes (04 §4.2: "user pauses the task; the queued session (if any) continues to drain — pause affects future runs only"); **the task itself stays `paused`/`disabled` after the drain — draining does not reactivate it**. Interpretation pinned here: the 04 §4.2 `queued → active` row applies only when the task is `active` at drain time — a paused/disabled task's queued session drains to `done|stopped|failed` without flipping the task; a paused/disabled task is never selected by tick or `recover_missed`. Cancel is explicit and separate: `queued → stopped` (04 §4.3 step 5). `POST /run` → same 04 §4.3 path, bypassing the due check (manual trigger).

## 5. Acceptance Criteria (testable)

1. A task with `nextRunAt` in the past (and app down at that time) is replayed exactly once within one tick interval of boot; the replayed session starts immediately when the slot is free (P2-3).
2. Tick fires a due task into a free slot → `sched.notice(action="started")`, session `pending→running→done`, `lastRunAt`/`lastRunSessionId` set, `nextRunAt` advanced.
3. Tick fires while an interactive session is active → `task.status=queued` + `Session(status=queued)` written in order (P1-4); on `session.ended` the queued session drains `queued→running→done`, task → `active`.
4. App down for 3 days over a daily task → exactly one replayed run at boot (coalescing); `nextRunAt` recomputes from the latest missed occurrence (grid-preserving) and is never past-due — if the grid advanced past the occurrence following the latest missed one while the replay sat queued, `nextRunAt` is the first grid point strictly after `now`.
5. `POST /api/tasks/{id}/run` on a `manual` task with a free slot → immediate direct start; with a busy slot → queued session; `nextRunAt` stays `None`.
6. Auto-approve: a run whose prompt uses a task-`allowedTools` tool executes it with no notice; a tool outside the policy is auto-denied, a `permission.notice` with `deny` and an audit row (`taskId` set) are produced, and the run continues to completion.
7. Five consecutive failed runs (e.g. injected `claude` binary failure) → `task.status=disabled` with `lastRunError` recording the reason; a successful run resets the streak; a paused/disabled task is never selected by tick or `recover_missed`.
8. App killed mid-run (SIGKILL during a scheduled run) → boot reconcile marks the session `failed` (PID-reuse-guarded), the task stays `active` with `nextRunAt` unchanged, and the next occurrence fires normally (06 §4 row 11).
9. Watchdog: a runner producing no events for `runnerNoEventTimeoutMinutes` is failed + group-killed; the task is not re-fired and not marked `missed`.
10. Deleting a task with a queued run cancels the queue (`queued→stopped`); deleting a task with a running/done session leaves the session intact (`task_id` NULL) and audit rows intact (P1-4).
11. DST: with injected clocks, a daily 02:30 task skips to the next valid time on spring-forward and fires once on fall-back (§3.3 policy, this doc).
12. Exactly-one validation: `TaskCreate` with both/neither of `cadence`/`cronExpr` is rejected by Storage (04 §1.3).
13. Pausing or disabling a task with an already-queued session does not cancel it — the queued run drains to completion; cancel (`queued → stopped`) is a separate explicit action (04 §4.3 step 5).

### 5.1 Test harness (how the criteria are verified)

- **Clock injection from day one** (RESEARCH §Gotchas — kimi-code bans `Date.now()` outside clock injection): `SchedulerEngine` and `recover_missed` take an injectable `now()`; tests drive boot, DST, and missed-window scenarios without sleeping. Acceptance 2/3/4/8/11 are clock-driven unit tests against the real `Storage` (SQLite in-memory, WAL) with a stub `SessionManager`/`RunnerAdapter`; the tick loop is exercised with `schedulerTickSeconds` overridden to 0.05 in integration tests.
- **Spy spawn**: `RunnerAdapter` is stubbed to record `SpawnSpec.allowed_tools` per run and emit scripted events (denial-bearing `tool_use`, `result`, or silence for the watchdog case) — acceptance 6/9 verify policy plumbing and watchdog behavior without spawning the real CLI.
- **Boot simulation**: `lastBootAt` is seeded to a known past instant; `recover_missed` runs against tasks with `nextRunAt` inside `(lastBootAt, now)`; assertion = exactly one replayed session row, `TaskStatus` path `missed → queued → running` (slot free) or `queued` (slot busy, P2-3).
- **Failure-streak test**: N injected `failed` terminal sessions (scripted `error`/watchdog) followed by one `done` session → counter resets; 5 `failed` in a row → `disabled` with `lastRunError` set.

## 6. Out of Scope (v1)

- **Cloud scheduling** (run without device online — Cowork's July pivot, RESEARCH §2): v1 is local-only; design headroom: `ScheduledTask` rows are server-sync-shaped (per-task session runs, no local-folder coupling required by the runner) (03 §5 line 70, RE §10).
- **Cron jitter / randomization** (kimi-code deterministic jitter, RESEARCH §2): load-spreading is a quota-farm concern; a single-user local engine gains nothing. [design decision]
- **Multiple concurrent scheduled runs**: the one-slot invariant serializes them (02 §7); overlapping scheduled runs queue (06 §3 row 2).
- **Per-run notification delivery beyond WS `sched.notice`/`task.*` push**: no OS notifications, no email, no dashboard feed in v1.
- **Retry-with-backoff** for failed scheduled runs: mid-flight crashes are not re-fired (03 §6 line 84); the consecutive-failure counter only disables.
- **Task quotas and stale expiry** (kimi quotas, 7-day expiry, RESEARCH §2): single-user, no account tiers; expiry adds no safety given coalescing (§3.4, this doc).

## 7. Open questions (for review)

- `recover_missed` replay order when multiple tasks missed during the same down-window: FIFO by `nextRunAt` (selected in this PRD) vs priority-by-cadence — confirm.
- Whether `lastRunError` on auto-disable is the right place for the reason (vs a dedicated field in a later 04 amendment).
