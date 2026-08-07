# Stage 1 Breadth Scan — News Coverage + Product Teardowns
## Claude Cowork (Anthropic) vs Kimi Work (Moonshot AI)
### For building a from-scratch clone

**Researcher note (agent):** This is the news/teardown angle of a breadth scan. Primary sources (Anthropic blog + help center, Moonshot blog + official product page) were fetched directly; press coverage via Google News RSS + direct site fetches (WIRED, ZDNET, CNBC, SiliconANGLE, Fortune, TechCrunch, The Verge, Yahoo Finance). DuckDuckGo/Bing/Mojeek all CAPTCHA-blocked bots; Google News RSS was the working search path. Reddit/Facebook skipped per instructions. Fetched on 2026-08-06.

**TL;DR for the orchestrator:** Both products are "agentic coworker" desktop apps that clone the Claude Code agent loop for knowledge workers. The single most important architectural fact: **Cowork pivoted in July 2026 from local-VM execution to cloud sessions (isolated envs on Anthropic servers) with the desktop app acting as a bridge to local files/browser; Kimi Work is the opposite — local-first execution (files, Python, browser via WebBridge) with cloud models, and scheduled tasks that require the machine on.** Everything below is organized around the 4 dimensions.

---

## 0. Product timeline & key facts

### Claude Cowork
| Date | Event | Source |
|---|---|---|
| Jan 13–15, 2026 | Research preview launch (Claude Desktop macOS only, $100/mo Max subscribers) | WIRED hands-on 01/15/2026; Business Insider ("mostly built by AI in <2 weeks"); Fortune (Jan) |
| Jan 30, 2026 | Plugins launch — 11 open-sourced starter plugins, research preview for all paid users | claude.com/blog/cowork-plugins |
| Feb 24, 2026 | Connector wave: Google Drive, Gmail, DocuSign, FactSet + enterprise plugins; stock market impact (IGV ETF) | CNBC 02/24/2026 |
| Mar 2026 | Projects (persistent workspaces) introduced | aifordevelopers substack |
| Apr 9, 2026 | GA on all paid plans (macOS + Windows); enterprise controls (RBAC, spend limits, analytics, OTel, Zoom MCP connector) | claude.com/blog/cowork-for-enterprise; The New Stack |
| Jun 2026 | Doubled Cowork usage limits promo (extended through Aug 5, 2026) | The New Stack 06/08; claude.com/blog/cowork-web-mobile |
| Jul 7, 2026 | **Web + mobile launch; sessions move to cloud; scheduled tasks run with no device online** | claude.com/blog/cowork-web-mobile; ZDNET 07/07; WIRED 07/07; TechCrunch, The Verge, NBC, Yahoo Finance (all 07/07) |
| Jul 2026 | Usage data: 1.2M sampled sessions (May 11–31, 2026), 600K+ orgs, >90% non-coding | claude.com/blog/how-people-are-using-claude-cowork |
| Jul 1–27, 2026 | Sandbox-escape disclosure wave (Armadin; Anthropic disputes) | SiliconANGLE 07/01; The Hacker News 07/23; AppleInsider/9to5Mac/Techzine 07/27 |

- Priced into paid plans: Pro $20/mo ($17 annual), Max 5x $100/mo, Max 20x $200/mo, Team $20/seat/mo (2–150 seats), Enterprise custom. Cowork included on all; consumes limits ~faster than chat (no exact multiplier published; substack cites "~20x compute by some estimates" — unofficial).
- Platforms now: macOS, Windows (x64 + arm64), ChromeOS, Linux (desktop); web (claude.ai); iOS + Android (mobile). Web/mobile beta: Max/Team/Enterprise first, Pro rolling out "over the next several weeks" (per July help doc).

