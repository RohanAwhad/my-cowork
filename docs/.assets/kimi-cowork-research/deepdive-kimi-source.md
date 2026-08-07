# Deep Dive: Moonshot AI `kimi-code` + OpenClaw — Source-Level Analysis for a Kimi Work Clone

**Repo**: `MoonshotAI/kimi-code` @ `main` (4634 blobs), plus `openclaw/openclaw` @ `main` (31,094 blobs)
**License**: kimi-code = MIT (Copyright 2026 Moonshot AI, `LICENSE`); OpenClaw = MIT (`LICENSE`, "Copyright (c) 2026 OpenClaw Foundation"). Caveat: official bundled plugins (`plugins/official/kimi-webbridge/kimi.plugin.json`) declare `"license": "Proprietary"` inside their manifests — the host is MIT but the shipped plugin *content* is not all open.
**Language**: TypeScript monorepo (pnpm workspaces). v2 kernel = DI × scoped-services engine (`agent-core-v2`), v1 kernel = classic class-based `agent-core`. The CLI (`apps/kimi-code`) is v2-first in current main.

---

## 1. Cron Scheduler

There are **two** generations. Both are in-tree and both are worth cloning from.

### 1a. v2 (current, authoritative) — `packages/agent-core-v2/src/`

**Files** (all under `src/`):
| Concern | Path |
|---|---|
| Task record | `app/cron/cronTask.ts` |
| Persistence contract | `app/cron/cronTaskPersistence.ts` |
| Persistence impl (atomic JSON docs) | `app/cron/cronTaskPersistenceService.ts` |
| Deterministic jitter | `app/cron/jitter.ts` |
| Clock abstraction (wall + monotonic, file-clock for tests/benches) | `app/cron/clock.ts` |
| Cron expression parser + human rendering | `app/cron/cron-expr.ts` |
| Env config (`KIMI_CRON_*`) | `app/cron/configSection.ts` |
| Fire-prompt renderer (`<cron-fire>` XML) | `app/cron/format.ts` |
| **Scheduler engine** (session-scoped) | `session/cron/sessionCronServiceImpl.ts` (727 lines) |
| Service contract | `session/cron/sessionCronService.ts` |
| Wire model + ops (`cron.add/delete/cursor`, model `cron`) | `session/cron/cronOps.ts` |
| Tools | `agent/tools/cron/cron-create/{cronCreateTool.ts,cron-create.ts,cron-create.md}`, `cron-list/*`, `cron-delete/*` |

**Data structure** (`app/cron/cronTask.ts:9`):
```ts
export interface CronTask {
  readonly id: string;
  readonly cron: string;          // normalized cron expression
  readonly prompt: string;        // re-injected into the session when fired
  readonly createdAt: number;     // epoch ms
  readonly recurring?: boolean;   // absent = recurring (by convention)
  readonly lastFiredAt?: number;  // cursor, persisted
  readonly tags?: Readonly<Record<string, string>>; // carries sessionId
}
export const CRON_SESSION_TAG = 'sessionId';
```

**Storage** — NOT in-memory-only. App-scoped `CronTaskPersistenceService` persists each task as an atomic JSON document under the `cron` persistence scope (`bootstrap.scope('cron')`, i.e. `<homeDir>/cron/`), laid out `<workspaceId>/<id>.json` via `IAtomicDocumentStore` (`cronTaskPersistenceService.ts:58-92`). Ids are ULIDs (`/^(?:[0-9a-f]{8}|[0-9A-HJKMNP-TV-Z]{26})$/i`). Shape guard `isValidCronTask()` drops corrupt rows silently (crash-safe, boot must not fail). Task ownership is via the `sessionId` tag: on load, untagged tasks are **adopted** by the loading session and re-tagged (`sessionCronServiceImpl.ts:265-286` `loadFromStore`).

**Scheduler loop** (`SessionCronServiceImpl`):
- **Polling timer**, not a sorted queue: `IntervalTimer` ticking every `cron.pollIntervalMs` (default **1000 ms**), `unref:true` so it doesn't hold the process open (`start()`, `tick()`).
- **Idle gate**: `tick()` returns early if main-agent loop `status().state === 'running'` — fires are deferred while the REPL is mid-turn; `lastSeenAt` is NOT advanced so the missed fire is delivered later with `coalescedCount` reflecting the gap (this is the coalescing behavior).
- **Per-task flow** (`processDue`): parse (cached in `parsedCache`) → seed `lastSeenAt` from persisted `lastFiredAt` → compute base = `max(seen, createdAt)` → `computeJitteredNext` → if `now < nextFireAt` skip → compute `ideal` run → **coalescing** via `countCoalesced` (walks consecutive due runs up to `MAX_COALESCE_ITERATIONS = 10_000`, returns `{count, lastDueMs}`) → `inFlight` guard set → `deliverDue` → advance cursor / delete one-shot.
- **Jitter** (`app/cron/jitter.ts`) — deterministic per-task, **not random**:
  - Recurring: `fractionFromId(id)` ∈ [0,1) (from hex id, else djb2 hash) × `cap` where `cap = min(period × 0.1, 15 min)`; shift **forward** (`jitteredNextCronRunMs`). Rationale documented: "thundering herd at :00".
  - One-shot: shift **earlier** up to 90 s, only if ideal minute is `:00` or `:30` (round-number heuristic), never before `createdAt` (`oneShotJitteredNextCronRunMs`).
  - Disabled by `KIMI_CRON_NO_JITTER=1`.
