# PRD — Local Files (folder grants, path confinement, deletion, uploads)

> Writer: W4d | Status: written — pending review
> Cross-refs (binding): 02 §2 folder-grant primitives + §6 fail-closed; 03 §5 dropped mechanisms + §6 line 85; 04 §1.1 `userSelectedFolders` + §1.5 `PermissionRecord`; 05 §1.4/§1.6/§2.1; 06 §6 (path-filter hook must not be homeless, P3-26)
> Sources: RE §2, §4, §7; docs/.assets/cowork-app-re/security-model.md §1–§4
> Scope note: 07-security-permissions.md (W5) owns the hook DENY rules + install contract (§5.3) and the deletion-audit decision (§4.1); this PRD implements them — per-spawn policy-file generation and the path-granular hook behavior are owned here (07 §10). Probe ground truth: claude 2.1.220, 2026-08-07.

## 1. Current Behavior

### 1.1 Cowork (clone source, RE §4 / security-model.md)

- **Folder grants**: `request_cowork_directory` tool → native directory dialog → realpath-vs-realpath **home confinement** (`Qye`: both paths realpath()ed, suffix containment) → VM mount `"rw"` + `userSelectedFolders` persisted on the session record (RE §4; security-model §2).
- **Path validation**: 5-stage fail-fast gate `validateVMPathAccess` (`local_` prefix → `/sessions/<name>/` shape → vmProcessName bind → posix-normalize containment → `vbe` blocklist); host-side file access gated by `gbe` suffix-containment against allowed roots (`userSelectedFolders` ∪ outputs ∪ uploads ∪ `.projects` ∪ sharedCwd; security-model §1.3–§1.4).
- **Deletion**: mounts default `rw` (not `rwd`) → `rm` fails EPERM in the VM; `allow_cowork_file_delete` → re-mount as `rwd`; approval is per-mount-name, per-session, persisted in the session JSON and honored across spawns (RE §4; security-model §3).
- **Uploads**: `prepareUploads` staging — md5-content dedup (hash-suffix rename), hardlink/rename into `<storage>/uploads`, `ro` mount, host→VM path rewrite in the message, home-only via realpath+lstat (RE §2, §4; security-model §4).
- **Extension blocklists**: `vbe` (8 binary exts) blocked for **any** file access; `tst` (17 script exts) blocked for `openLocalFile` only (security-model §1.1).
- **Permissions**: `canUseTool` → `tool_permission_request` → renderer dialog → deny/once/always; full per-session `audit.jsonl` trail (RE §4; security-model §6).

### 1.2 RH Co-work baseline (specs to date — no PRD yet)

- Grants are named as spawn-time primitives in 02 §2 (`--add-dir` + spawn cwd confinement + PreToolUse path-filter hook) but the hook is **homeless** — 06 §6 explicitly owns it to 07 + this PRD (P3-26).
- No deletion gate: the mounts matrix (`ro`/`rw`/`rwd`, deletion approval) is a dropped Cowork mechanism, deferred to prd-local-files (03 §5).
- Uploads deferred: v1 prompts are text-only (03 §5).
- Watcher-sourced deletion audit scope is **decided in 07 §4.1**: deletions become `deleted_observed` audit records (07 §4.2); only the deletion *approval* gate stays deferred here (03 §5, 07 §10).
- Grants are otherwise advisory UI state persisted per session (02 §2).
- Probe (claude 2.1.220, 2026-08-07): directory-based hooks are DEAD — only the settings.json hooks array works; hook errors are NON-BLOCKING (exit 1/bad JSON → tool proceeds; only explicit stdout `permissionDecision:"deny"` blocks); hooks hot-reload and inherit the CLI env; the spawn-time allowlist is the hard boundary (denied-wins, 07 §1.1/§2.2 amended).

### 1.3 Mechanism mapping (Cowork → v1)

