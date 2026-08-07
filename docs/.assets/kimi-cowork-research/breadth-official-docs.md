# Breadth Scan: Claude Cowork vs Kimi Work — Official Docs & Help Centers

**Stage 1 (breadth) research for building a from-scratch clone.**
**Angle:** Official docs, product pages, help centers. Fetched 2026-08-06.
**Scope covered:** Anthropic product page + help center (9 articles incl. architecture overview), Anthropic connector directory, Moonshot Kimi product pages (Work, Claw, WebBridge, Dashboard), Kimi help center (Work FAQ, Overview, Goal Mode, Plugin Center, Release Notes, Scheduled Tasks, Features).

---

## TL;DR architecture contrast (feeds directly into clone design)

| | **Claude Cowork** | **Kimi Work** |
|---|---|---|
| Execution home | Cloud-first: agent loop + code run in per-session sandboxes on Anthropic servers; desktop app is a *remote* that reaches local files/browser | Local-first: agent + code run on the user's machine; data stays on-device |
| Scheduling | Cloud cron — runs with zero devices online | Local cron — app must be open; missed triggers are lost |
| Artifacts | Session deliverables (downloadable) + desktop-only "live artifacts" (HTML dashboards w/ refresh + version history) | Files written back into mounted local folder + Widgets/Dashboard (pinnable desktop windows) + live PPT editor |
| Files | Folder-based grants via desktop app; code runs in isolated Linux VM | Mounted project folders; ask-permission vs allow-all modes; Python/shell executed locally |
| Connectors | ~300+ MCP connectors in directory (server-side, Anthropic cloud); plugins bundle skills+connectors+sub-agents | Plugin Center: built-in finance/legal/academic DB plugins + curated app plugins (Notion, Canva, WPS…), MCP/OAuth based |
| Pricing | Paid plans only (Pro $17-20, Max $100/$200, Team $20/seat, Enterprise custom) | Free tier (limited credits, 2 scheduled tasks); paid tiers up to 25 scheduled tasks |

---

## Dimension 1 — Live artifacts

### Claude Cowork

- **Output types produced:** Word (.docx/.doc), PDF, plain text, Markdown, HTML, JSON, CSV, TSV, Excel (.xlsx/.xls/.xlsm), PowerPoint (.pptx/.ppt), images (png/jpg/jpeg/gif/svg/webp), YAML/XML/TOML, Jupyter (.ipynb), and code files in "pretty much any programming language". (claude.com/product/cowork FAQ)
- **"Professional outputs"**: Excel files with *working formulas* (e.g. VLOOKUP, conditional formatting, multiple tabs — "not just CSVs that need fixing"), PowerPoint decks, formatted documents. (support.claude.com/en/articles/13345190)
- **Where outputs land:** "Delivers finished outputs to your session, where you can preview and download them." Session files are saved to the Claude account (cloud) and follow you across desktop/web/mobile. (support.claude.com/en/articles/13345190)
- **Edit drafts in place:** highlight any text in a Claude-drafted Markdown doc → "Edit with Claude" → edit happens right at the marked spot, no need to describe the section. (support.claude.com/en/articles/13345190)
- **Live artifacts (the flagship artifact feature):**
  - Persistent, interactive **HTML dashboards** Claude builds in Cowork — trackers, dashboards, comparison tools, morning briefs (Slack mentions + calendar + open PRs). (support.claude.com/en/articles/14729249)
  - Created two ways: (a) just ask in a Cowork task ("Build me a dashboard… pulling from Asana and Linear"), or (b) Artifacts sidebar → "New artifact" → "Create Cowork artifact" (Claude asks questions about connectors first).
  - **Desktop-only** (macOS/Windows/Linux-beta). Do NOT appear on web/mobile. Live artifacts are **local, not remote** — "they live on your computer. If you switch devices, they don't come with you." (support.claude.com/en/articles/14729249)
  - **Refresh with current data:** on open, they pull fresh data from connected apps (short cache for speed, re-queries automatically, manual refresh button). (support.claude.com/en/articles/14729249)
  - **Version history:** every iteration saves a version; compare and restore. (support.claude.com/en/articles/14729249)
  - **Sharing:** Team/Enterprise only, org-internal links, opens in Claude Desktop, viewer's *own* connectors/access are used (not the creator's). Pro/Max can't share. (support.claude.com/en/articles/14729249)
  - **Security caveat:** live artifacts use connectors **without asking permission**, even in modes that normally require approval. (support.claude.com/en/articles/14729249)
