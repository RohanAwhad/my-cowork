# Devlogs — cowork

## 2026-08-06/07 — Static RE of Claude Cowork app complete (Phase 1+3 of RE campaign)

### What happened
- Full static reverse-engineering of Claude Desktop 1.1.673 (Cowork build): extracted `app.asar` → `.vite/build/index.js` (3.3 MB), 7-agent swarm mined it + VM rootfs forensics + community RE (`johnzfitch/claude-cowork-linux`) + endpoint probing.
- Deliverable: `docs/REVERSE_ENGINEERING_claude_cowork.md` (architecture, session lifecycle, VM layer, security model, EIPC surfaces, endpoint table, mermaid diagrams). Raw: `/tmp/opencode/deepresearch/cowork_app_re-M3KQ/`.

### Key discoveries
- Cowork = Local Agent Mode inside Claude Desktop; kernel = **Claude Code 2.1.15** (Bun standalone, `local-agent` entrypoint) in a **Linux VM** (Virtualization.framework via `@ant/claude-swift`); UI = claude.ai web renderer, glued by EIPC (`$eipc_message$_<uuid>_$_claude.web_$_<Iface>_$_<method>`, 362 methods).
- VM rootfs (Ubuntu, built 2026-01-15): Node 22, `sdk-daemon` (Go vsock RPC + MITM proxy for *.anthropic.com), `srt`/sandbox-helper, doc stack (markitdown/LibreOffice); Claude Code injected at boot via `installSdk`. Mounts at `/sessions/<vm>/mnt/{outputs,uploads,.claude,.skills,.knowledge}`.
- Security: folder grants home-confined, `rw`→`rwd` mount upgrade for deletion, extension blocklists, path validation both sides, connector tokens never in VM (`claudeai-proxy` MCP), MITM proxy with host-approved OAuth token.
- EIPC surfaces: `LocalAgentModeSessions` (28+), `CoworkSpaces` (21), `ClaudeVM` (10), `CoworkScheduledTasks` (9) + `CCDScheduledTasks` (8), `CoworkMemory` (2), `ComputerUseTcc`, `BuddyBleTransport`.
- Endpoints: `wss://bridge.claudeusercontent.com/chrome/<userId>` (Chrome ext relay, full protocol), `api.anthropic.com/v1/sessions[/events]` (remote sync), `claude.ai/api/event_logging/batch`, `downloads.claude.ai/vms/linux/` + `claude-code-releases/`.
- MCPB = signed plugin bundle (PKCS#7), DXT = legacy desktop-extension manifest field — neither is a wire protocol.
- Claude Code 2.1.15 is public (npm/GitHub tag); downloads.claude.ai has no public manifest.
- claude.ai REST (`/api/cowork/*`, artifacts, scheduled tasks) is Cloudflare-gated → needs devtools capture from logged-in session.

### State
- Tools: e2fsprogs + mitmproxy installed (user ran installs).
- Backlog: `docs/RESEARCH_backlog.md` — live sessions (user-run), devtools capture, mitmproxy capture, newer-build diff, Webflow connector JSON.

## 2026-08-06 — Homework: reverse-engineer Claude Cowork + Kimi Work for a from-scratch clone

### What happened
- User wants to build an open-source clone of Claude Cowork + Kimi Work ("RH Co-work", repo forked from `akashgit/i-want-build-clone`). Four focus dimensions: **live artifacts, scheduled tasks, local files, MCP connectors + CLI tools**.
- Set up `kimi-daimon` (Kimi Work's agent runtime) locally from the bundled CLI inside `Kimi.app`. Full deepresearch (4 breadth + 3 deep-dive agents) + local reverse-engineering of both installed products.

### Kimi daimon setup (this machine)
- CLI: `/Applications/Kimi.app/Contents/Resources/resources/daimon-bundle/app/daimon/dist/src/runner/cli.js` (run via `node`; package `@kimi/daimon` v0.5.49).
- Release manifest: `/Applications/Kimi.app/Contents/Resources/resources/daimon-bundle/release/manifest.json` — tarballs NOT shipped; `setup --release <manifest> --skip-openclaw` works from local tree.
- `setup` wrote: `~/.kimi/daimon/config.json`, `~/.kimi/config.toml`, LaunchAgent `com.moonshot.kimi-daimon.plist`, managed python runtime, workspace `/Users/rawhad/Documents/kimi/workspace`.
- **Gotcha**: `set-key` maps the key to provider `qianxun-kimi` with base_url `https://openai.app.msh.team/v1` (wrong — unknown relay). The daimon provider `daimon-kimi-code` needs `credentials.kimiCode.apiKey` in config.json (set-key alone doesn't fill it — daemon fails "no resolved API key").
- **Fix applied**: base_url → `https://api.moonshot.ai/v1`, model `kimi-k2.6`, credential `kimiCode.apiKey` = MOONSHOT_API_KEY. Auth now passes.
- **Current state**: runner boots fully (blueprint automation scheduler, dream memory, hosted agents). Model calls return `429 engine overloaded` (Moonshot platform overloaded post-K3 launch — external, transient). Retry later.
- Daemon vs foreground: `start --prompt` conflicts with running daemon (runner.lock); stop daemon first (`daemon stop`) for prompt mode.

### Claude Cowork install (this machine)
- NOT a separate app: it's **Claude Desktop 1.1.673** (the Cowork-enabled build) — "custom version from cowork team" = Cowork-capable Claude.app.
- Local VM: `~/Library/Application Support/Claude/vm_bundles/claudevm.bundle/rootfs.img` (10 GB GPT image, Linux rootfs via Apple Virtualization.framework, Swift module `@ant/claude-swift`, `swift_addon.node`). Logs: `~/Library/Logs/Claude/{claude_vm_node,cowork_vm_node}.log`.
- Extracted `app.asar` → `.vite/build/index.js` (3.3 MB minified): full Cowork "local agent mode" internals — see research report §architecture. Key symbols: `LocalAgentModeSessionManager`, `CoworkVMProcess`, `request_cowork_directory` (host folder → VM mount at `/sessions/<name>/mnt/<folder>`), `allow_cowork_file_delete`, `mcp__cowork__create_knowledge_base`, `FileSystemWatcher` (fs_file_created/deleted events → artifact surface), plugin reader (`~/.claude/cowork_plugins/installed_plugins.json`, scopes user/project/local), `cowork_settings.json` (not yet present — feature not yet used on this machine).
- Claude side gaps: scheduler/artifact storage formats are server-side (closed). Desktop-side = VM + bridge + permissions.

### Research conclusions (curated)
- **Architectural fork**: Claude Cowork = cloud-first (isolated sandboxes on Anthropic servers, desktop app is a bridge to local files/browser; scheduled tasks run with no device online). Kimi Work = local-first (everything on-device; scheduled tasks need the app open; local cron, missed triggers lost).
- **Live artifacts**: Cowork = desktop-only interactive HTML dashboards w/ connector refresh + version history + org share (viewer's grants). Kimi = Widgets/Dashboard pinned desktop windows + annotation refinement; files written back into mounted folder.
- **Scheduling**: Cowork = built-in cadence (hourly/daily/weekly/weekdays/manual), each run = own session, cloud. Kimi = local cron engine (quota 2/6/15/20/25 active tasks by plan), kimi-code kernel has full CronCreate/CronList/CronDelete (per-session, 50 jobs, jitter, coalescing, 7-day stale auto-expire). OpenClaw = SQLite `cron_jobs` + auto-disable after 10 failures.
- **Local files**: Cowork = folder grants + Linux VM isolation (per-session user, seccomp, egress proxy) or cloud sandbox + brokered bridge. Kimi = mounted folders, ask/allow-all permission modes, no sandbox in kernel (approval prompts + hooks are the boundary; OpenClaw adds optional docker sandbox).
- **MCP/CLI**: Cowork = 300+ MCP connectors (directory, OAuth, per-tool Always/Needs-approval/Blocked), file-based plugins (plugin.json + .mcp.json + commands/ + skills/, `~~category` placeholders), no public API. Kimi = plugin center (MCP/OAuth), kimi-code CLI + `kimi web` (Fastify :58627, bearer token, journaled WS `{seq,epoch}`), OpenClaw plugin SDK.
- **Open-source gold**: kimi-code (MIT) = full agent kernel incl. cron + swarm (in-process, burst-5/700ms ramp, max 128). OpenClaw (MIT) = automations + sandbox. knowledge-work-plugins (Apache-2.0) = exact Cowork plugin format. Clones: openwork (opencode engine, best artifact detection), eigent (CAMEL + Postgres/Celery triggers), composio open-claude-cowork (Claude Agent SDK + minimal blueprint).

### Next steps
- Retry kimi prompt when Moonshot engine unloads (429).
- Decide clone architecture (see `docs/RESEARCH_claude_cowork_kimi_work.md` §Design Decisions); recommend: Electron shell + provider abstraction (Claude Agent SDK / opencode) + SQLite sessions + cron with boot recovery + openwork-style artifact detection.
- Mine `cowork_vm_swift.log` path + swift_addon surface if deeper VM internals needed.
