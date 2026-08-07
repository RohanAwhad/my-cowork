# Deep Dive: Claude Cowork Internals — research for a from-scratch clone

**Stage 2 deep-dive · compiled 2026-08-06**
**Audience:** developer building a Cowork clone. All quotes verbatim from cited URLs. Plugin file snippets are raw file contents from `github.com/anthropics/knowledge-work-plugins` (main branch, fetched via raw.githubusercontent.com / GitHub API).

## Sources fetched in full

| # | URL | What it gave us |
|---|-----|-----------------|
| 1 | https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview | Cloud vs local architecture, sandbox, egress, credentials, desktop bridge, MDM controls |
| 2 | https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-cowork | Scheduled task flow, cadence, local-only path, management |
| 3 | https://support.claude.com/en/articles/14729249-use-live-artifacts-in-claude-cowork | Live artifact definition, refresh, versioning, sharing, limits |
| 4 | https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities | Connector/MCP implementation, auth, per-tool permissions, custom connectors |
| 5 | https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork | Task execution model, approval modes, permissions, scheduling entry point |
| 6 | https://claude.com/blog/cowork-web-mobile/ | July 7, 2026 cloud launch; cross-surface continuity |
| 7 | https://claude.com/blog/cowork-plugins/ | Plugin architecture announcement; file-based components |
| 8 | https://github.com/anthropics/knowledge-work-plugins (README, tree API, raw files) | Exact plugin on-disk format |

---

## 1. Architecture: local session vs cloud session

Source: [Claude Cowork architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview) (primary), [Get started with Claude Cowork](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork).

### 1.1 The two execution modes

> "Cowork sessions run in the cloud by default: the agent loop and code execution run on Anthropic's servers, and sessions and files are saved to the member's Claude account. Cloud execution is in beta and rolling out gradually across plans."
> "Local execution remains available for existing desktop deployments: the agent loop and code execution run on the member's device, as described below."

### 1.2 Cloud session architecture (step-by-step)

> "In a session in the cloud, the agent loop and code execution run in an isolated, temporary sandbox on Anthropic-managed infrastructure. **Each session gets its own sandbox, created when the session starts and destroyed when it ends**, and sandboxes don't share state with each other or across organizations. This infrastructure is kept separate from Anthropic's corporate, research, and model-training environments."

Key properties (verbatim bullets from the article):

- **No access to your network by default.** "The sandbox can't reach private, internal, link-local, or cloud-metadata addresses, and it can't reach Anthropic-internal systems, so it can't be used to pivot into your network."
- **Network access follows your existing policy.** "A cloud session uses the same network-access setting that governs local Cowork and chat. No network access is the default for Enterprise organizations."
- **Egress is enforced outside the sandbox.** "All traffic leaving the sandbox passes through a mandatory proxy the sandbox can't reconfigure or bypass, and only allow-listed destinations are reachable."
- **Short-lived credentials only.** "The sandbox holds only session-scoped tokens that expire within hours. **Connector authorization tokens never enter the sandbox; connector calls are made on the server side.**"
- **Tenant isolation at the data layer.** "Every stored record is scoped to your organization and account."

**What's on host vs in sandbox (cloud mode):**
- On Anthropic servers: agent loop, code execution, shell commands, web fetch, connector calls, session state, files.
- On user device: only "local file or the browser" reachable *through* the Claude Desktop app (see §6).
- Local MCP servers: "**Local MCP servers don't run in sessions in the cloud.**"

**Step-by-step message flow (cloud)** — from Get Started, "How Claude Cowork runs your tasks":

> "When you start a task in Cowork, Claude:
> 1. Analyzes your request and creates a plan.
> 2. Breaks complex work into subtasks when needed.
> 3. Runs code and shell commands in an isolated environment on Anthropic's servers.
> 4. Coordinates multiple workstreams in parallel if appropriate.
> 5. Delivers finished outputs to your session, where you can preview and download them."

Session lifecycle: sandbox created at session start, destroyed at end; state persists in the member's Claude account (sessions/files), not in the sandbox.

### 1.3 Local session architecture (desktop)

> "Local sessions apply to existing desktop deployments and use two execution environments on the member's device:"

> "**The agent loop runs natively on the device.** This includes Claude's conversation handling, file reads and writes in connected folders, web fetches, and local plugin MCP servers. Access is gated by an application-layer permission system that enforces the member's connected-folder rules and your organization's network egress settings."

> "**Code execution runs in an isolated virtual machine (VM).** Shell commands and any code Claude writes execute inside a dedicated Linux VM, isolated from the host operating system by the platform's hypervisor (Apple Virtualization.framework on macOS, Hyper-V on Windows). The VM enforces its own network egress filtering, syscall restrictions, and per-session user isolation."

VM failure behavior: "Cowork continues running file and web tools while the VM is unavailable. Shell commands and code execution report 'workspace unavailable' until the VM recovers."