- **Chat artifacts vs Cowork artifacts** appear together in the Artifacts view; live ones carry a "Cowork" label. (support.claude.com/en/articles/14729249)
- **Spreadsheets/slides editable onward** with Claude for Excel and Claude for PowerPoint add-ins. (support.claude.com/en/articles/13345190)

### Kimi Work

- **Output types produced:** "code files, PDFs, PowerPoint decks, interactive reports, Excel spreadsheets, Word documents, or even websites." (kimi.com/resources/kimi-work-introduction)
- **Where outputs land:** once a local folder is mounted, results are **written straight back into that folder** ("nothing has to be downloaded, renamed, or swapped back into place by hand"); also delivered into the project workspace. (kimi.com/resources/kimi-work-introduction)
- **PPT slide editor (live):** release 3.1.6 (2026-07-29) — open and edit slides right in the workspace; "changes take effect immediately." (kimi.com/help/kimi-work/release-notes)
- **Widgets + Dashboard (the flagship artifact feature):**
  - Widgets = interactive visual components generated *through conversation* (weather, countdown, market watch, task boards). (kimi.com/resources/kimi-work-dashboard)
  - **Annotation refinement:** select a specific area of a rendered widget, request changes in natural language; each revision builds on the existing result. (kimi.com/resources/kimi-work-dashboard)
  - **Dashboard** = cross-session persistent home for widgets (survives the original conversation). (kimi.com/resources/kimi-work-dashboard)
  - **Pin to Desktop:** a widget can be pinned as an independent, always-visible desktop window while you work in other apps (3.1.7 loosened "stay on top" behavior). (kimi.com/resources/kimi-work-dashboard, kimi.com/help/kimi-work/release-notes)
- **File preview + screenshot annotation:** annotate files in the preview area and in the browser; finished annotations can be sent to the Agent for revision. (kimi.com/help/kimi-work/release-notes)
- **Kimi web-side generators (available to Work via inherited Skills):** Slides (presentations), Sheets (Excel formulas, pivots, charts), Docs, Websites builder, Deep Research (multi-format reports). (kimi.com nav + features pages)

---

## Dimension 2 — Scheduled tasks

### Claude Cowork

- **Creation — two paths:**
  1. **Natural language / Create with Claude:** type `/schedule` in any Cowork task, or "Scheduled" sidebar → "New task" → "Create with Claude". Claude asks clarifying questions (multiple-choice responses), then outputs the task name, schedule, and behavior; you confirm by clicking "Schedule". (support.claude.com/en/articles/13854387)
  2. **Manual:** "Scheduled" sidebar → "Set up manually" → modal with: task name, prompt, approval mode, frequency (**hourly, daily, weekly, weekdays, or manually**), optional model choice, optional folder. (support.claude.com/en/articles/13854387)
- **Execution model:** **cloud cron** — "Scheduled tasks run remotely, so they run on their cadence even when your computer is asleep or the Claude Desktop app is closed." No device needed. (support.claude.com/en/articles/13854387)
- **Key constraint:** scheduled tasks "work with your connectors and the files saved to your Claude account. **They can't be tied to a folder on your computer**." If a scheduled task requires local files/apps, "it will only run locally." (support.claude.com/en/articles/13854387)
- **Each run = its own Cowork session**; review upcoming and past runs from the "Scheduled" page on any surface; pause/resume/delete/run-on-demand supported. (support.claude.com/en/articles/13854387)
- **Available:** all paid plans (Pro, Max, Team, Enterprise); web/mobile beta rollout began with Max. (support.claude.com/en/articles/13854387)
- **Safety guidance:** scheduled tasks run while you're away — Anthropic explicitly warns to start simple, avoid sensitive data/consequential actions, review outputs after each run, pause unused tasks. (support.claude.com/en/articles/13364135)
- **Limits found:** NO documented cap on number of scheduled tasks, no documented max frequency/concurrency. Only the general statement that Cowork "consumes limits faster than Chat" (usage allocation, not task count). (support.claude.com/en/articles/13345190, 13854387)

