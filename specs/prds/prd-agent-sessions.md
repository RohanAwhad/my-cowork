# PRD — Agent Sessions

> Writer: W4a (prd-agent-sessions) | Status: written — pending review
> Grounding: 01 §3.1, 02 §2/§6/§7, 03 §3/§4a/§6, 04 §1.1/§1.2/§4.1/§4.3, 05 §1.1–§1.5/§2/§3, 06 §2/§3/§4/§5; RE §2/§4; docs/.assets/cowork-app-re/session-lifecycle.md §1–§8
> Binding: glossary statuses, 02 §2 spawn template, 05 §2.2 event mapping, 06 §2.3 ordering. This PRD owns the v1 session lifecycle end-to-end; it does not re-decide anything already fixed in 02/04/05/06.

## Current Behavior

- User starts a task in the claude.ai renderer; `startSession` creates `local_<uuid>` + a docker-style `vmProcessName`, persists the session JSON **before** the VM boots, and buffers the first user message immediately (RE §2; session-lifecycle §1.1–§1.4).
- Initialization runs a fixed step sequence `auth → skills → prompt → mcp_setup → query → complete`, emitting per-step status to the UI; `complete` is reached only on the **first streamed message** (session-lifecycle §2, §6.2).
- Tool-call permissions are a **mid-run dialog channel**: `canUseTool` → `tool_permission_request` → renderer dialog → `deny/once/always`, with a full `audit.jsonl` trail of every request/response (RE §4; session-lifecycle §4.3).
- Turn end is the `result` event (`num_turns`, `is_error`): the file watcher stops and the session's VM process is SIGTERMed after every completed turn; `stopSession` = interrupt → `inputStream.done()` → SIGTERM (session-lifecycle §6.2, §8.1).
- Artifacts surface via a per-session `FileSystemWatcher` emitting `fs_file_created`/`fs_file_deleted` (RE §1/§2; session-lifecycle §5); the transcript itself is NOT in the session JSON — it lives in the CLI's `.claude/projects/*.jsonl` (session-lifecycle §7.2).
- Archive marks the record archived and deletes uploads only; transcript and files persist (session-lifecycle §7.4). Sessions are resumable (`--resume` with `cliSessionId`, session-lifecycle §3.2).

## Desired Behavior

As a user I start a session from the workspace, watch it run live, see report-only notices when a tool call is denied, and get a persisted transcript plus artifacts when it ends.

Numbered flow (order per 06 §2.3 — binding; the CLI gates `init` on the first stdin message, P1-1):

1. `SessionManager.create_session` persists the row (`status=pending`) and mkdirs `sessions/<id>/outputs` **before** any spawn (persistence-before-spawn, RE §2); `init_status(step=auth)` emitted.
2. `SessionManager.start_session` — gatekeeper of the one-active invariant (02 §7): raises if `active_session()` exists; final authority is `Storage.transition` inside the same transaction (P1-5, 04 §4.3). An interactive start while a `queued` session exists is allowed — the queued session stays queued; the invariant is one `running`, not one `pending|queued` (04 §4.3 step 6).
3. `RunnerAdapter.spawn(SpawnSpec)` — binding args from 02 §2, env from 05 §2.1, **first message buffered** (RE §2); `init_status(step=prompt→mcp_setup→query)` markers per phase (05 §2.2 mapping); the Cowork `skills` step is **skipped — not emitted** — in v1 (no skills sync); the emitted sequence is `auth → prompt → mcp_setup → query → complete` [design decision].
4. **Flush the first message** to stdin as NDJSON — the buffered `UserMessage` (05 §3.1).
5. **Await first `system`/`init` or `error` event** within `spawnHealthTimeoutSeconds` (30 s, 06 §5 row 1): the health check passes on the first `system`/`init` — typically `init`, carrying `session_id` + the full tools list [probe 2.1.220] — or `error`; a **non-init `system` alone keeps the health timer running** (it is stored as a `message` event, no status change); an early `error` fails the health check immediately (P3-3); timeout → `pending→failed` with stderr tail in `session.error` (P1-7).
6. The `init` **subtype** binds `cliSessionId` (mapping our UUID → CLI id, RE session-lifecycle §6.2) → `pending→running` (04 §4.1): the transition REQUIRES `init` — a first non-init `system` is health-sufficient but not run-sufficient; `session.started` + `session.updated` + `init_status(step=complete)` published.
7. Events stream: every stream-json event is unwrapped (top-level `stream_event` wrapper, verbose mode), mapped per 05 §2.2, appended to `session_events` + `transcript.jsonl`, published as `session.event`; unknown types → `eventType="raw"`, **never raises** (P1-2).
8. `PermissionGate` (EventBus subscriber on `Topic.SESSION`) correlates each `tool_use` against the effective allowlist — deterministic (mission §5); the final `result` event's `permission_denials[]` (probe 2.1.220) is a **second deterministic recording source**, reconciled content-agnostically (tool names only — no `tool_result` string parsing); a deny writes a `PermissionRecord` and publishes `permission.notice` (report-only, no dialog, 02 §6).
9. `result` event → `running→done`, `numTurns`/`isError` persisted (04 §4.1); then `ArtifactWatcher.stop_watching` final scan (P2-12 — the CLI may write between `result` and kill) and teardown (step 11).
10. `SessionManager` publishes `session.ended` → SchedulerEngine drains the queue (04 §4.3 step 3).
11. Teardown protocol on every exit path (05 §3.3, P1-7): stdin EOF → ≤5 s → SIGTERM process group → ≤3 s → SIGKILL process group; `exitCode` recorded.
12. Errors at any step (spawn failure, health timeout, runner crash, EOF mid-turn, `error` event, no-event watchdog 06 §4 rows 1–4): fail the session (`pending→failed` or `running→failed`), run the teardown group-kill, **never fail the app** (02 §6, 03 §1).

