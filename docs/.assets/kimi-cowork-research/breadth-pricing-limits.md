# Breadth Scan: Pricing, Limits, Plans — Claude Cowork vs Kimi Work

**Stage 1 breadth scan (pricing/limits angle) for building a from-scratch clone.**
**Date:** 2026-08-06 · **Researcher:** pricing-limits agent

---

## 1. Executive Summary (key findings)

- **Claude Cowork has NO standalone price.** It is bundled into every *paid* Claude plan (Pro, Max 5x/20x, Team, Enterprise) and is **excluded from the Free plan**. Official pricing page: Pro $20/mo ($17/mo annual, $200 up front); Max from $100/mo (5x or 20x Pro usage per 5-hour session); Team $20/seat annual ($25 monthly); Enterprise $20/seat **+ all usage billed at API rates**.
- **Cowork was Max-only at launch (late 2025); Pro got access around Jan 2026.** Web/mobile rollout is beta and tier-staged (Max first).
- **Limits are soft and unenumerated.** No public message/task counts. All usage draws from ONE shared pool (chat + Code + Cowork), reset on a rolling **5-hour window** with weekly caps on paid plans. Cowork burns the pool **5–20x faster than chat** (screenshots, multi-step, sub-agents).
- **There is no "lifetime"/prepaid Cowork offer.** Closest things: (a) opt-in **usage credits** top-up at standard API rates on Pro/Max/Team; (b) a **limited-time promotion (June 5 → Aug 19, 2026)** doubling Cowork's 5-hour limit on Pro/Max/Team + legacy seat-based Enterprise (weekly limit unchanged; Cowork only); (c) an Enterprise activation promo for Code+Cowork (support article 15282265, not fetched in depth).
- **Kimi Work pricing rides on Kimi membership** (unified credit pool across all features: chat, deep research, slides, websites, Kimi Code, Kimi Work, Kimi Claw). International tiers (musical names): **Moderato $19, Allegretto $39, Allegro $99, Vivace $199/mo** (annual saves up to $480/yr). Free tier exists (limited; K2.6 chat free).
- **China-market tiers were reorganized July 2026** to Go ¥49 / Pro ¥269 / Max ¥699 / Ultra ¥1,399 per month (per Zhihu + 界面新闻 coverage; intl equivalents differ).
- **Kimi concurrency numbers are explicit**: agent credits 60/150/360/720 per month (≈task counts); **2/2/4/4 concurrent agent tasks**; Agent Swarm (beta) 25/50/120/240 uses, **2/4/4/8 concurrent subtasks**. Marketing claims Swarm can coordinate **up to 300 sub-agents in parallel and 4,000+ tool calls per task** — the "300" figure is the system ceiling, NOT what plans allow.
- **Kimi scheduled tasks are quota'd**: active-task caps Free 2 / Go 6 / Pro 15 / Max 20 / Ultra 25. Desktop local tasks only run while app is open (no catch-up); web tasks run in cloud. Default expirations: daily +7d, weekly +1m, monthly +3m.
- **Kimi Claw (24/7 cloud agent) costs ~0.6% of membership credits/day just to keep the sandbox host alive; published websites ~0.08%/day.** Pay-as-you-go top-ups exist.

---

## 2. Claude Cowork — Pricing by Plan (exact numbers)

Source: https://claude.com/pricing (official, fetched 2026-08-06) + https://claude.com/product/cowork + third-party cross-checks.

