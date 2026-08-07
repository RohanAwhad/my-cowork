# 01 — Mission

> Writer: W1 (foundation) | Status: written — pending review

## 1. Purpose

RH Co-work is a local-first coworking workspace: the user and an agent work side by side on the user's own files. The agent kernel is the host `claude` CLI (Claude Code), spawned per session as a subprocess speaking `stream-json` (RE §2). The system produces artifacts — real files written into a per-session outputs dir, detected, versioned, and previewable in the workspace (RE §2, §10). Sessions may run interactively or be triggered by scheduled tasks; connectors (MCP servers) extend the agent's reach into external tools. Everything persists on the host machine: sessions, transcripts, artifacts, permissions, audit trail (RE §7) `[design decision]`. There is no cloud component in v1; the only network traffic originates inside the `claude` CLI subprocess itself, which manages its own auth `[design decision]`.

## 2. Users

The system targets a single developer-user on their own machine. There is no multi-tenancy, no organization model, no account system. `Auth` is a no-op in v1: the host is trusted, the user owns the machine, and the `claude` CLI subprocess handles its own authentication (RE §5 — OAuth/PKCE is a Claude Code concern, not ours) `[design decision]`. All workspace state is addressed to one local operator.

## 3. Core loop

### 3.1 UI-driven session loop

1. The user opens the workspace (local web UI at `localhost`, served by `WorkspaceServer`).
2. The user starts a session: prompt plus optional folder grants (stored on the session, enforced at spawn).
3. `SessionManager` creates the session record (id, status, outputs dir), persists it via `Storage` before spawning (RE §2 — session JSON persisted before VM boot, first message buffered), and hands off to `RunnerAdapter`.
4. `RunnerAdapter` spawns the `claude` CLI subprocess in `-p` mode with `stream-json` I/O (`--output-format`/`--input-format`; exact template in 02 §2, verified against `claude` 2.1.220). All user messages, including the first, are written to stdin as NDJSON — the first is buffered pre-spawn and flushed post-spawn (RE §2 — first message buffered). Folder grants are enforced at spawn via `--add-dir` + spawn cwd confinement + a PreToolUse path-filter hook — not runtime mounts (v1 is host-native) `[design decision]`. The spawn uses the user's shared Claude config dir so user settings/allowlists/hooks keep applying `[design decision]`.
5. The agent works on the host files under the spawn-time policy (`--permission-mode manual` + `--allowedTools`/`--disallowedTools`): unallowed tool calls are auto-denied inside the CLI — the raw CLI in `-p` mode emits no `permission_request` event (Cowork's dialog channel is the Agent SDK `canUseTool`, RE §4; we spawn the raw CLI, hence `[design decision]`). `PermissionGate` records every denial in the audit trail and surfaces report-only notices in the workspace (denial reason, request transcript); "approve future" is recorded and applies to the next spawn only.
6. Files the agent writes to the session outputs dir are detected by `ArtifactWatcher`, versioned, and surfaced in the workspace (RE §2, §10 — `fs_file_created`/`fs_file_deleted`).
7. The session ends (`result` event: num_turns, is_error), `SessionManager` stops the runner (stdin EOF → SIGTERM → SIGKILL, 02 §2), and `Storage` persists transcript + artifacts (RE §2).

### 3.2 Scheduled loop

1. `SchedulerEngine` fires a persisted scheduled task at its cadence (RE §6 — local job store; RESEARCH §2 — each run is its own session).
2. The task carries an auto-approve policy: allowlisted tools are passed at spawn via `--allowedTools` (RE §6 — `shouldAutoApprovePermission` gate, adapted to spawn time `[design decision]`).
3. The triggered task enters the same session pipeline: spawn runner → agent runs → artifacts detected → transcript + artifacts persisted.
4. Runs that fired while the app was down are recovered at boot `[design decision]` (RE §6 notes local trigger model; research: kimi-code coalescing).

All events — session events, artifact fs events, permission notices, scheduler ticks — flow through `EventBus` (glossary).

## 4. Non-goals / OUT-OF-SCOPE (v1)

| # | Non-goal | Rationale |
|---|---|---|
| 1 | Cloud sync / claude.ai REST / Anthropic cloud APIs | v1 is local-first; our code never calls Anthropic APIs — only the `claude` CLI subprocess does `[design decision]` |
| 2 | VM/container sandbox | v1 = host-native execution with permission gates; OS-level sandbox (RE §3 VM layer) is the hard 30% nobody in OSS has shipped (RESEARCH §Design decisions) — defer |
| 3 | Org sharing / collaboration / team features | Single-user product; no team/enterprise surfaces (RE §5 EIPC team surfaces) |
| 4 | Chrome browser bridge | Cowork/Kimi WebBridge is a separate capability surface; defer to a later phase |
| 5 | Mobile | Local-first desktop-only product |
| 6 | Plugin ecosystem (Cowork plugin format) | Glossary marks `plugin` as v2; connector story ships first via MCP |
| 7 | Memory store beyond basics | Global read/write memory (RE §5 — `CoworkMemory`) deferred; session transcript + artifacts are the v1 persistence |
| 8 | Multi-user auth | No accounts; `Auth` is a no-op (see §2) |

## 5. Success criteria

"RH Co-work works" means, demonstrably:

1. **End-to-end session**: a user starts a session with a prompt + folder grant; the agent completes the task; at least one artifact appears in the workspace, previewable, with a persisted transcript.
2. **Unattended scheduled run**: a scheduled task fires, completes within its auto-approve policy (no dialog required for allowlisted tools), and its artifacts land in the workspace without user interaction.
3. **Denial is real**: a tool call denied under the effective allowlist (workspace policy ∪ user settings; `--disallowedTools` always binds) never executes, and the denial is visible in the workspace and the audit trail.
4. **Audit completeness**: every grant, denial, approval, and deletion decision is captured in the audit trail; the trail is queryable and append-only. Denials are determined by correlating `tool_use` events against the effective allowlist (deterministic), not by parsing `tool_result` strings. → Owned by: 05-interfaces.