| Cowork mechanism (evidence) | v1 adaptation | Where |
|---|---|---|
| `request_cowork_directory` dialog → `mountPath("rw")` (RE §4; security-model §2) | Pre-spawn UI grant in `SessionCreate.folderGrants` (05 §1.1); no runtime dialog | §2.1, §6 |
| Home confinement `Qye` (realpath-vs-realpath, security-model §2) | Realpath-under-`$HOME` check at create AND spawn | §2.2, §3.1 |
| VM mount `rw` + `userSelectedFolders` persistence (RE §4) | `--add-dir` + cwd confinement (02 §2) + persisted row (04 §1.1) | §2.4 |
| `gbe` suffix-containment against allowed roots (security-model §1.4) | Realpath suffix-containment in the path-filter hook | §3.4 |
| `allow_cowork_file_delete` / `rwd` re-mount (RE §4; security-model §3) | None — no runtime deletion gate in v1; observation-only via `deleted_observed` (07 §4.1) | §3.6 |
| `vbe`/`tst` blocklists (security-model §1.1) | Not applicable to the host runner | §3.5 |
| `prepareUploads` md5-dedup staging (RE §2; security-model §4) | Deferred — text-only prompts | §3.7 |
| `canUseTool` → dialog + `audit.jsonl` (RE §4; security-model §6) | Spawn-time policy + hook-denial ingestion + `PermissionRecord` (04 §1.5) | §3.2, §4 |

## 2. Desired Behavior

**User story**: "As a user I grant a folder so the agent can work there; the agent's access is confined to it; deleting my files requires explicit approval."

Numbered flow (v1):

1. User creates a session in the workspace and grants one or more folders (`SessionCreate.folderGrants`, 05 §1.1).
2. **Home-confinement check** at the UI boundary: each grant's realpath must resolve under `$HOME` [design decision — Cowork enforces home confinement, RE §4]; `$HOME` itself is never auto-granted, and the app-owned `~/.co-work/` tree is not grantable [design decision — stricter than 07 §5.1's Qye-clone, which admits `$HOME`; see §3.1]. Failure → `GrantValidationError`, no session row created, and the rejection is **recorded in the audit trail** (`PermissionRecord(decision="deny")`, 07 §5.1).
3. Grants are **persisted on the session** (`Session.userSelectedFolders`, 04 §1.1) before spawn (persist-before-spawn, RE §2).
4. At spawn `PermissionGate` writes the per-session policy file (mode **0600**) and ensures the single static PreToolUse hook is registered in the user's settings.json hooks array (07 §5.3 — one thin script, matcher `*`, appended with consent, never overwriting existing entries); `RunnerAdapter` spawns with `--add-dir <grant>` per grant (02 §2) and `cwd` inside the first granted folder, else the outputs dir (05 §2.1).
5. **The boundary is the spawn-time allowlist** (denied-wins, probe-verified — an unlisted tool is removed from the model toolset, 07 §2.2) + spawn cwd + `--add-dir`; the PreToolUse hook adds **path granularity on top** (best-effort — hook absence/errors are non-blocking by CLI design, probe, 07 §1.1). A hook path-denial returns stdout `permissionDecision:"deny"` → `tool_result` "Hook PreToolUse:\<tool\> denied this tool"; `PermissionGate` records the denial in the audit trail and surfaces a **report-only** notice (`permission.notice`, glossary `permission request`).
6. **Deletion**: v1 has **no runtime deletion gate** (07 §4.1 — the `rw → rwd` approval gate stays deferred, 03 §5) — `rm` inside a granted folder is permitted by the CLI. Accepted, flagged risk; observation is covered (step 7).
7. **Watcher-sourced deletion events** (outputs dir only — v1 watches the outputs dir, not granted folders, 03 §4c) feed the audit trail as `PermissionRecord(decision="deleted_observed", toolName="fs_delete")` (07 §4.1/§4.2); deletions in unmonitored dirs leave no row — known gap (07 §4.1).
8. **Uploads**: DEFERRED in v1 — prompts are text-only; the RE §2 staging model (md5 dedup, hardlinks, path rewrite) is reserved for a later phase.