## I/O Contracts

### HTTP/WS API — session surface of 05 §1.1

| Route | In | Out | Note |
|---|---|---|---|
| `POST /api/sessions` | `SessionCreate{prompt, folderGrants: list[Path], allowedTools?, deniedTools?}` | `Session` (`pending`) | 409 `{"error":{"code":"session_conflict","message":"<detail>"}}` if a session is `running` (02 §7); a `queued` session does NOT block the start (04 §4.3 step 6) |
| `POST /api/sessions/{id}/stop` | — | `Session` | user stop; teardown protocol; `running→stopped` (queued: `queued→stopped`) |
| `POST /api/sessions/{id}/archive` | — | `Session` | terminal; transcript + artifacts retained (session-lifecycle §7.4 analog) |
| `GET /api/sessions/{id}/transcript` | — | `list[SessionEvent]` ordered by seq | primary transcript store (04 §1.2) |
| `GET /api/sessions/{id}/events?after_seq=` | — | `list[SessionEvent]` | WS replay cursor (P3-24) |

WS `/ws` (server→client only; commands over HTTP): `session.started {sessionId}`; `session.init_status {sessionId, step}`; `session.event {sessionId, seq, eventType, payload}`; `session.updated {sessionId, status}`; `session.ended {sessionId, status, reason}`; `session.archived {sessionId}`; `permission.notice {sessionId, toolName, decision, reason}`. `session.updated` fires on EVERY `Storage.transition()` (every status change), alongside `session.started` on `pending→running` and `session.ended` on terminal transitions (04 §4.1). `init_status` steps emitted in v1: `auth → prompt → mcp_setup → query → complete` (`skills` skipped — no skills sync, 05 §2.2 mapping). WS disconnect never affects the session (06 §5 row 5); reconnect re-syncs via `events?after_seq=`.

### RunnerAdapter `SpawnSpec` → stream-json consumption (05 §2.1/§2.2)

`SpawnSpec{command, args: -p --verbose --output-format stream-json --input-format stream-json, permission_mode:"manual", allowed_tools, denied_tools, add_dirs, mcp_config, cwd: first granted folder else outputsDir, env: CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 + MCP_TOOL_TIMEOUT=30000 + COWORK_SESSION_ID + COWORK_POLICY_FILE + shared CLAUDE_CONFIG_DIR (02 §2), append_system_prompt (memory, 02 §2), first_message (buffered pre-spawn), health_timeout_s: 30, process_group: True}`.

| stream-json type | SessionEvent.eventType | Session fields / payload |
|---|---|---|
| `system` subtype `init` | `init` | `cliSessionId` bound; health-check success; payload `{session_id, slash_commands}` (+ full tools list, probe 2.1.220) |
| `system` (other) | `message` | `{kind:"system", content}` — health timer continues (no status change) |
| `assistant` | `message` | `{kind:"assistant", content}` |
| `assistant` w/ `tool_use` block | `tool_use` | `{id, name, input}` — the **only** live decision source for PermissionGate (05 §1.4) |
| `user` (echo) | `message` | `{kind:"user", content}` (P1-2 — user echo is mapped, not dropped) |
| `tool_result` | `tool_result` | `{tool_use_id, is_error, content}` — stored, **never** parsed for decisions (mission §5) |
| `result` | `result` | `numTurns`/`isError`; payload `{num_turns, is_error, permission_denials}` (permission_denials per probe 2.1.220); triggers `running→done` |
| `error` | `error` | `session.error`; triggers `running→failed` |
| (process exit) | `close` | `exitCode`; final flush |
| (internal) | `init_status` | `{step}` — spawn-phase marker, not a stream event (P3-5) |
| anything else | `raw` | verbatim payload; pipeline never raises (P1-2) |

