# Claude Cowork vs Kimi Work — Deep Research Report

> Generated: 2026-08-06 | Session: cowork homework | Tags: cowork, claude-cowork, kimi-work, agent, clone, architecture
> Sources: ~30 web (official docs, news, teardowns) + 4 codebases (kimi-code, OpenClaw, knowledge-work-plugins, 3 clone repos) + 2 local installs (Kimi.app daimon bundle, Claude.app 1.1.673 Cowork build)
> Raw material: `/tmp/opencode/deepresearch/cowork_re-A7X2/` (breadth-*.md ×4, deepdive-*.md ×3)

## TL;DR

- **Two opposite execution philosophies.** Claude Cowork is **cloud-first** (agent loop + code run in per-session isolated sandboxes on Anthropic servers; the desktop app is a *bridge* to local files/browser). Kimi Work is **local-first** (everything executes on-device; models are cloud).
- **Scheduling is the starkest difference.** Cowork scheduled tasks run in the cloud — "no device online" required. Kimi Work scheduled tasks run on a local cron engine — app must be open, missed triggers never replayed.
- **Both are file-native artifact products**, not chat toys: real .xlsx with working formulas, .pptx decks, .docx. Cowork adds desktop-only "live artifacts" (interactive HTML dashboards w/ connector refresh + version history); Kimi adds pinnable Widgets/Dashboards + annotation refinement.
- **Both are MCP-first for integrations.** Cowork: 300+ connector directory (OAuth, per-tool permission matrix), file-based plugins. Kimi: plugin center (MCP/OAuth), kimi-code CLI kernel, OpenClaw plugin host (MIT, with SQLite automations + optional docker sandbox).
- **You can clone ~70% from open source.** kimi-code (MIT) is Kimi Work's actual kernel — full cron scheduler + in-process Agent Swarm. knowledge-work-plugins (Apache-2.0) defines the exact Cowork plugin format. No one has cloned the OS-level VM sandbox — that's the hard 30%.

## Overview

Both products are "agentic coworker" desktop apps: they take the Claude Code-style agent loop (plan → subtasks → parallel workstreams → deliverables) and point it at knowledge-work — files, docs, spreadsheets, decks, connectors, scheduled runs — instead of code. Anthropic shipped Cowork in Jan 2026 (research preview) and pivoted it to cloud execution in July 2026. Moonshot launched Kimi Work desktop in June 2026, local-first, powered by the open-source kimi-code kernel (K2.6/K3 models, 1M context).

This report is organized around the four dimensions that matter for building a clone: **live artifacts, scheduled tasks, local files, MCP connectors + CLI tools** — then a design-decision section for a greenfield build.

---

## 1. Live artifacts

### Claude Cowork

- **Deliverables are real files** in the session: Word (.docx/.doc), Excel (.xlsx/.xls/.xlsm — with *working formulas*: VLOOKUP, conditional formatting, multi-tab), PowerPoint (.pptx/.ppt), PDF, txt/md/html/json/csv/tsv, images (png/jpg/jpeg/gif/svg/webp), YAML/XML/TOML, Jupyter (.ipynb), code files. Downloadable from the session; saved to the Claude account (cloud).
- **Live artifacts** (the flagship): persistent, interactive **HTML dashboards** Claude builds in Cowork — trackers, dashboards, comparison tools, morning briefs.
  - Created by asking in a task ("Build me a dashboard pulling from Asana and Linear") or Artifacts sidebar → New artifact → Create Cowork artifact (Claude asks connector questions first).
  - **Desktop-only** (macOS/Windows/Linux-beta); do NOT appear on web/mobile. **Local, not remote** — stored on the computer, don't follow you across devices.
  - **Refresh with current data**: short cache for speed, auto re-query on open, manual refresh button.
  - **Version history**: every iteration saves a version; compare + restore.
  - **Sharing** (Team/Enterprise only): org-internal links; rendered with the *viewer's* connectors, not the creator's. Pro/Max cannot share.
  - **Security caveat**: live artifacts use connectors **without asking permission**, even in approval-requiring modes.