| Plan | Price | Cowork included? | Usage vs Pro (per 5-hr session) | Notes |
|---|---|---|---|---|
| Free | $0 | ❌ **No** | below Pro | chat, web search, memory, file creation, desktop extensions; agentic features excluded |
| Pro | $20/mo; **$17/mo annual ($200 up front)** | ✅ | baseline | full Cowork; Anthropic warns Cowork consumes limits faster than chat |
| Max 5x | **$100/mo** (monthly only) | ✅ | **5x Pro** | higher output limits; priority at high traffic |
| Max 20x | **$200/mo** | ✅ | **20x Pro** | earlier access to new features (web/mobile beta first) |
| Team Standard | $25/seat/mo or **$20 annual** | ✅ | **1.25x Pro** per session | min 2 seats (claude.com: "2 to 150"); central billing, SSO |
| Team Premium | $125/seat/mo or **$100 annual** | ✅ | **6.25x Pro** | |
| Enterprise | **$20/seat + usage at API rates** | ✅ | no plan-level cap | self-serve min 20 seats; sales min 50 seats (felloai); SCIM, audit logs, HIPAA-ready |

- The "5x/20x" multipliers are **against Pro**, not against Free (felloai explicitly flags that misread; official FAQ says "Max gives you 5x or 20x more usage per 5-hour session than Pro"; Free is "at least 5x more than Free" = Pro ≈ 5x Free).
- **Enterprise = consumption-based**: seat fee "covers access only, all usage billed separately at API rates" (felloai, citing Anthropic docs). Cowork activity therefore *does* add to the Enterprise bill. Enterprise Cowork activity is **NOT yet captured in audit logs or Compliance API** (official Cowork page) — a compliance gap, not a pricing one.
- **Usage credits**: Pro/Max users can opt-in, pre-fund a balance; overage then bills at standard API rates (official FAQ + felloai). Team/seat-based Enterprise have an equivalent.
- **Cowork usage promotion (official, verified)**: June 5 → **Aug 19, 2026** (extended from Aug 5), **doubles Cowork's 5-hour usage limit**; applies automatically to Pro, Max, Team, legacy seat-based Enterprise; excludes Free and consumption-based Enterprise; weekly limits and other products (Claude web, Claude Code) unchanged. → Any "tier sizing" done during this window is flattered ~2x. (https://support.claude.com/en/articles/15400594-claude-cowork-june-2026-usage-promotion)
- Related promo: "Claude Enterprise activation promo for Claude Code and Cowork" (support article 15282265 — referenced, not deep-fetched).
- No free Cowork trial exists on the Free plan (multiple sources).

**API pricing context (for clone cost modeling)** — official claude.com/pricing: Fable 5 $10/$50 per MTok in/out; Opus 5 $5/$25; Sonnet 5 $2/$10 intro through Aug 31 2026 → $3/$15 standard; Haiku 4.5 $1/$5. Managed Agents runtime $0.08/session-hour; web search $10/1K searches; code execution 50 free container-hours/day then $0.05/hr. Legacy: Opus 4.5 $5/$25, Sonnet 4.5 $3/$15, etc.
- Programmatic usage (Agent SDK / headless Claude Code) metered as dollar credits at API rates **since June 15, 2026** — "build-your-own" no longer rides on a flat sub (automatonagency).

---

## 3. Claude Cowork — Limits & Usage Mechanics