### Kimi Work

- **Creation — two paths:**
  1. **Manual:** "Scheduled Tasks" left sidebar → "Create" → task name, description, execution clock time, frequency **Once/Daily/Weekly/Monthly**. (kimi.com/resources/kimi-work-introduction)
  2. **Natural language:** "Send a task and let Kimi Work create the scheduled task directly" — from chat, converted automatically. (kimi.com/resources/kimi-work-introduction)
- **Execution model:** **local cron** — "scheduled tasks run **locally** and only execute while the **app is open**. Triggers missed while your computer is asleep or shut down, or while the app is closed, are **not run retroactively**." (kimi.com/help/kimi-work/kimi-work-faq)
- **Built-in Cron engine** (product page): supports "LLM Agent Calls, Python/Shell executions, and more… daily, hourly, or conditionally". **"Keep Computer Awake" toggle** in settings for overnight runs. (kimi.com/products/kimi-work)
- **Contrast:** tasks created in the **Kimi web app** run **in the cloud** and don't need the client open. (kimi.com/help/kimi-work/kimi-work-faq)
- **Quotas — hard, documented per plan** (active tasks; no limit on creation): Free **2**, Go **6**, Pro **15**, Max **20**, Ultra **25**. Over-limit new tasks save as inactive; plan downgrades auto-pause overflow tasks. (kimi.com/help/features/scheduled-tasks)
- **Expiration defaults** (cloud tasks): daily +7 days, weekly +1 month, monthly +3 months. **Local desktop tasks are exempt** from expiration. (kimi.com/help/features/scheduled-tasks)
- **Task lifecycle:** on/off toggle, run-once-now, edit, delete; each run creates an unread notification with a result conversation (can continue with follow-ups, invoke plugins/skills with "/").
- **Skills integration:** scheduled tasks can invoke Skills (esp. finance Skills); install+test the Skill first. (kimi.com/help/features/scheduled-tasks)
- **Kimi Claw (cloud sibling product):** cloud-deployed OpenClaw with proactive scheduled tasks ("Every Friday at 5 PM, generate a weekly report…") via the pattern "At [time], do [task], output [format], follow [constraints]"; included with Allegretto plan and above; 24/7 uptime. (kimi.com/resources/kimi-claw-introduction)

---

## Dimension 3 — Local files

### Claude Cowork

- **Access model:** user **chooses folders** ("you choose the folders and tools. Claude can't reach anything else") — connected-folder rules enforced at the application layer. (claude.com/product/cowork, support.claude.com/en/articles/14479288)
- **Two execution environments (local session):**
  1. **Agent loop runs natively on the device** — conversation handling, file read/write in connected folders, web fetches, local plugin MCP servers; gated by application-layer permission system + org network egress settings.
  2. **Code execution runs in an isolated Linux VM** — separated by hypervisor (Apple Virtualization.framework on macOS, Hyper-V on Windows); the VM enforces its own network egress filtering, syscall restrictions, and per-session user isolation. (support.claude.com/en/articles/14479288)