EDR note: "The VM is isolated from host-based security tools by design, and sessions in the cloud run entirely outside your endpoints, so EDR tools can't observe them either."

### 1.4 Admin/org controls

- Org toggle: "The organization-wide Cowork toggle in **Organization settings > Cowork** (**Enable for your organization**) controls whether Cowork is available at all."
- Two MDM keys (device-level, via MDM, not org settings):
  - "Set `isLocalDevMcpEnabled` to false to disable plugin-bundled and locally configured MCP servers."
  - "Set `isDesktopExtensionEnabled` to false to block MCPB and DXT extension servers from running."
  - Scope: "These MDM keys govern the Claude Desktop app, so they apply to local sessions and to anything a session in the cloud reaches through the desktop app."
- Cloud-session org controls: on/off toggle, network-access policy, "Require fresh approval for every permission-gated tool call by turning off persistent 'always allow'", trusted-device enrollment + recent sign-in.
- Observability: "Cowork via mobile and web is captured in Compliance API" + OpenTelemetry monitoring for Team/Enterprise admins.

### 1.5 Clone checklist — architecture

- [ ] Sandbox-per-session: ephemeral env per session, destroyed on end, no cross-session or cross-org state sharing.
- [ ] Network policy: block private/link-local/cloud-metadata/metadata-IP ranges by default; org-configurable egress allowlist.
- [ ] Mandatory egress proxy *outside* the sandbox, not reconfigurable from inside.
- [ ] Session-scoped short-lived credentials (hours); connector tokens stored server-side, never injected into sandbox; connector calls proxied server-side.
- [ ] Tenant isolation on every stored record (org + account scoping).
- [ ] Local mode: agent loop natively on device + dedicated Linux VM via Virtualization.framework (macOS) / Hyper-V (Windows) with egress filtering, syscall restrictions, per-session user isolation; graceful "workspace unavailable" degradation when VM is down.
- [ ] App-layer permission system: connected-folder rules + org network egress enforced on every local tool call.
- [ ] Desktop extensions (MCPB, DXT) + local MCP servers behind configurable enable flags (`isLocalDevMcpEnabled`, `isDesktopExtensionEnabled`).
- [ ] Approval modes (Manual/Auto/Skip — see §7) applied to connector and local tool calls.

---

## 2. Scheduled tasks

Source: [Schedule recurring tasks in Claude Cowork](https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-cowork), plus Get Started (`/schedule`).

### 2.1 Core model

> "When you create a scheduled task, Claude saves your prompt as the task's instructions and runs them at the cadence you choose."
> "**Each scheduled task runs as its own Cowork session.** You can review the results when they're ready, just like any other task."
> "Scheduled tasks run remotely, so they run on their cadence even when your computer is asleep or the Claude Desktop app is closed."
> "Scheduled tasks use the built-in schedule options and work with your connectors and the files saved to your Claude account. **They can't be tied to a folder on your computer.**"
> "Scheduled tasks have access to the same capabilities as regular Cowork tasks, including connected tools, skills, and installed plugins."

### 2.2 Creation flow

**Path A — Create with Claude:**
1. Click "Scheduled" in the left sidebar → Scheduled tasks page.
2. Click "New task" → "Create with Claude."
3. "This creates a new task auto-filled with a prompt asking Claude to create a scheduled task."
4. "Claude may ask you questions with multiple choice responses before creating the scheduled task."
5. "Once Claude has all the necessary information, it will output the name of the task it's creating, the schedule it will follow, and what the task actually does."
6. User explicitly confirms with "Schedule" button.
7. Task created and added to the Scheduled tasks page.

**Path B — Set up manually** (modal fields, in order):
1. Task name
2. The prompt describing what your task does
3. The approval mode
4. "How frequently the task will run (hourly, daily, weekly, on weekdays, or manually)"
5. The model you want to use [optional]
6. Which folder Claude should work in [optional]
   - **Note:** "If a scheduled task requires local files or apps, it will only run locally."

**Shortcut:** "To schedule a task, type `/schedule` in any Cowork task." (Get Started)

### 2.3 Execution semantics

- **Cadence options:** hourly, daily, weekly, on weekdays, manually (on-demand). "Built-in schedule options" only — no arbitrary cron.
- **Remote execution:** "Scheduled tasks run in the cloud, so they don't need your computer to be awake or the desktop app open."
- **Local-resource dependency:** if the task needs local files/apps → "it will only run locally" (the local-only path; runs on the device, requiring desktop availability).
- **Results:** each run is a session; "You can review the results when they're ready, just like any other task"; "Review upcoming and past runs by clicking 'Scheduled' in the left sidebar on any surface." (No email/push notification of results documented — review in-app.)

### 2.4 Management