- **Reset window**: rolling **5-hour** session window for all plans; paid plans add **weekly limits** on top. (official FAQ; usagebar agrees)
- **Pooling**: web + desktop + mobile + Claude Code + Cowork all draw from the same pool (official FAQ). No separate Cowork meter.
- **No fixed message/task counts published** — dynamic per model/complexity. (official FAQ + usagebar + agensi)
- **Cowork burns usage 5–20x faster than chat** per unit of work (automatonagency, running it daily; usecarly/eesel concur). Drivers: screenshots, sub-agent coordination, tool calls, file ops.
- **Auto mode consumes more** usage than other approval modes (felloai, citing Anthropic docs).
- **Scheduled tasks**: "Schedule a task for any cadence... runs unattended" (official product page). Cloud-hosted sessions mean scheduled tasks fire with no device online since ~summer 2026 (usecarly limitations article). **No published cap on number of scheduled Cowork tasks or concurrent Cowork tasks.**
- **Concurrency**: official page says big projects are "split into chunks that run together" (parallel sub-tasks within a task). No per-plan concurrency numbers published (contrast: Kimi publishes 2/4 concurrent tasks).
- **Context window**: 200k (official pricing matrix: "Context window 200k" on Free/Pro/Max; Enterprise default model 500k).
- **Model access**: Fable (50% of weekly limits — usage-restricted), Opus, Sonnet, Haiku. Opus 4.5 was Cowork's headline brain per claudecowork.im (third-party; in 2026 line-up includes newer models per official page).
- **Files**: read/create/edit — docx/doc, pdf, txt, md, html, json, csv, tsv, xlsx/xls/xlsm, pptx/ppt, png/jpg/jpeg/gif/svg/webp, yaml/yml, xml, toml, ipynb, code files (official FAQ). **No artifact-size or storage limits published**; third-party notes long browser jobs hit **timeouts and action-step quotas** (usecarly), and sandbox state doesn't persist across sessions.
- **Email constraint**: sending only via **Microsoft 365 connector**, and M365 write tools **reject attachments**, cap sends/recipients per user; no OneDrive/SharePoint deletions (usecarly, citing support article 12684923).
- **Approval modes**: manual per-step / auto (self-blocking) / skip-all; deletion of anything requires approval (official + support article 13364135).
- **Admins**: org-level Cowork toggle at claude.ai/admin-settings/cowork; RBAC; spend controls; OpenTelemetry activity streaming to SIEM (official page; enterprise blog Apr 9, 2026).
- **Platforms**: macOS, Windows (x64+arm64), ChromeOS, Linux; web + mobile in beta.

---

## 4. Kimi Work — Pricing & Plans (official)

Kimi Work is a **desktop agent** (Windows + macOS Apple silicon) whose usage is metered through **Kimi membership** — there is no separate Kimi Work subscription. Source: https://www.kimi.com/help/membership/membership-overview, /membership-pricing, /products/kimi-work.

### International tiers (USD, official help center)

| Plan | Monthly | Annual (/mo) | Annual total | Agent credits/mo* | Concurrent agent tasks | Agent speed priority | Swarm (beta) uses | Swarm concurrent subtasks | Kimi Code credits | Kimi Claw | Pro DB calls |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Free | $0 | — | — | (limited) | n/a (not tabulated) | — | — | — | — | — | — |
| **Moderato** | **$19** | $15 | $180 | 60 | **2** | 4x | 25 | **2** | 1x | ❌ | 2,000 |
| **Allegretto** | **$39** | $31 | $372 | 150 | **2** | 4x | 50 | **4** | 5x | ❌ | 5,000 |
| **Allegro** | **$99** | $79 | $948 | 360 | **4** | 4x | 120 | **4** | 15x | ✅ | 12,000 |
| **Vivace** | **$199** | $159 | $1,908 | 720 | **4** | 4x | 240 | **8** | 30x | ✅ | 24,000 |

\* Agent credits are "approximate values based on typical task token consumption — monthly credits converted to equivalent number of tasks."