Every row is also appended raw to `sessions/<id>/transcript.jsonl` (04 §3). `transition()` + `append_event()` commit atomically (05 §1.9).

### Stdin NDJSON (05 §3.1)

```json
{"type":"user","uuid":"<uuid>","session_id":"<cliSessionId or None>","message":{"role":"user","content":[{"type":"text","text":"<prompt>"}]}}
```

`session_id` = our session UUID string until `init` returns the real CLI id [design decision]. v1 is single-turn: the first message is the only message (P2-11); `result` = turn end, no further turns [design decision — RE §2 is multi-turn].

### Permission notice flow (report-only, 02 §6)

- The raw CLI in `-p` mode emits **no** `permission_request`; unallowed tools are auto-denied inside the CLI, and the denial arrives as a `tool_result` [design decision] (verified).
- `PermissionGate.on_event` subscribes to `Topic.SESSION`; for each `tool_use` it applies `decide(tool_use, EffectivePolicy)` — deterministic correlation against the effective allowlist (workspace ∪ user settings; `--disallowedTools` always binds, merge rule → 07). `tool_result` strings are never the decision source (mission §5).
- `deny` → `PermissionRecord{decision:"deny", reason:"tool_use correlated against effective allowlist: not listed", input}` + `permission.notice` on WS. `approve_future` is **recorded only** (`decision:"approve_future"`) and applies to the next spawn via `consumedBySessionId` (P3-22); no mid-run channel, no timeout-deny (glossary).
- `result.permission_denials[]` reconciliation: on the final `result` event, any denial listed there (tool names only) with no matching `PermissionRecord` is recorded — content-agnostic, deterministic, no `tool_result` string parsing (mission §5; probe 2.1.220).

### Teardown protocol (binding, 05 §3.3 + 02 §2)

1. `close_input()` (stdin EOF; clean exit in `-p` mode); wait ≤ 5 s for exit.
2. SIGTERM to the process group (negative pid of the `start_new_session` group leader); wait ≤ 3 s.
3. SIGKILL to the process group.
4. Record `exitCode`; `running→stopped|failed` accordingly.

Applies to **every** exit path — user stop, natural end (`result`), runner crash, health-check failure, graceful shutdown (P1-7) — so orphan `claude` processes are impossible by construction; belt-and-braces boot reconcile still scans (02 §7, 06 §2.1).

## Component Touchpoints

| Component | Role in this PRD |
|---|---|
| `SessionManager` | Lifecycle policy owner (03 §3): create/start/stop/archive; internal `_on_init/_on_stream_event/_on_result/_on_error/_on_close` handlers (05 §1.2); publishes `Topic.SESSION` |
| `RunnerAdapter` | Process mechanics: `spawn(spec)` returns `RunnerHandle` (send/close_input/stop/events/stderr/pid/identity); sole kernel abstraction (02 §2); no lifecycle decisions |
| `PermissionGate` | EventBus subscriber on SESSION; `decide()` + `record()` + `permission.notice` publish; spawn-time `resolve_policy` consumed by SessionManager at spawn (05 §1.4) |
| `EventBus` | `Topic.SESSION` pub-sub; subscriber isolation (detach after 3 raising handlers, P-invented 05 §1.5); `publish()` never raises |
| `Storage` | `insert_session`, `transition` (one-active check in-txn, P1-5), `append_event` + `list_events` (replay), `append_permission` + audit.jsonl mirror (P2-14), `reconcile_running` (06 §2.1) |
| `WorkspaceServer` | HTTP commands + WS push; replay cursor; never owns session state (06 §5 row 5) |
| `SchedulerEngine` | Consumes `session.ended` → queue drain (04 §4.3); may create `queued` sessions; only it and boot reconcile may do so (04 §4.3 step 6) |

## State Machine Compliance

Transitions driven by this PRD (04 §4.1 — no transitions outside the glossary chain, 02/04 binding):

- `pending → running`: `init` subtype received within the health window (P1-1) — the health check passes on the first `system`/`init` or `error`, but the transition REQUIRES `init` (binds `cliSessionId`); a non-init `system` keeps the timer running.
- `pending → failed`: pre-spawn error (settings/connector resolution), spawn error/binary missing, health-check timeout or early `error` (P3-3); teardown group-kill applies (P1-7).
- `queued → running`: slot free — SchedulerEngine drain or boot reconcile direct-start (P1-6); identical pending-path spawn (04 §4.3).
- `queued → stopped`: user cancels the queued run (04 §4.1).
- `queued → failed`: drain failure (`start_session` raises), graceful app shutdown, or boot-reconcile orphan (04 §4.1).
- `running → done`: `result` received; `numTurns`/`isError` persist in the same transaction.
- `running → stopped`: user stop or graceful shutdown; teardown completed (02 §2).
- `running → failed`: runner crash, EOF mid-turn, `error` event, no-event watchdog (06 §4 rows 1–5).
- `done | stopped | failed → archived`: user archives; terminal.

