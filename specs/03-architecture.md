# 03 — Architecture

> Writer: W2 (architecture) | Status: written — pending review
> Diagrams: `specs/03-architecture-context.mmd` (L1), `specs/03-architecture-containers.mmd` (L2), `specs/03-architecture-components.mmd` (L3). View: `python3 specs/serve.py --port 8001` → open `http://localhost:8001/03-architecture-context.mmd`

## 1. Boundaries and ownership

**In-system (we build and run):** the RH Co-work App — one Python process (FastAPI + uvicorn + asyncio, 02 §4) hosting all components (glossary §Fixed component names — ten) — plus the `claude` CLI it spawns as a per-session subprocess. The `claude` CLI is *ours to spawn and supervise*, not to vendor: it is the agent kernel, resolved from `~/.claude/local/claude` then PATH (02 §3).

**External (never ours):**
- **Anthropic API** — reached *only* by the `claude` CLI subprocess, which owns its own auth and network (OAuth/PKCE, token cache, RE §5). Our components never hold, refresh, or proxy Anthropic credentials (02 §1).
- **Host filesystem** — user files, granted folders, and per-session outputs dirs live on the host; the app reads and writes them directly (no mounts, no VM, 02 §3).
- **Developer's browser** — the workspace UI surface.

**Ownership rules:**
- Our code never calls Anthropic cloud APIs (02 §1 binding); the CLI is the only egress.
- The app must function with the network disabled; only the runner's own traffic may fail (02 §1) `[design decision]`.
- Runner failures are contained at the boundary: a crashing `claude` subprocess fails the session, not the workspace (02 §6) `[design decision]`.
- `Auth` is a no-op in v1 (glossary): single local operator; server access is secured by `WorkspaceServerToken` (02 §4).

## 2. Containers (L2)