From the Scheduled page you can:
- "View all the scheduled tasks you've created"
- "Review upcoming and past runs"
- "Click into individual tasks to manually edit the instructions or cadence"
- "Pause a scheduled task"
- "Resume a paused task"
- "Delete a scheduled task"
- "Run a task on demand"

### 2.5 Availability / limits

- "Scheduled tasks are available in Cowork for all paid plans (Pro, Max, Team, Enterprise)."
- No documented numeric limits (max tasks, max frequency, run duration). Usage limits: "Working on tasks with Cowork consumes more of your usage allocation than chatting with Claude" (Get Started).

### 2.6 Clone checklist — scheduled tasks

- [ ] Task entity: name + prompt (instructions) + approval mode + cadence + optional model + optional folder.
- [ ] Scheduler supporting: hourly, daily, weekly, weekdays, manual; run history (upcoming/past).
- [ ] Each run spawns a fresh Cowork session (same agent loop as interactive tasks).
- [ ] Cloud execution default; explicit fallback flag → "runs only locally" when local resources required.
- [ ] CRUD: create (manual form + Claude-assisted flow with confirmation), edit instructions/cadence, pause/resume, delete, run-now.
- [ ] `/schedule` slash command available in any task.
- [ ] Runs use user's connectors + account files; cannot bind to local folders (cloud path).

---

## 3. Live artifacts