- **Staleness**: `isStaleAt` — recurring task older than `STALE_THRESHOLD_MS = 7 days` fires once with `stale="true"` in the prompt and is then **auto-deleted** (`deliverDue`, `cronTaskServiceImpl.ts:447-456`). `KIMI_CRON_NO_STALE=1` disables.
- **Fire injection** (`deliverFire`): builds a user `ContextMessage` with `origin: {kind:'cron_job', jobId, cron, recurring, coalescedCount, stale}` and text from `renderCronFireXml` (`app/cron/format.ts:27`):
  ```
  <cron-fire jobId="..." cron="..." recurring="true" coalescedCount="1" stale="false">
  <prompt>
  <the scheduled prompt>
  </prompt>
  </cron-fire>
  ```
  Injected via `IAgentPromptService.inject(message)` (steer). Fires while the loop is running are flagged `buffered` but still injected. Also publishes `cron.fired` domain event + `cron_scheduled/cron_fired/cron_missed/cron_deleted` telemetry.
- **Missed-notification**: `handleMissed()` injects a separate user message with `{kind:'cron_missed', count}` origin.
- **Wire integration** (`cronOps.ts`): a replayable `CronModel` (`Map<taskId, CronTask>`), three transient ops `cron.add`, `cron.delete`, `cron.cursor` (`persist:false` — authoritative store is the app-scoped file store, reloaded on resume). On wire-restore the service reloads from `ICronTaskPersistence` and restarts the timer.
- **Manual tick**: `KIMI_CRON_MANUAL_TICK=1` disables the timer; `SIGUSR1` triggers a tick (bench/test time-injection, posix only).
- **Clock abstraction** (`clock.ts`): `wallNow()` = `Date.now()` (or `KIMI_CRON_CLOCK=file:<path>` reading a number from a file for tests) + `monoNowMs()` = `process.hrtime.bigint()` (never overridable — lock-heartbeat safety net).

**Tools**:
- `CronCreateTool` (`cronCreateTool.ts`): validations in order — killswitch `KIMI_DISABLE_CRON=1` → cron parse → **must fire within 5 years** (`hasFireWithinYears`) → **`MAX_CRON_JOBS_PER_SESSION = 50`** cap (`cron-create.ts:17`) → `MAX_PROMPT_BYTES = 8*1024` → one-shot < 1 year out (`ONE_SHOT_MAX_FUTURE_MS = 350 days`). Returns `{id, cron, humanSchedule, recurring, nextFireAt}` with jittered `nextFireAt` via `computeDisplayNextFire`. Approval rule = literal JSON of the request (`literalRulePattern`). Double-checks the cap at execute time too.
- `CronListTool` / `CronDeleteTool`: list from session service (insertion order = Map order); delete by ids.
- **`KIMI_DISABLE_CRON=1`** → `disabled` config flag; tool errors with "Cron scheduling is disabled (KIMI_DISABLE_CRON=1)."

**Env knobs** (`app/cron/configSection.ts:46`): `KIMI_CRON_DEBUG`, `KIMI_CRON_NO_JITTER`, `KIMI_CRON_NO_STALE`, `KIMI_DISABLE_CRON`, `KIMI_CRON_MANUAL_TICK`, `KIMI_CRON_CLOCK`, `KIMI_CRON_POLL_INTERVAL_MS`.

### 1b. v1 (older, still present) — `packages/agent-core/src/tools/cron/`

Same behavior, simpler architecture — **better as a clone spec**:
- `types.ts` `CronTask`; `session-store.ts` `SessionCronStore` (in-memory Map, 8-hex ids `randomBytes`, insertion order); `persist.ts` `createCronPersistStore` → `<sessionDir>/cron/<id>.json` per-id atomic writes (crash-safe, shape-guarded); `scheduler.ts` `createCronScheduler({clocks, source, onFire, isIdle, isKilled, removeOneShot, onAdvanceCursor, pollIntervalMs})` — pure engine, no I/O; `clock.ts`, `jitter.ts`, `cron-expr.ts`, `cron-fire-xml.ts` (same `<cron-fire>` XML); `agent/cron/manager.ts` `CronManager` — the wiring: `source: () => store.list()`, `isIdle: () => !agent.turn.hasActiveTurn`, `onFire` → `steer`, mirrors mutations to disk, `loadFromDisk()` on resume. `KIMI_DISABLE_CRON` checked via `isKilled` (`manager.ts:176`).
- Tests to steal: `test/tools/cron/*` (jitter, scheduler, persist, cron-expr), `test/agent/cron/*` (e2e, resume, subagent-skip, manual-tick), and v2 `test/session/cron/cron-fire-steer.e2e.test.ts`.