Fail-closed posture: grants are re-validated at spawn (defense in depth); a stale/edited session row whose grants fail validation fails the spawn (`pending → failed`, 02 §6) [design decision]. Tool-level policy is always fail-closed (`--permission-mode manual`, denied-wins — probe, 07 §2.2); path-granular checks degrade to **allowlist-only** when the hook is absent or errors (non-blocking, probe) — still fail-closed at **tool** granularity, never path-wide-open [design decision].

### 2.5 State model (what persists vs transient)

| State | Location | Lifetime |
|---|---|---|
| Grants (authoritative) | `sessions.user_selected_folders` (04 §2) | Per session, persisted at create (RE §2 persist-before-spawn); read at every spawn; never mutated mid-run (v1 single-turn, 05 §1.2) |
| Grant event (audit) | `permissions` row `decision="grant"` + `audit.jsonl` mirror (04 §1.5) | Append-only |
| Per-session policy file | `~/.co-work/sessions/<id>/policy.json` (mode **0600**) | Per spawn — regenerated from the session row each spawn (AC 7); stale file is harmless (unread without `COWORK_POLICY_FILE`/`COWORK_SESSION_ID`); deleted at session end (04 §3; the session dir itself persists until archive) [design decision] |
| Static PreToolUse hook registration | user settings.json `hooks.PreToolUse[]` — one thin script, matcher `*` | Appended once **with consent** at first run; never overwrites existing entries; removed on uninstall (07 §5.3); hot-reloads, no per-spawn mutation (probe) |
| Hook decisions | `~/.co-work/sessions/<id>/hook-decisions.jsonl` | Per session; ingested to `permissions` at session close, then retained as raw log [invented] |

### 2.6 Data flow (spawn path)

1. `SessionManager.start_session` → reads grants from the persisted row → `PermissionGate.build_effective_allowlist(session)` (realpath-resolves each grant; rejects escaping grants → `pending → failed`).
2. `PermissionGate` writes `~/.co-work/sessions/<id>/policy.json` (0600) + ensures the static hook registration is present in settings.json (consent-gated, 07 §5.3) → returns policy path.
3. `RunnerAdapter.spawn(SpawnSpec)` — `add_dirs` = grants, `cwd` = first grant else outputsDir, env `COWORK_SESSION_ID` + `COWORK_POLICY_FILE` (05 §2.1 `SpawnSpec.env`, amended).
4. CLI runs; each tool call invokes the static hook (settings.json registration; hooks inherit the CLI env — probe) → reads the policy file via `COWORK_POLICY_FILE` → path rules (§3.4) → `allow`/`deny` stdout contract; `deny` also appends `hook-decisions.jsonl`.
5. Stream: hook path-denials arrive as `tool_result` ("Hook PreToolUse:\<tool\> denied this tool", probe) — stored as an event, never parsed for decisions (05 §2.2); gate-side audit comes from the hook-decision log ingestion at session close.
6. `permission.notice` published per recorded denial → workspace (report-only, 05 §1.1).

## 3. I/O Contracts (types first)

### 3.1 Grant shape

- `Session.userSelectedFolders: list[Path]` — binding, 04 §1.1; absolute host paths; JSON column `user_selected_folders` (04 §2). Grant timestamps live in the **audit trail** (`PermissionRecord(decision="grant", createdAt)`), since 04 §1.1 stores paths only; per-folder `grantedAt` on the Session would need a 04 amendment — open question, see §7 [design decision].
- Validation contract (WorkspaceServer boundary, pydantic-validated):
  `validate_grant(path: Path) -> Path` — raises `GrantValidationError` on: non-absolute, not a directory, realpath outside `$HOME`, realpath == `$HOME`, realpath inside `~/.co-work/` [design decision].
- Grant record: `PermissionRecord(toolName="folder_grant", decision="grant", input={folder: str})` (04 §1.5). **Rejected grants are audited too**: `PermissionRecord(decision="deny", reason=<GrantValidationError>)` (07 §5.1 — "rejected grants are refused at the UI boundary and recorded in the audit trail").
- Note vs 07 §5.1: this PRD refuses `$HOME` itself and `~/.co-work/` — stricter than 07 §5.1's Qye-clone (which admits `$HOME`); the tightening is intentional and narrows 07 §1.2's accidental-error residual [design decision].