| Container | Shape | Responsibility |
|---|---|---|
| Browser | running process (Developer's browser) | Workspace UI: sessions, artifact previews, report-only permission notices, scheduled tasks, connector settings. Server-rendered/static assets, no build step (02 §5). |
| RH Co-work App | one Python process | All component logic below. Binds **127.0.0.1 only**; HTTP + WS API and static artifact previews via `WorkspaceServer` (02 §4). |
| claude CLI subprocess | per-session process | The agent kernel in `-p` mode speaking `stream-json` (NDJSON) over stdin/stdout pipes. Exact spawn template is binding (02 §2): `claude -p --verbose --output-format stream-json --input-format stream-json [--permission-mode manual] [--allowedTools …] [--disallowedTools …] [--add-dir …] [--mcp-config …] [--strict-mcp-config] [--append-system-prompt …]`. First message buffered pre-spawn, flushed post-spawn; teardown = stdin EOF → SIGTERM → SIGKILL (02 §2). |
| SQLite | data store, WAL mode | All persistence: sessions, tasks, artifacts, permissions, audit trail, settings (02 §4; single writer owner = `Storage`, 02 §7). |
| Anthropic API | external | The CLI's upstream (model inference). Never touched by our code (02 §1). |
| Host filesystem | external | User files, granted folders, per-session outputs dirs, artifact content. |

**Ports and pipes:** WorkspaceServer binds 127.0.0.1 with an HTTP + WS API and serves artifact previews (browser-native embeds, 02 §5); port scheme documented as `127.0.0.1:8xxx` in the L2 diagram and pinned in 05-interfaces. RunnerAdapter↔CLI is NDJSON over stdin/stdout pipes; Storage↔SQLite is SQL over WAL.

## 3. Components (L3) — glossary symbols to Cowork mechanisms

| Component | Role (glossary binding) | Cowork analog (RE) | v1 adaptation |
|---|---|---|---|
| `WorkspaceServer` | FastAPI + websockets: HTTP/WS API for the UI, static artifact previews | Cowork EIPC surface `LocalAgentModeSessions` (RE §5 — `<Interface>_$_<method>` control-plane pattern) | `[design decision]`: plain HTTP/WS on 127.0.0.1 instead of an Electron EIPC bridge; API shapes in 05-interfaces. |
| `SessionManager` | Owns session lifecycle: create, spawn runner, stream events, stop, archive | `LocalAgentModeSessionManager.startSession` / `stopSession` (RE §2 — record persisted before spawn, first message buffered) | Mirror of the lifecycle: persist → spawn → stream → stop → archive (RE §2, §8). One active interactive session (02 §7) `[design decision]`. |
| `RunnerAdapter` | Abstraction over the agent kernel: spawns `claude` CLI, speaks `stream-json`, run/stop/input APIs | SDK `query()` with custom `spawnClaudeCodeProcess` (RE §2; symbol-map §3.4 — fake child with stdin forwarding) | `[design decision]`: real subprocess with pipe I/O instead of a VM-spawn interception; same contract shape (run/stop/input). Sole kernel abstraction (02 §2). |
| `PermissionGate` | Applies spawn-time policy (`--allowedTools`/`--disallowedTools`/`--permission-mode manual`), records every denial in audit trail, surfaces report-only notices | `canUseTool` → `tool_permission_request` dialog → `respondToToolPermission` deny/once/always + `audit.jsonl` (RE §4, symbol-map §4.3) | `[design decision]` — key divergence: raw CLI in `-p` mode emits no `permission_request`; the gate is spawn-time and fail-closed, denials arrive as `tool_result`, dialogs are report-only, "approve future" applies to the next spawn (02 §6, glossary `spawn-time policy`). |
| `EventBus` | Internal pub-sub: session events, artifact fs events, permission requests, scheduler ticks | Cowork main-process event emitter (session_updated, fs_file_created, tool_permission_request — symbol-map §3a) | `[design decision]`: asyncio pub-sub in-process; all components publish/subscribe, no network hop. |
| `ArtifactWatcher` | Watches session outputs dirs, detects created/modified files, versions them, emits artifact events | `FileSystemWatcher` → `fs_file_created`/`fs_file_deleted` per session (RE §1, symbol-map §5 — non-recursive watch, initial scan) | Same detection semantics; versions files into the artifact store (versioning detail in prd-live-artifacts). |
| `SchedulerEngine` | Local cron: persists tasks, fires triggers, enforces auto-approve policy, recovers missed runs at boot | Local `.claude/scheduled_tasks/<id>.json` store + `shouldAutoApprovePermission` gate (RE §6) | `[design decision]`: tasks in SQLite, per-run = own session (mission §3.2), auto-approve resolved at spawn, boot-time missed-run recovery (02 §6). |
| `ConnectorRegistry` | Connector config store + per-session `--mcp-config` compiler + spawn-time tool matrix (no in-app MCP client) | MCP coordinator `Pye.createAllServers` (RE §5, symbol-map §4) | `[design decision]`: no in-app MCP servers; connectors enter via the CLI's `--mcp-config`/`--strict-mcp-config` (02 §2). OAuth pre-auth outside sessions. |
| `Storage` | SQLite layer: sessions, tasks, artifacts, permissions, audit log, settings | Session JSON files + `audit.jsonl` (RE §7) | `[design decision]`: single SQLite DB (WAL) as sole writer owner (02 §7); append-only `audit trail` table (glossary). |
| `Auth` | no-op (v1) | Cowork renderer-side auth + OAuth (RE §5) | `[design decision]`: no user auth; the `claude` CLI authenticates itself (mission §2). |

Ownership split between `SessionManager` and `RunnerAdapter`: `SessionManager` owns lifecycle policy (when to create/spawn/stop/archive); `RunnerAdapter` owns process mechanics (how to spawn/stop/input); teardown is `SessionManager` → `RunnerAdapter.stop()`.

## 4. Data flow summary

**(a) Interactive session** — Developer → Browser → `WorkspaceServer` (HTTP) → `SessionManager` (L3: "session commands over HTTP and WS"). `SessionManager` persists the session record via `Storage` (SQL over WAL) before spawning, then hands the prompt to `RunnerAdapter` ("spawns, sends input to"). `RunnerAdapter` resolves policy with `PermissionGate` ("routes spawn-time policy to") and connector config with `ConnectorRegistry` ("compiles per-session mcp config for"), then spawns the `claude` CLI (NDJSON pipes). CLI events flow back through `RunnerAdapter` ("streams events to") → `SessionManager` → `EventBus` ("publishes session events on") → `WorkspaceServer` → Browser over WS.

**(b) Scheduled run** — the user creates and edits tasks via `WorkspaceServer` → `SchedulerEngine` (L3: "task commands over HTTP and WS"; `SchedulerEngine` owns task CRUD, not `SessionManager`). `SchedulerEngine` fires a persisted task (ticks published on `EventBus`), resolves its auto-approve policy with `PermissionGate`, then "fires triggers into" `SessionManager` — the run enters the same pipeline as (a) under the task's spawn-time policy; unlisted tools auto-denied by the CLI (RE §6 analog, 02 §2). Missed runs are recomputed at boot from `Storage` (02 §6).

**(c) Artifact surfacing** — the CLI writes files into the session outputs dir on the Host filesystem; `ArtifactWatcher` ("watches outputs dirs on" HFS) detects them, versions them, and "publishes artifact events on" `EventBus`; `WorkspaceServer` streams them to the Browser and serves previews (RE §1 `fs_file_created` analog). Artifact records and versions are persisted to `Storage` via `ArtifactWatcher` (L3: "persists artifact records and versions via"); the versioning scheme is `[design decision]` — Cowork's versioning is server-side/cloud (RE §10) — and is owned by prd-live-artifacts and 04-data-model. v1 watches the outputs dir only; Cowork watches the first user-selected folder else the outputs dir (RE session-lifecycle §5), granted-folder watching is deferred to prd-live-artifacts `[design decision]`.

**(d) Permission decision** — `PermissionGate` computes the effective allowlist at spawn (workspace policy ∪ user settings; `--disallowedTools` always binds, 02 §2), routes it to `RunnerAdapter`, records every grant/deny in the audit trail via `Storage`, and publishes report-only notices on `EventBus` → `WorkspaceServer` → Browser. Denial observation: the gate subscribes to `EventBus` (L3: "carries session events and denials to" PG), which carries the `tool_use` events emitted by the runner; denials arrive as `tool_result` in the CLI stream, and determination correlates `tool_use` against the effective allowlist (deterministic), not by parsing `tool_result` strings (mission §5) — event-to-decision mapping owned by 05-interfaces. No mid-run channel, no timeout-deny (glossary).

## 5. Dropped Cowork mechanisms (cross-reference)

Intentionally not in v1; owned by the relevant PRDs where details land:
- **VM sandbox / mounts matrix (`ro`/`rw`/`rwd`, deletion approval)** (RE §1, §3, §4) — v1 is host-native with spawn-time gates (02 §3); deletion approval semantics deferred to prd-local-files.
- **`request_cowork_directory` runtime folder dialog** (RE §4, symbol-map §4.2) — v1 folder grants are pre-spawn UI state enforced via `--add-dir` + cwd confinement + PreToolUse path-filter hook (02 §2); dialog flow deferred to prd-local-files.
- **Mid-run tool permission channel (`tool_permission_request` + `respondToToolPermission`)** (RE §2, §4) — replaced by spawn-time policy + report-only dialogs (see §3 `PermissionGate`); audit correlation detail in 05-interfaces (mission §5).
- **Cloud session sync (`/v1/sessions`), renderer-side cloud pivot, `CoworkMemory`, plugins (`plugin.json` + `.mcp.json`)** (RE §5, §7; glossary `plugin` = v2) — out of scope per mission §4.
- **Knowledge bases** (RE §4 — KBs mounted `rw` at `/mnt/.knowledge/<id>` + `create_knowledge_base` tool) — deferred to prd-memory; v1 has no KB surface.
- **File uploads** (RE §2, session-lifecycle §6.1 — uploads staging, md5 dedup, hardlinks, path rewrite) — v1 prompts are text-only; deferred to prd-local-files.
- **Scheduled-task cloud/server execution** (RE §6) — v1 is local-only; design headroom noted in prd-scheduled-tasks.

## 6. Owned-by (deferred details)

- `WorkspaceServerToken` scheme (per-run bearer, 127.0.0.1 binding, origin checks) → 07-security-permissions.md.
- Effective-allowlist merge rule (workspace policy ∪ user settings; `--disallowedTools` binding) → 07-security-permissions.md.
- Connector OAuth pre-auth flow (`claude mcp login` outside sessions; interactive-OAuth excluded from scheduled runs) → prd-mcp-connectors.
- Conflict policy (scheduled trigger vs active interactive session; overlapping scheduled runs) → 06-runtime, prd-scheduled-tasks.
- Artifact versioning scheme, missed-run replay policy, boot reconcile (`running → failed` via PID liveness, orphan kill, PID-reuse guard) → 04-data-model, 06-runtime.
- Port numbering for `127.0.0.1:8xxx` → 05-interfaces.
- Storage threading (SQLite in asyncio must not block the single event loop: aiosqlite or `run_in_executor`; decision) → 05-interfaces, 06-runtime.
- Transcript assembly (event-to-row mapping: rebuild from stream-json events vs re-parsing `~/.claude/projects/*.jsonl`) → 05-interfaces; resume semantics for stopped sessions — `--resume` is not in the v1 spawn template `[design decision]` (RE §2 uses `--resume` on resume) → 06-runtime.
- Runner hardening: the runner env must include `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` and a PreToolUse Task hook must block `run_in_background` (RE §2, claude-code-binary.md); teardown must kill the process group, not a single PID → 06-runtime, 07.
- EventBus subscriber isolation (one raising subscriber must not kill the bus). Tick path: `SchedulerEngine` publishes ticks on `EventBus` and also calls `SessionManager` directly — the direct call is intentional and kept → 05-interfaces.
- Scheduled run that died mid-execution (runner crash) is neither `missed` nor re-fired; handling defined → prd-scheduled-tasks.
- Deletion audit scope: v1 has no deletion gate; decide whether watcher-sourced deletion events count toward the audit trail or the trail is grants/denials only → 07, 05.
