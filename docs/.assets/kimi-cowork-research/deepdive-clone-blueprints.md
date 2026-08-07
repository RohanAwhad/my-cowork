# Stage 2 Deep Dive: Build Blueprints from Existing Cowork Clones

**Target:** From-scratch clone of Claude Cowork + Kimi Work ("coworker agent" desktop product)
**Method:** Read trees via GitHub API + raw files from 3 primary repos + GitHub API search for the rest.
**Date:** 2026-08-06

---

## 0. Reality check: what the *real* Claude Cowork is (evidence from a reverse-engineering repo)

`johnzfitch/claude-cowork-linux` (406★, reverse-engineered Cowork, [README](https://github.com/johnzfitch/claude-cowork-linux)) reveals the real architecture:

- Cowork is **not a separate app** — it is a special **Claude Desktop build** with a "Cowork" mode (macOS-only preview) that runs inside a **sandboxed Linux VM**.
- The agent core is the **Claude Code binary** running inside that VM; the desktop shell communicates with it and translates VM paths → host paths.
- Native macOS modules (`@ant/claude-swift`, `@ant/claude-native`) are stubbed on Linux; the stub sends **macOS platform headers** so the server enables the Cowork feature.
- Cowork works "inside a folder you point it at" — a **workspace folder** the agent reads/writes/organizes while running a plan.

**Implication for a clone:** nobody in OSS reproduces the VM isolation. Every clone instead runs the agent SDK/CLI directly on the host. That is the #1 deliberate gap (see Recommended Architecture).

---

## 1. composio-community/open-claude-cowork (4.3k★)

Stack: **Electron + plain JS renderer + Express backend (port 3001) + Claude Agent SDK + @opencode-ai/sdk + Composio Tool Router (remote MCP)**. Smallest, simplest of the three — the best "minimal blueprint."

### 1.1 Repo layout (29 files, HEAD)

```
open-claude-cowork/
├── main.js                      # Electron main (77 lines — just a window)
├── preload.js                   # contextBridge → electronAPI (SSE fetch wrapper)
├── renderer/index.html          # 2 views: home (greeting) + chat
├── renderer/renderer.js         # 1,764 lines: all UI, SSE parsing, tool sidebar
├── renderer/style.css
├── server/server.js             # Express on :3001, /api/chat (SSE), /api/abort, /api/providers
├── server/providers/
│   ├── base-provider.js         # abstract interface (sessions Map, async *query, abort)
│   ├── claude-provider.js       # Claude Agent SDK adapter
│   ├── opencode-provider.js     # @opencode-ai/sdk adapter (spawns server on :4096)
│   └── index.js                 # provider registry/cache
├── .claude/skills/              # bundled skills (SKILL.md)
└── setup.sh
```

The `clawd/` companion bot referenced by the README **was removed from this repo** — it now lives in `composio-community/secure-openclaw` (1.2k★, "OpenClaw"). The scheduling code is there (see 1.6).

### 1.2 Agent runtime wiring

- **Backend is a separate process** from Electron. README says run `cd server && npm start` + `npm start` in two terminals. `main.js` never spawns the server (no child_process).
- **Express on 3001** (`server/server.js:16`), `POST /api/chat` (`server.js:61`) sets SSE headers (`server.js:87-91`), writes `data: {...}\n\n` chunks, plus a **15s heartbeat comment** `: heartbeat\n\n` (`server.js:95-99`) so proxies/Electron don't kill the stream.
- **Provider abstraction**: `BaseProvider` (`base-provider.js`) defines `async *query(params)` yielding normalized chunks, plus `sessions` Map keyed by chatId. `getProvider()` caches instances (`providers/index.js:21-40`).
- **Claude provider** (`claude-provider.js`):
  - Calls `query()` from `@anthropic-ai/claude-agent-sdk` (`claude-provider.js:1,90`).
  - **Session resume**: captures `session_id` from the `system`/`init` chunk (`claude-provider.js:101-119`), stores per-chatId, and on next turn sets `queryOptions.resume = existingSessionId` (`claude-provider.js:75-78`). Session state lives **only in memory** (server restart = all sessions lost).
  - **Normalizes the SDK chunk stream** into: `session_init` (id), `text`, `tool_use`, `tool_result`, `done`, `aborted` (`claude-provider.js:113-172`). `permissionMode: 'bypassPermissions'` (`claude-provider.js:17`), `settingSources: ['user','project']` for skills (`claude-provider.js:67`), `maxTurns` default 20, tools `[Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch, TodoWrite, Skill]` (`claude-provider.js:12-15`; server.js:143).
  - **Abort**: `AbortController` per chatId (`claude-provider.js:83-86`), exposed via `POST /api/abort` (`server.js:177-201`).
- **Opencode provider** (`opencode-provider.js`): `createOpencode()` spawns an opencode server on `127.0.0.1:4096` (`opencode-provider.js:56-59`); creates session via `client.session.create({body:{config:{model}}})` (`opencode-provider.js:141-148`); streams via `client.event.subscribe()` + `session.promptAsync()` (`opencode-provider.js:168-178`); computes **text deltas** by tracking yielded length per partId (`opencode-provider.js:220-233`); ends on `session.idle` (`opencode-provider.js:294-296`).
- **Transport to renderer**: `preload.js` wraps `fetch('http://localhost:3001/api/chat')` in a `getReader()`-style interface with an `AbortController` (`preload.js:40-103`); renderer manually parses SSE lines (`renderer.js:867-974`).

### 1.3 Artifact / tool-visualization rendering

- **Right sidebar** = Steps (from `TodoWrite` tool input) + Tool Calls list; **inline collapsible tool cards** in the message stream.
- `tool_use` event → `addToolCall()` (sidebar card w/ status running/success) + `addInlineToolCall()` (inline card, expanded, input pretty-printed) (`renderer.js:901-913`, `1244-1281`); `tool_result` event → `updateToolCallResult()` renders output truncated to **2000 chars** (`renderer.js:1284-1305`).
- **TodoWrite special-case**: `TodoWrite` tool input → Steps sidebar with statuses pending/in_progress/completed (`renderer.js:911-913`, `1403-1442`).
- **Markdown streaming**: keeps `dataset.rawContent` and re-renders via `marked` per chunk into chunk containers (`renderer.js:1072-1090`); thinking streamed into a collapsed `<details>` section (`renderer.js:1092-1125`).
- **Browser preview**: regex-scans streamed text + tool results for `https://live.anchorbrowser.io?sessionId=...` (`renderer.js:1499-1506`) and embeds an **iframe with `sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"`** inline, movable to the sidebar, openable in new window (`renderer.js:1509-1753`).
- **No artifact pipeline at all** — no file watching, no HTML preview of generated files. Outputs only appear as tool-call JSON.

### 1.4 Session persistence

- **localStorage only** (`renderer.js:85-130`): saves serialized DOM (`.message-content` innerHTML) + todos + toolCalls per chatId. Chat list sidebar restored from localStorage. Nothing on disk; agent sessions themselves are in-memory on the server.

### 1.5 MCP / connector integration

- **Composio Tool Router** as a **remote HTTP MCP server**: `composio.create(userId)` returns `session.mcp.url` + headers (`server.js:19-31`); passed to the Claude SDK as `mcpServers.composio {type:'http', url, headers}` (`server.js:124-130`).
- For opencode, the MCP config is **written to disk** as `server/opencode.json` on every session create (`server.js:42-54,115-117`) — opencode reads config from file, so the provider itself never receives MCP params (`opencode-provider.js:135-136`).
- Also ships `.claude/skills/` (brand-guidelines, remotion-best-practices) — skills = `SKILL.md` files auto-discovered via `settingSources: ['user','project']` (`claude-provider.js:67`).

### 1.6 Scheduling — the "Clawd" companion bot (`composio-community/secure-openclaw`)

This is the only real scheduler implementation in the Composio family. Three files:

- `agent/runner.js` — per-session **message queue** (`runner.js:14,80-118`), sequential execution (`processQueue`), global stats.
- `agent/claude-agent.js` — Claude Agent SDK wrapper; builds a **system prompt** instructing the model when to use cron tools ("remind me in X minutes" → `schedule_delayed`, "every day at 9am" → `schedule_cron "0 9 * * *"`) (`claude-agent.js:60-74,125-129`); composes `allMcpServers = {cron, gateway, applescript, ...userMcps}` (`claude-agent.js:329-334`) and allowed-tools list incl. `mcp__cron__*` (`claude-agent.js:200-206`).
- `tools/cron.js` — the scheduler itself:
  - **Exposes scheduling as an in-process MCP server** via `createSdkMcpServer` + `tool()` + zod from `@anthropic-ai/claude-agent-sdk` (`cron.js:1-2,245-372`). Tools: `schedule_delayed`, `schedule_recurring`, `schedule_cron`, `list_scheduled`, `cancel_scheduled` (`cron.js:250-369`). NL → tool call happens in the model.
  - **Persistence**: JSON file `~/.secure-openclaw/cron-jobs.json` (`cron.js:8`), loaded at boot (`cron.js:29-42`), written on every mutation (`cron.js:44-51`).
  - **Trigger loop**: `setTimeout` for delayed, `setInterval` for recurring, **hand-rolled 5-field cron parser** (`getNextCronRun`, minute+hour only) with a `setTimeout` re-arm chain (`cron.js:161-193`). No cron library.
  - Jobs **survive restart** (re-scheduled from file at boot, `cron.js:34-36`); `executeJob` emits `'execute'` with platform/chatId/message/`invokeAgent` flag (`cron.js:195-211`) → gateway either sends the message or **re-invokes the agent** with the message.
- **Memory system** (bonus, directly relevant to Kimi): `memory/manager.js` — `MEMORY.md` curated + `memory/YYYY-MM-DD.md` daily logs in `~/secure-openclaw/`, injected into the system prompt (`claude-agent.js:11-58`).

### 1.7 Permission / approval UX

- Desktop app: **none** — `permissionMode: 'bypassPermissions'` (`claude-provider.js:17`). All tools auto-approved.
- OpenClaw bot: `createMessagingCanUseTool` (`runner.js:185-264`) — a `canUseTool` callback that formats "Claude wants to use: X" + input + "Reply Y to allow, N to deny" and sends via `gateway.waitForApproval(chatId, adapter, prompt)`; **timeout → deny** (`runner.js:254-255`). `AskUserQuestion` special-cased into numbered options ("Reply with a number") (`runner.js:191-238`).

### 1.8 What's missing vs real Cowork

- No disk persistence for sessions (memory-only server + localStorage UI snapshots)
- No artifact/preview pipeline, no file watching
- No permission UX (bypasses everything)
- No scheduling/automation in the desktop app itself
- No sandbox/VM isolation, no multi-turn "plan" state machine
- Session resume depends on the Agent SDK session id, which is ephemeral

---

## 2. eigent-ai/eigent (14.8k★, Apache-2.0)

Stack: **Electron shell + React 18/TS + Tailwind + Zustand + React Flow** frontend, **Python FastAPI + uvicorn + CAMEL-AI multi-agent framework** backend, **SQLModel/SQLAlchemy + Postgres + Redis + Celery** server, Chrome DevTools Protocol browser pool. The most feature-complete clone — closest thing to "Cowork as a product."

### 2.1 Repo layout

```
eigent/
├── electron/                    # Electron main (3,561 lines index.ts) + preload
│   ├── main/index.ts            # window mgmt, spawns python backend, IPC, CDP pool, terminal (node-pty), OAuth subscription auth
│   ├── main/webview.ts          # WebViewManager — stealth browser webviews + CDP screenshots
│   ├── main/fileReader.ts       # file → HTML converters (docx/xlsx/pptx/csv)
│   └── main/init.ts             # startBackend() — spawns uvicorn
├── src/                         # React frontend
│   ├── components/Session/PreviewPanel/  # browser/file/terminal tabs (artifacts)
│   ├── components/Trigger/      # scheduling UI
│   └── store/                   # Zustand stores incl. pageTabStore (preview tabs)
├── backend/                     # Python FastAPI agent backend
│   └── app/
│       ├── agent/               # agent_model.py, listen_chat_agent.py, factory/{single_agent,developer,mcp,question_confirm,...}.py, toolkit/ (40+ toolkits), prompt.py (895 lines system prompts)
│       ├── controller/          # chat_controller.py (SSE), file_controller.py, mcp_controller.py, skill_controller.py, tool_controller.py...
│       ├── service/             # chat_service.py (2,901 lines event stream), mcp_config.py, skill_service.py
│       ├── hands/               # capability/permission layer: sandbox_hands, full_hands, remote_hands, http_hands_cluster...
│       └── memory/              # local memory store (space/project/run scaffolding)
└── server/                      # Python cloud-ish server: domains/trigger (Celery scheduling), domains/mcp, domains/space, oauth
```

### 2.2 Agent runtime wiring

- **Python agent core, not a spawned CLI.** Uses the **CAMEL-AI framework**: `ModelFactory.create(...)` per platform (`agent/agent_model.py:286-294`), wrapped in a custom `ListenChatAgent` (`agent_model.py:298-313`). Model-agnostic (Anthropic, OpenAI, Bedrock, Azure, Ollama, vLLM...) with auto prompt-caching config per platform (`agent_model.py:217-236`), 10-min timeout.
- **Streaming transport = FastAPI SSE**: `POST /chat` → `StreamingResponse(stream, media_type="text/event-stream")` (`chat_controller.py:503-509`). The stream is a **typed event protocol** (see `chat_service.py` yields): `end`, `task_state`, `new_task_state`, `create_agent`, `activate_agent`, `assign_task`, `activate_toolkit`, `ask` (confirmation questions), `add_task`/`remove_task` (sub-task splits), `to_sub_tasks`, `decompose_text`, `request_usage`, `error` (`chat_service.py:1237,1303,1392,1702-1734,1789,2074`).
- **Concurrency model**: a `TaskLock` per project serializes runs and carries conversation history for follow-up turns; SSE close is interpreted as cancel, but completed locks are preserved ("frontend closes the SSE stream after a run reaches `end`... completed locks with history must survive it") (`chat_controller.py:295-311`). 60-min idle timeout wrapper (`chat_controller.py:82-83,314-381`).
- **Workspace model**: per-request `frozen_dirs` snapshot (`chat_controller.py:410-427`) — the "folder you point Cowork at" concept, implemented as directory freezing + snapshot persistence.
- **Multi-agent**: single-agent harness + "Workforce" (parallel sub-agents); sub-task decomposition events streamed to UI (`to_sub_tasks`, `add_task`).
- **Electron spawns the Python backend** on port 5001 (`electron/main/init.ts` `startBackend`), restarts it, runs diagnostics on failure.

### 2.3 Artifact / preview rendering

- **PreviewPanel with tab kinds**: `browser`, `file`, `terminal` (+ reserved `review`, `canvas` stubbed out) (`components/Session/PreviewPanel/tabKinds.tsx`).
- **File preview pipeline**: `FilePreview` (project page side panel) → `loadFileContent` → Electron IPC `invoke('open-file', type, path, showSource)` (`FilePreview.tsx:173-186`); Electron main `fileReader.ts` converts office formats **to HTML in the main process**: docx via `mammoth` (`fileReader.ts:51`), xlsx → styled HTML tables (`fileReader.ts:116-243`), pptx → slide HTML (`fileReader.ts:331-360`), csv → HTML tables (`fileReader.ts:379-396`). PDFs → data-URL iframe (`FilePreview.tsx:148-164`). `FileViewerPanel` renders markdown/PDF/docs/HTML/media identically in Inbox/Folder tabs.
- **Browser artifact**: `WebViewManager` (`electron/main/webview.ts`) — `WebContentsView` per session with `partition: 'persist:user_login'` isolation (`webview.ts:140-153`), **anti-bot stealth script** (hides webdriver, spoofs plugins/languages/WebGL) (`webview.ts:155-250`), CDP screenshot capture for previews (`webview.ts:61-109`), hidden off-screen bounds for background tabs, max 5 inactive webviews w/ cleanup.
- **Terminal artifact**: node-pty + xterm.js (`electron/main/terminal.ts`, `PreviewPanel/tabs/terminal/ShellTerminal.tsx`), one terminal per project dir.

### 2.4 Scheduling / automation

Real, DB-backed scheduler in `server/`:

- **Models**: `Trigger` (type=schedule/slack/webhook, cron expression, next_run_at, status, max_executions_per_hour/day) + `TriggerExecution` (status pending/running/succeeded/missed/failed) (`server/app/model/trigger/`).
- **Celery beat** → `poll_trigger_schedules` shared task (`trigger_schedule_task.py:41-53`) → `TriggerScheduleService.poll_and_execute_due_triggers` — batch-polls DB for `next_run_at <= now` (limit 100, `MAX_DISPATCH_PER_TICK` circuit breaker) (`trigger_schedule_service.py:52-84,287-341`).
- **Cron parsing via `croniter`** (`trigger_schedule_service.py:18,119-121`); next-run computed and persisted after each dispatch (`trigger_schedule_service.py:169-179`); single-execution triggers auto-deactivate (`:181-186`); expired schedules marked completed (`:343-391`).
- **Rate limits**: per-trigger hourly/daily caps enforced before dispatch (`trigger_utils.py:36-95`).
- **Execution handoff**: dispatch creates an execution record + **Redis pub/sub event** (`redis_manager.publish_execution_event`) — the **client is told to execute the task** (execution_created event with task_prompt) rather than the server running it (`trigger_schedule_service.py:205-234`).
- **Timeout enforcement**: `check_execution_timeouts` marks pending→`missed` after 60s, running→`failed` after 600s (`trigger_schedule_task.py:35-36,56-151`).
- UI: full Trigger manager (`components/Trigger/` — TriggerDialog, SchedulePicker, ExecutionLogs, DynamicTriggerConfig per app type).

### 2.5 MCP / connectors

- Config file `~/.eigent/mcp.json` in **Claude-Code-compatible `{mcpServers: {...}}` format** (`service/mcp_config.py:21-22,56-105`); CRUD API in `mcp_controller.py` (list/install/remove/update).
- At run time CAMEL `MCPToolkit(config_dict).connect()` loads every server's tools as CAMEL FunctionTools (`agent/tools.py:167-193`), with a shared auth dir (`MCP_REMOTE_CONFIG_DIR=~/.mcp-auth`) to persist remote-MCP auth across tasks (`tools.py:157-165`).
- A dedicated **`mcp_agent` factory** + `McpSearchToolkit` (`factory/mcp.py`); per-server allowlists enforced by the "hands" layer (`tools.py:140-153`).
- Plus 40+ built-in toolkits (Google Workspace, Notion, Slack, GitHub, excel, pptx, RAG/qdrant, craw4ai browser, markitdown, thinking...).

### 2.6 Permission / approval UX

- **"Hands" capability layer** (`backend/app/hands/`): every tool execution is gated by capability interfaces — e.g. `SandboxHands` allows terminal (with allowlist at toolkit layer), filesystem **only inside the workspace root**, MCP only from an allowlist, **no browser** (`hands/sandbox_hands.py:26-60`). `FullHands`/`RemoteHands` scale that up. This is the "sandbox/limits" model.
- **Interactive confirmation**: `question_confirm` agent factory + `ask` SSE event — the agent asks the user mid-run and the UI renders a confirmation dialog (`chat_service.py:821` sends `confirmed` payload; `factory/question_confirm.py`). User answer is fed back into the loop.
- Desktop permissions: electron `session`/partition isolation for browser webviews, subscription auth via OAuth PKCE (`electron/main/subscriptionAuth/`).

### 2.7 What's missing vs real Cowork

- No VM sandbox (hands layer is a best-effort capability gate, not OS isolation)
- No true agent-session resume across backend restarts for the chat loop (TaskLock is in-memory; runs are serialized per project)
- Scheduling executes *via client* — if the desktop is off, triggers just time out to `missed`
- No plugin marketplace / skill sharing (roadmap lists context engineering, RL envs, multi-agent fixes)
- Artifact preview is file-view only — no live localhost HTML auto-preview of running dev servers (browser tab is manual)

---

## 3. different-ai/openwork (21.3k★)

Stack: **pnpm monorepo; Electron desktop + React UI (`ai` SDK 6, Vite) + local Node HTTP server ("the runtime") + opencode as the embedded agent engine + cloud control plane ("Den")**. Most production-hardened of the three (23 CI workflows, evals, e2e suites).

### 3.1 Repo layout

```
openwork/
├── apps/desktop/electron/       # main.mjs (2,661), automation-runner.mjs, ui-control-server.mjs,
│                                # computer-use.mjs, browser-panel.mjs, remote-workspace.mjs,
│                                # workspace-store.mjs, connect-link.mjs, updater.mjs
├── apps/app/src/                # React UI: react-app/domains/session/artifacts/ (preview, open-target, artifact-panel...)
│   └── lib/artifacts.ts         # artifact detection from messages
├── apps/server/src/             # local runtime server
│   ├── managed-opencode.ts      # spawns `opencode serve` child
│   ├── embedded.ts              # in-process embed entry (config + spawn + start)
│   ├── routes/{sessions,files,workspaces,operations,core,mcp,cloud-mcp,registry}.ts
│   ├── mcp.ts / skills.ts / plugins.ts / reload-watcher.ts / opencode-db.ts
├── packages/automations/src/    # pure scheduling domain: schedule.ts, engine.ts, tick.ts, state.ts
├── packages/enterprise-mcp-client/  # MCP client for other agents
├── .opencode/skills/            # 50 skills shipped in the repo
└── ee/                          # enterprise edition
```

### 3.2 Agent runtime wiring

- **Agent engine = opencode, spawned as a child process**: `createManagedOpencodeServer` runs `opencode serve --hostname 127.0.0.1 --port <free> --cors *` with **random per-run username/password** injected via `OPENCODE_SERVER_USERNAME/PASSWORD` env (`managed-opencode.ts:70-96`); waits for stdout line `opencode server listening on <url>` (`managed-opencode.ts:136-144`); teardown SIGTERM → 1s → SIGKILL (`managed-opencode.ts:103-121`).
- **Config sync to the engine**: OpenWork writes an opencode config file and points the child at it with `OPENCODE_CONFIG=<path>` (`embedded.ts:141-162`); a `reload-watcher` keeps config fresh; `syncAllWorkspacesRuntimeMcpToEngine` pushes workspace MCPs into the running engine (`embedded.ts:200-202`).
- **Driving the agent**: `routes/sessions.ts` uses the official `@opencode-ai/sdk/v2/client` — `opencode.session.create({title})`, `opencode.session.promptAsync({sessionID, parts:[{type:'text',text}]})`, `session.get`, `session.messages` (`routes/sessions.ts:104-131,135-180`).
- **UI reads state by polling snapshots**, not SSE from the agent: `/session/:id/snapshot?limit=200` → `buildSessionSnapshot` read model (`routes/sessions.ts:169-184`; `session-read-model.ts`). Messages, todos, statuses fetched in parallel.
- **No session-in-memory problem**: sessions live in the opencode process; the OpenWork server proxies and adds its own DB (`opencode-db.ts`).

### 3.3 Artifact / result rendering (the most sophisticated of the three)

- **`deriveOpenTargets(messages)`** (`apps/app/src/lib/artifacts.ts`) — derives "open targets" (files + URLs) from a conversation with a **confidence-scored heuristic pipeline**:
  1. Regex scanning of assistant text: markdown links, URLs (http/ws), file paths (`FILE_PATTERN`) — files only scanned when the text mentions artifact keywords (`artifact|created|deck|saved|generated|wrote...`, `artifacts.ts:26-27`).
  2. **Tool-call metadata**: write tools (`write/edit/apply_patch/multi_edit/str_replace_editor/patch`) — extracts `path/file/filePath` keys from input+output (`artifacts.ts:30-33,210-238`); parses `*** Add File: x` / `*** Move to: y` from patch text (`artifacts.ts:236-259`).
  3. Chat attachments: `file://` URLs on message file parts → workspace-relative paths (`artifacts.ts:88-97`).
  4. Confidence: attachment 95, write-tool 95, assistant text 65, user text 40; dedup by `id:file:<lowercased path>` keeping max confidence (`artifacts.ts:160-167,313-322`).
  5. **Extension → preview kind classification**: `.md/.markdown/.mdx`→markdown, `.csv/.xlsx/.ods`→sheet, `.ppt*/.key`→slides, `.docx`→document, images→image, `.pdf`→pdf, `.html`→html, code/yml/json→text, else external (`artifacts.ts:54-64`).
- **Preview renderers** (`artifacts/preview.tsx`): Markdown via `MarkdownBlock`; **HTML in sandboxed iframe `srcDoc`** (`sandbox="allow-scripts allow-same-origin"`); PDF via `<embed type="application/pdf">` (comment: Chromium's built-in viewer renders via embed, object/iframe show blank) (`preview.tsx:60-79`); images; plain text.
- **File serving with security**: `routes/files.ts` — workspace-relative path normalization with **traversal protection** (`normalizeWorkspaceRelativePath`), inbox/outbox dirs per workspace (`.opencode/openwork/inbox`, `outbox`), file "sessions" with TTL (30s–24h) and 5MB cap (`routes/files.ts:17-25,49-107`).
- Localhost dev-server URLs are recognized as openable browser targets (`artifacts.ts:186-189`).

### 3.4 Scheduling / automation

- **`packages/automations`** — a *pure domain* engine (deliberately infra-free):
  - `schedule.ts`: once/daily/weekly schedules in a **named IANA timezone**; occurrence calculation with **DST handling** — resolves wall-clock time by searching ±18h around nominal time and returns the *shifted* minute with a warning (`schedule.ts:78-100,158-163`); `recoverableAutomationOccurrence` replays **only the latest missed occurrence**, never backlog (`schedule.ts:194-202`).
  - `engine.ts` (240 lines): lifecycle state machine, **revision digests** (config change = new revision), idempotency via **admission keys** persisted by the caller before events are observed, contiguous sequence cursors — survives process restart (`README.md`: "retrying that key must return the same persistence-safe receipt").
- **Desktop execution** (`apps/desktop/electron/automation-runner.mjs`): the desktop is a **lease-holding worker for the cloud scheduler**, not a scheduler itself:
  - SSE connection to Den `/v1/automation-runners/events` with bearer token + `Last-Event-ID` resume (`automation-runner.mjs:243-260`).
  - Reconcile loop: GET `/v1/automation-runner/work` → POST claim → run → heartbeats every 10s (cancel/lease-loss → abort) → event stream (user/assistant/usage/terminal, each sequence-numbered) → complete (`automation-runner.mjs:140-215`).
  - Executes an assignment by **creating a session in the local runtime** (`POST /workspace/:id/sessions` with prompt+model) and **polling snapshot** until `status.type === 'idle'` with an assistant result (`automation-runner.mjs:66-118`).

### 3.5 MCP / skills

- **Skills** (`apps/server/src/skills.ts`): SKILL.md with frontmatter (`name`, `description`, `trigger` or "## When to use" body); discovery walks **up to the repo root** (`.git` boundary) per workspace (`skills.ts:10-23`) plus global dirs, incl. `skills/<domain>/<name>/SKILL.md` convention (`skills.ts:62-88`); validation of name/description; skill list API for UI.
- **MCP** (`apps/server/src/mcp.ts`, 714 lines): passive inventory, engine sync (workspace MCPs pushed into opencode via runtime config), remote-connect, OAuth flow support (`mcp.oauth-flow.e2e.test.ts`), health checks.
- **OpenWork MCP server** exposes `search_capabilities` + `execute_capability` so Claude Code/Codex/etc. can drive the same skills/MCPs/connectors (from README).

### 3.6 Permission / approval UX

- Server-side **`requireApproval`** middleware on sensitive routes with `ApprovalRequest` records (`routes/files.ts:44-48`; `approvals.ts`), token scopes (`TokenScope`), audit trail (`audit.ts`), authorized-folders e2e tests.
- `ui-control-server.mjs`: loopback HTTP bridge with **random bearer token**, exposing `/snapshot /actions /execute` + semantic `/context /query /command` that execute JavaScript in the renderer (`ui-control-server.mjs:1-60`) — the "computer use" surface (`computer-use.mjs`).
- `connect-link` keypair-based auth for desktop↔Den; `desktop-app-policies.md` (enterprise desktop policy controls).

### 3.7 What's missing vs real Cowork

- No sandbox/VM for the agent (agent runs with host privileges in the workspace dir)
- Desktop is a *client* of a cloud scheduler — offline machines miss runs by design
- Artifacts are file/URL-based; no in-chat rich artifact canvas (sheet/slide editors are minimal)
- Multi-agent/workforce orchestration not present (single opencode session per thread)

---

## 4. Other clones (GitHub API search, sorted by stars)

| Repo | Stars | Stack |
|---|---|---|
| anthropics/knowledge-work-plugins | 23.3k | Official Anthropic plugin repo (plugins = skill packages for Cowork/Code) |
| different-ai/openwork | 21.3k | Electron + React + opencode engine + Node runtime + cloud Den (see §3) |
| eigent-ai/eigent | 14.8k | Electron + React + FastAPI + CAMEL multi-agent + Postgres/Redis/Celery (see §2) |
| composio-community/open-claude-cowork | 4.3k | Electron + Express + Claude Agent SDK/opencode + Composio MCP (see §1) |
| DevAgentForge/Open-Claude-Cowork | 3.4k | Electron + React 19 + Tailwind 4 + **Claude Agent SDK** + Radix |
| OpenCoworkAI/open-cowork | 2.0k | Electron + React + **`pi-coding-agent` embedded agent core** + react-markdown, electron-updater, i18next |
| kuse-ai/kuse_cowork | 751 | **Tauri 2 + SolidJS** + tauri fs/shell/store/dialog plugins (Rust backend) |
| AIDotNet/OpenCowork | 599 | Windows/macOS/Linux desktop (per README) |
| AFK-surf/OpenBridge | 419 | Open agent for everything (Cowork+Codex alternative) |
| johnzfitch/claude-cowork-linux | 406 | Reverse-engineered **real Cowork**: stubs `@ant/claude-swift`/`@ant/claude-native`, runs Claude Code binary directly, path translation, macOS header spoofing |
| caiqinghua/Open-Claude-Cowork | 284 | Cowork UI with GLM-4.7/MiniMax M2.1 |
| PM-Shawn/Abu-Cowork | 264 | local-first AI agent desktop, multi-mode |

Key takeaways: **Electron dominates** (only kuse uses Tauri); agent cores are either the **Claude Agent SDK** (in-process) or **opencode** (spawned server); nobody ships a VM sandbox; official plugin ecosystem = skill packages, not app code.

---

## 5. Recommended clone architecture

### 5.1 Stack recommendation

```text
Desktop shell:   Electron (main + preload + contextIsolation)      [evidence: all 3 clones]
UI:              React 19 + Tailwind (or SolidJS)                  [eigent, openwork; kuse: Solid]
Agent engine:    TWO providers behind one interface, like OCC:
                   - Claude Agent SDK (in-process, TypeScript)     [OCC claude-provider.js]
                   - opencode spawned via `serve` + @opencode-ai/sdk [OCC, openwork]
Local runtime:   Node HTTP/SSE server (Express or plain node:http) [OCC :3001, openwork embedded]
Sessions store:  SQLite (better-sqlite3) — NOT localStorage/memory [gap fixed vs OCC]
Scheduling:      croniter/Croner + JSON-or-SQLite jobs + boot recovery [OCC cron.js, eigent croniter]
Cron MCP:        in-process MCP server via createSdkMcpServer      [OCC cron.js]
Skills:          SKILL.md scanner (frontmatter name/description/trigger, repo-root walk) [openwork skills.ts]
MCP:             ~/.<app>/mcp.json (Claude-compatible) + CRUD + CAMEL-style MCPToolkit or SDK mcpServers [eigent, OCC]
Artifacts:       message+tool-call scanner → preview registry       [openwork deriveOpenTargets]
Previews:        iframe srcDoc (sandbox), <embed> PDF, mammoth/xlsx converters [openwork, eigent fileReader]
Browser panel:   Electron WebContentsView per session + partition isolation [eigent webview.ts]
Terminal:        node-pty + xterm.js                              [eigent terminal.ts]
Permissions:     canUseTool callback → modal (allow/deny/always) + capability "hands" layer [openclaw runner.js, eigent hands/]
```

### 5.2 Component list

1. **Desktop shell** — window, IPC bridge (preload contextBridge), native menu, tray, devtools guard; spawns/owns the runtime server child.
2. **Runtime server (Node)** — REST + SSE endpoints (`/api/chat`, `/api/abort`, `/api/sessions`, `/api/providers`, `/api/mcp`, `/api/skills`, `/api/triggers`, `/api/files`); 15s SSE heartbeat; 60-min idle timeout.
3. **Provider layer** — `BaseProvider` with `async *query()` yielding a normalized chunk vocabulary: `session_init | text | reasoning | tool_use | tool_result | done | aborted | error`. ClaudeProvider (resume via session_id from `system/init` chunk) and OpencodeProvider (session.create + event.subscribe + text-delta tracking).
4. **Session store** — SQLite: chats, messages (raw + rendered), toolCalls, todos, provider/model; agent session ids mapped to chats; restore on boot.
5. **Artifact engine** — watch workspace dirs (chokidar) + scan message parts (openwork's `deriveOpenTargets` heuristics) → artifact registry (path, kind, confidence) → preview tabs (markdown/html/pdf/image/sheet) + open-in-browser for localhost URLs.
6. **Skill system** — scan `.claude/skills` + workspace `.opencode` skills; validate frontmatter; inject via `settingSources:['user','project']` or OPENCODE_CONFIG file.
7. **MCP manager** — config CRUD, in-process servers (`createSdkMcpServer`), remote HTTP (Composio-style), tool whitelisting, auth dir persistence.
8. **Scheduler** — cron/once/recurring jobs in SQLite + file; croniter/Croner parsing; tick loop; **boot recovery** (re-arm from store); DST-safe wall-clock resolution (openwork's ±18h search); execution dispatch → new agent turn (invokeAgent flag).
9. **Permission layer** — `canUseTool` → renderer modal (approve/deny/always-allow for session), timeout = deny; capability gating ("hands": workspace-root fs confinement, MCP allowlist, terminal command allowlist).
10. **Browser panel** — isolated WebContentsView, hidden-bounds management, CDP screenshot capture.
11. **Terminal panel** — node-pty + xterm, cwd = project dir.
12. **Memory** (Kimi-like) — MEMORY.md + daily logs injected into system prompt (openclaw's design).

### 5.3 The 5 hardest parts (with evidence)

1. **Session/streaming protocol correctness.** Everything downstream depends on a stable chunk vocabulary and resume semantics. OCC had to hand-normalize Claude SDK chunks (`claude-provider.js:100-172`) AND hand-roll delta tracking + dedupe for opencode events (`opencode-provider.js:220-296`); eigent needed a 2,900-line service to emit its typed event zoo (`end/task_state/ask/...`) and explicit rules for SSE-close-as-cancel vs. preserve (`chat_controller.py:295-311`); openwork sidestepped streaming by **polling snapshots** with idempotent read models (`routes/sessions.ts:169-184`). → Build the normalized chunk contract first (I/O-first), keep a 15s heartbeat + idle timeout, persist session ids.

2. **Artifact detection and preview fidelity.** No clone uses an artifact protocol like real Cowork; all infer artifacts from text/tool-call side effects. openwork is the reference: confidence-scored scanning of markdown links/URLs/paths, write-tool metadata + `*** Add File:` patch parsing, attachment file:// URLs, extension→preview-kind map (`artifacts.ts`). Rendering pitfalls: PDFs must use `<embed>` not sandboxed iframe (openwork comment, `preview.tsx:75-78`); office formats need conversion in the privileged process (eigent `fileReader.ts` mammoth/xlsx/pptx→HTML); HTML needs sandboxed srcDoc; localhost dev-server URLs are the top artifact case (openwork `isLocalhostBrowserTarget`).

3. **Permission / approval UX that doesn't break flow.** Real Cowork gates actions in a sandboxed VM; clones fake it with callbacks. openclaw's `canUseTool` → "Y/N" chat prompt with **timeout-deny** (`runner.js:185-264`), eigent's "hands" capability gates + `ask` confirm agent, and openwork's `requireApproval` middleware + token scopes are the three viable models. The hard parts: interruption mid-stream (abort + resume), AskUserQuestion-style structured prompts, per-session "always allow", and capability *reporting* to the model so it avoids denied tools.

4. **Scheduling with timezone/DST/recovery correctness.** openwork's pure engine is the gold standard: named timezone, ±18h wall-clock search around DST transitions with "shifted" warnings, revision digests, admission keys + idempotent receipts, sequence cursors, replay-only-latest-missed (`schedule.ts`, `engine.ts`). eigent shows the production variant: DB-persisted triggers, croniter, rate limits, dispatch circuit breakers, execution timeouts (pending 60s/running 600s), client-executes-on-redis-event (`trigger_schedule_*`). OCC shows the minimal variant: JSON file + setTimeout chain + boot reload. → Ship file/DB persistence + boot recovery + missed-run policy from day one; DST as a follow-up.

5. **Agent process lifecycle & config reconciliation.** The engine is a long-lived child with its own config file, auth, and health. openwork: free-port selection, random serve credentials, stdout URL handshake with 15s timeout, SIGTERM→SIGKILL teardown, OPENCODE_CONFIG file kept fresh by a reload watcher, trusted-process registration, config→engine sync (`managed-opencode.ts`, `embedded.ts`, `reload-watcher.ts`). eigent: Electron spawns/restarts uvicorn, CDP browser pool, backend port management (`electron/main/init.ts`). OCC: server is a separate manual process (weakest). → The runtime must own the engine: spawn, health-check, restart, and config hot-reload.

### 5.4 Gaps every serious clone must still build (nobody has solved)

- **OS-level sandboxing** for agent tool execution (real Cowork's Linux-VM isolation; clones only gate capabilities).
- **True workspace isolation + "folder you point at" UX** (eigent's frozen-dirs snapshot is the closest).
- **Plugin/skill marketplace** (real Cowork has Anthropic's plugin ecosystem: `knowledge-work-plugins`, `claude-plugins-community`; openwork ships marketplace infra but it's cloud-gated).
- **Offline scheduling** (desktop-owned cron that survives closed apps / sleep).
- **Cross-session context reuse** (Kimi's "projects share context" — only openclaw's memory files approximate this).