**Clone difficulty**: LOW-MEDIUM. The v2 engine is ~800 lines total and fully self-contained (only DI decorators + `IntervalTimer` + `IAtomicDocumentStore` are external). The subtle parts to replicate exactly: jitter determinism, coalesce-then-inject, idle gating, 7-day stale auto-expire, one-shot `:00/:30` early-shift rule, `MAX_COALESCE_ITERATIONS` cap.

---

## 2. `kimi web` — local REST + WS server

**CLI entry**: `apps/kimi-code/src/cli/sub/web/` — `index.ts` (builds command: `--port`, `--host`, `--allowed-host`, `--no-open`, `--dangerous-bypass-auth`, `--log-level`), `run.ts` (foreground runner, `startServer` from kap-server, opens browser with `#token=<token>` URL fragment — token never sent to server), `shared.ts`, `access-urls.ts`, `rotate-token.ts`, `networks.ts`, `deprecated-server.ts`, `legacy-kill.ts`.

**Server package**: `packages/kap-server/` (Fastify).

- **Port**: `DEFAULT_SERVER_PORT = 58627` (`cli/sub/web/shared.ts:15`). `DEFAULT_SERVER_HOST = 127.0.0.1`; `--host` (no value) → `0.0.0.0`. Multiple instances share the home dir via an instance registry that picks the next free port (`instanceRegistry.ts`, `start.ts`).
- **Auth**: persistent bearer token written to `<KIMI_CODE_HOME>/server.token` (mode 0600) on first boot, reused thereafter (`shared.ts:18-19`, `tryResolveServerToken`). `middleware/auth.ts` `createAuthHook` → `defaultIsBypassed`: bypass for `OPTIONS`, `GET /api/v1/healthz`, and non-`/api/` static assets; **everything else including `/openapi.json` and `/asyncapi.json` requires `Authorization: Bearer <token>`**. Failed auth → `40101 Unauthorized`; rate limiter bans repeated failures (`middleware/rateLimit.ts`, `AUTH_RATE_LIMIT_*`). WS upgrade uses the same credential via `transport/ws/bearerProtocol.ts`. Optional password auth + `rpcToken` also accepted (`services/auth/*`).
- **Composition root**: `src/start.ts` — `bootstrap()` from `agent-core-v2` builds the Core `Scope`; routes resolve services via `core.accessor.get(IXxx)`. `registerApiV1Routes`, `registerApiV2Routes`, `registerWebAssetRoutes` (serves `dist-web/` SPA). `securityHeaders.ts`, `origin.ts` (CORS allowlist), `hostnames.ts` (Host-header check, `--allowed-host`).
- **Envelope**: every response is `{ code, msg, data, request_id }` (`protocol/envelope.ts`); `code: 0` success, `40001` validation, `40101` auth, `40922` stale page_token, `50001` server error. HTTP status only reflects transport-level outcomes.
- **Session listing**: `routes/sessions.ts` (v1 contract) and `routes/v2/sessions.ts` — `GET /api/v1/sessions` and `GET /api/v2/sessions`. v2: filters `workspace.id`, `activity.status` (`running|approval|question|failed|idle`), `meta.updated_after`, `meta.archived`, sorts `meta.updated_at_desc/asc`, `meta.created_at_desc`, `include=git`; **keyset pagination** `page_size` (max 100, default 50) + opaque `page_token` (base64url JSON binding version + query fingerprint + keyset position; mismatch → 40922). Backed by `ISessionIndex` (`agent-core-v2/src/app/sessionIndex/`) with an authoritative file scan fallback and a minidb read model (flag `persistence_minidb_readmodel`).
- **Streaming**: `transport/ws/v1/` — `WS_PATH = '/api/v1/ws'` (`registerWsV1.ts`). `WsConnectionV1` + `SessionEventBroadcaster` — a journaled, replayable event stream with `{seq, epoch}` watermark; volatile events (`volatile: true`) are never replayed; `resync_required` tells the client to re-fetch REST. Events are transcript ops (see §3). Also `sessionEventJournal.ts`, `inFlightTurnTracker.ts`, `subagentRosterTracker.ts`, `fsWatchBridge.ts`.
- **RPC surface**: `transport/rpc` (`serviceDispatcherRoutes`, `mainAgent`) — a debug RPC over `/api/v1/debug/...` that routes to core services (also used by `kimi-inspect`).
- **Other routes**: `auth`, `approvals`, `questions`, `messages`, `prompts`, `tasks`, `tools`, `skills`, `terminals`, `files`, `fs`, `workspaces`, `workspaceFs`, `snapshot`, `transcript`, `search`, `guiStore`, `config`, `meta`, `modelCatalog`, `oauth`, `shutdown`, `sessionExport`.
- OpenAPI/AsyncAPI docs generated at `openapi.json` / `asyncapi.json` (auth-gated), OpenAPI transform in `openapi/transforms.ts`.