### Kimi Work
| Date | Event | Source |
|---|---|---|
| Feb 13, 2026 | Agent Swarm announced (research preview, top-tier subs): 100 sub-agents, 1,500+ tool calls, 4.5x faster than sequential (K2.5) | kimi.com/blog/agent-swarm |
| Apr 2026 | Kimi K2.6 released (current production model at Work launch; Cursor adopted K2 family Mar 2026) | eigent.ai blog 06/04/2026 |
| Jun 3, 2026 | **Kimi Work desktop app launched (beta), macOS (Apple Silicon) + Windows** | usercarly 07/20/2026; kimi.com/products/kimi-work |
| Jun 10–12, 2026 | Press wave: "300 agents on your desktop" (Decrypt, Moneycontrol, MarkTechPost, Crypto Briefing) | Google News RSS |
| May 2026 | Moonshot raised $2B at $20B valuation (per eigent) — later reports: seeking $30B valuation (Jun) | ETEnterpriseai, NewsBytes 06/08 |
| Jul 16–20, 2026 | Kimi K3: 2.8T-param open MoE, "Kimi Delta Attention", 1M context; demand crashed servers; paused new subscriptions; HK IPO talk | MarkTechPost 07/16; ETEnterpriseai 07/20; NewsBytes |

- Kimi Work pricing (from usercarly 07/20/2026; **single-source, verify against live page**): Adagio (free, ~6 agent tasks, no Swarm, ≤2 scheduled tasks), Moderato $19 (~60 tasks, 25 Swarm uses), Allegretto $39 (~150 tasks, 50 Swarm), Allegro $99 (~360 tasks, 120 Swarm), Vivace $199 (~720 tasks, 240 Swarm). Credits deduct per token/complexity; monthly refresh, no rollover. Moonshot help center says a new plan structure is coming (pricing in transition).
- Model lineage: K2.5 (Jan 2026, open) → K2.6 (Apr 2026) → K3 (Jul 2026, 2.8T open MoE). Kimi Work launched on K2.6 ("reportedly" per MarkTechPost headline; usercarly agrees).

---

## 1. Live artifacts (decks/docs/spreadsheets)

### Claude Cowork
- **Output artifacts are real Office files, not chat blocks:** Word (.docx/.doc), Excel (.xlsx/.xls/.xlsm), PowerPoint (.pptx/.ppt), PDF, plus txt/md/html/json/csv/tsv, images (png/jpg/jpeg/gif/svg/webp), YAML/XML/TOML, Jupyter .ipynb, and "pretty much any programming language" code files. Official FAQ lists all. (claude.com/product/cowork FAQ)
- Docs built with "working formulas" — VLOOKUP, conditional formatting, multi-tab sheets, not just CSVs (help center: "Excel spreadsheets with working formulas", "Generate Excel files with working VLOOKUP, conditional formatting, and multiple tabs").
- Spreadsheets/slides are further editable via Claude for Excel and PowerPoint connectors (help center).
- **Live artifacts** (interactive data views inside sessions): exist; **desktop-only** currently; on Team/Enterprise plans, users can share live artifacts within the org; individual plans have no session sharing at all (help center "Current limitations").
- **"Edit with Claude" in-place editing**: select text in a drafted Markdown doc → "Edit with Claude" → inline edit, no need to describe the section in the thread (help center).
- Where artifacts persist:
  - **Pre-July (desktop-era):** files written to your local folder (folder-attach model); "No cloud sync — everything happens locally" (substack, Apr 2026).
  - **Post-July (current):** "your sessions and files are saved to your Claude account" — cloud sessions; outputs delivered to the session "where you can preview and download them"; projects/artifacts live together across web+desktop (claude.com/blog/cowork-web-mobile; help center).
  - Deletion: task delete removes from history immediately, backend deletion within 30 days per retention policy (help center).
- **Preview/live behavior:** progress indicators per step, transparency on reasoning, mid-task steering, parallel sub-agents; example prompt on product page shows a contract-review memo artifact (markdown, cited clauses) and a weekly marketing readout deck spec (slides 1–3 defined) (claude.com/product/cowork).
- Hands-on evidence (WIRED, Jan): organized desktop screenshots into month folders; Gmail triage (deleted 1,000 emails as asked, "and nothing I didn't"); Google Calendar booking flow stopped before purchase (safety). (WIRED 01/15/2026)
- **Gaps:** no published spec for live-artifact format (proprietary interactive views); artifact download/export paths for cloud sessions not detailed in fetched sources; no versioning details.