### Mechanics
- **One unified credit pool** for everything: website deployment, Deep Research, Slides, Kimi Code, Kimi Work, Kimi Claw, K3, Swarm. Metered by token usage; using one feature drains the others. Monthly refresh at billing cycle.
- **Kimi Code** additionally has its own 5-hour/weekly rate limit (only affects Kimi Code).
- **K2.6 chat is free** for all users and doesn't consume credits.
- **Pay-as-you-go top-ups** ("Extra Usage") exist (help article membership-extra-usage).
- **Kimi Claw hidden costs**: ~**0.6% of membership credits/day** charged for the cloud sandbox host (settled 4 PM daily), even when idle; published agent websites ~0.08%/day. (official pricing FAQ)
- **Kimi Business** (team offering) exists; pricing not enumerated on the fetched pages (purchase via kimi.com/membership/pricing; bank transfer supported; mobile app doesn't support Business yet).

### China-market pricing (CNY) — July 2026 revamp
- 2025-09 launch: Adagio (free) / Andante ¥49 / Moderato ¥99 (快科技, 2025-09-25; 界面新闻: 49/99/199/699 入门/效率/专业/尊享).
- **July 2026 new general membership (Web+App+Work): Go ¥49, Pro ¥269, Max ¥699, Ultra ¥1,399 per month** (Zhihu, 2026-07-20, quoted via Baidu; matches the Free/Go/Pro/Max/Ultra naming in the scheduled-tasks quota table).
- An aggregator page (爱企查 snippet, 2026-07-17) still lists a 5-tier 0→¥699 scale with musical names (adagio free, andante 49, moderato 99...) — **stale vs the Go/Pro/Max/Ultra revamp; flag as contradiction in-transition.**
- Note: ¥269 ≈ $37, ¥699 ≈ $98, ¥1,399 ≈ $196 → CN Pro/Max/Ultra roughly map to intl Allegretto/Allegro/Vivace; CN Go (¥49) has no direct intl equivalent.

---

## 5. Kimi — Limits That Constrain the Cloneable Feature Set

- **Parallel agents ("300?")**: YES — the "300" figure exists: **"Kimi Agent Swarm can coordinate up to 300 sub-agents working in parallel and support over 4,000 tool calls per task"** (official resources page, kimi.com/resources/parallel-agent). BUT plan-level "Agent Swarm concurrent subtasks" is 2/4/4/8 — so 300 is the engine ceiling, not the per-subscription allowance. Contradiction worth flagging.
- **Agent concurrency**: 2 (Moderato/Allegretto) or 4 (Allegro/Vivace) concurrent agent tasks; 4x speed priority on all paid tiers.
- **Scheduled tasks**: active-cap quota **Free 2 / Go 6 / Pro 15 / Max 20 / Ultra 25** (official scheduled-tasks doc; intl musical tiers presumably map same structure — the doc's table uses the CN names). Frequencies: daily, weekly, monthly, one-time. Default expiry: daily +7d, weekly +1m, monthly +3m. No limit on *creating* tasks (over-limit ones saved inactive). **Desktop (Kimi Work) local scheduled tasks run ONLY while the app is open** — missed triggers are not run retroactively ("Keep Computer Awake" toggle exists). Web-created tasks run in the cloud regardless of device state.
- **Browser automation (WebBridge)**: free-form browsing, clicks, form-filling, scraping; runs in a browser extension; used by web app and Kimi Work. **No numeric limits published** on pages/sessions; long browser jobs subject to plan credit burn (like Cowork).
- **Local files**: mounts local folders, Python execution, permission modes ("Request permission" / "Allow all"); no storage limits published (files stay local).
- **Scheduled-run model choice**: manual creation defaults to K2.6; conversational creation lets you pick model; post-run follow-ups + "/" plugin/Skill invocation.
- **Kimi Claw**: 24/7 cloud-deployed agent (OpenClaw SaaS); sandbox billed by runtime (~0.6%/day of credits); requires Allegro+.
- **Kimi Work release cadence**: v3.1.7 (2026-08-05), v3.1.6 (2026-07-29) — actively shipping.

---

## 6. Dimension Matrix (feature-level pricing/limits constraints)

| Dimension | Claude Cowork | Kimi Work |
|---|---|---|
| **Artifacts / outputs** | Docs (docx/pdf/md…), Excel with formulas, PPT, PDF; artifact *size* limits unpublished; output counts toward usage pool; M365 email writes reject attachments | Slides/Docs/Sheets/Websites are separate credit-metered features in the same pool; published websites incur ~0.08%/day cloud fee |
| **Scheduled tasks** | Any cadence, unattended, cloud-run (no device needed); **no published count/concurrency caps**; scheduled runs consume the 5-hr/wk pool; promotion doubled 5-hr Cowork usage Jun 5–Aug 19 2026 | Hard active-task quota per plan: 2/6/15/20/25 (Free→Ultra); daily/weekly/monthly/once; default expirations; desktop runs local-only (app must be open) |
| **Local files** | Grant specific folders; read/write/rename/move; sandbox VM; deletions need approval; computer-use "research preview" | Mount local folders; ask-before-act or allow-all; runs Python locally; 24/7 local cron engine |
| **Connectors / CLI** | GUI connectors (Slack, Linear, Google Calendar, Gmail, GitHub, M365, Amplitude, Drive, Notion, Asana…); MCP limited to connector-style; plugins/skills/sub-agents marketplace; Windows/Linux/macOS/ChromeOS | WebBridge extension; Kimi Code CLI/IDE separate (own rate limit); finance data integrations (A/HK/US equities) native; plugin center + skills |
| **Concurrency** | Parallel sub-tasks within a task (unspecified count); plans sell usage, not concurrency | 2 or 4 concurrent agent tasks; Swarm 2/4/4/8 concurrent subtasks; 300-sub-agent engine ceiling |
| **Meter** | Rolling 5-hr + weekly, shared pool; usage-credit top-ups at API rates; no free tier | Monthly credit pool (token-metered), monthly reset; extra-usage top-ups; K2.6 chat free; Kimi Code extra 5-hr/week limit |

---

## 7. Contradictions / Discrepancies Flagged

1. **"Kimi 300 parallel agents"** — marketing (300 sub-agents, 4,000+ tool calls) vs plan-gated reality (2–8 concurrent subtasks on Swarm, 2–4 concurrent agent tasks). Same-ish tension as Cowork's "any cadence scheduling" vs unpublished caps.
2. **CN plan names/prices mid-transition**: scheduled-tasks table + Zhihu use Free/Go/Pro/Max/Ultra (¥49/269/699/1399); 爱企查 aggregator + older press still list musical tiers (¥0/49/99/199/699). Both may be live for different locales/accounts.
3. **Promotion dates**: felloai says "June 5 → Aug 5" (as originally announced); official support article says **extended to Aug 19** — official wins; third-party pages are stale on this.
4. **"Cowork $30/user"** (usagebar) vs "bundled in paid plans" (everything else) — usagebar's article is really about the **Claude Team plan** ($30 annual floor claim vs official $20 annual seat); it also claims a 5-seat minimum vs claude.com's "2 to 150". **Official claude.com/pricing wins** (Team $20/seat annual, from 2 seats).
5. **Max multipliers baseline**: usagebar/agensi say "5x/20x more than Free"; official FAQ says Max = 5x/20x *Pro*, Pro = 5x Free (so Max 20x ≈ 100x Free). Felloai explicitly calls the "vs Free" reading wrong.
6. **Team seat multipliers** (1.25x/6.25x Pro) published only by felloai; not on claude.com pricing page itself — single-source, treat as plausible-but-unverified.
7. **Cowork "free"**: claudecowork.im's pricing table visually lists "Claude Cowork ✅" under the Free row (copy/paste artifact) while its own text says Free lacks Cowork; official page confirms Free excludes Cowork.
8. **Enterprise seat minimums**: felloai says self-serve 20 / sales 50; claude.com pricing page doesn't state numbers. Single-source.

---

## 8. Gaps (couldn't verify / not published)

- No official message/task/day or token counts for Cowork on any plan — Anthropic deliberately doesn't publish; all estimates are third-party.
- Cowork scheduled-task count limits, concurrent-task limits, artifact/storage size limits: **not published anywhere found**.
- Kimi Work WebBridge numeric quotas (pages per session, concurrent browser sessions): not published.
- Kimi free-tier numeric credit allowance: help pages tabulate paid tiers only (a CN aggregator claims "basic allowance" on free).
- Kimi Business seat pricing: not enumerated on fetched pages.
- Kimi Code tier pricing in USD beyond relative "1x/5x/15x/30x" multipliers (CN market has separate Kimi Code memberships per vfuturemedia note: "general tier + dedicated Kimi Code membership" after K3 demand pause; not fetched).
- A direct EN "Cowork vs Kimi Work" head-to-head review was not reachable (search engines bot-blocked; CN coverage exists — CSDN "Kimi Work vs Claude Cowork: 到底选谁" 2026-06-22, 智能纪元AGI 2026-06-04 calling Kimi Work a ~95% free clone of Codex/Cowork, 新浪财经 2026-07-18 on Kimi forcing OpenAI/Anthropic pricing changes).
- "Lifetime"/prepaid Cowork deals: **none found — likely nonexistent**; the only offers are the usage promotion and enterprise activation promo.

---

## 9. Surprises

- Anthropic built Cowork with **100% AI-written code in ~10 days** (差评/XPIN via Baidu, Jan 2026) — relevant to a "clone feasibility" narrative.
- Cowork officially says **"deleting anything needs your approval"** — a hard product constraint that a clone should mirror.
- Kimi charges **0.6%/day of credit balance for idle cloud-hosted agents (Claw)** — an unusual "infrastructure rental" pricing mechanic with no Cowork equivalent.
- Kimi's **K2.6 chat being permanently free** (no credit consumption) is a deliberate traffic/moat play vs Cowork's hard paid gate.
- Enterprise Cowork **lacks audit-log/Compliance API coverage** even at GA — compliance gap even on the most expensive plan (automatonagency + official page agree).
- CN Kimi top tier (Ultra ¥1,399/mo ≈ $196) costs roughly what Max 20x ($200) does — the two products' power tiers converged on ~$200/mo.

---

## 10. Key Sources (URLs)

Official:
- https://claude.com/pricing
- https://claude.com/product/cowork
- https://support.claude.com/en/articles/15400594-claude-cowork-june-2026-usage-promotion
- https://support.claude.com/en/articles/9797557-usage-limit-best-practices (referenced)
- https://www.kimi.com/help/membership/membership-overview
- https://www.kimi.com/help/membership/membership-pricing
- https://www.kimi.com/help/features/scheduled-tasks
- https://www.kimi.com/help/kimi-work/kimi-work-faq
- https://www.kimi.com/products/kimi-work
- https://www.kimi.com/resources/parallel-agent

Third-party:
- https://felloai.com/claude-cowork-pricing/ (Team multipliers, usage credits, Enterprise mechanics)
- https://automatonagency.com/insights/claude-cowork-pricing (rate-limit reality, 5–20x burn, June 15 2026 programmatic billing)
- https://www.agensi.io/learn/claude-cowork-pricing (Pro $17 annual, Max framing)
- https://claudecowork.im/pricing (Pro access since Jan 2026; note: unofficial squatter-adjacent site)
- https://www.usecarly.com/blog/claude-cowork-pricing/ and /blog/claude-cowork-limitations/ (M365 email restrictions, timeouts, approval modes)
- https://usagebar.com/blog/claude-cowork-pricing-and-limits (Team-plan conflation; 5-hr rolling window)
- Baidu search results (CN market): Zhihu 2026-07-20 (Go ¥49/Pro ¥269/Max ¥699/Ultra ¥1,399); 界面新闻 (49/99/199/699 Sept 2025); 快科技 2025-09-25; CSDN 2026-06-22 (Kimi Work vs Cowork); 智能纪元AGI 2026-06-04 (Kimi Work ≈95% free clone); 差评XPIN 2026-01-20 (100% AI-built Cowork); vfuturemedia (K3 demand paused subscriptions; Code membership split).

---

## 11. Status / Next Steps (for orchestrator)

- Done: full pricing surfaces for both products (intl + CN), usage mechanics, concurrency, scheduled-task quotas, promotions, feature-dimension matrix, contradiction map.
- Recommend Stage 2 deep dives: (1) Cowork support docs on limits (support.claude.com articles 13345190, 13364135, 12684923, 11049741); (2) Kimi Work release notes + WebBridge "how it works" for numeric quotas; (3) CN-market Kimi Code standalone memberships; (4) OpenAI ChatGPT Work pricing as the third comparator that CN media keeps pairing with Cowork.
