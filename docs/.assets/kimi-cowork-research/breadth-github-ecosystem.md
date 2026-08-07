# Breadth Scan (Stage 1): GitHub Repos + Open-Source Ecosystem — Claude Cowork vs Kimi Work

**Topic:** Architecture & feature surface of Anthropic's **Claude Cowork** and Moonshot AI's **Kimi Work**, from the GitHub/ecosystem angle, for building a from-scratch clone.
**Agent angle:** GITHUB REPOS + ECOSYSTEM / OPEN-SOURCE COMPONENTS
**Date:** 2026-08-06
**Status:** Complete (DuckDuckGo HTML was bot-blocked mid-session; all findings sourced directly from GitHub API/raw + official docs sites)

---

## 0. Executive summary

- **Kimi Work's agent kernel is open source**: `MoonshotAI/kimi-code` (MIT, 6.1k stars) is a full TypeScript monorepo (agent loop, TUI, MCP client, plugin marketplace, cron scheduler, ACP adapter, local web server). The **scheduled-task system (CronCreate/CronList/CronDelete) is fully documented** — this is the single best spec source for dimension 2.
- **Claude Cowork's plugin format is open source**: `anthropics/knowledge-work-plugins` (Apache-2.0, 23.3k stars) defines the exact Cowork plugin structure (`.claude-plugin/plugin.json` manifest + `.mcp.json` connectors + `commands/` + `skills/`), plus a marketplace.json listing **93 plugins incl. connector names** (Slack, Notion, Asana, Linear, Jira, HubSpot, Canva, Figma, Snowflake, BigQuery, etc.).
- **OpenClaw** (openclaw/openclaw, ~385k stars, TypeScript, MIT-ish) is the plugin host in Kimi's ecosystem ("the lobster way"): full plugin SDK (`openclaw/plugin-sdk/*` subpaths, TypeBox schemas, `openclaw.plugin.json` manifests), ClawHub registry (clawhub.ai), a sophisticated sandbox system (docker/podman/ssh/openshell backends, workspaceAccess ro/rw, bind mounts with blocked paths), and a **built-in scheduler** (`openclaw automations` CLI, SQLite-persisted, croner parsing, webhooks, Gmail PubSub triggers).
- **Multiple open-source Cowork clones exist and are popular**: `different-ai/openwork` (21.2k stars, powered by opencode), `eigent-ai/eigent` (14.8k, Apache-2.0, Electron desktop), `composio-community/open-claude-cowork` (4.3k, Electron + Claude Agent SDK + Composio Tool Router, 500+ integrations, includes cron scheduling in its companion bot "Clawdbot"), `DevAgentForge/Open-Claude-Cowork` (3.4k).
- The user-specified clone project `akashgit/i-want-build-clone` ("RH Co-work", created 2026-08-06) exists but is **scaffold-level** (FastAPI + React 19 + Postgres, 0 stars, 19 issues).

---

## 1. Live artifacts (dimension 1)

