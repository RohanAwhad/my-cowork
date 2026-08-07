# Research Backlog — Claude Cowork RE

Status tracker for the reverse-engineering campaign (see `RESEARCH_claude_cowork_kimi_work.md` + `devlogs.md`).

## Pending — blocked on live sessions (user-run)

> **2026-08-07: User is NOT running anything right now.** Live/dynamic items below are blocked until user runs real Cowork sessions in Claude.app.

- [ ] **Live session trace (a) — artifact-building task**: create a task that produces files/artifacts; capture: session dirs created on disk, VM boot, outputs flow, FileSystemWatcher events, cowork_settings.json creation
- [ ] **Live session trace (b) — scheduled task**: create + trigger a scheduled task; observe where state lands (local vs cloud), run-per-session behavior
- [ ] **Live session trace (c) — folder-grant task**: grant a local folder via `request_cowork_directory`; capture mount points (`/sessions/<name>/mnt/`), permission prompts, deletion approval flow
- [ ] **mitmproxy capture** of app traffic during sessions (CA trust + relaunch with proxy env; fallback: logs+lsof only if TLS pinned)
- [ ] **Enable app debug logging**: `CLAUDE_ENABLE_LOGGING` + VM debug (`cowork_vm_swift.log`) — needs app restart

## Done — 2026-08-06/07 (static RE campaign)

- [x] **Static RE swarm** (7 agents) — symbol map, session lifecycle, VM layer, cloud bridge, security model, claude-code binary, web endpoints/community RE → `/tmp/opencode/deepresearch/cowork_app_re-M3KQ/`
- [x] **rootfs.img inventory** via debugfs (GPT: ext4 @ sector 206848; Ubuntu image; Node 22, sdk-daemon, srt, doc stack baked; Claude Code injected at boot)
- [x] **Synthesis**: `docs/REVERSE_ENGINEERING_claude_cowork.md` (architecture + lifecycle + security + endpoints + EIPC surfaces + mermaid diagrams)

## Pending — blocked on live sessions (user-run)

> **2026-08-07: User is NOT running anything right now.** Live/dynamic items below are blocked until user runs real Cowork sessions in Claude.app.

## Tooling status

- e2fsprogs — installed ✅ (`/opt/homebrew/opt/e2fsprogs/sbin/debugfs`)
- mitmproxy — installed ✅ (`~/Library/Python/3.9/bin/mitmproxy`)