**Clone difficulty**: MEDIUM. Port + bearer token + `{code,msg,data,request_id}` envelope + keyset pagination + journaled WS are all cleanly copyable patterns. The hard parts: WS resync protocol (`{seq,epoch}` watermark semantics), the transcript-op → WS fan-out, and the RPC dispatcher.

---

## 3. Session Model

**Home dir** (`apps/kimi-code/src/utils/paths.ts` + `agent-core-v2/src/app/bootstrap/bootstrap.ts`):
- `homeDir = KIMI_CODE_HOME ?? ~/.kimi-code` (`resolveKimiHome`, `bootstrap.ts:185`), created `0o700`.
- `configPath = <homeDir>/config.toml`.
- App path layout (`bootstrapService.ts:56-70`):
  - `sessionsDir = <homeDir>/sessions`
  - `blobsDir = <homeDir>/blobs`
  - `storeDir = <homeDir>/store` (minidb query store)
  - `cacheDir = <homeDir>/cache`, `logsDir = <homeDir>/logs`
  - scopes: `sessions`, `blobs`, `store`, `logs`, `cache`, `credentials`, `cron`

**Session directory layout** (`sessionIndexSource.ts`): authoritative index is the directory tree
```
<sessionsDir>/<workspaceId>/<sessionId>/state.json
```
- `state.json` is the session metadata document, shared by v1/v2; `version: 2` = epoch-ms timestamps, absent = v1 ISO strings; legacy fallback `<sessionDir>/session-meta/state.json`. Fields incl. `cwd`/`workDir`, `title`, `lastPrompt`, `createdAt`, `updatedAt`, `archived`, `custom`, `lastTurnReason` (`parseTurnOutcome`: completed/cancelled/failed), `childOf`/`childSessionKind` markers.
- **workspaceId**: `encodeWorkDirKey(cwd)` = `wd_<slug40>_<sha256(normalized)[:12]>` (`_base/utils/workdir-slug.ts`). Normalization: backslashes→slash, trailing slashes stripped; case-sensitive (workspaceRootKey is the case-insensitive comparator).
- Cron lives at `<homeDir>/cron/<workspaceId>/<taskId>.json` (§1); per-session agent transcripts at `<sessionDir>/agents/<agentId>/` (filename-safe agent ids `^[A-Za-z0-9._-]{1,128}$`, `transcript/contract/schema.ts`).

**Transcript format** (`packages/transcript/`): an operation-log model — `AgentTranscript.apply(ops)` converges state; items are `turn` / `frame` (text, thinking, tool call/result) / task / todo / interaction / attachment / prompt / meta (`model/*.ts`); ops in `ops/operation.ts`, gap signals when an append can't land. Server = core events → ops → WS; client = REST snapshot then WS ops. Turn origins incl. `cron` (with taskId) — cron-fired turns are first-class.

**Resume semantics** (`workspaceLifecycle/sessionLookup.ts` + `sessionIndex`): `resumeSessionById` → `ISessionLifecycleService.resume(sessionId)`; sessions are found via `ISessionIndex` (summary lookup), live sessions short-circuit (`liveHandlerForSession`); `session_load_failed` telemetry on error. The wire (conversation) state is rebuilt on resume — cron ops are transient (`persist:false`) and reloaded from the file store (§1), which is the documented mechanism for "fires during downtime are collapsed into a single delivery with `coalescedCount`."

**Clone difficulty**: LOW. It's just `state.json` + per-id JSON docs + a file-walking index. The subtle bits: v1↔v2 timestamp normalization, `cwd` recovery across `cwd`/`workDir`/`custom.cwd`, and minidb read-model projection (optional optimization).

---

## 4. Approval / Permission Model

**v1 (classic, best spec)** — `packages/agent-core/src/agent/permission/`:
- `types.ts`: `PermissionMode = 'manual' | 'yolo' | 'auto'` with documented semantics: *manual* = rules drive; unmatched tool calls **ask**; *yolo* = only deny rules can block; *auto* = caller may bypass rule checks. `PermissionRule {decision: allow|deny|ask, scope: turn-override|session-runtime|project|user, pattern}` — pattern DSL like `Read(/etc/**)`, `Bash(rm *)`, bare `Write`; tools provide matchers (`matches-rule.ts`).
- `index.ts` `PermissionManager`: policy chain evaluated in order, first non-undefined wins (`evaluatePolicies`); results `approve` (with optional `executionMetadata`) / `deny` / `ask`; `ask` → `requestToolApproval` → user prompt → `ApprovalResponse {decision: approved|rejected|cancelled, scope?: 'session', feedback?, selectedLabel?}`; **approve-for-session** records a `session-runtime` rule (via `SessionApprovalHistoryPermissionPolicy`); rejection feedback is fed back to the model; sub-agents get harsher "don't bypass" phrasing.
- **Policy order** (`policies/index.ts:31-69`): `PreToolCallHook` → `AgentSwarmExclusiveDeny` → `AutoModeAskUserQuestionDeny` → `PlanModeGuardDeny` → `UserConfiguredDeny` → `AutoModeApprove` → `SessionApprovalHistory` → `UserConfiguredAsk` → `UserConfiguredAllow` → `ExitPlanModeReviewAsk` → `GoalStartReviewAsk` → `PlanModeToolApprove` → `SensitiveFileAccessAsk` → `GitControlPathAccessAsk` → `YoloModeApprove` → `SwarmModeAgentSwarmApprove` → `DefaultToolApprove` → `GitCwdWriteApprove` → `FallbackAsk`.
- **Plan mode**: `PlanModeGuardDenyPermissionPolicy` + `PlanModeToolApprovePermissionPolicy` (reads tools are allowed; writes denied), `ExitPlanModeReviewAsk` (review gate when plan_review active, non-empty plan, non-auto).
- **Tool classification**: tools declare `accesses: ToolFileAccess[]` (`operation: read|write|readwrite|search` + path) and an `approvalRule` string. Sensitive files via `tools/policies/sensitive.ts`; git control paths via `tools/support/git-worktree.ts`; path containment via `tools/policies/path-access.ts`.