Invariants: persistence-before-spawn (the `pending` row exists before any process starts, RE §2); one-active-session checked by `Storage.transition(→ running)` in the **same transaction** as the write (P1-5 — no TOCTOU); boot reconcile (`running → failed`, `error="app restarted"`) runs before scheduler recovery so recovered tasks never see a phantom `running` slot (06 §2.1, §7); PID-reuse guard — identity mismatch means dead, never kill (02 §7, 06 §4 row 12). Every transition emits `session.updated` on WS (05 §1.1), with `session.started`/`session.ended` accompanying `pending→running` and terminal transitions. Stopped sessions are terminal until archived; `--resume` is not in the v1 spawn template (06 §2.4).

## Acceptance Criteria

1. GIVEN no other session running WHEN `POST /api/sessions` THEN a `pending` session row exists in SQLite and `sessions/<id>/outputs` exists BEFORE any `claude` process is spawned; the session stays `pending` until the `init` subtype arrives, and `cliSessionId` is bound before `pending→running` (persistence-before-spawn + init binding, RE §2; probe 2.1.220).
2. GIVEN a `running` session WHEN a second `start` is attempted THEN the request fails with HTTP 409 `{"error":{"code":"session_conflict","message":"<detail>"}}` and no second process is spawned (02 §7). GIVEN only a `queued` session THEN the start succeeds and the queued session stays queued (04 §4.3 step 6).
3. GIVEN a CLI that emits no first event THEN `pending→failed` within `spawnHealthTimeoutSeconds` with the buffered stderr tail in `session.error` and the process group SIGKILLed (P1-7).
4. GIVEN a CLI that emits `error` during startup THEN `pending→failed` immediately, not after the timeout (P3-3).
5. GIVEN an unknown stream-json type THEN it is stored as `eventType="raw"` with verbatim payload and the pipeline continues without raising (P1-2).
6. GIVEN the CLI echoes the user message THEN the echo is persisted as a `message` event, not dropped (P1-2).
7. GIVEN a `tool_use` not in the effective allowlist THEN a `PermissionRecord{decision:"deny"}` is written and a `permission.notice` is published; the accompanying `tool_result` is stored but never parsed for the decision (mission §5). GIVEN a denial listed in `result.permission_denials[]` with no prior record THEN it is recorded from that source — content-agnostic, tool names only (probe 2.1.220).
8. GIVEN a `result` event THEN `running→done`, `numTurns`/`isError` persisted, and `session.ended` published atomically with the `result` event row.
9. GIVEN the CLI writes a file between `result` and teardown THEN the final `stop_watching` scan versions it (P2-12).
10. GIVEN a natural end THEN teardown is stdin EOF → clean exit within 5 s with `exitCode=0` recorded.
11. GIVEN `POST /api/sessions/{id}/stop` mid-run THEN `running→stopped`, group teardown completed, `exitCode` recorded; transcript/artifacts remain (06 §2.4).
12. GIVEN a WS client disconnected and reconnected THEN `GET /api/sessions/{id}/events?after_seq=` replays the gap; the session itself is unaffected (P3-24).
13. GIVEN an app restart with `running` rows THEN boot reconcile probes each identity; a live PID with mismatched start time is NOT killed (PID-reuse guard); a matched orphan is group-killed and the row → `failed ("app restarted")` (06 §2.1).
14. GIVEN a runner emitting no events for `runnerNoEventTimeoutMinutes` THEN `running→failed` with `error="no events for N min"` and group teardown (06 §4 row 4).
15. GIVEN non-NDJSON garbage on stdout THEN the session fails with the `cli_stdout_pollution`-style category [design decision, RE session-lifecycle §6.2] and teardown runs.
16. GIVEN a non-init `system` event arrives before any `init` THEN the health timer keeps running, the event is stored as a `message` event, and status stays `pending` until `init` or timeout (probe 2.1.220).

## Out of Scope (v1)

- Multi-turn messaging: no `send_message` (P2-11); the first message is the only message; `result` = session end [design decision — RE §2 is multi-turn, Cowork's hot path is out].
- Resume: `--resume` is not in the spawn template; `stopped`/`failed` sessions are terminal until archived (06 §2.4).
- Plugin ecosystem, skills sync, knowledge bases (glossary `plugin` = v2; RE §4 KBs deferred to prd-memory).
- Uploads / image attachments (session-lifecycle §6.1/§6.3 → prd-local-files).
- Cloud sync / remote sessions (mission §4 non-goal 1); the `claude` CLI's own auth is its own concern (02 §1).
- Mid-run permission dialogs, runtime folder requests (`request_cowork_directory` analog → prd-local-files), model selection, system-prompt customization, session sharing/export (RE §5 `shareSession` analog not before v2).