Source: [Use live artifacts in Claude Cowork](https://support.claude.com/en/articles/14729249-use-live-artifacts-in-claude-cowork).

### 3.1 Definition

> "Live artifacts are persistent, interactive HTML dashboards that Claude builds for you. They refresh with current data from your connected apps and appear alongside your chat artifacts in the Artifacts view on Claude Desktop."
> "A live artifact is a persistent, interactive HTML page that Claude creates for you in Cowork, shaped around your specific work. It might be a tracker, a dashboard, a comparison tool, or a reference. Every live artifact you create is saved to the Artifacts view in your Cowork sidebar, marked with a 'Cowork' label."

Differences vs chat artifacts:
- "**They live on their own.** You don't have to find the chat they came from."
- "**They refresh with current data.** When you open a live artifact, it can pull from your connected apps and local files so the view reflects today, not the day it was built."
- "**They keep their history.** Each update saves a version. You can review how the artifact has evolved and restore an earlier version."

**Availability:** paid plans only; "Claude Desktop for macOS, Claude Desktop for Windows, Claude Desktop for Linux (beta)". "**Note:** Live artifacts are available on the desktop app only. They don't appear in the Artifacts view on web or mobile."

### 3.2 Creation

**From a Cowork task:** "Ask Claude to build what you need" (e.g. "Build me a dashboard that shows open tasks by project, pulling from Asana and Linear."). "When you describe the artifact, mention the connected apps or local files Claude should use. The result saves automatically to the Artifacts view."

**From the Artifacts view:** "Select 'Artifacts' from the sidebar → Click 'New artifact' in the top right → Select 'Create Cowork artifact.'" → "A new session opens with a starting prompt, and Claude asks a few questions about your connectors and what you want to build."

### 3.3 Refresh behavior

> "When you open a live artifact, it pulls fresh data from your connected apps. Most of the time you won't need to refresh manually, as **a short cache holds recent data so the artifact loads quickly, and it re-queries your connected apps on its own.** If you want to force new data, use the refresh button in the artifact's header."

### 3.4 Version history

> "Each time you iterate on a live artifact with Claude, the previous version is saved. Open the artifact's version history to:
> - See how the artifact has changed over time.
> - Compare an earlier version with the current one.
> - Restore an earlier version if an update didn't work out."

### 3.5 Sharing (Team/Enterprise only)

> "Sharing live artifacts is available on Team and Enterprise plans. On Pro and Max plans, live artifacts can't be shared or published."

Flow: open artifact → "Share" button in header → "Share & copy link" → send link to org members; opens in Claude Desktop; "Import from link" at top of Artifacts view.

Rules:
- "**Sharing stays within your organization.** There are no external or public links and no per-person recipient selection. Anyone in your organization who has the link can open the artifact."
- "**Shared artifacts use the viewer's access, not yours.** When someone opens your artifact, it connects to their connectors and data sources. If they don't have access to an underlying data source, that part of the artifact shows an error instead of your data."

### 3.6 Storage & permissions

- "**Local, not remote.** Live artifacts live on your computer. If you switch devices, they don't come with you."
- "**Live artifacts use your connectors without asking.** Live artifacts can only use the connectors you approved during creation or update. However, artifacts don't ask for permission before using connectors, even if your session mode would normally require approval. Use care when creating live artifacts that use connectors that can make changes to your data."

### 3.7 Clone checklist — live artifacts

- [ ] HTML-dashboard artifact type, persisted with a "Cowork" label in an Artifacts view (desktop only).
- [ ] Creation path from task (auto-save on build) and from Artifacts view ("Create Cowork artifact" → new session + connector questions).
- [ ] On-open refresh pipeline: short cache + automatic re-query of connectors/local files; manual refresh button in header.
- [ ] Version history: snapshot per update; compare + restore.
- [ ] Org-internal share links (no public links); renderer runs with viewer's connector grants; per-section error surfaces when viewer lacks source access.
- [ ] Connector permission model for artifacts: grants pinned at creation/update time; no per-use permission prompts even in approval-requiring modes.
- [ ] Local-only storage (per-device), excluded from cloud sync.

---

## 4. Connectors

Source: [Use connectors to extend Claude's capabilities](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities).

### 4.1 What they are / how implemented

> "Connectors let Claude access your apps and services, retrieve your data, and take actions within connected services. Claude inherits each person's permissions from the connected service."
> "Connectors work across Claude, Claude Desktop, Claude Code, and the API (via the **MCP Connector**)."
> "You can find available connectors in the Connectors Directory, where each connector has a page detailing its use cases, read/write capabilities, and availability. **You can also add custom connectors or connect to any service that supports MCP.**"

So: connectors are MCP servers. Directory connectors are Anthropic-hosted/curated; custom connectors are remote MCP endpoints pointed at user URLs.

### 4.2 Auth

- Directory connectors: "Follow the authentication prompts to grant Claude access to your account" (OAuth against the service).
- Custom connectors: "Enter advanced settings (OAuth Client ID and secret) if desired" — i.e. custom connector OAuth can be configured with client ID/secret.
- Team/Enterprise: "an Owner or Primary Owner needs to enable them for the organization... Each person still needs to authenticate individually before they can use it." Enterprise-managed auth: "you authorize a connector once for your entire organization, and your team inherits access automatically on first login" (beta).
- Verified-domain restriction: Enterprises can block connecting services on their verified domains to accounts outside the org.

### 4.3 Per-tool permissions

> "Navigate to **Customize > Connectors**. Select the connector to see **Tool permissions**. The permissions will be categorized by type (for example, read-only tools, write/delete tools). For each permission category or individual permission, select **Always allow, Needs approval, or Blocked**."

- Org-level action restrictions (Owners, Team/Enterprise): restrict write/delete org-wide, "individual users can't override it."
- "Restricting actions in Claude never grants more access than the source system permits — it only narrows it."
- Per-conversation: toggle connectors on/off via "+" menu; "Tool access" setting: **Auto** (default) vs **On demand** ("If you have 10 or more connectors active, consider switching to On demand").

### 4.4 Custom connectors (remote MCP)

> "Custom connectors using remote MCP are available on Claude, Cowork, and Claude Desktop for users on free, Pro, Max, Team, and Enterprise plans. Free users are limited to one custom connector."

> "Custom connectors connect to your MCP server **from Anthropic's cloud, not from your local device. Your server must be reachable over the public internet.** If it's behind a firewall or on a private network, see ... for network requirements and private network options."

> "Custom connectors (remote MCP servers) are reached from Anthropic's cloud infrastructure, not from your local machine. This is true even if you're using Cowork or Claude Desktop, which run locally on your computer."

Fix for firewalled servers: "allowlist Anthropic's IP ranges in your firewall to create a secure outbound-only connection from your network."

Add flow: Customize > Connectors → "+" → "Add custom connector" → name + URL → optional OAuth client ID/secret → Add → same connection process as directory connectors.

### 4.5 Interactive connectors

> "Some connectors are interactive and can render live interfaces—like dashboards, task boards, and design tools—directly within your conversation. Look for the **Interactive** badge in the Connectors Directory to find connectors with this capability."

### 4.6 Other constraints

- "For Team and Enterprise plans: ... Connectors are only available in private projects. Chats with synced content can't be shared."
- Encryption: "All data transfers are encrypted."
- Suggested-apps behavior: "Once you've connected an app, Claude can bring it into a conversation on its own when it fits what you're asking for" (see [How Claude suggests connected apps](https://support.claude.com/en/articles/14730684-how-claude-suggests-connected-apps)).

### 4.7 Clone checklist — connectors

- [ ] MCP-based connector runtime: directory connectors (curated server definitions) + custom remote-MCP connectors (URL + optional OAuth client ID/secret).
- [ ] OAuth flows (individual + org-managed), token storage server-side (never in sandbox), per-user grants.
- [ ] Per-tool permission matrix: Always allow / Needs approval / Blocked, grouped read-only vs write/delete; org-level action restrictions that override individual settings.
- [ ] Connector calls routed from server side (cloud), with cloud reachability requirement for custom servers.
- [ ] Tool-access modes: Auto vs On demand (10+ connectors threshold).
- [ ] Interactive connector surfaces (embedded live UIs in conversation).
- [ ] Private-projects-only enforcement for connectors on Team/Enterprise; no sharing of chats with synced content.
- [ ] Auto-suggestion of connected apps in conversation when relevant.

---

## 5. Plugin format (exact, from the repo)

Sources: [knowledge-work-plugins README](https://github.com/anthropics/knowledge-work-plugins), repo tree via GitHub API, raw files (all paths below verified against the actual tree, `main` branch).

### 5.1 High-level structure (README verbatim)

> "Every plugin follows the same structure:
> ```
> plugin-name/
> ├── .claude-plugin/plugin.json   # Manifest
> ├── .mcp.json                    # Tool connections
> ├── commands/                    # Slash commands you invoke explicitly
> └── skills/                      # Domain knowledge Claude draws on automatically
> ```"
> "Every component is file-based — markdown and JSON, no code, no infrastructure, no build steps."

Observations from the real tree:
- `productivity` has **no** `commands/` dir; `product-management` has `commands/`. Both are optional.
- No `subagents/` directory exists anywhere in the repo yet (blog announces sub-agents as a bundle component; not present in the open-source collection).
- Skills may contain `references/`, `scripts/`, `examples/`, `LICENSE.txt`, `requirements.txt`.
- Each plugin dir also ships `README.md`, `CONNECTORS.md`, `LICENSE`.
- Root repo has `.claude-plugin/marketplace.json` (the marketplace index).

### 5.2 Manifest — `.claude-plugin/plugin.json`

`productivity/.claude-plugin/plugin.json` (raw):
```json
{
  "name": "productivity",
  "version": "1.3.0",
  "description": "Manage tasks, plan your day, and build up memory of important context about your work. Syncs with your calendar, email, and chat to keep everything organized and on track.",
  "author": {
    "name": "Anthropic"
  }
}
```

`product-management/.claude-plugin/plugin.json` (raw) — identical shape:
```json
{
  "name": "product-management",
  "version": "1.2.0",
  "description": "Write feature specs, plan roadmaps, and synthesize user research faster. Keep stakeholders updated and stay ahead of the competitive landscape.",
  "author": {
    "name": "Anthropic"
  }
}
```

**Manifest fields observed:** `name` (slug, used in slash-command namespace e.g. `/product-management:brainstorm`), `version` (semver), `description`, `author.name`. No `commands`, `skills`, or `mcp` arrays — components are discovered from directories, not declared in the manifest.

### 5.3 Tool connections — `.mcp.json`

`productivity/.mcp.json` (raw):
```json
{
  "mcpServers": {
    "slack": {
      "type": "http",
      "url": "https://mcp.slack.com/mcp",
      "oauth": {
        "clientId": "1601185624273.8899143856786",
        "callbackPort": 3118
      }
    },
    "notion": {
      "type": "http",
      "url": "https://mcp.notion.com/mcp"
    },
    "asana": {
      "type": "http",
      "url": "https://mcp.asana.com/v2/mcp"
    },
    "linear": {
      "type": "http",
      "url": "https://mcp.linear.app/mcp"
    },
    "atlassian": {
      "type": "http",
      "url": "https://mcp.atlassian.com/v1/mcp"
    },
    "monday": {
      "type": "http",
      "url": "https://mcp.monday.com/mcp"
    },
    "clickup": {
      "type": "http",
      "url": "https://mcp.clickup.com/mcp"
    },
    "google calendar": {
      "type": "http",
      "url": ""
    },
    "gmail": {
      "type": "http",
      "url": ""
    }
  }
}
```

Key facts:
- Schema: top-level `mcpServers` object; each server: `type: "http"` (remote MCP over HTTP), `url`, optional `oauth: { clientId, callbackPort }`.
- **Empty `url` = built-in Anthropic connector** ("google calendar", "gmail" here) — the plugin declares intent, and Claude binds the platform's built-in connector of that name.
- `callbackPort` (e.g. 3118 for Slack) suggests local OAuth callback handling in the desktop app during connect.

### 5.4 Slash commands — `commands/<name>.md`

`product-management/commands/brainstorm.md` (raw, head — full file is long; frontmatter is the format contract):
```markdown
---
description: Brainstorm a product idea, problem space, or strategic question with a sharp thinking partner
argument-hint: "<topic, problem, or idea to explore>"
---

# /brainstorm

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Brainstorm a product topic with a sharp, opinionated thinking partner. ...

## Usage

```
/brainstorm $ARGUMENTS
```
```

Command file contract:
- Filename → command name (`brainstorm.md` → `/product-management:brainstorm` — plugin name is the namespace prefix; README shows `/sales:call-prep`, `/data:write-query`).
- YAML frontmatter: `description` (shown in command menu), `argument-hint` (placeholder for the argument the user supplies; referenced as `$ARGUMENTS` in body).
- Body is a full agentic instruction document: usage, workflow steps, decision rules, session rhythm, follow-ups.
- Commands are user-invoked explicitly (README: "slash commands you invoke explicitly" vs skills "Claude draws on automatically").

### 5.5 Skills — `skills/<name>/SKILL.md`

`productivity/skills/task-management/SKILL.md` (raw, head):
```markdown
---
name: task-management
description: Simple task management using a shared TASKS.md file. Reference this when the user asks about their tasks, wants to add/complete tasks, or needs help tracking commitments.
user-invocable: false
---

# Task Management

Tasks are tracked in a simple `TASKS.md` file that both you and the user can edit.
...
## Dashboard Setup (First Run)
...
1. Check if `dashboard.html` exists in the current working directory
2. If not, copy it from `${CLAUDE_PLUGIN_ROOT}/skills/dashboard.html` to the current working directory
3. Inform the user: "I've added the dashboard. Run `/productivity:start` to set up the full system."
...
```

Skill file contract:
- `skills/<slug>/SKILL.md` with YAML frontmatter: `name`, `description` (when to use — triggers automatic activation), `user-invocable` (false = auto-drawn knowledge, not a user command).
- Body: markdown instructions; skills are loaded automatically "when relevant".
- `${CLAUDE_PLUGIN_ROOT}` env var → root of installed plugin, so skills can reference sibling assets (e.g. `dashboard.html`).
- Skills may carry `references/*.md` (deep docs), `scripts/*` (e.g. Python helpers with `requirements.txt`), `LICENSE.txt`.

### 5.6 Tool-agnostic connector references — `CONNECTORS.md`

`productivity/CONNECTORS.md` (verbatim key section):
> "Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `~~project tracker` might mean Asana, Linear, Jira, or any other project tracker with an MCP server."
> "Plugins are **tool-agnostic** — they describe workflows in terms of categories (chat, project tracker, knowledge base, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works."

Category table (productivity): chat `~~chat` (Slack; alt: Teams, Discord), email `~~email` (M365), calendar `~~calendar` (M365), knowledge base `~~knowledge base` (Notion; alt: Confluence, Guru, Coda), project tracker `~~project tracker` (Asana, Linear, Atlassian, monday, ClickUp; alt: Shortcut, Basecamp, Wrike), office suite `~~office suite` (M365).

### 5.7 Marketplace index — `.claude-plugin/marketplace.json`

Root `marketplace.json` (raw head):
```json
{
  "name": "knowledge-work-plugins",
  "owner": {
    "name": "Anthropic"
  },
  "plugins": [
    {
      "name": "productivity",
      "displayName": "Productivity",
      "source": "./productivity",
      "description": "Manage tasks, plan your day, and build up memory of important context about your work. Syncs with your calendar, email, and chat to keep everything organized and on track."
    },
    ...
    {
      "name": "slack-by-salesforce",
      "displayName": "Slack",
      "source": "./partner-built/slack",
      "description": "Slack integration for searching messages, sending communications, managing canvases, and more",
      "author": {
        "name": "Salesforce"
      }
    }
  ]
}
```

Marketplace entry fields: `name`, `displayName`, `source` (relative dir), `description`, optional `author{name}` (for partner-built plugins). Partner-built plugins live in a `partner-built/` subdir.

### 5.8 Install & lifecycle (README + blog)

- Cowork: "Install plugins from [claude.com/plugins](https://claude.com/plugins/)."
- Claude Code: `claude plugin marketplace add anthropics/knowledge-work-plugins` then `claude plugin install sales@knowledge-work-plugins`.
- "Once installed, plugins activate automatically. Skills fire when relevant, and slash commands are available in your session (e.g., `/sales:call-prep`, `/data:write-query`)."
- Blog: "Every component of plugins (skills, connectors, slash commands, and sub-agents) is file-based, so plugins are easy to build, edit, and share."
- Blog: "Plugins are currently saved locally to your machine. Better support for org-wide sharing and management (support for private plugin marketplaces, etc.) are coming in the weeks ahead."
- 11 open-source plugins: Productivity, Enterprise search, Plugin Create/Customize, Sales, Finance, Data, Legal, Marketing, Customer support, Product management, Biology research.

### 5.9 Clone checklist — plugin format

- [ ] Loader for the exact layout: `.claude-plugin/plugin.json` manifest (name/version/description/author), `.mcp.json`, `commands/`, `skills/`.
- [ ] Manifest discovery by convention (no component lists in manifest).
- [ ] `.mcp.json` parser supporting `type: "http"`, `url`, `oauth.clientId`/`callbackPort`, and empty-URL entries bound to built-in connectors by name.
- [ ] Commands: `commands/*.md` → slash commands namespaced `/<plugin>:<name>`; frontmatter `description` + `argument-hint`; `$ARGUMENTS` injection.
- [ ] Skills: `skills/*/SKILL.md` with `name`/`description`/`user-invocable` frontmatter; auto-activation by relevance; `${CLAUDE_PLUGIN_ROOT}` resolution; support `references/` and `scripts/` assets.
- [ ] `~~category` placeholder resolution against connected MCP servers (tool-agnostic commands/skills).
- [ ] Marketplace manifest: `name`, `owner`, `plugins[]` with `source` relative paths, optional per-plugin `author`.
- [ ] Install flows: marketplace add + plugin install (CLI-style), claude.com/plugins (GUI), local file upload; local storage of installed plugins.
- [ ] Local MCP servers from plugins only in local sessions (not cloud); MDM disable flag (`isLocalDevMcpEnabled`).

---

## 6. The desktop ↔ cloud bridge

Sources: [architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview), [Get started](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork).

### 6.1 The model: "Claude reaches through the desktop app"

> "When a session in the cloud needs something on the user's device, like a local file or the browser, the request goes through the Claude Desktop app on that device **over an Anthropic-brokered connection**. Local file access is limited to folders the member has connected on the desktop, and **each local tool call is checked against the member's permissions before it runs**. If the desktop app is offline, a session in the cloud can't reach the device."

> "When a task needs something on your computer, like a local file or your browser, Claude reaches it through the Claude Desktop app on that computer." (Get Started)

### 6.2 Data flow implications

> "Because a session in the cloud runs on Anthropic's servers, the agent's work, including any local files it opens through the desktop app, is processed on Anthropic's servers rather than staying on the device."

> "Sessions keep running even when the desktop app is closed or your computer is asleep. If your task uses local files, your browser, or your computer, keep the desktop app open so Claude can reach them." (Get Started)

So: cloud agent → Anthropic-brokered channel → desktop app → local file system / browser / computer. Desktop offline ⇒ bridge unavailable, cloud session continues but without local tools.

### 6.3 What the bridge exposes

- **Local files:** "only for folders the member has connected, and only while the app is online" (FAQ). "Local file access is limited to folders the member has connected on the desktop."
- **Browser/computer use:** "For local file access, browser use, and computer use: The Claude Desktop app for macOS or Windows, open and connected." Browser actions run via Claude in Chrome ("Claude can open Chrome and work on websites—clicking, typing, navigating, and filling forms").
- **Desktop extensions:** two kinds named in the MDM docs — "MCPB and DXT extension servers" (`isDesktopExtensionEnabled`). These are the desktop-side extension server protocols the bridge can invoke.
- **Local MCP servers:** "Local MCP servers don't run in sessions in the cloud" — the bridge does NOT proxy arbitrary local MCPs into cloud sessions. With `isLocalDevMcpEnabled=false`, "only the folder-limited desktop file tools remain available to sessions in the cloud."

### 6.4 Permission gating on the bridge

- "each local tool call is checked against the member's permissions before it runs" (device side).
- Org controls apply through the app: "The device-level MDM keys above govern the Claude Desktop app, so they also apply to what a session in the cloud can reach through the app."
- Cloud org controls additionally gate cloud-side approval prompts for permission-gated tool calls (fresh approval per call when "always allow" is disabled; trusted-device enrollment + recent sign-in can be required).

### 6.5 Clone checklist — desktop↔cloud bridge

- [ ] Persistent, brokered connection between cloud session and desktop app (Anthropic's is server-relayed; clone could use WebSocket + authenticated relay; must survive laptop sleep on the server side, not the client).
- [ ] Desktop-side tool surface: connected-folder file tools, browser/Chrome automation, computer-use, MCPB + DXT extension servers.
- [ ] Folder-scoped access enforcement on device + per-call permission check before execution.
- [ ] Cloud-side visibility: session must keep running when device offline; local tools surface as unavailable.
- [ ] No local-MCP proxying into cloud sessions; only built-in desktop tool types cross the bridge.
- [ ] Approval orchestration across the bridge (cloud-side approval prompts for local tool calls).

---

## 7. Cross-cutting: approval modes, permissions, surface matrix

Source: [Get started](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork).

**Three permission modes** (mode selector in chat box):

| Mode | Read-only tools | Write/delete tools |
|------|-----------------|--------------------|
| **Manual** ("Ask before acting") | Approved | Asks for permission |
| **Auto** (Pro/Max only) | Approved | "Claude decides" — safety review each action; blocks unsafe; degrades to manual on repeated blocks |
| **Skip** ("Act without asking") | Approved | Approved |

> "Auto mode applies to all of your existing connectors, plugins, Claude in Chrome, and some Cowork actions like fetching websites. Because Claude does this extra checking for you, **auto mode consumes more of your usage limit than the other modes**."
> "We tested Claude's safety check extensively before releasing it, including working with outside security experts who tried to sneak dangerous actions past it." (Auto-mode safety reviewer: checks data exfiltration / prompt injection.)

**Other behaviors:**
- Deletion protection: "Claude requires your explicit permission before permanently deleting any files."
- Global instructions: Settings > Cowork > Global instructions (apply to every session).
- Folder instructions: project-specific context when a local folder is selected; "Claude can also update these on its own during a session."
- Memory: chat memory doesn't carry into Cowork; "Within Cowork, memory is supported in projects only."
- Projects: persistent self-contained workspaces with own files, links, instructions, memory.
- Outputs: Excel w/ formulas, PPTX, formatted docs; "Edit with Claude" in-place draft editing; Claude for Excel/PowerPoint follow-ups.
- Deletion of tasks: immediate removal from history, "deleted from our backend storage systems within 30 days."
- Usage: Cowork consumes more usage than chat; doubled-Cowork-limits promo ran through Aug 5, 2026 (blog).

**Surface availability (July 2026 launch):** web (claude.ai home screen) + mobile (sidebar, iOS/Android) + desktop (full experience with local files/browser); "sessions and files live with your Claude account and follow you across desktop, web, and mobile"; "Start a task at your desk, check on it from your phone, and pick up the finished output anywhere"; "work continues in the background... Scheduled tasks now run with no device online" (blog). "Desktop remains the place for deep work, and it's the full Cowork experience."

**"Setting up Claude's workspace"** message = Cowork updating to latest version at session start (troubleshooting section).

---

## 8. Gaps (not documented publicly)

- **Sandbox runtime internals:** what image/OS, how the "mandatory proxy" and allowlist are implemented, sandbox resource limits (CPU/RAM/disk), timeout/length caps on long-running tasks ("long-running tasks" claim has no numeric limits).
- **Egress policy mechanics:** how the allowlist is org-configured (UI only mentioned: "network-access policy"), default allowlist contents (web search/fetch exemptions: "Network egress permissions don't apply to the web fetch or web search tools or MCPs" — Get Started "Important" note).
- **Desktop bridge protocol:** the "Anthropic-brokered connection" protocol details (transport, auth handshake, request types) — closed.
- **Scheduler backend:** cron semantics, timezone handling, run retries, max concurrent runs, notification delivery (docs only say "review results"; no push/email documented).
- **Live artifact internals:** exact storage format/location on disk, how "short cache" TTL works, artifact↔connector grant pinning mechanism, HTML sandboxing.
- **Auto-mode safety checker:** blocklist heuristics, thresholds for "keeps running into blocks" fallback.
- **Usage metering:** precise per-mode token multipliers ("consumes more of your usage allocation").
- **Credentials store:** where connector tokens live server-side, rotation, Enterprise-managed-auth mechanics.
- **Sub-agents:** announced as a plugin component (blog) but no sub-agents/ dir exists in the open-source repo — format unspecified.
- **MCPB / DXT extension server protocols:** names only, no spec.
- **Plan rollout:** cloud execution rollout schedule (Max first, "Pro over the next several weeks").

---

## 9. Master "what a clone must implement" checklist

**Runtime/agent core**
- [ ] Agent loop with plan → subtasks → parallel workstreams → deliverable flow.
- [ ] Session-per-sandbox ephemeral execution env (cloud) + local VM fallback (Virtualization.framework/Hyper-V).
- [ ] Server-side connector call routing (tokens never in sandbox).
- [ ] Session state/files persisted to account storage, resumable across surfaces.

**Security/permissions**
- [ ] Org egress policy + out-of-band egress proxy + private/metadata address blocking.
- [ ] Connected-folder file scope; per-call permission checks (local & via bridge).
- [ ] Approval modes Manual/Auto/Skip + per-tool Always/Needs-approval/Blocked + org action restrictions + deletion protection + trusted-device gate.
- [ ] Tenant isolation on all stored records; Compliance API + OTel capture.

**Cloud-only features**
- [ ] Scheduled tasks (cadence: hourly/daily/weekly/weekdays/manual; run-per-session; local-only flag; pause/resume/delete/edit/run-now; `/schedule`).
- [ ] Live artifacts (HTML dashboards, auto-refresh w/ cache, version history + restore, org share links w/ viewer-scoped grants, no-permission-ask connector use, local-only storage).
- [ ] Desktop bridge (brokered persistent channel; folder files/browser/computer-use/MCPB/DXT surfaces; offline-tolerant).

**Integration surface**
- [ ] MCP connector runtime (directory + custom remote MCP with OAuth, free-plan 1-custom-connector cap, interactive connectors).
- [ ] Plugin system per §5.9 (manifest-by-convention, .mcp.json, commands/, skills/, `~~category` placeholders, marketplace.json, local install storage).

**Surfaces**
- [ ] Chat+Cowork unified home (message box mode switch), web + desktop + mobile continuity, Artifacts view, Scheduled view, Projects workspaces, global instructions.

---

*End of deep dive. All quotes verbatim from the cited sources; repo paths/contents verified against `anthropics/knowledge-work-plugins` main branch (tree SHA `5ee4541fa29fc41808ef176cf272ff0ccc921246`).*