### 3.2 Hook contract (Claude Code PreToolUse hooks — probe-verified, claude 2.1.220, 2026-08-07)

- **Mechanism (probe — ground truth)**: directory-based hooks are DEAD; the only working registration is the settings.json hooks array: `{"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "<static script path>"}]}]}}`. Matcher `*` — one static script; path tools are filtered inside the script [design decision]. Hooks **hot-reload** (registration edits apply without restart) and **inherit the CLI env** (probe) — the script reads `COWORK_POLICY_FILE`/`COWORK_SESSION_ID` from its env.
- **stdin JSON**: `{session_id, transcript_path, cwd, hook_event_name, tool_name, tool_input}`.
- **stdout JSON**: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"|"deny", "permissionDecisionReason": "<reason>"}}`; only an explicit `permissionDecision: "deny"` blocks — `deny` → `tool_result` "Hook PreToolUse:\<tool\> denied this tool" (probe). v1 never returns `"ask"` — `-p` mode has no mid-run permission channel (02 §6, glossary `permission request`) [design decision].
- **Errors are NON-BLOCKING (probe)**: exit 1 / bad JSON / missing script → the tool proceeds. Consequence (07 §1.1 amended): path-granular protection is best-effort; the **spawn-time allowlist remains the enforcement boundary** — fail-closed at tool granularity (`--permission-mode manual`, denied-wins, 07 §2.2). Path-coverage loss is logged + surfaced (§4.6).
- Decision rule: `allow` iff every path argument resolves (realpath) inside an allowed root; `deny` otherwise, with the escaping path in the reason.

### 3.3 Hook file layout (owned path — pick + justification)