**v2** — `agent-core-v2/src/agent/`:
- `permissionMode/`: `PermissionMode = 'manual'|'yolo'|'auto'`; persisted default `defaultPermissionMode` config section (`manual|auto|yolo`), live mode is Agent-scope wire state.
- `permissionGate/permissionGate.ts`: `IAgentPermissionGate.authorize(ctx) → BeforeExecuteDecision` hook before tool execution.
- `permissionPolicy/`: same approve/deny/ask result algebra (`types.ts`), `PermissionPolicy` interface.
- `permissionRules/`: rule matching (`matchesRule.ts`).
- `toolPolicy/`: activation allowlist/denylist (`evaluate.ts`) — `[tools] enabled/disabled` config; MCP tools matched by `mcp__<server>__<tool>` patterns via picomatch; workspace-veto > profile > global > session layers.

**CLI flags** (`apps/kimi-code/src/cli/options.ts`): `yolo`, `auto`, `plan` booleans; conflicts: `--prompt` × (`--yolo|--auto|--plan`), `--yolo` × `--auto`; `--agent/--agent-file` × `--session/--continue`.

**Clone difficulty**: LOW-MEDIUM. The policy-chain-with-first-wins + ask/approve-for-session/rejection-feedback loop is simple to reproduce; the subtle parts are the sensitive/git-path classifications and plan-mode read-vs-write gating semantics.

---

## 5. Plugin + Skill System

**Plugin manifest** (`packages/agent-core/src/plugin/`): `kimi.plugin.json` at plugin root OR `.kimi-plugin/plugin.json` (root file shadows dir file). Schema (`manifest.ts`, `types.ts`):
```jsonc
{
  "name": "kimi-webbridge", "version": "1.11.3", "description": "...",
  "keywords": [...], "author": {...}, "homepage": "...", "license": "...",
  "skills": ["./skills/"],        // resolved absolute dirs
  "agents": [...],                 // agent profile dirs
  "sessionStart": { "skill": "..." },
  "mcpServers": { "<name>": { "command|url", "args", "env", "cwd", "transport", ... } },
  "hooks": [...],                  // HookDefConfig
  "commands": [...],               // PluginCommandEntry
  "interface": { "displayName", "shortDescription", "longDescription", "developerName", "websiteURL" },
  "skillInstructions": "...", "systemPrompt": "..."
}
```
- Unsupported runtime fields (`tools`, `apps`, `inject`, `configFile`, `bootstrap` — Claude/Codex legacy) are diagnosed, not executed.
- Manager: `manager.ts` (install/enable/disable, plugin dirs), `github-resolver.ts` (git-installed plugins), `archive.ts`, `store.ts` (state), `source.ts`.
- Marketplace: `plugins/marketplace.json` — `{version:"1", plugins:[{id, tier: official|curated, displayName, version, description, keywords, source (local path or GitHub URL)}]}`. Official plugins live under `plugins/official/<id>/` (e.g. `kimi-webbridge`, `kimi-datasource`).

**Skills** (`packages/agent-core/src/skill/`): SKILL.md with YAML frontmatter; types `prompt|inline|flow` (only these are supported — others error `UnsupportedSkillTypeError`). Roots (`scanner.ts`): user `<KIMI_CODE_HOME>/skills` + `<home>/.agents/skills`, project `.kimi-code/skills` + `.agents/skills`, builtin dir, plugin skill dirs; scan depth ≤ 8. Frontmatter aliases: `when-to-use`→`whenToUse`, `disable-model-invocation`→`disableModelInvocation`. v2 equivalent: `agent-core-v2/src/app/skillCatalog/` (`builtin/mcp-config.ts|md`, etc.).

**`/mcp-config`** — implemented as a **skill** (`agent-core-v2/src/app/skillCatalog/builtin/mcp-config.md`), not a command: OAuth login flow via per-server `mcp__<server>__authenticate` tool when a server is `needs-auth`; otherwise config edit over three merged files (precedence later-wins):
1. `<KIMI_CODE_HOME>/mcp.json` (user-global)
2. `<project root>/.mcp.json` (walk up to nearest `.git`; Claude-compatible)
3. `<cwd>/.kimi-code/mcp.json` (project-local overrides)
Format: `{ "mcpServers": { "<name>": { "command", "args", "env", "cwd" | "url", "bearerTokenEnvVar", "enabled", "startupTimeoutMs", "toolTimeoutMs", "enabledTools", "disabledTools", "headers" } } }`; transport inferred from command vs url. Global timeouts in `config.toml` `[mcp] startup_timeout_ms` / `tool_timeout_ms`.