### Kimi Work
- Artifacts: finished **spreadsheets, documents, slides (PowerPoint), websites** (kimi.com/products/kimi-work; usercarly). Swarm output can be "converted into professional PowerPoint decks or Excel sheets in seconds" (official page).
- Slides/Websites/Sheets/Docs are also standalone Kimi web features; Kimi Work inherits them with shared session context (eigent).
- Outputs are saved back **into the local workspace folder** ("saves the result back to the same workspace"; "drop the finished document right back where it belongs" — aitoolsclub; usercarly).
- **Dashboards** (newer feature): natural-language request → persistent interactive widgets (countdown, task panel, experiment tracker, market overview); refine by annotating rendered result; pin to desktop (usercarly).
- Deep Research → multi-format structured reports (eigent).
- **Gaps:** no evidence of "Edit with Claude"-style inline artifact editing; artifact file-format specifics (docx? xlsx? md?) not spelled out in fetched sources; no download/export docs captured.

---

## 2. Scheduled tasks

### Claude Coword (note: sources spell the product "Cowork"; keep canonical spelling in clone docs)
- **Specified via `/schedule` slash command in any Cowork task, or via "Scheduled" sidebar → New task (Create with Claude / Set up manually)** (help center).
- Cadence options: **hourly, daily, weekly, on weekdays, or manual/on-demand**. Manual setup form: task name, prompt, approval mode, frequency, optional model, optional folder (help center).
- **Where they run — CRITICAL evolution:** April-era docs: tasks run locally, machine must be awake + app open, skipped if off (auto-runs on reopen), "can't be tied to a folder… only run locally" if local resources needed (substack Apr; older help docs). **Post-July 2026: "Scheduled tasks run remotely, so they run on their cadence even when your computer is asleep or the Claude Desktop app is closed" and "run in the cloud, with no device online"** (current help center; claude.com/blog/cowork-web-mobile: "Scheduled tasks now run with no device online. Set Monday's client prep for 6 am: Claude works through the email threads, transcripts, and recent news, builds the briefing doc, and leaves the follow-up email drafted but unsent.").
- Constraint that remains: scheduled tasks "work with your connectors and the files saved to your Claude account. They can't be tied to a folder on your computer" — if the task requires local files/apps it "will only run locally" (i.e., cloud scheduling + local execution are two paths).
- Each scheduled run = its own Cowork session; review upcoming/past runs, edit, pause, resume, delete, run on demand (help center).
- **Limits/pricing:** available on all paid plans (Pro, Max, Team, Enterprise). No explicit per-plan scheduled-task count published in fetched sources. Doubled Cowork usage limits promo extended through **Aug 5, 2026** (claude.com blog). Scheduled/agentic work consumes more usage than chat; auto-approval mode consumes the most (help center).
- **Surprise:** no cloud-queued scheduled tasks existed before July 2026; this was the #1 difference vs Kimi (device-on dependency) and it was eliminated for cloud-tasks.

### Kimi Work
- **Cron-based scheduler**, part of the desktop app: "one-time, daily, weekly, monthly" (usercarly) and "daily, hourly, or at a specific time" (aitoolsclub) and "daily, hourly, or conditionally" (official FAQ). Supports **LLM Agent Calls, Python/Shell executions** (official FAQ).
- Configure manually or ask Kimi to convert a chat instruction into a schedule (usercarly).
- **Where they run: locally on the computer.** Machine must be awake; **Keep Computer Awake** toggle for overnight runs; "If it is asleep, the agent cannot quietly move the job to Moonshot's cloud" (usercarly; official FAQ answers "no" to sleep question).
- **Limits:** free plan capped at **2 scheduled tasks** (usercarly); paid plans add more; credit-metered per task.
- Examples: morning briefing from sites+local files; Friday spreadsheet reconciliation; overnight Python data-cleaning; daily market summary (usercarly).
- **Gap:** no published max scheduled tasks per paid tier; cron-condition syntax ("conditionally") not documented in fetched sources; no cloud fallback (contrast with Cowork) — confirmed by official FAQ.