### Key findings
- **kimi-code (Kimi Work's kernel) is a terminal/web agent, not an artifacts-first product.** The "artifact" surface lives in the local web app: `kimi web` runs a local REST+WebSocket server + web UI from one process; `GET /openapi.json` (REST OpenAPI) and `GET /asyncapi.json` (WebSocket AsyncAPI) describe the API. Default port 58627 (auto-increment on busy), bearer-token auth via `~/.kimi-code/server.token`, instances registered under `~/.kimi-code/server/instances/`. `kimi web rotate-token` regenerates the token. URL: https://moonshotai.github.io/kimi-code/en/reference/kimi-command
- **`kimi vis`** is a session visualizer: in-process server that renders a session as it unfolds, in the browser (`kimi vis [sessionId] --port --host --no-open`).
- **`kimi export <sessionId> -o out.zip`** packages a session directory into a ZIP (the session dir is the artifact store; the global log `~/.kimi-code/logs/kimi-code.log` is included by default).
- **Media artifacts**: `ReadMediaFile` tool ingests images/videos (≤100 MB) as multimodal model input with compression to model limits — a "video input" artifact path (screen recordings → LUT/code). `kimi-webbridge` plugin = real browser control ("Control your real browser from Kimi Code") — the closest thing to rendered artifact interaction in the kernel.
- **kimi-code monorepo packages relevant to artifact/state plumbing**: `packages/transcript` (session transcript model), `packages/minidb` (embedded DB — likely session/state store), `packages/telemetry`, `packages/protocol`, `packages/pi-tui` (TUI, forked from earendil-works/pi-mono), `packages/kaos` + `packages/kosong` (OS abstraction / LLM abstraction layers).
- **Cowork side**: `anthropics/knowledge-work-plugins` includes a `pdf-viewer` plugin and `design` category — artifact-type plugins are file-based skills. `anthropics/claude-desktop-buddy` (C++, 2.5k stars) is a Bluetooth-device reference app "for makers in Claude Cowork & Claude Code Desktop" — evidence of device-local (companion app) artifact surface. No open spec for Cowork's artifact rendering model found in OSS.
- OpenClaw "companion apps and nodes" add Canvas, camera, screen, voice on device (docs.openclaw.ai/platforms) — an artifacts-like surface for the Kimi-side host.
- RH Co-work clone: no artifact code yet (backend is scaffold).

### Citations
- https://moonshotai.github.io/kimi-code/en/reference/kimi-command (kimi web, kimi vis, kimi export)
- https://github.com/MoonshotAI/kimi-code/tree/main/packages (transcript, minidb, pi-tui, kaos, kosong)
- https://raw.githubusercontent.com/MoonshotAI/kimi-code/main/plugins/marketplace.json (kimi-webbridge v1.11.3)
- https://github.com/anthropics/knowledge-work-plugins (pdf-viewer/, design/)
- https://github.com/anthropics/claude-desktop-buddy

### Gaps / surprises
- **Gap:** No open-source repo documents Cowork's live artifact rendering (HTML previews, image generation panels, PPT/Excel builders). Assume proprietary desktop UI layer; clones (eigent, openwork) implement their own previews — verify in Stage 2 by reading `eigent-ai/eigent` and `different-ai/openwork` trees.
- **Surprise:** kimi-code exposes a full local HTTP+WS API (`kimi web`) — a clone can reuse this API shape for a web artifact UI without building a TUI.

---

## 2. Scheduled tasks (dimension 2) — richest dimension, two complete open implementations

### 2a. kimi-code (Kimi Work kernel) — CronCreate / CronList / CronDelete
Documented at https://moonshotai.github.io/kimi-code/en/reference/tools (Built-in Tools, "Scheduled Tasks"):
- **CronCreate**: params `cron` (standard **5-field cron** `minute hour day-of-month month day-of-week`, local timezone), `prompt` (≤8 KB, injected into session on fire), `recurring` (bool; `false` = one-shot, auto-deletes after firing). Returns `id` (8-hex-digit), `humanSchedule` ("every 5 minutes"), `nextFireAt` (ISO).
- **CronList**: read-only; returns per task: `id, cron, humanSchedule, nextFireAt, recurring, ageDays, stale` (sorted by schedule time, records separated by `---`).
- **CronDelete**: cancels; blocked in Plan mode.
- **Semantics**: schedules are **session-bound** (survive `kimi --session` resume, NOT carried into a new session); max **50 active scheduled tasks per session**; kill switch env `KIMI_DISABLE_CRON=1`.
- **Anti-thundering-herd jitter**: recurring tasks shifted by `min(10% of period, 15 min)`; one-time tasks landing exactly on `:00`/`:30` shifted ≤90 s.
- **Coalescing**: if several fire times were missed (laptop sleep), fires **once on wake** with a `<cron-fire>` envelope carrying `coalescedCount`.
- **Staleness**: recurring tasks alive >7 days fire one final time with `stale="true"` then auto-delete.
- **Approval**: CronCreate/CronDelete require user approval by default; CronList auto-allowed. (Consistent with the unified approval model: read-only tools auto-allow, write/exec require approval.)

### 2b. OpenClaw (Kimi's plugin host) — "Automations" built-in scheduler
Documented at https://docs.openclaw.ai/automation/cron-jobs and https://docs.openclaw.ai/cli/cron:
- **CLI**: `openclaw automations <add|create|list|get|show|enable|disable|edit|run|runs|remove>` (`openclaw cron` is an alias).
- **Schedule kinds**: `--at` (ISO or relative `20m`), `--every` (fixed interval), `--cron` (5- or 6-field, `--tz` IANA), `--on-exit` (event trigger when a watched command exits), `--stream-command` (fire from batched lines of a supervised long-lived command; `--stream-mode line|match`, `--stream-batch-ms`, `--stream-match` regex).
- **Persistence**: job definitions, runtime state, run history persist in **shared SQLite state DB** — survives restarts; runs execute **inside the Gateway process**, not the model.
- **Payloads**: `--system-event` (main-session enqueue, no model call), `--message` (model-backed agent turn; sessions `main|isolated|current|session:<id>`), `--command`/`--command-argv` (shell on Gateway host, no model), `--script` (headless code-mode script with the agent's tools, timeout 300 s cap 900 s, tool budget 50/200).
- **Cron parsing**: `croner` (https://github.com/Hexagon/croner); day-of-month/day-of-week use OR logic (Vixie style); `+` modifier for AND.
- **Condition triggers** ("event watchers"): headless script per evaluation returns `{fire, message?, state?}`; state persisted (16 KB cap); dedup via `trigger.state`; min interval 30 s; **full tool policy incl. exec runs unattended** — gated behind `cron.triggers.enabled` (explicitly a security surface).
- **Reliability**: watchdog timeouts per phase; run-level failure → error counters; auto-disable after **10 consecutive execution failures** or 3 schedule-computation errors; failure alerts (per-job or global, channel delivery); SSRF-guarded webhook delivery (`cron.webhookSsrfPolicy`); one-shot auto-delete after success (`--keep-after-run` to retain); overdue isolated jobs rescheduled on Gateway startup, not replayed.
- **Dynamic cadence**: `pacing.min/max` + the agent tool `automations(action:"next_check", in:"30m")` lets a job reschedule itself within bounds.
- **Chat loop**: `/loop [interval] <prompt>` owner-only slash command creates conversation-bound recurring jobs; `/loop status`, `/loop stop`.
- **External triggers**: HTTP webhooks (`POST /hooks/wake`, `/hooks/agent`, mapped `/hooks/<name>`; bearer token; 15 s admission contract; 200/400/409/502/503) and **Gmail PubSub** integration (`openclaw webhooks gmail setup`) with a recommended restricted reader-agent pattern.
- **Migration**: legacy heartbeat `tasks:` blocks auto-migrate via `openclaw doctor --fix`.

### 2c. Clones with scheduling
- **composio-community/open-claude-cowork** — "Secure Clawdbot" companion: **"Scheduling — natural language reminders and cron jobs"** in README feature list (plus browser automation and persistent memory).
- **eigent-ai/eigent** (14.8k stars) — desktop Cowork alternative; scheduler presence unknown at breadth stage (verify repo tree in Stage 2).
- **RH Co-work clone** — unknown (scaffold); has `eval/` harness only.

### Citations
- https://moonshotai.github.io/kimi-code/en/reference/tools (CronCreate/CronList/CronDelete full semantics)
- https://docs.openclaw.ai/automation/cron-jobs (full automations spec)
- https://github.com/composio-community/open-claude-cowork (README features)
- https://github.com/Hexagon/croner

### Gaps / surprises
- **Surprise:** Kimi Work's scheduled tasks are implemented as *session re-injection* (cron fires a prompt into an existing session) — not a standalone job runner. OpenClaw's automations are the standalone counterpart (SQLite + Gateway-owned). A clone can choose either model.
- **Gap:** No public spec for Cowork's own "scheduled tasks" (Claude Desktop scheduled tasks feature); check claude.com product docs in another stage.

---

## 3. Local files (dimension 3)

### 3a. kimi-code — file tools + permission model
From https://moonshotai.github.io/kimi-code/en/reference/tools (Built-in Tools):
- **File tools**: `Read` (path, line_offset, n_lines; ≤1000 lines/100 KB per call), `Write` (path, content, mode overwrite|append; auto-creates parents), `Edit` (old_string/new_string, `replace_all` for duplicates), `Grep` (ripgrep-backed; `files_with_matches|content|count_matches`; offset+head_limit pagination; **sensitive files (`.env`, private keys) auto-filtered**; `include_ignored` opts into .gitignore'd files), `Glob` (respects .gitignore/.ignore/.rgignore; 100-entry cap; brace patterns), `ReadMediaFile` (images/video ≤100 MB, multimodal).
- **Unified approval model (dimension-critical)**: read-only tools (Read, Grep, Glob, ReadMediaFile, WebSearch, FetchURL) **auto-allowed by default**; write/execution tools (Write, Edit, Bash, TaskStop, CronCreate, CronDelete, AgentSwarm outside swarm mode) **require approval by default**. `--yolo`/`-y` skips regular approvals; `--auto` auto-approves and never asks; Plan mode only restricts Write/Edit to the plan file and blocks TaskStop. `Bash` is always the highest-permission tool. Flag conflicts: `--yolo`/`--auto` mutually exclusive; `-p` uses auto perms.
- **Bash**: foreground timeout 60 s (max 5 min), timeout auto-backgrounds (600 s default bg timeout, configurable `bash_task_timeout_s`); background tasks get IDs, notify on completion, stdin always closed, two-phase termination SIGTERM→5 s→SIGKILL; on Windows uses bundled Git Bash (`KIMI_SHELL_PATH`).
- **Sandboxing: none in kimi-code.** No container/VM isolation — trust boundary is the approval prompt + deny rules + sensitive-file filtering. (Kimi's sandboxing lives in the OpenClaw host, see below.)
- **Extra workspace dirs**: `kimi --add-dir <dir>` mounts additional workspace dirs per session.
- **Lifecycle hooks**: local commands at key points to gate risky tool calls ("run local commands at key points to gate risky tool calls, audit decisions") — the gate mechanism instead of sandboxing.

### 3b. OpenClaw — full sandbox system (docs.openclaw.ai/gateway/sandboxing)
- **Config**: `agents.defaults.sandbox.{mode, scope, backend}` — mode `off|non-main|all` (default off; main session key `agent:<id>:main`), scope `agent|session|shared`, backend `docker|podman|ssh|openshell` (default docker).
- **Sandboxed tools**: `exec, read, write, edit, apply_patch, process`; the Gateway itself always stays on host; `tools.elevated` is the explicit escape hatch.
- **Docker backend defaults**: image `openclaw-sandbox:bookworm-slim` (built via `scripts/sandbox-setup.sh`, Dockerfile at `scripts/docker/sandbox/Dockerfile`), `network:"none"` (no egress), `readOnlyRoot:true`, `capDrop:["ALL"]`, init process + no-new-privileges; workspace mounted read-only at `/agent` (ro) or `/workspace` (rw) depending on `workspaceAccess` (`none|ro|rw`; default none → isolated sandbox workspace under `~/.openclaw/sandboxes`); tmpfs `/tmp /var/tmp /run`; `setupCommand` runs once per container; GPU passthrough via `docker.gpus`.
- **Bind mounts** `host:container:ro|rw` with **hard security defaults**: blocks system paths, Docker socket dirs, and credential roots `~/.aws ~/.cargo ~/.config ~/.docker ~/.gnupg ~/.netrc ~/.npm ~/.ssh`; symlink-parent escape checks; external sources and reserved targets need explicit `dangerouslyAllow*` flags; `network:"host"` and `container:<id>` namespace joins blocked by default.
- **SSH backend**: any SSH host; seeds remote workspace once from local; no auto sync-back; auth via identityFile or SecretRef data.
- **OpenShell backend**: managed remote sandbox; `mode: mirror` (sync in/out per turn) or `remote` (seed once).
- **Sandboxed browser**: separate browser container with CDP, dedicated network `openclaw-sandbox-browser`, noVNC observer with token URL, Chromium hardening flags, `allowHostControl` default false.
- **Ops CLI**: `openclaw sandbox list|explain|recreate|prune`, `openclaw doctor`, `openclaw doctor --fix`.
- **Skills in sandbox**: `read` tool is sandbox-rooted; skills mirrored into sandbox when `workspaceAccess:none`.

### 3c. Clone projects
- **RH Co-work** (akashgit/i-want-build-clone): backend FastAPI + SQLAlchemy 2.0 async + PostgreSQL 13 + Alembic; OpenAI-compatible API (model-agnostic); Podman rootless containers for deploy. File-handling/VM code not present yet.
- **eigent / openwork / composio**: composio runs tools via Composio Tool Router (cloud-side tool execution) — a different file-access model (SaaS integrations rather than local FS).

### Citations
- https://moonshotai.github.io/kimi-code/en/reference/tools (file tools + approvals)
- https://docs.openclaw.ai/gateway/sandboxing
- https://raw.githubusercontent.com/akashgit/i-want-build-clone/main/README.md

### Gaps / surprises
- **Surprise:** Kimi Work's kernel has **no sandbox at all** — permission prompts + hooks are the entire boundary; OpenClaw provides optional containerization. Cowork similarly relies on the desktop app's permission UI (no public sandbox spec).
- **Gap:** No OSS sandbox/VM implementations found inside Cowork clones yet (eigent may embed one — Stage 2).

---

## 4. MCP connectors and CLI tools (dimension 4)

### 4a. kimi-code CLI surface (commands, subcommands, packages)
- **Commands**: `kimi` (interactive TUI; flags `-S/--session`, `-c/--continue`, `-m/--model`, `-p/--prompt`, `--output-format text|stream-json`, `-y/--yolo`, `--auto`, `--plan`, `--skills-dir`, `--agent`, `--agent-file`, `--add-dir`; hidden aliases `-r`, `--yes`, `--auto-approve`).
- **Subcommands**: `kimi login` (RFC 8628 device-code OAuth), `kimi acp` (Agent Client Protocol server over stdio — Zed/JetBrains integration), `kimi web` (local REST+WS server, see §1), `kimi doctor` (validates config.toml/tui.toml under `KIMI_CODE_HOME`), `kimi export`, `kimi migrate` (from legacy kimi-cli), `kimi upgrade`/`kimi update`, `kimi vis`, `kimi provider` (add/remove/list + `provider catalog list|add` against **models.dev** catalog, `KIMI_REGISTRY_API_KEY`).
- **MCP config**: `/mcp-config` — AI-native conversational MCP server add/edit/auth (no hand-editing JSON). MCP servers are also installable as "plugins" with **trust levels surfaced at install**.
- **Plugin system**: `plugins/marketplace.json` (versioned registry, tiers `official|curated`) currently lists: **kimi-datasource** v3.3.0 (data/MCP workflows), **kimi-webbridge** v1.11.3 (browser automation), **superpowers** (obra/superpowers — planning/TDD skills), **vercel-plugin** (vercel/vercel-plugin). Plugin sources can be local dirs or GitHub repos; skills/MCP servers/data sources all installable.
- **Monorepo packages** (all TS, pnpm workspace): `acp-adapter`, `acp-server`, `agent-core-v2`, `agent-core`, `kaos`, `kap-server`, `klient`, `kosong`, `migration-legacy`, `minidb`, `node-sdk`, `oauth`, `pi-tui`, `protocol`, `telemetry`, `transcript`, `tree-sitter-bash`. Related repos: `MoonshotAI/kimi-agent-sdk` (553 stars, TS, Apache-2.0 — "programmatic interface to interact with the Kimi CLI"), `MoonshotAI/kimi-agent-rs` (72 stars, Rust — "Kimi Code CLI Wire mode-compatible agent server"), `MoonshotAI/kimi-cli` (11k stars, Python, Apache-2.0 — legacy CLI, migration source), `MoonshotAI/pykaos` (21 stars — "lightweight OS abstraction layer for agents", sandbox/filesystem topics), `MoonshotAI/kosong` (523 stars — LLM abstraction layer), `MoonshotAI/kimi-code-zed-extension`.

### 4b. OpenClaw plugin SDK + MCP bridging
- **Install**: `openclaw plugins install clawhub:<package>` | `npm-pack:<tarball>` | bare npm (during cutover); `clawhub` CLI publishes (`clawhub package publish org/plugin --dry-run`). Registry: **ClawHub** — https://clawhub.ai, repo `openclaw/clawhub` (9.3k stars, MIT, TypeScript).
- **Plugin shapes**: channel plugin, provider plugin (model/media/search/fetch/speech/realtime), CLI backend plugin (local AI CLIs), tool plugin, hook, media provider, custom Gateway RPC.
- **Format**: npm package + `openclaw.plugin.json` manifest (`id, name, description, contracts.tools, activation.onStartup, configSchema` JSON-schema, `toolMetadata` optional flags) + package.json `openclaw.extensions`, `openclaw.compat.pluginApi`, `minGatewayVersion`; peerDependency `openclaw >= 2026.3.24-beta.2`; TypeScript ESM; TypeBox schemas for parameters.
- **SDK entry points**: `definePluginEntry` from `openclaw/plugin-sdk/plugin-entry`, `defineChannelPluginEntry` from `openclaw/plugin-sdk/core`, plus subpaths `plugin-sdk/runtime-store`, `plugin-sdk/gateway-method-runtime`, `plugin-sdk/sdk-overview`. API surface: `api.registerTool({name,description,parameters,outputSchema,execute})`, `registerAgentToolResultMiddleware`, `registerTrustedToolPolicy`, plugin permission requests (approval after model selection), optional tools via `tools.allow`.
- **MCP**: OpenClaw runs MCP tools Gateway-side and gates them by sandbox tool policy (`tools.sandbox.tools`) — "Plugin and MCP tool access: Gateway-side execution, additionally gated by sandbox tool policy". `openclaw mcp` CLI exists (docs sitemap: /cli/mcp). MCP servers are first-class plugin-type installs, matching Kimi's marketplace model.
- **Ecosystem scale**: `VoltAgent/awesome-openclaw-skills` (51.7k stars — "5,400+ skills filtered from the official OpenClaw Skills Registry"), `hesamsheikh/awesome-openclaw-usecases` (31.7k), `garrytan/gbrain` (27.9k, "Garry's Opinionated OpenClaw/Hermes Agent Brain"), `mengjian-github/openclaw101` (3k, Chinese tutorial). OpenClaw itself: 385k stars, 81k forks, TypeScript, pnpm workspace, npm package `openclaw` (Node 22.22.3+/24.15+/25.9+), install `curl -fsSL https://openclaw.ai/install.sh | bash`, commands `openclaw onboard --install-daemon`, `gateway status`, `dashboard`, `pairing approve`; channels WhatsApp/Telegram/Slack/Discord/Google Chat/Signal/iMessage; built by Peter Steinberger (steipete) + OpenClaw Foundation; sponsors OpenAI/GitHub/NVIDIA/Vercel/Blacksmith/Convex.

### 4c. Claude Cowork connectors — official connector names
From `anthropics/knowledge-work-plugins` (Apache-2.0, 23.3k stars, Python+markdown/JSON, "file-based, no code, no infra"):
- **Plugin structure** (per plugin dir): `.claude-plugin/plugin.json` (manifest; fields observed: `name, version, description, author`), `.mcp.json` (tool/connector connections), `commands/` (slash commands, e.g. `/finance:reconciliation`, `/sales:call-prep`), `skills/` (markdown domain knowledge). Marketplace file: `.claude-plugin/marketplace.json` — keys `{name, owner, plugins}`, **93 plugins**, sources can be `./local`, `{source:"url", url: <git>}`, or `{source:"git-subdir", url, path, ref, sha}`.
- **Install**: from Cowork at claude.com/plugins; from Claude Code: `claude plugin marketplace add anthropics/knowledge-work-plugins` then `claude plugin install sales@knowledge-work-plugins`.
- **11 first-party role plugins** with explicit connector lists:
  - productivity → Slack, Notion, Asana, Linear, Jira, Monday, ClickUp, Microsoft 365
  - sales → Slack, HubSpot, Close, Clay, ZoomInfo, Notion, Jira, Fireflies, M365
  - customer-support → Slack, Intercom, HubSpot, Guru, Jira, Notion, M365
  - product-management → Slack, Linear, Asana, Monday, ClickUp, Jira, Notion, Figma, Amplitude, Pendo, Intercom, Fireflies
  - marketing → Slack, Canva, Figma, HubSpot, Amplitude, Notion, Ahrefs, SimilarWeb, Klaviyo
  - legal → Slack, Box, Egnyte, Jira, M365
  - finance → Snowflake, Databricks, BigQuery, Slack, M365
  - data → Snowflake, Databricks, BigQuery, Definite, Hex, Amplitude, Jira
  - enterprise-search → Slack, Notion, Guru, Jira, Asana, M365
  - bio-research → PubMed, BioRender, bioRxiv, ClinicalTrials.gov, ChEMBL, Synapse, Wiley, Owkin, Open Targets, Benchling
  - cowork-plugin-management → (meta; builds new plugins)
- **Notable marketplace entries** (connector ecosystem evidence): slack-by-salesforce, apollo, zoom, miro, figma (figma/mcp-server-guide), zapier (zapier/zapier-mcp), intercom, box, dropbox, canva, airtable, adobe-for-creativity, sanity, planetscale, prisma, cockroachdb, clickhouse, datadog, grafana-cloud-mcp, tavily, exa, browser-use, desktop-commander (wonderwhy-er/DesktopCommanderMCP), gitkraken, datarobot, qdrant, langfuse, auth0, servicenow-sdk, twilio-developer-kit, wix, monday-crm, cloudinary, brightdata, postiz, sp-global, lseg, carta (×3).
- **Cowork's own Claude Desktop connectors** (gmail/google drive/notion/slack/github) are hosted by Anthropic's desktop app (not OSS); the OSS proxy is the MCP connector model shown above. **GitHub's MCP Registry** (github.com/mcp) is the general catalog.

### 4d. Clones & SDKs
- **composio-community/open-claude-cowork** (4.3k stars, MIT, JavaScript): Electron.js + Node/Express server (port 3001) + **Claude Agent SDK** (platform.claude.com/docs/en/agent-sdk) OR **opencode** as providers, **Composio Tool Router + MCP** for 500+ integrations (Gmail, Slack, GitHub, Google Drive...), SSE streaming, persistent sessions, tool visualization sidebar, skills via `SKILL.md` in `.claude/skills/`. Companion "Secure Clawdbot" (clawd/, node cli.js): WhatsApp/Telegram/Signal/iMessage adapters, memory, browser automation, **scheduling (NL reminders + cron)**.
- **different-ai/openwork** (21.2k stars, TypeScript): "open-source alternative to Claude Cowork (powered by opencode)" — i.e., the **opencode** agent core (the tool running this research session) as engine.
- **eigent-ai/eigent** (14.8k stars, Apache-2.0, TypeScript): "Open Source Cowork Desktop — Local and Free Alternative to Claude Cowork and Codex"; topics: agent-skills, desktop-agent, multi-agent-systems; active (pushed 2026-08-06).
- **AIDotNet/OpenCowork** (599 stars, Apache-2.0, TypeScript): cross-platform desktop Cowork clone.
- **johnzfitch/claude-cowork-linux**: run Claude Desktop's Cowork mode natively on Linux.
- **akashgit/i-want-build-clone** (RH Co-work, 0 stars, Python): FastAPI/React-19/Postgres stack, OpenAI-compatible API; `backend/app`, `backend/alembic`, `eval/`, `deploy/` (Containerfile + podman-compose); no MCP/connector code yet.

### Citations
- https://github.com/MoonshotAI/kimi-code (+ /blob/main/plugins/marketplace.json, /tree/main/packages, /tree/main/plugins/official)
- https://moonshotai.github.io/kimi-code/en/reference/kimi-command, .../reference/tools
- https://github.com/moonshotai (org repo list: kimi-agent-sdk, kimi-agent-rs, kimi-cli, pykaos, kosong, kimi-code-zed-extension)
- https://docs.openclaw.ai/plugins/building-plugins ; https://docs.openclaw.ai/automation/cron-jobs ; https://github.com/openclaw/openclaw (README)
- https://github.com/openclaw/clawhub ; https://github.com/VoltAgent/awesome-openclaw-skills
- https://github.com/anthropics/knowledge-work-plugins (README + .claude-plugin/marketplace.json + productivity/.claude-plugin/plugin.json)
- https://github.com/composio-community/open-claude-cowork (README)
- https://github.com/eigent-ai/eigent ; https://github.com/different-ai/openwork ; https://github.com/AIDotNet/OpenCowork

### Gaps / surprises
- **Surprise:** Claude Cowork's "connectors" are, in OSS terms, just MCP servers referenced by a marketplace JSON with a pinned git SHA — trivially cloneable. The plugin manifest is only 5 fields.
- **Surprise:** kimi-code's `/mcp-config` lets the agent configure MCP servers conversationally — the AI-native MCP management pattern; OpenClaw mirrors MCP-first plugin philosophy.
- **Gap:** kimi-work's own product-side connectors (the Kimi Work web app's Google Drive/Notion integrations) are closed; only the CLI kernel + OpenClaw host are open. Cowork's scheduled tasks + artifacts internals also closed (desktop app).

---

## 5. Recommended Stage 2 targets (ordered by clone-building value)

1. `MoonshotAI/kimi-code` — read `packages/agent-core-v2` (agent loop), `packages/minidb` (state store), `docs/` (plugin format + skill format), `packages/acp-server` (protocol), cron implementation.
2. `anthropics/knowledge-work-plugins` — copy 1-2 full plugin dirs (e.g. `productivity/`, `pdf-viewer/`) to nail the file-based plugin format incl. `.mcp.json` schema.
3. `openclaw/openclaw` — `extensions/*` (bundled plugins), scheduler (`automations`), sandbox bridge, plugin SDK package layout.
4. `eigent-ai/eigent` and `different-ai/openwork` — desktop shell + artifact preview + scheduling implementation in a Cowork clone.
5. `composio-community/open-claude-cowork` — Electron shell + Claude Agent SDK integration pattern + clawd scheduler.
6. `akashgit/i-want-build-clone` — the named clone target (early stage; useful as diff baseline).

---

## 6. Raw data notes
- All star counts as of 2026-08-06 via GitHub API.
- Search tool notes: `html.duckduckgo.com` returned a CAPTCHA mid-session (bot detection); GitHub REST API (`api.github.com/search/repositories`, `/contents`, `/git/trees`) and `raw.githubusercontent.com` worked throughout; docs sites (moonshotai.github.io, docs.openclaw.ai) are LLM-readable (some expose `.md` variants — kimi-code docs recommend `/kimi-code/en/reference/*.md`).