**Clone difficulty**: LOW. Manifest + marketplace JSON + SKILL.md scanner are trivial to clone; the interesting bits are MCP config layering and the OAuth tool-per-server mechanism.

---

## 6. Agent Swarm — `agent-core-v2/src/`

**Answer: the swarm runs 100% locally, in-process** — sub-agents are scoped agent instances in the same process, NOT worker threads/processes.

- Tool: `agent/tools/agent-swarm/agentSwarmTool.ts` (+ `agent-swarm.md` spec). Contract: `prompt_template` with `{{item}}` placeholder + `items[]` (≥2 items enforced), or `resume_agent_ids` map, or both; expanded prompts must be distinct; **max 128 subagents** (`MAX_AGENT_SWARM_SUBAGENTS`, `agent-swarm.ts`); "If AgentSwarm is called, that call must be the only tool call in the response."
- Spawning (`session/swarm/sessionSwarmService.ts`): `spawnAttempt` → `this.lifecycle.create({binding: {profile, model, thinking}, labels})` — creates an in-process `IAgentScopeHandle` (same DI Scope engine as the main agent); inherits the caller's permission mode + user tools; prompt passed through `applyProfilePromptPrefix` (profile prompt templating); runs the normal `AgentLoop`, result observed via `observe()` → `completion: Promise<{result, usage}>`.
- **Concurrency & rate limiting** (`session/swarm/agentRunBatch.ts` `AgentRunBatch`):
  - `INITIAL_LAUNCH_LIMIT = 5` (burst of 5) then 1 per `INITIAL_LAUNCH_INTERVAL_MS = 700 ms` — "burst-then-throttle ramp".
  - Optional cap `maxConcurrency` from env **`KIMI_CODE_AGENT_SWARM_MAX_CONCURRENCY`** (`resolveSwarmMaxConcurrency` — must be positive int); **undefined = uncapped** (default).
  - **Provider-rate-limit recovery loop**: on `isProviderRateLimitError`, the run is requeued with exponential backoff `retry.createTimeout(3s base, ×2 factor)`; `rateLimitCapacity` starts at `startedSuccessCount`, shrinks every 2 s while failing, recovers after 3 min; global retry spacing `globalRetryIntervalMs`; emits `subagent.suspended` event; the last unfinished task fails instead of requeueing (`isOnlyUnfinishedTask`).
  - Batch abort: one shared `AbortController` linked to each task's signal; user cancellation → graceful `finishWithUserCancellation`.
- Results aggregate into `Array<SessionSwarmRunResult<T>>` with per-task `{status: completed|failed|aborted, result, usage, error}`; task kinds `prompt` vs `resume` (`resumeAgentId`).
- Swarm mode is itself a session concept: `agent/swarm/swarm.ts` `IAgentSwarmService {isActive, enter(trigger: 'manual'|'task'|'tool'), exit()}`; permission policies `SwarmModeAgentSwarmApprove` / `AgentSwarmExclusiveDeny` (agent-swarm tool is auto-approved only in swarm mode); TUI swarm progress UI in `apps/kimi-code/src/tui/components/messages/agent-swarm-progress.ts`.
- v1 sibling: `packages/agent-core/src/tools/builtin/collaboration/agent-swarm.ts` + `src/agent/swarm/index.ts`.

**Implication**: a 300-agent swarm is feasible on one machine but bounded by: same-process memory (each agent = DI scope + wire state), provider rate limits (handled by the built-in recovery loop), and the 700 ms launch ramp (~1 agent / 700 ms after the first 5). All 128 runs of a swarm share the caller's model/thinking by default.

**Clone difficulty**: MEDIUM. The spawn-in-process + observe pattern is straightforward once you have an agent loop factory; the `AgentRunBatch` rate-limit scheduler (capacity shrink/recovery, backoff, requeue, `suspended` events) is the piece worth copying verbatim — it's pure, dependency-light logic (only `retry` npm package).

---

## 7. OpenClaw Automations (cron) — `openclaw/openclaw`, `src/cron/`

Huge subsystem (~300 files). Core facts:

