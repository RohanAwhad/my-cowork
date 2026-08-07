# Glossary — RH Co-work

Shared terminology. Fixed names are binding: all docs/PRDs must use these terms and symbol names. No collisions, no synonyms.

## Product concepts
| Term | Meaning |
|---|---|
| **Co-work** (product) | The system being built: a local-first workspace where an agent (Claude Code) works alongside the user on their files, producing artifacts, on a schedule, with MCP connector access. |
| **Workspace** | The user-facing surface (local web UI at `localhost`) — sessions, artifact previews, permission dialogs, scheduled tasks, connector settings. |
| **Session** | One agent run: user prompt → Claude Code process → result. Has an id, owner, status, transcript, artifacts. Persisted. |
| **Artifact** | A file the agent produced in the session outputs dir, detected by the watcher, versioned, previewable in the workspace. |
| **Scheduled task** | A persisted definition (cadence, prompt, auto-approve policy) that the SchedulerEngine triggers into a new session. |
| **Folder grant** | User-approved permission for a session to read/write a host folder. Stored on the session; enforced at spawn (`--add-dir`, spawn cwd confinement, PreToolUse path-filter hook), not at runtime (v1 has no mounts). |
| **Connector** | An MCP server (or remote tool proxy) registered in the workspace, exposed to sessions via the ConnectorRegistry. |

## Fixed component/symbol names (binding)
| Symbol | Responsibility |
|---|---|
| `SessionManager` | Owns session lifecycle: create, spawn runner, stream events, stop, archive. |
| `RunnerAdapter` | Abstraction over the agent kernel: spawns `claude` CLI subprocess, speaks stream-json, exposes run/stop/input APIs. |
| `EventBus` | Internal pub-sub: session events, artifact fs events, permission requests, scheduler ticks. |
| `PermissionGate` | Applies the spawn-time policy (`--allowedTools`/`--disallowedTools`/`--permission-mode manual`), records every denial in the audit trail, and surfaces report-only notices to the workspace; dynamic checks via PreToolUse hook files. |
| `ArtifactWatcher` | Watches session outputs dirs, detects created/modified files, versions them, emits artifact events. |
| `SchedulerEngine` | Local cron: persists scheduled tasks, fires triggers, enforces auto-approve policy, recovers missed runs at boot. |
| `Storage` | SQLite layer: sessions, tasks, artifacts, permissions, audit log, settings. |
| `ConnectorRegistry` | Connector config store + per-session `--mcp-config` compiler + spawn-time tool matrix (v1 has no in-app MCP client). |
| `WorkspaceServer` | FastAPI + websockets server: HTTP/WS API for the UI, static serving of artifact previews. |
| `WorkspaceServerToken` | Per-run bearer token for WorkspaceServer HTTP/WS requests (binds 127.0.0.1; exact scheme in 07-security-permissions.md). |
| `Auth` | (v1: no user auth — local only; Claude Code has its own auth. Server access uses `WorkspaceServerToken`.) |

## Domain terms
| Term | Meaning |
|---|---|
| `stream-json` | Claude Code's JSON output mode (`--output-format stream-json`): NDJSON of events (system, init, user, assistant, tool_use, tool_result, result, error…). No `permission_request` events are emitted in `-p` mode (02 §6); permission enforcement is spawn-time policy. |
| `permission request` | Tool-call approval event. v1: the raw CLI in `-p` mode emits none — unallowed tools are auto-denied inside the CLI (denial arrives as a `tool_result`); workspace dialogs are report-only, and "approve future" applies to the next spawn. |
| `auto-approve policy` | Per scheduled task: which tools are passed via `--allowedTools` at spawn under `--permission-mode manual`; unlisted tools are auto-denied by the CLI (RE §6 — `shouldAutoApprovePermission` analog). |
| `spawn-time policy` | The v1 permission model: allowance is fixed when the runner spawns the CLI (`--allowedTools`/`--disallowedTools`/`--permission-mode`); there is no mid-run permission channel. |
| `timeout-deny` | (superseded in v1) Deny-on-timeout for blocking permission dialogs. v1 has no blocking channel — unallowed tools are auto-denied by the CLI at spawn time. |
| `audit trail` | `audit.jsonl`-style append-only log of every grant/deny/approval/deletion decision (adapted from Cowork `audit.jsonl`). |
| `outputs dir` | Per-session host directory where the agent writes artifacts; watched by ArtifactWatcher. |
| `mcp__<server>__<tool>` | Tool name format the CLI exposes for MCP tools (verified 2.1.220); used in tool_use events, --allowedTools/--disallowedTools, and PermissionRecord rows. |
| `deleted_observed` | PermissionRecord.decision value for watcher-observed deletions (07 §4.1). |
| `COWORK_SESSION_ID` | Env var passed to the runner; inherited by hook processes (verified) for per-session identity. |
| `COWORK_POLICY_FILE` | Env var naming the per-session hook policy JSON; read by the thin hook script (07 §5.3). |
| `plugin` | (v2) Cowork-style plugin package (plugin.json + .mcp.json + commands/ + skills/). Out of scope for v1. |

## Statuses
- `Session.status`: `pending → queued → running → done | stopped | failed | archived` (queued may also go directly to stopped/failed; pending → failed pre-spawn on spawn/health errors — see 04-data-model §4.1) (`awaiting_permission` removed — v1 has no blocking permission channel, permission is spawn-time policy; `queued` = scheduled session waiting for its run slot — including boot-replay direct-create (`missed → queued`, 04 §4.2) — conflict policy per 06-runtime)
- `Task.status`: `active | paused | disabled | missed | queued` (missed = trigger fired while app down, recovered at boot; queued = trigger fired while any run slot is busy — interactive or scheduled (06-runtime §3 row 2); boot-replay creates the queued session directly (`missed → queued`, 04 §4.2))
