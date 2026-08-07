# RH Co-work

Local-first clone of Claude Cowork + Kimi Work. An agent (Claude Code CLI) works alongside you on your files — producing live artifacts, on a schedule, with MCP connector access — through a local web workspace.

Status: **spec phase complete (approved)** — no implementation code yet.

## Docs

- `specs/00-index.md` — spec map + read order + status
- `specs/01-mission.md` — intent, users, core loop, out-of-scope
- `specs/02-constraints.md` — binding rules (local-first, runner contract, spawn template)
- `specs/03-architecture.md` + `.mmd` — C4 context/containers/components (view: `python3 specs/serve.py --port 8001`)
- `specs/04-data-model.md`, `05-interfaces.md`, `06-runtime.md`, `07-security-permissions.md`
- `specs/prds/` — PRDs: agent sessions, live artifacts, scheduled tasks, local files, MCP connectors, memory
- `specs/glossary.md` — binding terminology
- `docs/` — reverse-engineering research (`REVERSE_ENGINEERING_claude_cowork.md`, `.assets/`)
- `devlogs.md` — session history

## Stack (locked)

Python 3.12+ · SQLite (WAL, aiosqlite) · FastAPI + uvicorn + websockets · pydantic · loguru · host `claude` CLI (stream-json) as runner · host-native isolation with permission gates (no VM in v1).