- **Cloud sessions:** agent loop + code run on Anthropic servers in a per-session temporary sandbox (destroyed at session end). Local files are reached **through the Claude Desktop app over an Anthropic-brokered connection** — only folders the member connected, each local tool call checked against permissions, and **if the desktop app is offline the cloud session can't reach the device**. (support.claude.com/en/articles/14479288)
- **Sandbox network properties:** no access to private/internal/link-local/cloud-metadata addresses; mandatory egress proxy that the sandbox can't reconfigure (allowlist only); short-lived session-scoped credentials (expire within hours); connector tokens never enter the sandbox (connector calls are server-side). (support.claude.com/en/articles/14479288)
- **Privacy implications:** for cloud sessions, local files opened through the desktop app are **processed on Anthropic's servers**; conversation data isn't used for training (commercial commitments). For local sessions, **conversation history is stored locally on the user's computer** — NOT subject to standard data-retention policy and **can't be centrally managed or exported by admins**. (support.claude.com/en/articles/13455879, 14479288)
- **Deletion protection:** Claude requires explicit user approval before permanently deleting any file, in every permission mode. (support.claude.com/en/articles/13345190)
- **Permission modes (approval UX):** Manual (ask before acting) / Auto (Claude self-checks each action for safety — data exfiltration, prompt injection; consumes *more* usage; currently Pro/Max only) / Skip (no checks at all). (support.claude.com/en/articles/13345190)
- **Computer use (desktop automation):** research preview, Pro/Max only (NOT Team/Enterprise), desktop only; per-app permission prompts; app blocklist; screenshots taken; **no sandbox** between Claude and the screen; tool priority = connectors → browser (Claude in Chrome) → screen. (support.claude.com/en/articles/14128542)
- **Memory:** per get-started article, chat memory does NOT carry into Cowork; within Cowork, memory is supported in projects only. (Note: computer-use article says "Cowork has memory… excludes passwords/financial/health data" — docs inconsistent on this point.) (support.claude.com/en/articles/13345190 vs 14128542)
- **Global + folder instructions:** standing instructions per user (Settings > Cowork > Global instructions) and per-folder (Claude can update these itself during a session). (support.claude.com/en/articles/13345190)
- **EDR limitation:** the local VM is isolated from host security tools by design; cloud sessions run entirely outside endpoints — "EDR tools can't observe them either." (support.claude.com/en/articles/14479288)

### Kimi Work

- **Access model:** user **mounts/links a local folder** to a project ("project… linked to a folder… becomes the place Kimi Work reads from, writes to, and stores its files"); one-off tasks can skip the folder. Kimi can also organize/clean an entire folder in one click. (kimi.com/resources/kimi-work-introduction)
- **Permission model — two modes, chosen before the task:**
  - **"Request permission" (Ask permission):** prompts for explicit authorization before modifying, overwriting, or running code within local files — "Nothing happens without your consent."
  - **"Allow all" (Full access):** runs start-to-finish without interruption. (kimi.com/products/kimi-work, kimi.com/help/kimi-work/kimi-work-faq)
