# 02 — Constraints

> Writer: W1 (foundation) | Status: written — pending review

Non-negotiable rules. Docs that follow (architecture, data model, interfaces, runtime, security) must conform; deviations require an amendment to this file.

## 1. Local-first rules (binding)

- **No Anthropic cloud APIs called by our code.** The `claude` CLI subprocess manages its own auth and network (OAuth/PKCE, token cache — RE §5). Our components never hold, refresh, or proxy Anthropic credentials `[design decision]`.
- **Everything persists on the host.** Sessions, tasks, artifacts, permissions, and audit trail live in local storage (SQLite + files on disk) (RE §7 — on-disk data model as reference) `[design decision]`.
- **Works with network disabled.** The workspace — WorkspaceServer, session lifecycle, spawn-time permission policy application, artifact watching, scheduling, persistence — must function with the network fully disabled, except for whatever the `claude` CLI subprocess itself needs (i.e., an interactive session started with no network may fail *inside the runner*, not in the workspace) `[design decision]`.

## 2. Runner contract

- **Kernel**: the host `claude` CLI (Claude Code), spawned per session as a subprocess in `-p` (print) mode. The session is UI-driven, not interactive at the CLI level. Verified against `claude` 2.1.220: `stream-json` output and stream input only work with `-p`, and `--output-format stream-json` requires `--verbose`.
- **Exact spawn template (binding, v1)**:
  `claude -p --verbose --output-format stream-json --input-format stream-json [--permission-mode manual] [--allowedTools <allowlist>] [--disallowedTools <denylist>] [--add-dir <granted-folder> ...] [--mcp-config <cfg>] [--strict-mcp-config] [--append-system-prompt <workspace memory text>]`
  - All user messages, including the first, are written to stdin as NDJSON (`{"type":"user", ...}`); the first message is buffered pre-spawn and flushed post-spawn (RE §2 — first message buffered).
  - Scheduled runs use the same `--permission-mode manual` with `--allowedTools <policy tools>`; unlisted tools are auto-denied by the CLI (mirrors Cowork's `shouldAutoApprovePermission`, RE §6).
  - `--append-system-prompt <text>` is passed when workspace memory is enabled; it is model-side only and NOT visible in stream-json events `[probe 2026-08-07]`.
- **Folder grants (v1 — no mounts)**: enforced at spawn via `--add-dir <granted-folder>` (CLI permission scoping) + spawn cwd confinement; a PreToolUse path-filter hook adds path granularity but is best-effort (see hooks). Grants are otherwise advisory UI state persisted per session `[design decision]`. The HARD boundary is the spawn-time allowlist: `--allowedTools`/`--disallowedTools` overlap → denied-wins, unlisted tools are removed from the model's toolset entirely `[probe 2026-08-07]`.
- **Hooks (binding mechanism)**: directory-based hooks (`~/.claude/hooks/PreToolUse/<name>`) are dead — the registry scans settings.json only `[probe 2026-08-07]`. The only mechanism is settings.json `"hooks": {"<HookEvent>": [{"matcher": "...", "hooks": [{"type": "command", "command": "...", "timeout": 30}]}]}` `[probe 2026-08-07]`. v1 installs ONE thin static PreToolUse hook script (matcher `"*"`) by appending an entry to the user's settings.json with explicit user consent, never overwriting existing entries `[design decision]`. Per-session policy via `COWORK_POLICY_FILE` env; per-session identity via `COWORK_SESSION_ID` env (hook process inherits CLI env `[probe 2026-08-07]`). Hook errors are non-blocking by CLI design: nonzero exit / bad JSON → tool proceeds; only an explicit `{"hookSpecificOutput":{"permissionDecision":"allow"|"ask"|"deny"}}` decision blocks `[probe 2026-08-07]`. Hooks are therefore path-granular best-effort; hook absence or error degrades to allowlist-only — still fail-closed at the tool level.
- **No handshake**: there is no stdout stream handshake. Health check = wait for the first `system`/`init` event with a timeout, then proceed (verified: first events are `system` carrying `session_id`).
- **Teardown sequence (binding)**: close stdin (EOF → clean exit, verified) → if still alive, SIGTERM → SIGKILL (RE §2 — result → kill; stop = interrupt → inputStream.done() → SIGTERM) (RESEARCH §Gotchas — managed process lifecycle).
- **Config dir**: spawn with the user's shared Claude config dir (do not set an isolated `CLAUDE_CONFIG_DIR`) so the user's settings.json allowlists and hooks keep applying `[design decision]`; a per-session isolated dir silently disables user permission settings. Revisit only if isolation is required for correctness. **Precedence**: effective allowlist = workspace policy ∪ user settings; `--disallowedTools` always binds. → Owned by: 07-security-permissions.md (exact merge rule).
- **Version pinning**: the supported `claude` CLI version is pinned exactly in `docs/` (mirroring Cowork's pinned binary, RE §3). The user may override via settings; overrides are recorded in the audit trail — `[design decision]`. The system shall not silently use an untested version.
- **MCP**: connector mechanism is the CLI `--mcp-config` (`--strict-mcp-config` to ignore other MCP sources); `-p` mode has no TTY, so connector OAuth must be pre-authenticated outside the session (e.g. `claude mcp login`), and interactive-OAuth connectors are excluded from scheduled runs in v1. The settings.json `mcpServers` key is silently ignored by the CLI `[probe 2026-08-07]` — the ConnectorRegistry must compile and pass a `--mcp-config` file, never settings.json. → Owned by: prd-mcp-connectors.
- **Replaceable kernel**: `RunnerAdapter` is the sole abstraction over the agent kernel (glossary). It must expose run/stop/input APIs over a typed interface so the CLI can be swapped without touching `SessionManager` or downstream consumers (RE §2 — Cowork's SDK `query()` with custom spawn is the pattern) `[design decision]`.

## 3. Platform

- **Target**: macOS (dev environment). The `claude` binary is resolved from `~/.claude/local/claude` first, then `claude` on PATH; both documented `[design decision]`.
- **No VM/container sandbox in v1**: execution is host-native; isolation is via PermissionGate spawn-time policy (02 §2 folder-grant primitives). A sandbox tier (RE §3 VM layer) is explicitly out of scope for v1.
- **POSIX paths everywhere.** No Windows path handling in v1; path validation assumes POSIX semantics.

## 4. Stack policy (binding)

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.12+ | type hints required |
| Persistence | SQLite, WAL mode | plain `sqlite3` or a thin layer; no ORM beyond what is needed |
| Server | FastAPI + uvicorn + websockets | `WorkspaceServer` HTTP/WS API for the UI (RESEARCH — kimi `web` local REST+WS server as a blueprint) |
| Contracts | pydantic | all I/O shapes, validation at boundaries |
| Logging | loguru | `LOGGING_LEVEL` env var; file sink under `logs/` (project convention) |
| Async | asyncio | websockets + subprocess streaming |

- **WorkspaceServer binds 127.0.0.1 only**; auth (per-run bearer token or strict Origin check) is defined in 07-security-permissions.md. → Owned by: 07-security.

No new frameworks or libraries unless a spec doc justifies them.

## 5. Dependency policy

- **Minimal deps.** Each third-party dependency must appear with a justification in a spec/PRD.
- **No Electron** `[design decision]` — UI is server-rendered/simple static assets served by FastAPI; v1 has no build step; any build tooling requires justification in a spec/PRD (RESEARCH §Design decisions — Electron dominates clones; we deliberately diverge for a zero-build local-first surface).
- File previews render via browser-native embeds (e.g. `<embed>` for PDF), not converter libraries, in v1 (RESEARCH §Gotchas — sandboxed iframes render PDFs blank).

## 6. Failure behavior

- **Fail fast.** No `try/except` swallowing (project error policy). Exceptions surface with stack traces to the log; session status reflects the failure (`failed`).
- **Runner failures are contained at the boundary** `[design decision]`: a crashing `claude` subprocess fails the session, not the workspace (RESEARCH §3 — local sessions degrade gracefully, "workspace unavailable", as the analog).
- **SchedulerEngine is crash-recoverable**: on boot it recomputes missed triggers from persisted task state and fires them (missed-run recovery), consistent with the coalescing model (RESEARCH §2 — kimi-code coalescing, openwork replay-only-latest-missed) `[design decision]`; policy for which occurrences replay is documented in the scheduled-tasks PRD.
- **PermissionGate is spawn-time and fail-closed**: in `--permission-mode manual` unallowed tool calls are auto-denied inside the CLI — no `permission_request` event is emitted in `-p` mode (verified), and `--allowedTools` tools run with zero permission events `[probe 2026-08-07]`. The denial surface is deterministic: `tool_result` text plus `result.permission_denials[]` (correlation owned by 05-interfaces). Hooks are best-effort (non-blocking by CLI design `[probe 2026-08-07]`); tool-level fail-closed comes from the allowlist, not hooks. The workspace renders report-only notices; there is no mid-run approval channel, hence no timeout-deny (term superseded, see glossary). Nothing is ever auto-approved outside the spawn-time policy.

## 7. Concurrency

- **One active interactive session at a time** in v1 `[design decision]` (single machine, single user, single spawn-time policy display).
- **Scheduled runs may execute while no interactive session is active**; they run under their spawn-time policy (`--allowedTools <policy tools>` under `--permission-mode manual`) and never wait on an unattended dialog — tools outside the policy are auto-denied by the CLI `[design decision]` (RE §6 — `shouldAutoApprovePermission` analog).
- **SchedulerEngine shall not violate the one-active-session invariant**: when a scheduled trigger fires while an interactive session is active, and whether two scheduled runs may overlap, the conflict policy (defer/skip/queue) is defined there. → Owned by: 06-runtime, prd-scheduled-tasks.
- **Boot reconcile**: on startup, sessions left `running` by a killed app are reconciled `running → failed` via PID liveness, and orphaned `claude` subprocesses are killed; guard against PID reuse (an orphan whose PID was recycled is detected by process identity, not PID alone) (macOS does not kill child processes on app termination). → Owned by: 06-runtime, 04-data-model.
- **SQLite WAL mode** for concurrent reads (workspace UI + scheduler + watcher writes) with a single writer owner (`Storage`).
