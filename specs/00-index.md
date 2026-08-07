# Spec Index — RH Co-work

Local-first clone of Claude Cowork + Kimi Work. Runner: host `claude` CLI (stream-json). Stack: Python (SQLite, FastAPI + websockets, pydantic, loguru). Platform: macOS (dev), host-native isolation with permission gates.

## Read order
1. `01-mission.md` — intent, users, core loop, out-of-scope
2. `02-constraints.md` — non-negotiable rules (local-first, runner contract, no cloud)
3. `03-architecture.md` + `03-architecture-{context,containers,components}.mmd` — C4 context → containers → components
4. `04-data-model.md` — entities, schemas, state machines
5. `05-interfaces.md` — component boundaries + I/O shapes
6. `06-runtime.md` — processes, lifecycle, recovery
7. `07-security-permissions.md` — grants, permission matrix, audit
8. `prds/` — one PRD per capability dimension
9. `glossary.md` — shared terminology

## Status table

| Doc | Writer | Reviewer | Status |
|---|---|---|---|
| 01-mission.md | W1 | — | written — pending review |
| 02-constraints.md | W1 | — | written — pending review |
| 03-architecture.{md,mmd} | W2 | — | written — pending review |
| 04-data-model.md | W3 | — | written — pending review |
| 05-interfaces.md | W3 | — | written — pending review |
| 06-runtime.md | W3 | — | written — pending review |
| 07-security-permissions.md | W5 | — | written — pending review |
| prds/prd-agent-sessions.md | W4a | — | written — pending review |
| prds/prd-live-artifacts.md | W4b | — | written — pending review |
| prds/prd-scheduled-tasks.md | W4c | — | written — pending review |
| prds/prd-local-files.md | W4d | — | written — pending review |
| prds/prd-mcp-connectors.md | W4e | — | written — pending review |
| prds/prd-memory.md | W4f | — | written — pending review |
| glossary.md | W1 | — | written — pending review |

## Grounding (must-read before writing any doc)
- `docs/REVERSE_ENGINEERING_claude_cowork.md` — primary evidence for clone-of-Cowork mechanisms
- `docs/RESEARCH_claude_cowork_kimi_work.md` — product research, §Design Decisions, open-source gold
- `docs/.assets/cowork-app-re/*.md` — per-dimension deep detail (symbol map, session lifecycle, vm-layer, cloud-bridge, security-model, claude-code-binary, web-endpoints-community)

## Citation rules
- Mechanism cloned from Cowork → cite `§<section>` of the RE report
- Local-first adaptation → flag `[design decision]`
- Invented (no evidence) → flag `[invented]`