- **Execution is on-device:** "Runs Python and shell locally and processes local files, with data kept on-device" (vs Kimi web's cloud execution). "Kimi Work runs locally and executes code on the local machine, so files remain on the computer." (kimi.com/resources/kimi-work-introduction FAQ)
- **Long-horizon execution:** K2.6-powered — 13 hours continuous coding, 300 sub-agents in parallel, 4,000+ autonomous tool calls; Goal Mode runs up to 24 hours. (kimi.com/help/kimi-work/overview, /goal-mode)
- **System requirements:** macOS 12+ (Apple silicon only) / Windows 10+; storage-drive migration supported on Windows (3.1.6). (kimi.com/help/kimi-work/overview, /release-notes)
- **Browser access (WebBridge):** pairs a local service + browser extension; uses **Chrome DevTools Protocol** against the user's existing Chrome/Edge; "Everything runs locally, so your login sessions and page content never leave your device." (kimi.com/features/webbridge)
- **Projects:** sidebar includes Projects; goal-mode-style persistent context. (kimi.com/help/kimi-work/overview)

---

## Dimension 4 — MCP connectors and CLI tools

### Claude Cowork

- **Connector architecture:** directory connectors are **MCP-powered**; "powered by the Model Context Protocol" is stated on the connectors hub. (claude.com/connectors)
- **Directory scale:** claude.com/connectors paginates at 17+ pages — roughly **300+ connectors** (samples seen: Amplitude, Microsoft 365, Google Drive, Slack, Airtable, Salesforce-family, Adobe suite, Ahrefs, Apollo.io, Aiera, Affinity, 10x Genomics, ActiveCampaign, Airwallex, Aiwyn Tax, AllTrails, alphaXiv, AppFolio Realm-X, AdisInsight…). Third-party guides cite "38+ workplace tools" at the Feb 2026 enterprise launch and "30+"/"hundreds" today. (claude.com/connectors; pluginsforcowork.com/claudecoworkexpert CNBC coverage — third party)
- **Named connectors in official docs:** "Google Drive, Gmail, Slack, DocuSign, and many more" (plugins help article). Amplitude + Microsoft 365 + Google Drive + Slack appear in Cowork product-page marketing prompts. **FactSet appears only in third-party/CNBC coverage of the Feb 24, 2026 enterprise launch — could not verify in official docs during this scan.** (support.claude.com/en/articles/13837440; claude.com/product/cowork)
- **How they're installed/authorized:** browse directory in-app (+ menu or Customize > Connectors) → Connect/Install → OAuth auth flow with the service (each connector provider has own terms; OAuth presented at connect time). Connectors work across Claude, Desktop, Cowork, Code, and the API (via MCP Connector). (support.claude.com/en/articles/11176164)
- **Cowork-specific networking fact:** "In Cowork, connectors reach external services **through Anthropic's cloud, not through your local network**." Custom connectors must be reachable over the public internet from Anthropic's IP ranges (allowlist in firewall). (support.claude.com/en/articles/13837440, 11176164)
- **Free users:** limited to **one custom connector**; paid plans unrestricted. (support.claude.com/en/articles/11176164)
- **Action-level permissioning:** per-connector tool permissions — Always allow / Needs approval / Blocked, categorized (read-only vs write/delete); org-wide "Allow always for connector tools" setting off by default on Team/Enterprise (per-task approval required for write tools); source-system permissions always the outer bound. (support.claude.com/en/articles/11176164, 13455879)
- **Tool access modes:** Auto (default) vs On demand — "If you have 10 or more connectors active, consider switching to On demand." (support.claude.com/en/articles/11176164)
- **Interactive connectors:** some connectors render live UIs (dashboards, task boards, design tools) in-conversation ("Interactive" badge). (support.claude.com/en/articles/11176164)
- **Enterprise-managed auth (beta):** authorize a connector once org-wide; team inherits on first login. Verified-domain connector restriction available. (support.claude.com/en/articles/11176164)
- **Plugins:** bundle skills + connectors + sub-agents; **hooks and sub-agents run only in Cowork**; plugins may bundle local MCP servers (run on user's computer with normal program permissions); org plugin marketplaces with Installed by default/Available/Required/Not available states; MDM keys `isLocalDevMcpEnabled` (disable local MCP servers) and `isDesktopExtensionEnabled` (block MCPB/DXT extension servers); skill/plugin scanning on Enterprise. Anthropic-built plugins on GitHub: `anthropics/knowledge-work-plugins`. (support.claude.com/en/articles/13837440, 14479288, 13364135)
- **CLI/API:** Cowork itself exposes **no public CLI or API**. Related: Claude Code is the CLI product; MCP Connector (platform.claude.com) exposes connectors to the API. Monitoring surfaces: OpenTelemetry stream (tool calls, file access, approval decisions) and Compliance API (Cowork via mobile/web). (support.claude.com/en/articles/14477985; platform.claude.com)
- **Enterprise admin surface:** org-wide Cowork toggle; separate "Run Cowork in the cloud" toggle (Team: on by default; Enterprise: off by default, granted via custom roles/groups); network egress policy per org; require fresh approval / disable persistent always-allow; trusted-device enrollment; spend limits and usage analytics; company branding. (support.claude.com/en/articles/13455879)

### Kimi Work

- **Plugin Center (two buckets):**
  1. **Built-in professional database plugins:** Wind Financial Data Service, Hundsun Gildata, **S&P Global Market Intelligence**, IMF database, Straight Flush (Tonghuashun), Tianyancha, Huayu Yuandian. (kimi.com/help/kimi-work/plugin-center)
  2. **Curated external app plugins:** Baidu Netdisk, DingTalk, Feishu, **WPS**, **Canva**, **Notion**, **Cloudflare**, **Kimi Computer Use** (AI controls the desktop for system-level ops), **GitHub**, **Neon**, **Supabase**, and more. (kimi.com/help/kimi-work/plugin-center)
- **How they work technically:** "Plugins extend Kimi with external capabilities, built from **several MCPs connected through skills**." Accounts connect "through MCP, OAuth, or open-platform capabilities" — authorization scope defined by the connecting service; you can only connect accounts you own/are authorized for; uninstall anytime. (kimi.com/resources/kimi-work-introduction)
- **Install/use flow:** Plugins → browse Featured/Search → Install (some require OAuth) → type "/" in input → select plugin (e.g. `/Notion`). "Installing a plugin means Kimi can use it, not that it will be called automatically in every round." (kimi.com/resources/kimi-work-introduction)
- **Native data access (no plugin needed):** global equities, futures, indices (A-shares, HK, US), World Bank macro data (GDP, population, employment, trade), academic layer (journals, papers, preprints, dissertations, patents). (kimi.com/products/kimi-work, /resources/kimi-work-introduction)
- **Skills:** inherits online Kimi Agent's professional Skills (website building, PPT creation), supports third-party Skills and **uploading local Skills**; type "/" to use; "@" to add context. (kimi.com/help/kimi-work/overview)
- **Kimi Claw:** web-based SSH terminal into the cloud OpenClaw; 5,000+ ClawHub skills; 40GB cloud storage; "Restart/Auto-fix Kimi Claw" settings; file send/receive via plugin. (kimi.com/resources/kimi-claw-introduction)
- **CLI/API:** Kimi Work desktop exposes no public CLI. **Kimi Code** is the separate CLI/IDE agent (18 help articles; terminal + VS Code); **Kimi API** (platform.kimi.ai) is the model-level API. Kimi Work's kernel is Kimi Code. (kimi.com/help/kimi-code, /help/kimi-api)
- **Business tier:** "Kimi Business" enterprise plan exists (team management, workspaces) — 3 help articles; details thin in English. (kimi.com/help)

---

## Source citations

**Claude (Anthropic) — official:**
- https://claude.com/product/cowork (features, use cases, pricing: Pro $17/mo annual/$20 monthly, Max 5x $100, Max 20x $200, Team $20/seat, Enterprise; file-type FAQ; computer-use FAQ; enterprise notes)
- https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork (availability, cloud execution, approval modes Manual/Auto/Skip, global/folder instructions, usage limits, deletion protection, current limitations)
- https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview (cloud sandbox properties, local VM, egress proxy, credentials, MDM keys, EDR limits)
- https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-cowork (creation paths, frequencies, cloud execution, folder caveat)
- https://support.claude.com/en/articles/14729249-use-live-artifacts-in-claude-cowork (definition, creation, refresh, versioning, org sharing, limitations)
- https://support.claude.com/en/articles/13455879-cowork-for-team-and-enterprise-plans (admin toggles, cloud toggle defaults, connector approvals, compliance/OTel, local storage)
- https://support.claude.com/en/articles/13364135-use-cowork-safely (risk model, safety layers, scheduled-task guidance)
- https://support.claude.com/en/articles/13837440-use-plugins-in-cowork (plugin structure, marketplaces, cloud connector routing)
- https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities (directory, OAuth, per-tool permissions, custom connectors, tool access modes)
- https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork (computer use, permissions, blocklist, plan availability)
- https://claude.com/connectors (directory hub, MCP, paginated listing)

**Kimi (Moonshot AI) — official:**
- https://www.kimi.com/products/kimi-work (product page: local agent, cron engine, WebBridge, market data, FAQ)
- https://www.kimi.com/resources/kimi-work-introduction (full feature doc: Goal Mode, 300-agent swarm, plugins, scheduled tasks, use cases, FAQ incl. free tier + 2 scheduled tasks)
- https://www.kimi.com/resources/kimi-work-dashboard (Widgets/Dashboard/annotation/pinning)
- https://www.kimi.com/resources/kimi-claw-introduction (cloud OpenClaw, 40GB storage, 5,000+ skills, Allegretto+)
- https://www.kimi.com/features/webbridge (CDP-based local browser automation, privacy)
- https://www.kimi.com/help/kimi-work/kimi-work-faq (local scheduled task semantics, permission modes)
- https://www.kimi.com/help/kimi-work/overview (kernel=Kimi Code, K2.6, 13h/300 agents/4k tool calls, system requirements, launch June 3 2026)
- https://www.kimi.com/help/kimi-work/goal-mode (24h goal loop)
- https://www.kimi.com/help/kimi-work/plugin-center (built-in DB plugins + curated app plugins)
- https://www.kimi.com/help/kimi-work/release-notes (3.1.7 / 3.1.6: PPT slide editor, screenshot annotation, storage migration)
- https://www.kimi.com/help/features/scheduled-tasks (quotas Free 2 / Go 6 / Pro 15 / Max 20 / Ultra 25; expiration defaults; run semantics)

---

## Gaps identified (could NOT find in official docs)

1. **Claude Cowork scheduled-task limits:** no documented max number of tasks, max frequency, or concurrency limits. Anthropic only says Cowork consumes usage allocation faster than chat. (Clone-relevant: you'll have to set your own numbers.)
2. **Claude Cowork cloud sandbox specs:** no CPU/RAM/disk/timeout numbers for the cloud sandbox or the local VM; no file-size upload/artifact limits; no max parallel sub-agents number (marketing says "big projects split into chunks that run together" — no number).
3. **Claude Cowork API/CLI:** none exists publicly — no way to programmatically create sessions/tasks. Only OTel events + Compliance API as observability surfaces.
4. **Kimi Work pricing detail:** the membership/pricing page is JS-rendered — returned empty; exact Work-mode credit costs per tier unverified. Only the scheduled-task quota ladder (2/6/15/20/25) is documented.
5. **Kimi Work artifact storage internals:** where Widgets/Dashboard state is stored (local app data dir?), and whether dashboard state syncs across machines — undocumented.
6. **Kimi Work file-type support list:** no explicit allowed-extension list (unlike Claude's FAQ); only "PDF, Excel, Word, PPT, code files" examples.
7. **Kimi Work scheduled-task concurrency:** whether multiple scheduled tasks can run in parallel locally; no docs.
8. **FactSet / DocuSign connectors:** DocuSign named in official plugins article; **FactSet confirmed only via third-party/CNBC coverage** of the Feb 24, 2026 enterprise launch — not found on official pages in this scan (directory is paginated; full A–Z not enumerated here).
9. **Kimi Claw pricing:** "included with Allegretto & above" but no price; tier boundaries unverified.
10. **Both products: deletion/retention specifics** for scheduled-task outputs and cloud session files beyond "30 days backend deletion" (Claude) — no per-artifact retention controls documented.

---

## Surprises

- **Opposite execution philosophies:** Claude Cowork is *cloud-first* (work runs on Anthropic servers; the desktop app is a remote control for local resources), while Kimi Work is *local-first* (everything on-device, cloud only in the web product). A clone must pick a side — or architect a dual-mode like Claude (local session + cloud session toggles exist in enterprise settings).
- **Scheduling contrast is stark:** Claude scheduled tasks run with *zero* devices online; Kimi Work scheduled tasks die with the app closed and *never* replay missed triggers (though Kimi web tasks run in the cloud). This is likely the single biggest user-visible differentiator.
- **Claude live artifacts are desktop-only AND local AND org-sharable**; Kimi widgets are pinnable desktop windows with annotation-based refinement. Both are "artifacts" but completely different mechanics (HTML dashboard w/ connector refresh + versioning vs widget component + dashboard page).
- **Enterprise compliance contradiction in Claude's own docs:** product page says "Cowork activity is not yet captured in audit logs or Compliance API," while the architecture article says "Cowork via mobile and web IS captured in the Compliance API" — depends on plan/session type; don't hard-code one answer.
- **Memory documentation inconsistency (Claude):** get-started says memory doesn't carry into Cowork (projects only); computer-use article says "Cowork has memory." Untrustworthy as spec — verify against product behavior.
- **Kimi Work free tier exists with 2 scheduled tasks** — versus Claude Cowork being paid-only. Big pricing-surface difference for a clone (freemium vs premium-only).
- **Kimi's 300-agent swarm / 13-hour / 4,000-tool-call numbers are concrete and huge** — Claude markets "sub-agents" but publishes no comparable numbers.
- **Claude Auto-approval mode burns extra usage allocation** — a per-action safety screening is metered against quota; no equivalent metering documented for Kimi.
- **Kimi WebBridge keeps login sessions 100% on-device** (CDP against user's own browser) vs Claude's Claude-in-Chrome + server-side web fetch — very different privacy postures for web automation.