**Scheduler loop** — `src/cron/service/timer-scheduler.ts`:
- Single self-arming `setTimeout` per process (`armTimer`): delay = `clamp(nextWakeAtMs - now, MIN_REFIRE_GAP_MS=2000, MAX_TIMER_DELAY_MS=60000)` — floors at 2 s to prevent hot-loops, caps at 60 s "to avoid schedule drift and recover quickly when the process was paused or wall-clock time jumps". Maintenance recheck timer at 60 s when enabled jobs have no nextRunAtMs.
- `onTimer` → gateway root work admission (`beginGatewayRootWorkAdmissionWhenOpen`, drains on restart) → `onAdmittedTimer`:
  - `state.running` guard (re-arm 60 s watchdog while a tick executes; a long job can't kill the scheduler — issue #12025)
  - `locked(state, ...)` per-store mutex → `ensureLoaded(forceReload, skipRecompute)` (reload from SQLite) → `collectRunnableJobs` → **reserve queued runs** (`run-admission.ts`: reservation markers, `resolveRunConcurrency`) → execute jobs via `timer-job-runner.ts` with `executeJobCoreWithTimeout` (per-job timeout from `timeout-policy.ts`) → finalize outcomes (`timer-outcome-finalization.ts`), session reaper (`session-reaper.ts`), persist, re-arm.
- Restart catch-up: `restart-catchup` behavior recomputes due runs after downtime (sub-second precision tests).

**Storage** — SQLite, NOT JSON files: `src/cron/store.ts` + `src/state/openclaw-state-db.ts`. Table `cron_jobs` in the shared OpenClaw state DB (`~/.openclaw` config dir; `resolveConfigDir` + `cron/jobs.json` legacy default path still resolvable). Kysely facade (`store/schema.ts`); full-table replace (`replaceCronRows`) or runtime-only column update (`updateCronRuntimeRows`) in one write transaction; per-store-key revision counters (max 64 tracked) so sibling scheduler snapshots invalidate without polling SQLite; malformed rows go to a **quarantine** store.

**`cron_jobs` table columns** (from `openclaw-state-db.generated.d.ts:420-491`): `job_id` (PK), `store_key` (partition), `name`, `description`, `display_name`, `enabled` (int), `session_key`, `session_target` (`main|isolated|current|session:<id>`), `agent_id`, `owner_agent_id`, `owner_session_key`, `schedule_kind`, `schedule_expr`, `schedule_identity`, `schedule_tz`, `at`, `every_ms`, `anchor_ms`, `stagger_ms`, `trigger_once`, `delete_after_run`, `wake_mode` (`next-heartbeat|now`), `payload_kind`, `payload_message`, `payload_model`, `payload_thinking`, `payload_timeout_seconds`, `payload_tools_allow_json`, `payload_tools_allow_is_default`, `payload_light_context`, `payload_external_content_source_json`, `payload_allow_unsafe_external_content`, `payload_fallbacks_json`, `trigger_script`, `delivery_*` (channel/to/thread_id/account_id/mode/completion_mode/best_effort/completion_to), `failure_delivery_*`, `failure_alert_*` (mode/after/cooldown/disabled/include_skipped/to/channel/account_id/last_failure_alert_at_ms), `job_json`, `state_json` (generated), `next_run_at_ms`, `last_run_at_ms`, `last_run_status`, `last_delivered`, `last_delivery_status`, `last_delivery_error`, `last_error`, `last_duration_ms`, `running_at_ms`, `consecutive_errors`, `consecutive_skipped`, `schedule_error_count`, `runtime_updated_at_ms`, `created_at_ms`, `updated_at`, `sort_order` (generated).

**Trigger types** (`src/cron/types.ts` `CronSchedule`):
- `{kind:'at', at}` — one-shot time
- `{kind:'every', everyMs, anchorMs?}`
- `{kind:'cron', expr, tz?, staggerMs?}` — deterministic stagger: `stagger.ts` auto-applies `DEFAULT_TOP_OF_HOUR_STAGGER_MS = 5 min` to top-of-hour recurring exprs (`0 * * * *`-shaped; 5- or 6-field), explicit `staggerMs` wins (0 = exact)
- `{kind:'on-exit', command, cwd?}` — event-driven: fires once when a gateway-supervised watcher process exits (ProcessSupervisor-owned so it survives per-turn teardown, #71662)
- `{kind:'stream', command[], cwd?, mode:'line'|'match', match?, batchMs?, maxBatchBytes?}` — supervised argv emitting payload-triggering lines

Delivery: `mode: none|announce|webhook`, channel-specific `to`/`threadId`/`accountId`, separate `failureDestination`, `failureAlert` with cooldown. Execution: `sessionTarget` decides main-session join vs isolated agent run (`src/cron/isolated-agent/`) vs named session; wake via heartbeat (`heartbeat-*`).

**Auto-disable-after-10-failures** — `src/cron/service/auto-disable.ts`:
```ts
const MAX_CONSECUTIVE_RUN_FAILURES = 10;  // run failures (provider/network transient, restart-interrupted runs count)
// schedule errors: 3 (documented: "Run failures get more room than schedule errors (10 vs 3)")
```
`maybeAutoDisableCronJobAfterRunFailure` fires only for time-based recurring jobs (`kind === 'cron' | 'every'`); `autoDisableCronJob`: `job.enabled = false; state.nextRunAtMs = undefined; state.autoDisabled = {reason: 'consecutive-failures'|'schedule-errors', atMs, consecutiveErrors}` + queued system-event notification to the owning agent with context key `cron:<id>:auto-disabled` + heartbeat request; re-enable via `openclaw automations enable <id>`.

**Clone difficulty**: HIGH-MEDIUM. The scheduler core (arm/clamp/re-arm, admission, locked reload, reservation) is ~400 lines of hard-won logic (hot-loop fixes, watchdog re-arm, restart catch-up). The SQLite schema is a great reference for a relational job store (vs kimi's per-id JSON). The isolated-agent execution pipeline is the deep part to skip or stub in v1 of a clone.

---

## License Implications

- **Both repos are MIT** → code can be copied, modified, and vendored into a from-scratch clone with attribution (`LICENSE` files retained). No copyleft obligations.
- kimi-code packages are `@moonshot-ai/*` published under MIT; note the **`plugins/official/*` manifests say `"license": "Proprietary"`** for the bundled plugin content (webbridge browser daemon etc.) — don't vendor those. The plugin *host* machinery (`packages/agent-core/src/plugin/`) is MIT.
- API/telemetry endpoints of Kimi's cloud (login, model API) are not in the repo — the clone needs its own backend or a compatible provider.
- OpenClaw has `THIRD_PARTY_NOTICES.md` for adapted code — follow suit if you adapt heavily.

---

## Building a Clone From This

Components + exact files to use as **spec** (all MIT):

1. **Cron scheduler** — v1 stack is the cleanest spec: `packages/agent-core/src/tools/cron/{scheduler,jitter,cron-expr,cron-fire-xml,persist,session-store,types,clock}.ts` + wiring `src/agent/cron/manager.ts`. Add v2 upgrades: 50-job cap + 8 KB prompt cap + 5-year window + 7-day stale auto-expire (`agent-core-v2/src/agent/tools/cron/cron-create/cronCreateTool.ts`, `cron-create.ts`), `<cron-fire>` injection format (`app/cron/format.ts`), env knobs (`app/cron/configSection.ts`). Persist as per-id JSON docs under `<home>/cron/` like `cronTaskPersistenceService.ts`.
2. **Local web server** — `packages/kap-server/src/start.ts` (Fastify composition), `middleware/auth.ts` (bearer token, `server.token` 0600, bypass policy), `protocol/envelope.ts` (`{code,msg,data,request_id}`), `routes/v2/sessions.ts` (keyset pagination contract), `transport/ws/v1/{registerWsV1,protocol,sessionEventBroadcaster,sessionEventJournal}.ts` (journaled streaming). Port 58627 + `#token=` fragment is a UI detail worth copying.
3. **Session store** — `~/.kimi-code/sessions/<workspaceId>/<sessionId>/state.json` layout (`app/sessionIndex/sessionIndexSource.ts`), `wd_<slug>_<sha256>[:12]` workspace ids (`_base/utils/workdir-slug.ts`), `resolveKimiHome` (`app/bootstrap/bootstrap.ts:181`), scopes (`app/bootstrap/bootstrapService.ts:56`). Transcript op-log model from `packages/transcript/src/{store,ops,model}`.
4. **Permissions** — policy chain in `packages/agent-core/src/agent/permission/policies/index.ts` (order matters, copy verbatim), `PermissionManager` ask/approve-for-session/feedback in `index.ts`, rule DSL + `matches-rule.ts`, sensitive/git path policies, plan-mode deny/approve split. Modes `manual|yolo|auto` from `permissionMode/permissionMode.ts` + `types.ts` doc comments.
5. **Plugins/skills** — manifest parser `packages/agent-core/src/plugin/manifest.ts` + `types.ts`, marketplace shape `plugins/marketplace.json`, skill scanner `src/skill/scanner.ts` + parser, mcp layering from `skillCatalog/builtin/mcp-config.md`.
6. **Swarm** — `agent-core-v2/src/session/swarm/agentRunBatch.ts` (burst-5/700 ms ramp, rate-limit capacity shrink/recover, backoff requeue — copy this file's logic), `sessionSwarmService.ts` spawnAttempt (in-process lifecycle.create + profile prompt + observe), tool contract from `agent/tools/agent-swarm/agent-swarm.md` ({{item}} template, ≥2 items, 128 max, sole tool call).
7. **OpenClaw automations** — scheduler loop `src/cron/service/timer-scheduler.ts` (arm/clamp/re-arm + admission), `cron_jobs` SQLite schema (generated.d.ts), trigger union `src/cron/types.ts`, stagger `src/cron/stagger.ts`, auto-disable `src/cron/service/auto-disable.ts` (10 run failures / 3 schedule errors).

**Do NOT clone**: `kap-server` RPC/debug surface, OpenClaw `isolated-agent/*` execution pipeline (defer), the minidb read-model index (start with the authoritative file scan), telemetry/update/native-binary machinery.

**Hard-to-clone notes**: (a) v2's wire-op model + `{seq,epoch}` WS resync — requires the transcript op-log discipline; (b) determinism guarantees (jitter, no `Date.now()` outside clocks, `no-date-now` test guards) — adopt the clock-injection discipline early; (c) OpenClaw's restart-catch-up + hot-loop fixes are only visible in git history/tests — copy the tests too.