| Path | Role | Owner |
|---|---|---|
| `~/.co-work/sessions/<id>/policy.json` | per-session policy file `{sessionId, cwd, allowed_roots: [granted realpaths, outputsDir, ~/.co-work/memory.md], deny_rules: [...]}` (format owned by 07 §5.3); mode **0600**; written pre-spawn, per spawn; deleted at session end (04 §3; the session dir itself persists until archive). Everything else under `~/.co-work/` stays blocked — session state, policy files, server token (07 §5.3) | PermissionGate |
| user settings.json — `hooks.PreToolUse[]` | ONE thin static registration: matcher `*`, command = static script path; appended **with consent**, never overwriting existing entries, removed on uninstall (07 §5.3 install contract) | RunnerAdapter (first run) / uninstall path |
| static hook script (`~/.co-work/hooks/pre-tool-use.sh` — canonical, 07 §5.3 settings.json example) | pass-through (exit 0) when `COWORK_SESSION_ID`/`COWORK_POLICY_FILE` absent (user's own terminal claude untouched); else reads the policy file, applies §3.4 rules, prints the stdout decision, appends the decision log | 07 §5.3 (authored); PermissionGate ships |
| `~/.co-work/sessions/<id>/hook-decisions.jsonl` | hook-appended NDJSON decision lines `{ts, toolName, input, decision, reason}`; ingested at session end → `PermissionRecord` rows (DB authoritative, 04 §1.5) | hook appends; PermissionGate ingests [invented] |

**Decision**: one static script registered once in settings.json + per-session policy file addressed by env. Justification: probe ground truth — directory-based hooks are dead, only the settings.json array registers; hot-reload means the registration is written once with consent and stays stable across sessions (no per-spawn config mutation); the per-session policy file (0600, env-addressed) is what changes per spawn, keeping the script static and the user's settings.json untouched after install (02 §2 shared config dir — never isolated, never rewritten). Env scoping (markers only in our spawn env) keeps the user's own terminal `claude` sessions pass-through. **Fallback (07 §1.1 amended)**: hook absent or erroring is NON-BLOCKING — confinement degrades to the spawn-time allowlist only (granted tools allowed, everything else denied at tool level; fail-closed at tool granularity, 02 §6); path-granular checks are best-effort + audited. Supersedes the earlier "--add-dir + cwd advisory" degradation wording.

### 3.4 Path rules (binding for hook and gate — single source of truth is the session policy file, 07 §5.3)

- **Allowed roots** = granted folders (realpath-resolved at spawn) ∪ outputsDir ∪ spawn cwd (`cwd` ∈ first grant else outputsDir, 05 §2.1 — listed explicitly for defense in depth) **∪ the memory carve-out** `~/.co-work/memory.md` (07 §5.3 — prd-memory D4/D6; agent read/write of global memory + cap check). The session state dir `~/.co-work/sessions/<id>/` is **not** writable except `outputs/` — protects transcript + audit from agent writes [design decision].
- **Containment check** (Cowork `gbe` suffix-containment pattern, security-model §1.4): resolve realpath of the target (target's parent for writes); `allow` iff `relpath(realpath(root), realpath(target))` is not absolute and does not start with `".."`.
- **Symlink policy**: resolve realpath at check time — a symlink inside a grant pointing outside is denied [design decision — Cowork realpaths everywhere: `Qye`, `gbe`, `kXe`].
- `$HOME` is never auto-granted.
- **Covered tools/args**: structured path args of Read/Write/Edit/NotebookEdit/Glob/Grep (`file_path`, `pattern`, …) only. **Bash is not path-filterable** — 07 §5.3 [design decision]: its target is an opaque command string; Bash coverage is policy-only (spawn-time allowlist). Superseded: the earlier best-effort command-string scan is dropped. **MCP tools**: not path-filtered in v1 — accepted limitation (MCP tool matrix is 07/prd-mcp-connectors territory) [design decision].
- Session-id or cwd mismatch between stdin and the allowlist payload → `deny` (defense in depth).
- Dotfiles are not special (Cowork's dotfile filtering is watcher-side, security-model §5).

### 3.5 Extension blocklists — NOT applicable in v1

`vbe`/`tst` (security-model §1.1) are sandbox-model artifacts: they gate VM path access and `openLocalFile` in a mount-isolated runtime. The host runner has no mounts and no VM path-validation stage, and the CLI executes scripts directly — a `.sh`/`.py` blocklist is meaningless here. v1 relies on the path-filter hook + spawn-time CLI policy instead; blocklists are explicitly **not implemented** [design decision].

### 3.6 Deletion contract (v1)

No gate (07 §4.1 — the `rw → rwd` approval gate stays deferred, 03 §5): `rm` inside a granted folder is permitted by the CLI; there is no `rwd` analog. Observation is decided (07 §4.1): watcher-sourced deletions (outputs dir only, 03 §4c) produce `PermissionRecord(decision="deleted_observed", toolName="fs_delete", input={path}, reason="watcher observed deletion")` (07 §4.2). Deletions in unmonitored dirs leave no row — known gap, not silent (07 §4.1).

### 3.7 Uploads contract

Deferred (03 §5; RE §2). No staging dir, no md5 dedup, no path rewrite in v1. `SessionCreate` carries text-only prompts.

## 4. Component Touchpoints

| Component | Responsibility |
|---|---|
| `PermissionGate` | Authors the policy file: `build_effective_allowlist(session) -> Path` (writes `~/.co-work/sessions/<id>/policy.json`, 0600, pre-spawn, per spawn, from the persisted session row; deleted at session end, 04 §3 (the session dir persists until archive)); ensures the static hook registration is present in settings.json (consent-gated install/remove, 07 §5.3); ingests `hook-decisions.jsonl` at session close → `PermissionRecord(decision="deny", reason="path outside granted folders (PreToolUse hook)")`; records grants AND grant rejections (`decision="grant"`/`"deny"`, §3.1); publishes `permission.notice` (05 §1.4, 03 §4d). Denials are never derived from `tool_result` string parsing (mission §5.4). |
| `RunnerAdapter` | `--add-dir <grant>` per grant (02 §2 template); `cwd` = first grant else outputsDir (05 §2.1 `SpawnSpec.cwd`); env `COWORK_SESSION_ID=<sessionId>` + `COWORK_POLICY_FILE=<policy path>` — `SpawnSpec.env`, amended in 05 §2.1; ships the settings.json hook registration at first run (07 §5.3 install). |
| `SessionManager` | Passes grants from the persisted session row at every spawn — grants are never re-entered from UI memory; spawn-time re-validation of grants (defense in depth, fail-closed per §2) [design decision]. |
| `Storage` | Persists `user_selected_folders` (04 §2) and `PermissionRecord` rows (04 §1.5). |
| `WorkspaceServer` | Grant validation at session create (home confinement realpath); renders `permission.notice` (report-only, glossary). |

### 4.5 Ownership boundary vs 07 and other PRDs

- **07-security-permissions.md (W5)**: owns the hook DENY rules + fail-closed semantics (§5.3), the settings.json install contract (consent, non-destructive, uninstall — §5.3), the deletion-audit decision (§4.1), the effective-allowlist merge rule (§2.2), `WorkspaceServerToken` (§6), and the `run_in_background` Task hook (07 §7). This PRD owns only the **path dimension**: per-session policy-file generation, the static script's path rules, and path-level denial audit.
- **prd-live-artifacts**: v1 watches outputs dir only (03 §4c); future granted-folder watching is owned by prd-local-files (mirror: prd-live-artifacts §8, orchestrator-aligned).
- **prd-mcp-connectors**: MCP tool path arguments are not filtered by this hook (§3.4 accepted limitation).
- Nothing in this PRD changes the spawn template (02 §2) — `--add-dir` and `--permission-mode manual` were already binding; the PRD adds only the policy file + static hook registration + env markers.

## 4.6 Failure behavior (fail fast, 02 §6)

| # | Failure | Behavior |
|---|---|---|
| 1 | Grant fails validation at create | `GrantValidationError` surfaces to the UI; no session row (02 §6, fail fast) |
| 2 | Grant fails re-validation at spawn (row edited/tampered) | Spawn aborted, `pending → failed`, `error` = validation reason; teardown protocol still runs (05 §3.3) |
| 3 | Hook registration absent or policy file missing at spawn (`~/.co-work/sessions/<id>/policy.json`) | NON-BLOCKING (probe) — tools proceed; confinement degrades to the spawn-time allowlist only (fail-closed at tool granularity, 07 §1.1); logged + surfaced warning; path-coverage loss recorded as a known gap [design decision] |
| 4 | User settings.json already has hooks entries | Registration is appended WITH consent, never overwriting (07 §5.3); if the user declines, path granularity is off — allowlist-only fallback (§4.6 row 3) [design decision] |
| 5 | Hook crashes (nonzero exit, bad JSON) | Tool proceeds (probe — non-blocking); gate logs the path-coverage gap in `hook-decisions.jsonl`; tool-level policy unaffected [invented] |
| 6 | `hook-decisions.jsonl` write fails (ENOSPC) | Hook still returns the decision (allowlist is in-memory); loss of audit line is logged — DB completeness gap is accepted, never blocks the tool call [design decision] |
| 7 | Session ends with unconsumed hook-decision lines | Ingested at close (last writer = PermissionGate); ingestion failure → `failed` state is unaffected, gap logged + reconciled on next boot pass [invented] |

## 5. Acceptance Criteria (testable)

1. Grant outside `$HOME` → `create_session` rejects with `GrantValidationError`; no session row created.
2. `$HOME` itself as grant → rejected.
3. Agent Write outside all grants (e.g. `~/Documents/other/x.txt`) → hook stdout `permissionDecision:"deny"` → `tool_result` "Hook PreToolUse:\<tool\> denied this tool" (probe contract); `PermissionRecord(deny)` in audit; `permission.notice` in workspace.
4. Agent Write inside a granted folder → succeeds; no denial records.
5. `rm` of a file inside a granted folder → permitted by the CLI (no v1 gate, 07 §4.1); watcher-visible deletions (outputs dir) produce `PermissionRecord(decision="deleted_observed")`.
6. Symlink escape: a symlink inside a grant pointing outside (e.g. `/etc/passwd`) → write denied.
7. Per-session policy file regenerated per spawn (0600) — payload reflects current grants + spawn cwd; settings.json registration stays stable (one static script, hot-reload — probe); install is idempotent.
8. Grants honored across respawns: every spawn derives `--add-dir`/policy file from the persisted session row (e.g. a failed-spawn retry), never from UI memory.
9. User's terminal `claude` session (no `COWORK_SESSION_ID`/`COWORK_POLICY_FILE`) → static hook pass-through; hooks never affect the user's own usage.
10. Audit rows for hook denials come from `hook-decisions.jsonl` ingestion — never `tool_result` parsing (mission §5).
11. Probe COMPLETE (claude 2.1.220, 2026-08-07): settings.json-only mechanism, env inheritance, non-blocking errors, `deny` → "Hook PreToolUse:\<tool\> denied this tool" — §3.2 is ground truth, no re-verification pending.
12. Fallback: with the hook registration removed, a granted tool (e.g. Write) outside a grant is NOT path-blocked (non-blocking by CLI design) but tool-level policy still binds — unlisted tools never enter the model toolset (denied-wins, probe, 07 §2.2); degradation logged + surfaced.

### 5.5 Verification approach (first-run evidence rule)

- **Probe DONE** (2026-08-07, claude 2.1.220): settings.json hooks mechanism, env inheritance, non-blocking error behavior, and the `deny` → "Hook PreToolUse:\<tool\> denied this tool" tool_result were captured; §3.2 records the ground truth (docs-over-code rule satisfied).
- **Hook unit tests**: pure-function tests of the path rules (§3.4) — containment, symlink escape, `..` traversal, cwd mismatch — with no CLI dependency (fast, deterministic).
- **End-to-end**: spawn a real session with a grant; (a) Write-tool to a path outside the grant → hook `deny` → assert `tool_result` "Hook PreToolUse:Write denied this tool", one `hook-decisions.jsonl` line, one `PermissionRecord(deny)` row, and the WS `permission.notice`; (b) Bash-behavior assertion matching spec reality — an allowed-Bash write outside the grant **succeeds** at path level (Bash is not path-filterable, 07 §5.3): no hook-decision, no `PermissionRecord`; the documented residual is asserted, not asserted-away.
- **Fallback**: with the hook registration removed, assert tool-level denials still hold (unlisted tool absent from `init.tools`) and the degradation warning is logged (AC 12).
- **Env isolation**: run the CLI from the user's shell (no `COWORK_SESSION_ID`/`COWORK_POLICY_FILE`) with the hook registered; assert pass-through (AC 9).
- Evidence-only reporting: every claim in the PRD review cites log file + line number (project convention), not assertions.

## 6. Out of Scope (v1)

- Uploads staging / drag-drop with md5 dedup + hardlinks (RE §2) — deferred per 03 §5.
- Mount-based isolation (ro/rw/rwd matrix, RE §4) — host-native only (02 §3).
- Extension blocklists `vbe`/`tst` (security-model §1.1) — sandbox-model only (§3.5).
- Deletion approval gate — no runtime gate in v1 (07 §4.1: observation only; approval gate deferred, 03 §5).
- Knowledge-base folder mounts (→ prd-memory).
- Per-folder read-only vs read-write distinctions — all grants are rw (mirrors Cowork's `rw` mount default, RE §4).
- Runtime (mid-run) grant dialog (`request_cowork_directory` analog, RE §4) — grants are pre-spawn only (glossary `FolderGrant`).
- Granted-folder artifact watching — v1 watches outputs dir only (03 §4c). Future-feature ownership: **prd-local-files** (mirrored in prd-live-artifacts §8; orchestrator aligns both sides) [design decision].

## 7. Open Questions

- Per-folder `grantedAt` on `Session` vs audit-only timestamps — needs a 04 §1.1 amendment if required by UI (see §3.1).
- Consent UX for the settings.json hook registration (decline → allowlist-only fallback, §4.6 row 4) — confirm presentation at 05/07 review.