---

## 3. Local files (access model, sandbox/isolation, privacy)

### Claude Cowork — the big architectural finding
- **User's premise verified:** current (July 2026+) docs state Cowork tasks "run in the cloud (in beta)… Claude's work runs on Anthropic's servers, in an isolated environment" and "Runs code and shell commands in an isolated environment on Anthropic's servers" — sessions/files live with your Claude account; desktop app is a **bridge** ("When a task needs something on your computer, like a local file or your browser, Claude reaches it through the Claude Desktop app on that computer") (support.claude.com/en/articles/13345190).
- **But this was NOT always true:** Jan–Jun 2026 desktop Cowork ran a **sandboxed VM on your machine**: "sandboxed virtual machine on your desktop (using Apple's Virtualization Framework on macOS)" (substack Apr 2026); on Windows, **Hyper-V-isolated Ubuntu VM** with "signature-gated communication, per-session unprivileged users, a seccomp filter and a proxy that restricts which domains the machine can reach" (SiliconANGLE/Armadin). Boris Cherny (head of Claude Code, who led Cowork): "We use a virtual machine under the hood… if you don't give it access to a folder, Claude literally cannot see that folder" (WIRED 01/15).
- So: **two execution models in one product — local-VM (desktop, legacy) and cloud isolated env (current default, web/mobile/desktop)**. Clone should support both or pick one; cloud model matches the "sessions run on Anthropic servers" claim.
- **Folder permission model:** user grants folder access explicitly; Claude reads/writes only granted folders; **permanent file deletion requires explicit "Allow"** (deletion protection) (help center; WIRED).
- **Approval modes:** Manual ("ask before acting"), Auto (Claude self-checks for exfiltration/prompt injection; Pro/Max only), Skip (no checks) (help center).
- **Network egress controls:** Cowork respects egress permissions; web fetch/search run server-side and are exempt (help center).
- **Retention/privacy:** tasks deleted → backend within 30 days; Compliance API captures web/mobile Cowork; OpenTelemetry events stream to SIEM (Splunk/Cribl) with shared user identifier (help center; enterprise blog).
- **Sandbox security incident (must cite):** Armadin Inc. (Kevin Mandia's company) disclosed a chain (reported Mar 20, Anthropic declined Mar 24) that escapes the Windows VM sandbox: **DLL sideloading of USERENV.dll into claude.exe** to pass the service signature gate (CoworkVMService named pipe), then two unchecked spawn-command params — resume flag (skip fresh unprivileged user → run as root) and wildcard domain override (kill network filtering) → root shell + nsenter escape + exfiltration. Validated on **Claude Desktop for Windows v1.9255.2.0**. Anthropic: not a vuln because attacker needs prior local code execution (SiliconANGLE 07/01/2026). Headlines claiming "500,000 Mac users exposed" (SQ Magazine, Yellow.com) overstate — the validated chain was Windows; **flag as media exaggeration**; the same VM-escape research wave hit Mac press (AppleInsider/9to5Mac 07/27) but the validated technical detail is the Windows chain.
- Privacy stance quotes: Anthropic's own safety page: "Since Claude can read, write, and permanently delete these files, be cautious about granting access to sensitive information…" recommends dedicated sandbox folder + backups (WIRED).
- Enterprise data-sovereignty: "Runs where your data lives — Amazon Bedrock, Google Cloud, Microsoft Foundry" (product page).

### Kimi Work
- **Local-first:** mount a folder (workspace) → agent reads/edits/executes inside it; files "remain on your machine the entire time" (aitoolsclub). "Local" = files/code/browser actions execute on-device; **models are cloud-based** ("powered by cloud-based models") — not an offline LLM app (usercarly; official FAQ semantics).
- **Permissions:** "Ask before acting" — explicit approval before modify/overwrite/run anything (official FAQ; aitoolsclub). Permission levels chosen per project ("choose a permission level" — usercarly). Request-permission + site/folder scope restrictions recommended (usercarly).
- **WebBridge:** browser extension via local service; reuses your signed-in browser sessions; "actions and page content execute locally rather than being sent through a remote browser"; cookies/logins never leave the machine (official; aitoolsclub). Browser automation risk: web pages can influence the agent (usercarly caution).
- **Privacy caveats:** because models are cloud, "organizations with sensitive data should verify privacy and retention terms rather than relying on the local-agent label" (usercarly) — mirrors the Cowork "local ≠ offline" caveat.
- Platform constraint: macOS 12+ **Apple Silicon only** (no Intel); Windows 10+ (usercarly).
- **Gap:** no public sandbox/VM architecture detail for Kimi Work (unlike Cowork's documented VM); no reported sandbox-escape research in the news wave (only Cowork was researched publicly as of Aug 2026).

---

## 4. MCP connectors & CLI tools

### Claude Cowork
- **Connector directory:** ~17 pages of connectors (page-pager "1/17") at claude.com/connectors, all "powered by the Model Context Protocol" (MCP), third-party submitted ("Submit your own connector"); capabilities tagged Read / Read & write / Interactive; most connectors work with both Claude and Claude Code (claude.com/connectors).
- **Feb 24, 2026 enterprise wave (CNBC):** Google Drive, Gmail, DocuSign, FactSet + customizable domain plugins (financial analysis, engineering, HR) "encoding institutional knowledge and workflows". Named partners on the product page: Amplitude, Microsoft 365, Google Drive, Slack (plus Databricks mentioned in a Zapier customer quote).
- **Enterprise blog (Apr 9):** Zoom MCP connector (AI Companion summaries, transcripts, action items); **per-tool connector controls** (e.g., read-only org-wide, write disabled); OTel events for tool/connector calls; admin approval flows for write-capable connectors (Team/Enterprise can force per-task approval).
- **Plugins ecosystem:** plugins bundle skills + connectors + slash commands + sub-agents, all file-based ("plugins are just markdown files and JSON"), built with "Plugin Create"; **11 open-sourced starter plugins** on GitHub `anthropics/knowledge-work-plugins` (productivity, enterprise search, plugin create, sales, finance, data, legal, marketing, customer support, product management, biology research); financial-services plugins (investment banking, equity research, PE, wealth management) (substack; claude.com/blog/cowork-plugins). Private plugin marketplaces + auto-install for enterprise (Apr 9 blog).
- **Skills:** instruction files (pdf/docx/pptx/xlsx built-ins; custom skills via Skill Creator; "Browse skills" directory). July 2026: **skills can be learned from screen recordings + voice-over explanations** (the-decoder 07/21; PCMag 07/22 "Claude Can Now Learn Your Workflows By Watching Your Screen").
- **MCP versioning:** "Bringing MCP 2026-07-28 to Claude" (blog, Jul 28) — MCP spec date in the wild; enterprise-managed OAuth for MCP connectors (blog Jun 18).
- **CLI/API:** Cowork itself has **no public CLI** (terminal equivalent is Claude Code, a separate product); **no Cowork-specific API** published; Analytics API exists for admins (enterprise blog); Compliance API captures remote Cowork sessions; docs platform at docs.claude.com. Desktop app installable via direct download URLs (claude.ai/api/desktop/...).
- **Pricing implications:** connectors/plugins included in paid plans (no per-connector fee seen); heavy connector use accelerates usage-limit burn; enterprise governance features gated to Team/Enterprise.

### Kimi Work
- **Plugins:** extend to third-party tools + professional data: **Notion, Canva, WPS**, plus financial, academic, legal, and economic databases. "Some plugins use OAuth, MCP, or both" (usercarly). **No public plugin marketplace/directory detail** captured — gap.
- **Native finance data:** built-in market data for **US, HK, A-shares** — earnings reports, market anomaly analysis, spreadsheet reconciliation via conversation, no API setup (official page; aitoolsclub).
- **MCP:** Kimi's own WebBridge is a browser-extension agent bridge (local service); Kimi supports MCP-using plugins; **Kimi Platform** (platform.kimi.ai) = API for K-series models (eigent).
- **CLI:** **Kimi Code** is a separate terminal/IDE coding agent product (kimi.com/code) — the closest thing to Claude Code; Kimi Work itself has no public CLI/API surface in fetched sources (gap). Kimi Claw = 24/7 deployed agents feature (kimi.com features).
- **Pricing implications:** Swarm uses and task counts are plan-gated (25→240 Swarm uses across $19–$199 tiers, per usercarly); credits shared between Chat and Work.

---

## 5. Cross-checked claims & contradictions

| Claim | Source A | Source B | Verdict |
|---|---|---|---|
| Cowork sessions run in isolated environments on **Anthropic servers** | Official help center (current) | Substack (Apr): local VM on desktop (Apple Virtualization Framework); SiliconANGLE: Hyper-V Ubuntu VM on Windows | **Not contradictory once dated** — pre-July = local VM; post-July = cloud env + desktop bridge. Flag for clone design (pick era). |
| Kimi Work Swarm = **300 sub-agents / 4,000+ tool calls** | Press (Decrypt, Moneycontrol, MarkTechPost, Crypto Briefing, Jun 10–12) + usercarly ("current docs") | Moonshot's own launch blog (Feb 2026): **100 sub-agents, 1,500+ tool calls, 4.5x faster** (K2.5) | Likely evolution (K2.6 raised limits). Flag: cite both numbers with dates. |
| Cowork scheduled tasks | Substack/older help (Apr): local-only, skipped if machine off | Current help center (Jul): run remotely, "no device online" | **Direct contradiction resolved by the July cloud launch** — flag. |
| Sandbox escape "exposed 500,000 Mac users" | SQ Magazine, Yellow.com headlines | SiliconANGLE (validated chain is **Windows** v1.9255.2.0); Anthropic disputes severity | Headlines overstate; validated chain = Windows; Mac coverage (9to5Mac/AppleInsider) exists but without the same validated detail. |
| Kimi Work launch date | usercarly: Jun 3, 2026 | Press wave Jun 10–12, 2026 | Consistent. |
| Kimi Work pricing tiers ($19–$199, free tier ≤2 scheduled tasks) | usercarly (Jul 20) | Official pricing page: JS-rendered, not fetchable; Moonshot help center confirms "new plan structure coming" | **Single-source pricing — needs verification.** |
| Cowork price | Product page: Pro $20 ($17 annual), Max $100/$200, Team $20/seat | WIRED (Jan): research preview $100/mo only | Consistent; launch gating changed over time. |
| Kimi Work model | usercarly/aitoolsclub: K2.6 | MarkTechPost: "reportedly K2.6" | Consistent; superseded by K3 (Jul 2026). |
| 90% of Cowork sessions non-coding | ZDNET + Anthropic blog (Jul 7) | Anthropic data post: 33.4% business process/ops, 16.4% content/copy, software dev 8.7%, DevOps 7%, research 6.4% | Consistent (same source). |

---

## 6. Key gaps for Stage 2 (deep dives recommended)

1. **Claude Cowork**: exact usage-limit math per plan (support.claude.com usage articles); live-artifact file format & sharing internals; how cloud sessions mount Drive vs local folders; Compliance API record structure; desktop ↔ cloud task handoff mechanics ("local sessions" still exist — help center mentions "For local sessions, ensure the Claude Desktop app was open"); Cowork architecture overview article exists (support.claude.com/en/articles/14479288) — **fetch it in Stage 2**.
2. **Kimi Work**: verify pricing table against live page; scheduled-task cron condition syntax; plugin catalog details (which databases, MCP endpoints); artifact file formats; whether Swarm runs locally or server-side (important architecture question for a clone!); Kimi Work's EULA/privacy retention specifics.
3. **Both**: third-party security audits beyond Armadin; Windows vs macOS sandbox differences for Cowork (Apple's Virtualization Framework vs Hyper-V — clone implication); Kimi's Windows sandbox (if any).
4. Yahoo Finance "work around work" article (07/07) — found in RSS but not fetched (JS-gated); CNBC 07/07 coverage likewise; both redundant with Anthropic's own blog + ZDNET.

## 7. Surprises worth surfacing to the user

- Cowork's scheduled tasks went **from "skipped if your laptop is asleep" (April) to "runs with no device online" (July)** — a 90-day pivot that fundamentally changes the clone's architecture (needs a cloud task runner + desktop bridge daemon).
- The **desktop app is now a bridge, not the runtime**: Claude executes in Anthropic's cloud env and "reaches through" the app for local files/browser — architectural inversion vs Kimi Work (local execution, cloud models).
- Kimi Work's **Agent Swarm is genuinely multi-agent at scale** (100→300 sub-agents, 1,500→4,000+ tool calls) — no equivalent marketing number from Anthropic for Cowork sub-agents (Cowork uses sub-agents too, but Anthropic doesn't publish counts).
- Both vendors ship **office-file-native artifacts** (real .xlsx with VLOOKUP, .pptx) — "artifact" is a first-class concept in both, but Cowork alone has "Edit with Claude" in-place editing and shared live artifacts for orgs.
- **Sandbox escapes are already a public incident for Cowork** (Armadin, Jul 2026) — a clone of the Windows VM approach inherits this attack surface; Kimi Work has no public equivalent research yet.
- Business context: Cowork launch shook software stocks (IGV -5% Feb 23, CNBC); Moonshot K3 demand crashed their servers and paused subscriptions (Jul 2026) — both products are demand-constrained by compute, not features.

---

## Sources (all fetched 2026-08-06)

**Claude Cowork:**
- CNBC: https://www.cnbc.com/2026/02/24/anthropic-claude-cowork-office-worker.html
- ZDNET: https://www.zdnet.com/article/anthropic-claude-cowork-comes-to-phone-web-cloud/ (07/07/2026)
- Anthropic blog: https://claude.com/blog/cowork-web-mobile/ (07/07/2026)
- Anthropic data post: https://claude.com/blog/how-people-are-using-claude-cowork
- Product page (FAQ, pricing, file types): https://claude.com/product/cowork
- Help center: https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork (architecture, permissions, deletion)
- Help center: https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork
- Connectors directory: https://claude.com/connectors
- Blog plugins: https://claude.com/blog/cowork-plugins (01/30/2026)
- Blog enterprise: https://claude.com/blog/cowork-for-enterprise (04/09/2026)
- WIRED hands-on: https://www.wired.com/story/anthropic-claude-cowork-agent/ (01/15/2026)
- WIRED (Jul 7): Shut Those Laptops — URL confirmed via wired.com/search
- SiliconANGLE sandbox: https://siliconangle.com/2026/07/01/armadin-details-full-sandbox-escape-claude-cowork-anthropic-disputes-risk/
- AI For Developers substack guide (Apr 15, 2026): https://aifordevelopers.substack.com/p/the-complete-guide-to-claude-cowork

**Kimi Work:**
- Official: https://www.kimi.com/products/kimi-work
- Agent Swarm primary: https://www.kimi.com/blog/agent-swarm (Feb 2026)
- usercarly: https://www.usecarly.com/blog/what-is-kimi-work/ (07/20/2026)
- aitoolsclub: https://aitoolsclub.com/meet-kimi-work-a-local-ai-agent-on-your-desktop-that-automates-your-work-for-you/ (06/21/2026)
- eigent.ai: https://www.eigent.ai/blog/kimi-work-moonshot-ai-workspace (06/04/2026)
- Press titles (Google News RSS): Decrypt, Moneycontrol, MarkTechPost, Crypto Briefing (06/10–12/2026); MarkTechPost K3 (07/16); ETEnterpriseai (07/20)

**Status: breadth scan complete.** Fetched 20+ primary/secondary pages; all 4 dimensions covered with concrete numbers; contradictions flagged in §5; verified cloud-isolation architecture claim for Cowork and local-execution architecture for Kimi Work. Recommended Stage 2 targets listed in §6 (top: Cowork architecture-overview help article, Kimi live pricing + Swarm execution model, artifact formats for both).
