# PRD — MCP Connectors

> Writer: W4e | Status: written — pending review
> Binding: 02 §2 MCP line (mechanism = `--mcp-config`/`--strict-mcp-config`; OAuth pre-auth outside sessions; interactive-OAuth excluded from scheduled runs), 04 §1.6 `Connector` entity, 04 §3 `tmp/mcp-config-<id>.json`, 04 §1.5 `mcp__<server>__<tool>` naming, 05 §1.8 `ConnectorRegistry`, 05 §1.1 connector routes/WS, 02 §6 fail-closed, 06 §5 row 8 `MCP_TOOL_TIMEOUT`, 07 §2.4 (scheduled deny side) + 07 §8.1 (secrets).
> Parallel amendments (binding): `connector_tools` DDL (04 §2), `POST /api/connectors/{id}/refresh` + `PUT /api/connectors/{id}/tools` + `ConnectorCreate.requiresOAuth` + `connector.updated.probeError` (05 §1.1), 07 §2.4 ask-tool rule.
> Owned-by: 03 §6 line 76, 04 §1.6 P2-15, 05 §1.8 (P2-15, pre-auth flow).

## 1. Current Behavior (Cowork — evidence)

- Cowork exposes a **300+ connector directory** (`claude.com/connectors`, ~17 pages — RESEARCH §4): MCP-powered, OAuth presented at connect time.
- Directory search is bridged to the renderer (`directory_servers_search`, 10 s timeout; cloud-bridge §4); connector shape `{uuid, name, oneLiner, url, iconUrl, toolNames, isConnected}` (RE §5; cloud-bridge §4).
- Connected cloud connectors enter the agent loop as **`claudeai-proxy` MCP servers**; tool calls route server-side (`…/mcp/servers/<uuid>/tools/call`); **connector tokens never enter the VM** (RE §4, §5) — OAuth and tokens are Anthropic-cloud concerns (RE §5; cloud-bridge §5).
- Per-tool permission matrix **Always allow / Needs approval / Blocked** (grouped read vs write; RESEARCH §4); per-tool enabled set via `replaceEnabledMcpTools` (web-endpoints §3.1); 1P gates `enabled_bananagrams/foccacia/sourdough` (RE §5; cloud-bridge §5 — "Internal 1P connectors (Google)").
- Scheduled runs auto-approve tools via `shouldAutoApprovePermission(scheduledTaskId, …)` (RE §6).
- Cowork's own control plane is EIPC, not a CLI contract — our runner is the raw `claude` CLI (02 §2), so the connector mechanism is the CLI's `--mcp-config` surface `[design decision]`.

## 2. Desired Behavior

**User story:** "As a user I add a local MCP server (or connector), control per-tool permissions, and the session's CLI gets it as `--mcp-config` with my policy baked in."

**Numbered flow:**

1. **CRUD via workspace UI.** User creates a connector in the Workspace (name, command, args, env, `requiresOAuth`); `ConnectorRegistry` persists it (04 §1.6). No cloud directory, no browsing — config is manual (out of scope §6).
2. **Tool inventory acquired.** `ConnectorRegistry` probes the server for its tool list (mechanism decided in §3.4) and caches it in `Connector.toolNames`.
3. **Per-tool permission matrix.** User sets each discovered tool to `always | ask | blocked` (§3.2). Default for discovered tools: `ask` `[design decision]` — mirrors Cowork's Needs-approval default (RESEARCH §4); tools *not* in `toolNames` are denied regardless (unlisted-denied, 04 §1.6).
4. **Spawn-time compile.** At `start_session`, `ConnectorRegistry.compile_mcp_config` writes `~/.co-work/tmp/mcp-config-<sessionid>.json` (04 §3 — **file, not stdin** `[design decision]`: survives CLI startup, matches 04 §3, trivially auditable; stdin NDJSON stays the message channel) and `RunnerAdapter` passes `--mcp-config <file> --strict-mcp-config` (02 §2; strict whenever a compiled file exists, 05 §1.8). File deleted on session end.
5. **Matrix merged into the effective allowlist.** `always` → `--allowedTools mcp__<server>__<tool>`; `blocked` → `--disallowedTools mcp__<server>__<tool>` on **every** spawn, interactive and scheduled — denied-wins enforced via emission (07 §2.3; scheduled deny side = user settings ∪ connector-matrix blocked entries, 07 §2.4; blocked tools feed the deny side, 07 §8.2). With the shared config dir (02 §2), a user-settings allow could otherwise re-admit a matrix-blocked tool in scheduled runs; `ask` → neither (§3.2). Exact merge rule (workspace ∪ user settings) is owned by 07-security-permissions.md — this PRD defines only the matrix **contribution** to workspace policy.
6. **Scheduled runs.** At task create/update, `SchedulerEngine` validates connector-tool selections via `ConnectorRegistry.eligible_for_scheduled` (05 §1.8); only `always`/`ask` tools may enter `task.allowedTools` — `ask` auto-allows iff selected (07 §2.4) — and `blocked` tools are never selectable, but they still feed the scheduled deny side via `--disallowedTools` (07 §2.4/§8.2). Interactive-OAuth connectors → task creation rejected with explanation (§5). OAuth pre-auth happens outside sessions via `claude mcp login <name>` (02 §2) `[design decision]`.