- **"Edit with Claude"**: select text in a drafted markdown doc → inline edit at that spot.
- Evidence (local RE, Claude.app 1.1.673): session outputs dir mounted at `/sessions/<vmProcessName>/mnt/outputs`; a `FileSystemWatcher` emits `fs_file_created` / `fs_file_deleted` events per session — the plumbing behind live artifact surfaces. Path validation blocks binary types (.exe/.app/.dmg/.pkg/.jar) and script extensions across the VM boundary.

### Kimi Work

- **Outputs written straight back into the mounted folder** — "nothing has to be downloaded, renamed, or swapped back into place by hand"; also delivered to the project workspace.
- **Widgets + Dashboard** (flagship): interactive visual components generated in conversation (weather, countdown, market watch, task boards); **annotation refinement** — select an area of a rendered widget, request changes in NL, each revision builds on the previous; **Pin to Desktop** — independent always-visible window; Dashboard = cross-session persistent home for widgets.
- **Live PPT slide editor** (v3.1.6, 2026-07-29): open and edit slides in the workspace; changes apply immediately.
- Inherits Kimi web generators: Slides, Sheets, Docs, Websites builder, Deep Research (multi-format reports).

### Clone implication

Two artifact models: **file-artifacts** (write real .xlsx/.pptx via agent tools; render with previews) and **interactive artifacts** (HTML dashboards with data refresh + versioning, or widget components). openwork's `deriveOpenTargets` (confidence-scored regex + write-tool metadata + patch parsing → artifact registry → preview tabs) is the best OSS approximation of detection; eigent's `fileReader.ts` (mammoth/xlsx→HTML converters in the Electron main process) is the preview reference.

---

## 2. Scheduled tasks

### Claude Cowork

- **Creation**: `/schedule` slash command in any task, or Scheduled sidebar → New task → *Create with Claude* (Claude asks clarifying questions, you confirm "Schedule") or *Set up manually* (name, prompt, approval mode, frequency, optional model, optional folder).
- **Cadence**: built-in options only — hourly, daily, weekly, weekdays, manual. **No arbitrary cron.**
- **Execution**: **cloud cron** — runs even when computer asleep / app closed / no device online. Each run = its own Cowork session; review upcoming/past runs from any surface; pause/resume/delete/run-on-demand.
- **Constraint**: "They can't be tied to a folder on your computer" — scheduled tasks work with connectors + account files. If local files/apps required → "it will only run locally."
- **Limits**: no published task-count/concurrency caps; available on all paid plans; consumes usage pool 5–20x faster than chat.
- Local RE note: the desktop build's scheduler backend is server-side (closed). Desktop app carries `/schedule` UX + local-only execution path.

### Kimi Work