## 3. I/O Contracts

### 3.1 `Connector` entity — exactly 04 §1.6 (binding, no field changes)

```python
class Connector(BaseModel):
    id: UUID
    name: str                                  # valid mcpServers key: ^[A-Za-z0-9][A-Za-z0-9_-]*$, ≤64, unique
                                               # [design decision — guarantees mcp__<name>__<tool> determinism]
    command: str                               # e.g. npx, uvx
    args: list[str]
    env: dict[str, str] = {}
    toolNames: list[str]                       # inventory cache (bare tool names); default [] — unlisted denied (04 §1.6)
    requiresOAuth: bool = False
    oauthPreAuthDone: bool = False             # set by successful probe of a requiresOAuth connector [invented]; cleared by user
    status: Literal["registered","disabled"] = "registered"   # disabled connectors are never compiled [design decision]
    createdAt: datetime
    updatedAt: datetime
```

- v1 is **stdio-only**: the entity has no `url` field (04 §1.6 binding), so HTTP/remote servers are deferred (§6) even though the CLI schema supports them (§3.3) `[design decision]`.

### 3.2 Tool permission matrix — binding per the parallel 04 §2 amendment

```python
class ToolPolicy(StrEnum):
    ALWAYS = "always"          # → --allowedTools mcp__<server>__<tool> at every spawn
    ASK = "ask"                # interactive: NOT pre-allowed → CLI auto-denies (no mid-run channel, glossary; 02 §6)
                               # scheduled: selectable into task.allowedTools → auto-allowed (RE §6 gate analog)
    BLOCKED = "blocked"        # → --disallowedTools; always binds (02 §2); never selectable for scheduled tasks

class ConnectorToolMatrix(BaseModel):
    connectorId: UUID
    entries: dict[str, ToolPolicy]             # keys ⊆ Connector.toolNames (UI-enforced; unknown names rejected) [design decision]
                                               # absent keys default to "ask" [design decision]
```

- **Persistence**: `connector_tools(connector_id REFERENCES connectors(id) ON DELETE CASCADE, tool_name, policy, PRIMARY KEY (connector_id, tool_name))` — binding per the parallel 04 §2 amendment; single writer `Storage` (02 §7).
- **Audit**: matrix writes are audit rows (01 §5.4 completeness, 04 §1.5): `always` entry → `PermissionRecord(tool_name="mcp__<server>__<tool>", decision="grant", reason="connector matrix")`; `blocked` entry → `decision="deny"`; connector add/remove → `decision="grant"/"deny"` with `tool_name=<name>` `[design decision]`.

### 3.3 `--mcp-config` JSON schema (CLI contract, 02 §2)

```json
{
  "mcpServers": {
    "<server>": { "command": "npx", "args": ["-y", "@x/y"], "env": {"K": "v"} }
  }
}
```

- Server key = `Connector.name`; v1 emits only the `command`/`args`/`env` shape.
- CLI-documented variants not emitted in v1: `{"url": "https://…", "headers": {"Authorization": "Bearer …"}}` and the `claudeai-proxy` shape `{url, id, timeout}` (web-endpoints §5.1) — documented for compat, deferred per §6.
- `--strict-mcp-config` accompanies the file whenever present (05 §1.8).
- **Consequence (binding, 02 §2)**: a session compiled with workspace connectors does not load the user's CLI-registered MCP servers (`claude mcp add`, `.mcp.json`, plugins) — workspace connectors are the sole MCP surface for that session.
- A session with zero connectors gets neither flag; the user's CLI MCP config applies unchanged.
- **Secrets (07 §8.1, binding)**: `Connector.env` values live only in the `connectors` table and the compiled file (mode **0600**, deleted on session end, 04 §3). `Session.mcpConfig` stores server definitions **without** secret-bearing `env` values — redacted from the audit snapshot (07 §8.1: "never persist in session records"); loguru masks keys matching `(authorization|token|secret|api[_-]?key|headers)`, including `PermissionRecord.input` snapshots (07 §8.1).