- **Creation**: manual form (name, description, clock time, Once/Daily/Weekly/Monthly) or NL ("send a task and let Kimi Work create the scheduled task directly").
- **Execution**: **local cron engine** — app must be open; missed triggers (sleep/shutdown) **never replayed**; "Keep Computer Awake" toggle for overnight runs. Supports LLM agent calls, Python/Shell executions. Web-app tasks run in cloud instead.
- **Quotas (hard, documented)**: active tasks Free **2** / Go **6** / Pro **15** / Max **20** / Ultra **25**; over-limit tasks save as inactive. Cloud-task default expirations: daily +7d, weekly +1m, monthly +3m (local desktop tasks exempt).
- **Underlying kernel (kimi-code, MIT) — full cron implementation**: `CronCreate/CronList/CronDelete` tools; per-session, max 50 jobs/session, 8 KB prompt cap, must fire within 5 years; **deterministic jitter** (recurring: ≤10% of period cap 15 min forward; one-shot: ≤90 s earlier only on `:00`/`:30`); **coalescing** (missed fires delivered once with `coalescedCount`); **7-day stale auto-expire**; fire injects `<cron-fire jobId cron recurring coalescedCount stale>` prompt into the session; storage = per-id JSON docs at `<home>/cron/<workspaceId>/<id>.json`; 1 s polling timer; `KIMI_DISABLE_CRON=1` kill switch.
- **OpenClaw (Kimi's plugin host, MIT) — production-grade automations**: `openclaw automations` CLI; SQLite `cron_jobs` table (full schema in raw notes); triggers `at/every/cron/on-exit/stream`; 5-min top-of-hour stagger; single self-arming setTimeout clamped 2 s–60 s; **auto-disable after 10 consecutive run failures or 3 schedule errors**; webhooks + Gmail PubSub triggers; restart catch-up recompute.

### Clone implication

Three implementation levels: (a) kimi-code v1 cron stack (`packages/agent-core/src/tools/cron/` — pure engine, ~800 lines, best spec); (b) OpenClaw automations (SQLite + timeout-policy + auto-disable — production reference); (c) Cowork-style cloud scheduler (server-owned, session-per-run, DST-safe — openwork's `packages/automations` engine has the DST ±18 h wall-clock search + admission keys + replay-only-latest-missed).

---

## 3. Local files

### Claude Cowork

- **Access model**: user chooses folders; app-layer permission system enforces connected-folder rules on every tool call. Deletion of any file requires explicit approval in every mode.
- **Local session (desktop)**: agent loop runs natively on device; **code execution runs in an isolated Linux VM** — Apple Virtualization.framework (macOS) / Hyper-V (Windows); VM enforces own egress filtering, syscall restrictions (seccomp), per-session unprivileged users. VM failure degrades gracefully ("workspace unavailable"; file/web tools keep working).
- **Cloud session (current default)**: per-session ephemeral sandbox on Anthropic servers, destroyed at end; no private/link-local/cloud-metadata access; **mandatory egress proxy outside the sandbox (allowlist-only, not reconfigurable from inside)**; session-scoped credentials expiring within hours; **connector tokens never enter the sandbox** (connector calls server-side); tenant isolation on every record.
- **Desktop ↔ cloud bridge**: cloud session reaches local files/browser **through the Claude Desktop app over an Anthropic-brokered connection**; folder-scoped + per-call permission checks; desktop offline ⇒ no device access (session continues, local tools unavailable); local MCP servers NOT proxied into cloud sessions.
- **Approval modes**: Manual (ask before acting) / Auto (Claude self-checks exfiltration/prompt-injection; consumes more usage; Pro/Max) / Skip (no checks).
- Local RE evidence (Claude.app): `request_cowork_directory` tool → host directory picker → `mountPath(hostPath, subpath, name, "rw")` → mounted at `/sessions/<name>/mnt/<folder>`; `allow_cowork_file_delete` for rwd; uploads hardlinked at `/sessions/<name>/mnt/uploads/`; path-traversal + extension blocklists on both sides; `cowork_plugins/` dir scoped user/project/local with `installed_plugins.json`.
- **Security incident to design against**: Armadin sandbox-escape chain (Windows Claude Desktop v1.9255.2.0, DLL sideload → service signature gate bypass → root shell + nsenter escape). Anthropic disputes severity (requires prior local code execution).

### Kimi Work

- **Access model**: mount/link a local folder to a project → agent reads/writes/executes inside it; one-off tasks can skip folders. **Permission modes**: "Request permission" (prompt before modify/overwrite/run) vs "Allow all" (uninterrupted).
- **Execution is on-device**: Python/shell run locally; data stays on the machine; models are cloud.
- **WebBridge**: local service + browser extension; drives the user's real Chrome/Edge via **Chrome DevTools Protocol**; login sessions/page content never leave the device.
- **Kernel has NO sandbox** (kimi-code): trust boundary = approval prompts + deny rules + sensitive-file filtering (.env, private keys auto-filtered in Grep). OpenClaw adds optional docker sandbox (network:none, readOnlyRoot, cap-drop-all, credential-path-blocked bind mounts).

### Clone implication

Pick an isolation tier: (0) permission prompts only (kimi-code model — fastest to ship); (1) capability "hands" gating (eigent: workspace-root fs confinement, MCP allowlist, terminal allowlists); (2) real OS-level VM (Cowork's Virtualization.framework approach — nobody in OSS has done it; hardest, inherits Armadin-class attack surface).

---

## 4. MCP connectors and CLI tools

### Claude Cowork

- **Connectors = MCP servers** (directory hub: ~17 pages / 300+ connectors, third-party submitted, "powered by MCP"). Named: Google Drive, Gmail, Slack, DocuSign, Microsoft 365, Amplitude, Notion, Asana, Linear, Jira, HubSpot, Canva, Figma, Snowflake, Databricks, BigQuery, FactSet (third-party-confirmed, Feb 2026 enterprise wave)…
- **Auth**: OAuth at connect time; Enterprise-managed auth beta (authorize once org-wide); verified-domain restriction option. Custom connectors = remote MCP servers reached **from Anthropic's cloud, not the device** — must be public-internet reachable (allowlist Anthropic IPs for firewalled servers). Free plan: 1 custom connector.
- **Per-tool permissions**: Always allow / Needs approval / Blocked, grouped read-only vs write/delete; org-wide action restrictions can't be overridden; source-system permissions are the outer bound. Tool access modes: Auto (default) vs On demand (10+ connectors).
- **Plugins (file-based, no code)**: `plugin.json` (name/version/description/author) + `.mcp.json` (mcpServers with type:"http", url, oauth.clientId/callbackPort; **empty url = built-in connector**) + `commands/*.md` (YAML frontmatter description/argument-hint, `$ARGUMENTS`) + `skills/*/SKILL.md` (name/description/user-invocable frontmatter, `${CLAUDE_PLUGIN_ROOT}`); `~~category` placeholders make plugins tool-agnostic; marketplace.json indexes plugins by relative `source` dir. Anthropic's open-source collection: `anthropics/knowledge-work-plugins` (93 plugins, 11 first-party role plugins).
- **CLI/API**: **no public CLI or API for Cowork**. Claude Code is the terminal sibling; MCP Connector exposes connectors to the API; OTel event stream + Compliance API for enterprise observability.

### Kimi Work

- **Plugin Center**: built-in professional DB plugins (Wind, S&P Global, IMF, Tonghuashun, Tianyancha…) + curated app plugins (Notion, Canva, WPS, DingTalk, Feishu, Cloudflare, GitHub, Neon, Supabase, Kimi Computer Use…). "Plugins extend Kimi with external capabilities, built from several MCPs connected through skills" — MCP/OAuth based; `/` to invoke.
- **Native data**: US/HK/A-share market data, World Bank macro, academic layer — no plugin needed.
- **CLI**: Kimi Work desktop has no public CLI. **Kimi Code is the CLI/IDE agent** (this machine has its full kernel installed via daimon). `kimi web` runs a local REST+WS server (Fastify, port 58627, bearer token `~/.kimi-code/server.token` 0600, `{code,msg,data,request_id}` envelope, keyset-paginated `/api/v2/sessions`, journaled WS `/api/v1/ws` with `{seq,epoch}` resync). `kimi acp` = Agent Client Protocol server (Zed/JetBrains). MCP config via `/mcp-config` skill over 3-layer file merge (`~/.kimi-code/mcp.json` > project `.mcp.json` > `.kimi-code/mcp.json`).
- **OpenClaw plugin SDK** (MIT): npm package + `openclaw.plugin.json` (TypeBox schemas, `api.registerTool(...)`), ClawHub registry (clawhub.ai), channels (Telegram/WhatsApp/Discord/…), ~385k★ ecosystem.

### Clone implication

The connector story is: (1) an MCP client runtime with OAuth + per-tool permission matrix (Claude Agent SDK / opencode / CAMEL MCPToolkit all do this); (2) a connector directory (marketplace.json referencing remote MCP URLs); (3) a file-based plugin loader (plugin.json + .mcp.json + commands + skills — trivially cloneable, exact format documented above). For CLI: kimi-code's `kimi web` API shape is a ready-made blueprint for a local HTTP artifact/control surface.

---

## Design decisions (for a greenfield clone — "RH Co-work")

| Decision | Option A | Option B | Evidence |
|---|---|---|---|
| **Execution home** | Local-first (Kimi model): agent + code on-device, quick, private, simple infra | Cloud-first (Cowork model): sandboxes server-side + desktop bridge; needs relay infra | Cowork pivoted to cloud in Jul 2026; Kimi stayed local. Local-first is the cheaper v1; cloud-scheduling can be added later (openwork's Den pattern) |
| **Desktop shell** | Electron (all major clones; node-pty, WebContentsView, contextIsolation) | Tauri (kuse_cowork — Rust backend, lighter) | Electron dominates: open-claude-cowork, eigent, openwork, DevAgentForge, Open-Cowork |
| **Agent engine** | Dual providers behind one normalized chunk contract (`session_init\|text\|tool_use\|tool_result\|done\|aborted`): Claude Agent SDK (in-process) + opencode (spawned `serve` + sdk) | Single provider | open-claude-cowork's provider abstraction; openwork spawns opencode with random per-run credentials |
| **Session store** | SQLite (better-sqlite3) with state.json-style metadata + per-id JSON docs | localStorage/in-memory (open-claude-cowork — loses sessions on restart) | kimi-code's file layout is the model; SQLite fixes clone weakness |
| **Scheduling** | kimi-code v1 cron engine spec (pure, jitter/coalesce/stale, 50-job cap) + SQLite job store + boot recovery | Cowork-style cloud scheduler (server-owned sessions) | kimi-code cron is MIT and complete; OpenClaw automations for production hardening (auto-disable, timeouts) |
| **Artifacts** | openwork `deriveOpenTargets` detection + sandboxed iframe/PDF `<embed>`/office→HTML previews | eigent PreviewPanel tabs (browser/file/terminal) | openwork's confidence-scored detection is the best OSS; office conversion in the privileged process |
| **Permissions** | canUseTool callback → modal (approve/deny/always) + timeout-deny + capability "hands" layer | kimi-code policy-chain (manual/yolo/auto, first-wins policies) | openclaw runner.js + eigent hands/ + kimi-code `policies/index.ts` (order matters) |
| **Sandbox** | Tier 0: permission prompts only (fastest) | Tier 2: Virtualization.framework Linux VM (Cowork-class; nobody in OSS has shipped it) | kimi-code has zero sandbox; Armadin incident shows VM escape is a real attack surface — start Tier 0/1, design for Tier 2 later |
| **Plugins/connectors** | Cowork plugin format (plugin.json/.mcp.json/commands/skills + marketplace.json) — file-based, tool-agnostic via `~~category` | kimi.plugin.json format | knowledge-work-plugins format is simpler + matches Claude Code's plugin system too |

## Recommended first build (v1 scope)

1. Electron shell + React, local Node runtime server (Express or node:http) — SSE with 15 s heartbeat, idle timeout.
2. Provider layer with normalized chunk vocabulary; opencode (or Claude Agent SDK) behind it.
3. SQLite sessions; workspace = "folder you point at" (frozen-dirs snapshot like eigent).
4. Artifact engine: file watcher + openwork-style detection → preview tabs (markdown/html/pdf/sheet/slides).
5. Cron scheduler per kimi-code spec + SQLite jobs + boot recovery + missed-run policy.
6. MCP manager: `mcpServers` JSON config, remote HTTP + local stdio, per-tool allowlist, approval modals.
7. Skills: SKILL.md scanner; plugins: Cowork file format loader.

## Gotchas & pitfalls

1. **Cron determinism**: kimi-code bans `Date.now()` outside clock injection (`no-date-now` test guards) — adopt clock injection from day one; DST wall-clock resolution needs the ±18 h search (openwork) — the "just use croniter" approach breaks at DST.
2. **SSE cancellation semantics**: eigent spent 2,900 lines on an event protocol where "close = cancel" vs "preserve completed locks" must be explicit; openwork sidestepped with snapshot polling + idempotent read models. Decide early.
3. **PDF previews**: sandboxed iframes render blank; use `<embed type="application/pdf">` (openwork comment).
4. **Agent process lifecycle**: spawn → stdout URL handshake → health → SIGTERM→SIGKILL teardown → config hot-reload (openwork `managed-opencode.ts` is the reference). open-claude-cowork's manual two-terminal setup is the anti-pattern.
5. **Sensitive file filtering**: kimi-code auto-filters `.env`/private keys in Grep; OpenClaw blocks credential roots in bind mounts — mirror both.
6. **Missed-run policy**: kimi replays with `coalescedCount`; openwork replays only the latest missed occurrence; Cowork cloud never misses (server-side). Pick one per surface and document it.
7. **License**: kimi-code + OpenClaw are MIT (usable); `plugins/official/*` plugin *content* is Proprietary — don't vendor; knowledge-work-plugins is Apache-2.0.
8. **Moonshot platform is overloaded (Jul 2026)**: Kimi model API returns 429 "engine overloaded" — verify provider capacity assumptions before committing.

## Sources

**Official — Claude Cowork**: claude.com/product/cowork · support.claude.com (13345190 get-started, 14479288 architecture, 13854387 scheduled tasks, 14729249 live artifacts, 11176164 connectors, 13837440 plugins, 13455879 team/enterprise, 13364135 safety, 14128542 computer use) · claude.com/connectors · claude.com/blog (cowork-plugins, cowork-for-enterprise, cowork-web-mobile, how-people-are-using-claude-cowork) · claude.com/pricing

**Official — Kimi Work**: kimi.com/products/kimi-work · /resources/kimi-work-introduction · /resources/kimi-work-dashboard · /resources/kimi-claw-introduction · /features/webbridge · /help/kimi-work/* (overview, faq, goal-mode, plugin-center, release-notes) · /help/features/scheduled-tasks · /help/membership/* · /blog/agent-swarm

**Code (all MIT unless noted)**: MoonshotAI/kimi-code · openclaw/openclaw (+ clawhub) · anthropics/knowledge-work-plugins (Apache-2.0) · clones: different-ai/openwork, eigent-ai/eigent (Apache-2.0), composio-community/open-claude-cowork, johnzfitch/claude-cowork-linux

**News/teardowns**: CNBC 02/24/2026 · ZDNET 07/07/2026 · WIRED 01/15 + 07/07 · SiliconANGLE 07/01 (Armadin sandbox) · aifordevelopers.substack.com (complete guide) · usecarly.com (Kimi Work + Cowork pricing/limitations) · aitoolsclub.com · eigent.ai · felloai.com · automatonagency.com

**Local reverse-engineering**: Kimi.app 3.1.6 daimon bundle (@kimi/daimon 0.5.49 — release manifest, blueprint automation scheduler, control server) · Claude.app 1.1.673 app.asar (LocalAgentModeSessionManager, CoworkVMProcess, request_cowork_directory, FileSystemWatcher, cowork_plugins, knowledge bases) · `~/Library/Application Support/Claude/vm_bundles/claudevm.bundle/rootfs.img` (10 GB Cowork VM)