**Verified against `claude` 2.1.220 (ground truth):**
- `--mcp-config` with `{"mcpServers": {"<name>": {command, args, env}}}` loads; per-server `env` values are honored by the CLI (server observed the config env) — `env` is a supported config path.
- `--strict-mcp-config` loads **only** `--mcp-config` servers; project `.mcp.json` is excluded (verified).
- settings.json key `"mcpServers"` is **silently ignored** — user-scope servers live in `.claude.json` via `claude mcp add`. **ConnectorRegistry must never write `mcpServers` into settings.json**; the compiled `--mcp-config` file is the only config surface (02 §2) `[design decision]`.
- Tool naming `mcp__<server>__<tool>` confirmed in `init.tools` and `tool_use.name`; MCP tool names are valid in `--allowedTools` (verified).
- `init` carries `mcp_servers: [{name, status: connected|failed}]` — probe-verified 2026-08-07 on `claude` 2.1.220; the spawn-time health signal per compiled server (§3.6).

### 3.4 Tool inventory probe — mechanism decided `[design decision]`

- **Mechanism**: `ConnectorRegistry.probe_tools(c: Connector) -> list[str]` spawns `command args` (env merged) and speaks MCP stdio: `initialize` (protocolVersion `2024-11-05`) → `notifications/initialized` → `tools/list` → `shutdown` → `exit`. Returns bare tool names (deduped, sorted).
- **Probe wire contract** (JSON-RPC 2.0, one message per line on the child's stdin; the child's stdout is parsed for the id-matched responses; `initialize` response must carry `protocolVersion` and `capabilities`; `tools/list` response `result.tools[].name` is the inventory):

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"rh-co-work","version":"0.1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"shutdown","params":{}}
```

- This is the app's **only** MCP protocol code — a probe *client*, not an in-app MCP server (03 §3 "no in-app MCP client" refers to runtime server hosting; the probe is config-time, ~100 lines, justified).
- **Independence**: does not depend on the user's `claude mcp` registrations; works offline; OAuth-gated servers fail the probe until pre-authed.
- **Timing**: (a) at `add_connector`; (b) manual `POST /api/connectors/{id}/refresh`; (c) refresh-on-spawn-if-empty `[invented]` — `compile_mcp_config` re-probes any `registered` connector with `toolNames == []`.
- **Timeout**: 30 s, reusing `MCP_TOOL_TIMEOUT` (06 §5 row 8) `[design decision]`; stderr tail logged (loguru, `LOGGING_LEVEL`).
- **Caching/staleness**: `toolNames` is a snapshot; a server that grows tools later is undiscovered until refresh, and undiscovered tools are denied at spawn (04 §1.6). No auto-refresh in v1 (§6).
- **OAuth coupling**: successful probe of a `requiresOAuth` connector sets `oauthPreAuthDone=True` `[invented]` — after the user runs `claude mcp login <name>`, refresh proves the auth works.
- **Failure**: fail-fast (02 §6 — no swallowing) but **contained**: connector excluded from the compiled config, `probeError` surfaced via `connector.updated {connector, probeError}` (05 §1.1 WS message reused) `[design decision]`, spawn proceeds without it (§5).

### 3.5 Spawn flags — assembled by RunnerAdapter from 05 §2.1; no new template fields

- `--mcp-config ~/.co-work/tmp/mcp-config-<sessionid>.json` (05 §2.1 `mcp_config`; 04 §3)
- `--strict-mcp-config` iff the file exists (05 §1.8)
- `--allowedTools … mcp__<server>__<tool>` per `always` entry; `--disallowedTools … mcp__<server>__<tool>` per `blocked` entry (04 §1.5 naming — server = `Connector.name`)
- Runner env unchanged: `MCP_TOOL_TIMEOUT=30000` (06 §6)
- `CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS` is **not** set (05 §2.1 env is binding) → subagents cannot call MCP tools in v1 `[design decision]` (RE §2 sets it true; dropped, out of scope §6)

**Matrix → policy resolution (deterministic; consumed by PermissionGate at spawn):**

| Matrix policy | Interactive session | Scheduled run | Spawn artifact |
|---|---|---|---|
| `always` | auto-allowed | auto-allowed (if selected into `task.allowedTools`, else not carried) | `--allowedTools mcp__<server>__<tool>` |
| `ask` | auto-denied + notice (02 §6 fail-closed); "approve future" on the notice is recorded and consumed at the **next interactive spawn only** (07 §3.3 — scheduled runs never inherit `approve_future`) | auto-allowed iff selected into `task.allowedTools` at creation (07 §2.4 — fail-open bounded by the task policy) | none / `task.allowedTools` |
| `blocked` | auto-denied + notice | denied — never selectable | `--disallowedTools mcp__<server>__<tool>` (both run types) |
| not in `toolNames` | auto-denied + notice | denied | none (unlisted-denied, 04 §1.6) |

`--disallowedTools` emission from the matrix applies to **both run types** (07 §2.3 — denied-wins is enforced via emission; 07 §2.4 — scheduled deny side = user settings ∪ connector-matrix blocked entries; 07 §8.2 — blocked tools feed the deny side). With the shared config dir (02 §2), a user-settings allow must not re-admit a matrix-blocked tool in unattended runs — emission makes the CLI enforce the block regardless of user settings.

### 3.6 Compile output contract (`compile_mcp_config`, 05 §1.8)

- Input: `Session` (pre-spawn, status `pending`). Resolves `registered` connectors; re-probes any with `toolNames == []` (§3.4 timing (c)); probe failures excluded.
- Output: `Path | None` — the tmp file path, or `None` when zero connectors compile.
- Side effects: writes `~/.co-work/tmp/mcp-config-<sessionid>.json` (0600, `json.dumps(mcpServers, indent=2)`); sets `Session.mcpConfig = {"mcpServers": {…}}` with **secret-bearing `env` values redacted** (07 §8.1 — audit snapshot of what the CLI received, minus secrets); publishes `connector.updated` per probe failure (§3.4).
- **Spawn-time health signal** (owned by this PRD): the `init` event carries `mcp_servers: [{name, status: connected|failed}]` — probe-verified 2026-08-07 on `claude` 2.1.220; 05 §2.2's `init` mapping is being amended in parallel to include it (orchestrator applies it). A compiled server with `status:"failed"` (e.g. server crash at boot) → `connector.updated {connector, probeError}` notice + audit row, session continues (its tools are simply absent) `[design decision]`.
- Cleanup: deletion on session end (done/stopped/failed) is owned by `SessionManager` (`start_session` completion paths, 05 §1.2 `_on_result`/`_on_error`/`_on_close`) `[design decision]`; a crash leaves the file behind and the boot reconcile does not clean `tmp/` in v1 `[invented]` (file is keyed by session id — harmless residue, overwritten on any rerun).

### 3.7 Connector state model `[invented]` — no mid-run transitions; config-time only

| State dimension | Values | Transitions |
|---|---|---|
| `status` | `registered` / `disabled` | UI toggle; disabled = never compiled, matrix retained |
| inventory | `[]` (unprobed/failed) / `toolNames` populated | add → probe; refresh; refresh-on-spawn-if-empty; probe failure → `[]` + `probeError` |
| OAuth | `requiresOAuth=False` / `True∧¬oauthPreAuthDone` / `True∧oauthPreAuthDone` | `claude mcp login` (outside sessions) + successful probe → `oauthPreAuthDone=True` (02 §2) `[invented]`; user may clear |

Invariant: `connector_tools` entries ⊆ current `toolNames` at write time; a refresh that shrinks `toolNames` leaves stale matrix entries but they resolve to "not in toolNames" → denied at spawn (fail-closed; UI shows them as stale) `[design decision]`.

## 4. Component Touchpoints

| Component | Change |
|---|---|
| `ConnectorRegistry` (05 §1.8) | `probe_tools(c) -> list[str]` (new); `set_tool_policy(id, matrix)` (new); `compile_mcp_config(session)` (existing — now: re-probe-if-empty, write tmp file 0600, delete on session end, return `Path\|None`); `tool_names(c)` (existing); `eligible_for_scheduled(c)` (existing — formula §2 step 6); publishes `connector.updated` on every mutation/probe |
| `RunnerAdapter` (05 §1.3/§2.1) | no code change — `SpawnSpec.mcp_config` already in the binding template; strict flag conditional per §3.5 |
| `PermissionGate` (05 §1.4) | consumes the matrix contribution to workspace policy (`always`→allowed, `blocked`→denied, `ask`→none); denials correlated from `tool_use` (mission §5, 05 §1.4); full merge rule (∪ user settings) owned by 07-security-permissions.md — referenced, not duplicated |
| `WorkspaceServer` (05 §1.1) | routes `POST /api/connectors/{id}/refresh`, `PUT /api/connectors/{id}/tools` (`ConnectorToolMatrix` in → `Connector` out), `ConnectorCreate.requiresOAuth: bool = False`, `connector.updated.probeError` — binding per the parallel 05 §1.1 amendment |
| `SchedulerEngine` (05 §1.7) | task create/update validates connector-tool selections (`eligible_for_scheduled` + no `blocked` tools); rejection is a validation error, task not created (§5) |
| `SessionManager` | compile + probe happen pre-spawn in `start_session`; probe failure never fails the session (02 §6 containment) |

## 5. Acceptance Criteria

Testable end-to-end (play.py-style script + spawn-flag assertion):

1. **Add → spawn.** `POST /api/connectors {name, command, args}` → `toolNames` populated by probe; next session spawns with `--mcp-config ~/.co-work/tmp/mcp-config-<id>.json` and `--strict-mcp-config`; file exists during the run; `session.mcpConfig` equals the resolved servers dict **with secret-bearing `env` values redacted** (07 §8.1).
2. **Blocked binds.** Every spawn — interactive and scheduled — carries `--disallowedTools mcp__<server>__<tool>` for matrix-blocked entries (07 §2.3/§2.4/§8.2); a prompt forcing that tool yields an auto-denied `tool_result` (is_error), a `PermissionRecord(decision="deny", reason="policy=blocked")`, and a `permission.notice` in the workspace — even when the tool is allowed by the user's own settings (denied-wins, 07 §2.3).
3. **Always allows.** Tool set to `always` → spawn carries it in `--allowedTools`; a call succeeds with no notice.
4. **Ask semantics.** Interactive: `ask` tool is denied with notice (fail-closed, 02 §6); "approve future" on the notice applies to the next interactive spawn only, never a scheduled run (07 §3.3). Scheduled: the same tool is selectable at task creation; the run carries it in `task.allowedTools` and the call succeeds unattended — auto-allow iff selected, bounded by the task policy (07 §2.4; RE §6 gate analog).
5. **Scheduled exclusion.** Task creation attaching a connector with `requiresOAuth=True, oauthPreAuthDone=False` → rejected with an explanation (pre-auth via `claude mcp login`); no task row created. Pre-auth done → creation allowed.
6. **Probe failure contained.** Connector with a bad command → `toolNames=[]`, `probeError` set, `connector.updated` notice; session spawns **without** that connector and completes.
7. **Cleanup.** `tmp/mcp-config-<id>.json` deleted on session end (done/stopped/failed).
8. **Unknown tool denied.** An agent-requested tool not in `toolNames` (server grew after inventory) → denied, audited (unlisted-denied, 04 §1.6).
9. **Strict isolation.** With a compiled config, **only** `--mcp-config` servers load — project `.mcp.json` and the user's `.claude.json` servers (`claude mcp add`) are excluded (verified 2.1.220); without a compiled config, neither flag passes and CLI-managed servers apply. `settings.json` never receives `mcpServers` writes (§3.3).
10. **Spawn-time connector health.** A compiled server crashing at boot surfaces as `init.mcp_servers status:"failed"`; the session continues, a `connector.updated {probeError}` notice and an audit row record it (§3.6).

## 6. Out of Scope (v1)

- **Cloud connector directory search** (claude.ai registry; `directory_servers_search`/`suggest_connectors`, RE §5 §4) — no browse/install from a registry; manual config only.
- **Remote MCP via `claudeai-proxy` / server-side tokens** (RE §5, §10; web-endpoints §5.1 §6.3) — plus plain HTTP `{url, headers}` servers, since `Connector` has no `url` field (04 §1.6) `[design decision]`. Tokens never enter our process; the CLI owns all auth (02 §1).
- **Plugin bundles** (`.mcpb` signed format, DXT, web-endpoints §4) — glossary `plugin` = v2.
- **OAuth inside sessions / OAuth for scheduled runs** (02 §2) — pre-auth only, via `claude mcp login` outside sessions.
- **Connector auto-refresh / server-driven tool discovery** — manual refresh + refresh-on-spawn-if-empty only (§3.4).
- **In-app MCP server runtime / mid-run connector management** (`setMcpServers`/`mcpCallTool` EIPC analogs, web-endpoints §3.1) — config-time only; the probe client (§3.4) is the sole MCP protocol code.
- **MCP tools for subagents** (`CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS`, RE §2) — env not in the binding spawn template (05 §2.1) `[design decision]`.

## 7. Open questions

- Probe of long-booting servers (cold `npx` fetch): the 30 s probe timeout may be tight; revisit with a `Settings` knob if real connectors hit it `[invented]`.
- `init.mcp_servers` `status:"failed"` is notice-only in v1 (§3.6); whether a failed compiled server should fail the session (fail-closed analog) is deferred — revisit with 07 when spawn-failure telemetry exists.
