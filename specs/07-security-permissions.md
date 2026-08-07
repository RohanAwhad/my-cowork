# 07 — Security & Permissions

> Writer: W5 | Status: written — pending review
> Binding: 02 §2 (spawn-time policy, config dir, merge rule), 02 §4 (127.0.0.1), 02 §6 (fail-closed), 04 §1.5 (`PermissionRecord`), 05 §1.4 (`PermissionGate`), 05 §3.3 (teardown), 06 §6 (runner hardening). Resolves 03 §6 lines 74–85 deferrals: WorkspaceServerToken, effective-allowlist merge, runner env + hooks, **deletion audit scope**.

## 1. Threat model

### 1.1 Honesty preamble (v1 is advisory, not a sandbox)

v1 has **no OS-level sandbox**: no VM (02 §3, RE §3), no per-process seccomp (security-model §8 — Cowork's is VM-native), no mounts matrix `ro/rw/rwd` (03 §5, RE §4). All gates are (a) spawn-time CLI flags and (b) a static PreToolUse hook registered in the user's shared settings.json (02 §2) — mechanisms the `claude` CLI honors. **Only the flags are an enforcement boundary**: hook errors are non-blocking by CLI design (probe, claude 2.1.220, 2026-08-07: an exit-1 hook still let Bash run; only explicit stdout `{"hookSpecificOutput":{...,"permissionDecision":"deny"}}` blocks), so hooks are path-granular best-effort (§5.3). These mechanisms constrain the *agent*, never the *user*. A determined agent with an allowed Bash can edit its own hook config (same uid); malware on the host is out of scope (02 §3 — host is trusted, mission §2). The gates raise the cost of errant behavior and make it visible; they do not contain it. Every row below states the honest residual.

### 1.2 Adversaries

Adversaries: **malicious/errant agent behavior** (prompt injection, path escape, destructive tools, exfiltration via web tools), **accidental user error**, **rogue MCP server**.

| Threat | v1 mitigation | Residual risk |
|---|---|---|
| Prompt injection — hostile instructions in fetched content, artifacts, or connector output steer the agent | Spawn-time allowlist caps reach (02 §6: nothing auto-approved outside policy); every `tool_use` correlated and audited (§3); no content is ever executed by our code (02 §1 — we call no APIs, run no sandbox around fetched bytes) | Within the allowlist, injected content steers real decisions (reads, writes, exfil attempts inside grants); the workspace renders agent output verbatim — display-only, but users may act on it |
| Path escape — `..`, absolute paths, symlinks out of grants | Grant-time realpath home confinement (RE §4 `Qye`); check-time realpath containment in the path-filter hook (§5.3 — best-effort granular, errors non-blocking by CLI design); **the spawn-time allowlist is the hard boundary** (denied-wins, verified §2.2) + cwd + `--add-dir` | Hook is plain config the agent can edit (same uid); a hook exit 1 or missing hook does NOT block (probe — CLI design); hook cannot filter Bash (§5.3); a future OS-level boundary is out of scope (02 §3) |
| Destructive tools — `rm -rf`, overwriting user files | `--disallowedTools` always binds (02 §2); conservative per-task `allowedTools` for scheduled runs (RE §6 gate analog); outputs-dir artifacts are versioned (04 §1.4 — undo within outputs) | No deletion gate in v1 (03 §5 — deferred to prd-local-files); any *allowed* Bash/Write can destroy granted folders; no restore for non-outputs files |
| Exfiltration via web tools — WebFetch/WebSearch leaking file contents | Web tools run only if allowlisted (default-deny, §2.2); every `tool_use` recorded with input snapshot (§3.2) | Our code never sees the CLI's network traffic (02 §1 — CLI owns its auth/network); a session with Read+WebFetch can exfiltrate granted files, unobservable in v1 |
| Accidental user error — over-broad grant, careless prompt, granting `~` | Grant-time home confinement rejects out-of-home folders (RE §4 `Qye`, §5.1); grants are per-session, explicit, re-reviewable in the workspace + audit | `$HOME` itself and the `~/.co-work/` tree are non-grantable (§5.1); a wide allowlist on a mis-prompted run is still a wide blast radius |
| Rogue MCP connector — malicious tool with destructive capability | Tool matrix default-deny: only `Connector.toolNames` enter the allowlist (05 §1.8); `--strict-mcp-config` blocks non-matrix MCP sources (02 §2); interactive-OAuth connectors excluded from scheduled runs (02 §2) | Allowlisted connector tools run unconstrained inside grants; the connector binary executes as the user with full network (no sandbox) |
| Local tampering — user/malware edits DB or audit after the fact | Append-only storage API (§4.5); sensitive files 0600 (§6, §8); optional hash chain `[invented]` detects post-hoc edits | Same-user attacker rewrites anything (detection ≠ prevention); out of scope (no sandbox, 02 §3) |

## 2. Permission model (binding, from 02)

### 2.1 Spawn-time policy only

Allowance is fixed when the runner spawns the CLI: `--permission-mode manual` + `--allowedTools` + `--disallowedTools` (02 §2, glossary `spawn-time policy`). There is **no mid-run permission channel** in v1 — the raw CLI in `-p` mode emits no `permission_request` (glossary, verified 02 §6); unallowed tools are auto-denied inside the CLI, the denial arrives as a `tool_result`. Workspace dialogs are report-only (01 §3.1, 05 §1.1 `permission.notice`).

### 2.2 Precedence and merge algorithm (binding — resolves 03 §6 line 75)

**Effective allowlist = workspace policy ∪ user settings; `--disallowedTools` always binds** (02 §2). Exact algorithm, evaluated once at spawn by `PermissionGate.resolve_policy` (05 §1.4):

```
userPolicy    = read from the shared CLI settings.json (allow/deny lists, 02 §2 config dir;
                exact keys follow the pinned CLI version, 02 §2 version pinning)
workspacePolicy = per run type (§2.4)
allowed = workspacePolicy.allowed ∪ userPolicy.allowed     # union — one source suffices to allow
denied  = workspacePolicy.denied  ∪ userPolicy.denied      # union — one source suffices to deny
decide(toolName) = DENY if toolName ∈ denied               # denied wins over allowed
                   else ALLOW if toolName ∈ allowed
                   else DENY                                # unlisted ⇒ default-deny
```

- **Union for allow**: a tool need only be allowed by *one* source (workspace or user settings). Intersection ("both must agree") is **not applicable** — it would silently narrow the user's own settings, and 02 §2 names union.
- **Denied wins**: a tool in `denied` is denied even if it is also in `allowed`; `--disallowedTools` is always passed at spawn, never dropped (02 §2). **Verified (probe, claude 2.1.220): an overlapping allow+deny tool is removed from the model's toolset (`init.tools`) — never passed in both flags** (§2.3); an unlisted tool under `--permission-mode manual` yields `tool_result` "you haven't granted it yet" plus `result.permission_denials[]`.
- **Default-deny**: anything unlisted is denied under `--permission-mode manual` (02 §6). No `permission_request` events exist in `-p` mode, ever (probe).
- The CLI applies the same policy at spawn; the gate re-derives it from the same sources for deterministic correlation (01 §5.4). A divergence between gate-derived and CLI-applied policy (e.g. settings.json shape drift) is logged at spawn; enforcement remains the CLI's, audit remains the gate's.

### 2.3 Worked example

| Source | allowed | denied |
|---|---|---|
| Workspace policy (interactive session) | `Read, Write` | `WebFetch` |
| User settings.json | `Read, Edit, WebFetch` | `Bash` |
| **Effective (union; denied wins)** | **`Read, Write, Edit`** | **`WebFetch, Bash`** |

Decisions: `Read` → allow; `Edit` → allow; `WebFetch` → **deny** (in denied despite being allowed by user settings); `Bash` → **deny** (user denied binds); `Grep` → deny (unlisted). Spawn args: `--permission-mode manual --allowedTools Read,Write,Edit --disallowedTools WebFetch,Bash` (02 §2 template).

**Overlap note (verified, probe)**: `WebFetch` is allowed by user settings *and* denied by workspace policy — denied wins, and it is **omitted from `--allowedTools`** (the CLI removes an overlapping tool from the model's toolset, `init.tools`). The two flags never list the same tool; `--disallowedTools` carries it.

### 2.4 Policy sources: per-session vs per-task

| Run type | Workspace-policy source | Bindings at spawn |
|---|---|---|
| Interactive | `Session.allowedTools/deniedTools` (SessionCreate, 05 §1.1; snapshot on the session record, 04 §1.1) | merged with user settings (§2.2) |
| Scheduled | `ScheduledTask.allowedTools` (04 §1.3 — the auto-approve policy, RE §6 `shouldAutoApprovePermission` analog; tasks carry **no** task-level deny field) | merged with user settings; deny side = user settings ∪ connector-matrix `blocked` entries (§8.2) |

- **Matrix `ask` tools in scheduled runs — explicit fail-open `[design decision]`**: the connector tool matrix tracks per-tool modes `always | ask | blocked` (05 §1.8). A matrix-`ask` tool is **auto-allowed** in a scheduled run iff it was selected into `task.allowedTools`; otherwise it is denied at spawn (default-deny). This closes the unattended-run question: no scheduled spawn ever waits on an approval — the task policy is the bound (02 §7).
- **`approve_future` is interactive-only** (§3.3): scheduled spawns never inherit pending `approve_future` tools — a scheduled run's policy is exactly `task.allowedTools ∪ user settings, minus denies`; no runtime-recorded approval leaks into it.

`Session.allowedTools/deniedTools` and `task.allowedTools` are persisted on their records (04 §1.1/§1.3) so the audit can re-derive any run's exact policy post-hoc.

### 2.5 Mid-run policy changes `[design decision]`

Policy is fixed at spawn (argv); editing a session's `deniedTools` or a task's `allowedTools` (TaskPatch, 05 §1.1) mid-run has **no effect on the running session** — it applies to the next spawn (next session / next scheduled occurrence). `approve_future` follows the same rule: recorded during the run, consumed at the next **interactive** spawn only (§3.3). The workspace shows policy as-of-spawn (04 §1.1 snapshot fields). Rationale: no mid-run channel by construction (glossary); re-spawning to apply policy would break the run.

## 3. PermissionGate (05 §1.4)

### 3.1 decide()

`decide(tool_use, EffectivePolicy) -> Allow | Deny(reason)` — a pure function over `toolName` and the effective policy (§2.2). Deterministic: the decision source is the `tool_use` event fields `{id, name, input}` (05 §2.2 — "the only decision source"); **never** `tool_result` strings (01 §5.4, mission §5). The correlation mechanism (tool_use event → decision → denial) is owned by 05-interfaces (§1.4 `on_event`, §2.2 mapping); this doc owns the policy semantics (§2) and the record semantics (§3.2). The CLI's own auto-denial arrives as a `tool_result` and is stored as an event — it is evidence, not the decision source (05 §1.4).

### 3.2 record() every decision

Every decision (`grant` at spawn for allowlisted tools, `deny`, `approve_future`) → `Storage.append_permission(PermissionRecord)` (05 §1.9): DB row committed first (authoritative), `audit.jsonl` mirror appended best-effort after commit (P2-14, 04 §3). Failures to *record* never change the *decision* (§9). Denial also publishes `permission.notice` (05 §1.1) — report-only, no dialog, no timeout (06 §5 row 4).

### 3.3 approve_future consumption

"Approve future" on a report-only notice is recorded as `PermissionRecord(decision="approve_future")` (04 §1.5; no mid-run channel, glossary). It has **no effect on the current run**. Consumption is **interactive-only** `[design decision]`: at the next *interactive* spawn, `resolve_policy` merges pending `approve_future` tools into `allowed` **for that spawn only** and marks `consumedBySessionId` on the record (04 §1.5, P3-22) — the consumption itself is auditable. **Scheduled spawns never consume pending `approve_future` records** (§2.4) — the task policy is the only source for unattended runs.

## 4. Audit trail (resolves 03 §6 line 85)

### 4.1 Deletion-audit scope — DECISION: 05 §1.6 option (a)

**Watcher-sourced deletion events count as audit records** — this implements 05 §1.6 option (a) (deletions as `PermissionRecord`s), the option 07 chose; option (b) (trail stays grants/denials/approvals, deletions only in the `artifacts` table) is rejected. `ArtifactWatcher` already sees `fs_file_deleted`-style events (03 §4c, RE §1) and sets `deletedAt` (04 §1.4); the same event now also produces a `PermissionRecord`.

- **Strength**: 01 §5.4 and the glossary promise *every grant, deny, approval, and deletion decision* captured; option (a) is the only option that keeps that promise.
- **Weakness (stated)**: v1 watches the session outputs dir only (03 §4c — granted-folder watching belongs to prd-local-files), non-recursive, dotfiles ignored (RE §5). A deletion in an unmonitored dir leaves **no** audit row — the trail records deletions it can see, and this gap is known, not silent.
- Deletion *approval* semantics (the `rw → rwd` gate, RE §4) remain deferred to prd-local-files (03 §5); this decision concerns *observation*, not *gating*.

**Encoding**: new `PermissionRecord.decision` value `deleted_observed` — extends the 04 §1.5 literal (`grant | deny | approve_future | deleted_observed`; the 04 amendment was applied).

### 4.2 Record shape

`PermissionRecord` (04 §1.5), fields as bound, plus the `deleted_observed` extension:

| field | grant/deny/approve_future | deleted_observed |
|---|---|---|
| `toolName` | tool name (`mcp__<server>__<tool>` or builtin) | `"fs_delete"` |
| `decision` | per literal | `"deleted_observed"` |
| `input` | `tool_use.input` snapshot | `{path: <absolute host path>}` |
| `reason` | e.g. "tool_use correlated against effective allowlist: not listed" (mission §5) | "watcher observed deletion" |
| `sessionId`/`taskId` | as bound | sessionId always set (watcher is per-session); taskId from the session row |
| `consumedBySessionId` | approve_future only | NULL |

### 4.3 Storage: authoritative + mirror

SQLite `permissions` table is **authoritative**; per-session `audit.jsonl` is a best-effort human-readable mirror, appended after commit, divergence resolved from the DB (P2-14, 05 §1.9). Mirror capped at 50 MB then refuse-write + log (04 §3). Audit rows survive task deletion (`ON DELETE SET NULL`, P1-4) and session archival (04 §3 — mirror retained with the session).

### 4.4 Retention `[design decision]`

DB rows pruned at boot by `Storage` when `created_at` < now − **30 days**; the 30-day window bounds the authoritative store and the `/api/permissions` surface (05 §1.1). The per-session `audit.jsonl` mirrors (size-capped, 04 §3) are the long-term record, retained with the session until archive. Pruning is a lifecycle policy, not an edit: append-only is preserved within the retention window.

### 4.5 Tamper evidence

- **Append-only by construction**: `Storage` exposes no update/delete path for `permissions`; an attempted illegal transition raises (fail fast, 02 §6) `[design decision]`.
- **Optional hash chain `[invented]`**: each `audit.jsonl` line carries `prev_hash = sha256(previous line)`; a tampered line breaks the chain from that point. Off by default (feature flag) — DB rows are the authoritative record and the chain is detection-only. Not required for v1 correctness.

## 5. Folder grants and path safety

### 5.1 Grant time — realpath home confinement (RE §4)

A folder grant is accepted only if `realpath(selected)` is within `realpath(home)` — both sides realpath'd, symlink escapes rejected (RE §4 `Qye`/`XL`; clone of the Cowork folder-picker rule). **Non-grantable set (binding)**: `$HOME` itself (the picker must reject `realpath == realpath(home)`) and anything under the app-owned `~/.co-work/` tree (session state, policy files, server token, memory file — prd-local-files §3.1). Rejected grants are refused at the UI boundary and recorded in the audit trail (`decision="deny"`, `reason="outside home directory"` or `"app-owned path"`). Grants are per-session UI state (`Session.userSelectedFolders`, 04 §1.1), not persisted global trust (unlike Cowork's `localAgentModeTrustedFolders` settings surface, security-model §5, which v1 drops).

### 5.2 Spawn-time enforcement (02 §2, binding)

- `--add-dir <granted-folder>` per grant — CLI permission scoping.
- **Spawn cwd confinement** `[design decision]`: cwd = first granted folder, else the session outputs dir (05 §2.1).
- **`--allowedTools`/`--disallowedTools`** — **the enforcement boundary** (denied-wins, verified §2.2).
- **PreToolUse path-filter hook** — best-effort path granularity on top of the boundary (§5.3).
- Grants are otherwise advisory UI state (02 §2); nothing is mounted.

### 5.3 PreToolUse path-filter hook mechanism (owned-by: 07 defines mechanism + rules; supersedes prior "generated per-spawn hook files" language and any prd-local-files per-spawn generation/degrade-abort language)

**Mechanism (probe-verified, claude 2.1.220, 2026-08-07):** directory-based hooks (`hooks/PreToolUse/<name>`) are **dead** — the CLI registry scans settings.json only. The sole mechanism is settings.json:

```json
"hooks": { "PreToolUse": [{ "matcher": "*", "hooks": [{ "type": "command",
  "command": "~/.co-work/hooks/pre-tool-use.sh", "timeout": 30 }] }] }
```

- **ONE thin static hook script** (matcher `*`), registered in the user's shared settings.json `hooks` array (02 §2 config dir) — appended **with explicit user consent** (first-run prompt), **never** overwriting or removing existing user entries; **removed on uninstall** `[design decision]`. **Canonical script path: `~/.co-work/hooks/pre-tool-use.sh`** — the single path in the settings.json entry above and everywhere else (prd-local-files aligned to it); the script is installed by `RunnerAdapter` at first run (0600).
- The script is stateless and path-stupid: it reads `COWORK_POLICY_FILE` (per-session policy JSON: `{allowed_roots: [...], deny_rules: [...]}`) and `COWORK_SESSION_ID` from env — **verified inherited** (probe) — and emits the only output that matters:
  `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"|"deny"}}`
  `"deny"` → `tool_result` "Hook PreToolUse:<tool> denied this tool", `is_error:true`; `"ask"` in `-p` mode → blocked with the reason as content (probe). No other output (exit codes, stderr, malformed JSON) has any blocking effect — **hook errors are non-blocking by CLI design**.
- **Policy file**: written by `PermissionGate` per spawn (alongside `resolve_policy`, 05 §1.4), at `~/.co-work/sessions/<id>/policy.json`, mode **0600**, **deleted at session end** (04 §3 lists it as a session-dir lifecycle artifact). Session dirs themselves persist until archive — only the policy file is lifecycle-deleted. Content: granted roots (realpath'd) + session outputsDir + deny rules (§5.4). The hook emits `"deny"` when the target's `realpath` is outside `allowed_roots`; `"allow"` otherwise — a static script never embeds session state.
- **Memory carve-out**: `allowed_roots` always includes the workspace memory file `~/.co-work/memory.md` (prd-memory D4/D6 — agent read/write of global memory; cap enforcement via the hook). Everything else under `~/.co-work/` stays blocked (session state, policy files, server token).
- **Security consequence (binding)**: because hook errors/absence are non-blocking by CLI design, the hook is **path-granular best-effort only** — it narrows what a tool can touch *inside* its own run, and it fails open silently if broken. **The enforcement boundary is the spawn-time allowlist (denied-wins, verified §2.2) + cwd + `--add-dir`.** The old "spawn aborts when hook files are missing" rule is **superseded**: aborting is neither enforceable via hooks nor desirable — hooks add granularity, not boundary. A spawn proceeds allowlist-only when hooks are unavailable; **fail-closed at TOOL level still holds** (§2.2 default-deny). Any prd-local-files text implying hook degrade-to-abort or per-spawn hook generation is superseded by this section.
- **matcher**: `*` — one hook for all tools; the script applies only to path-taking tools (`Read, Write, Edit, NotebookEdit, Glob, Grep`; for `Glob`/`Grep` it checks resolved matches); non-path tools pass through with `"allow"`.
- **Bash is not path-filterable** `[design decision]` — its target is an opaque command string; Bash coverage is policy-only (allowlist, §2.2). prd-local-files' Bash command-string scan is **dropped** (superseded by this paragraph).

### 5.4 Symlink policy at check time

Confinement is re-verified with `realpath` **at check time**, not grant time `[design decision]` — v1 has no runtime mounts to pin a path (RE §4 pins via the VM mount). A symlink created inside a grant after spawn that resolves outside the union → hook emits `"deny"`. Stricter than Cowork's grant-time check (security-model §2) — the hook is the only check-time mechanism, and it is best-effort (§5.3): the grant union is also the spawn-time `--add-dir` + cwd scope, so the boundary holds even when the hook does not fire.

### 5.5 --add-dir scoping

`--add-dir` widens the CLI's permission *scope awareness* (fewer internal prompts inside the folder); it is **not** the boundary — the allowlist (§2.2) + cwd are (02 §2). Grants outside the union are never passed to `--add-dir` at all (filtered at spawn).

## 6. WorkspaceServer hardening (resolves 03 §6 line 74; fills 05 §1.10 stubs)

### 6.1 Bind and token

- Binds **127.0.0.1 only** (02 §4); no 0.0.0.0, no dual-stack wildcard.
- **`WorkspaceServerToken`** (glossary): generated at first run (`secrets.token_hex(32)` `[invented]` — token format is our choice; the kimi-web pattern is the file discipline), stored at `~/.co-work/server-token`, mode **0600** (kimi web pattern — `~/.kimi-code/server.token` 0600, RESEARCH_claude_cowork_kimi_work.md:115) `[design decision]`. Required for **all** HTTP API routes, artifact previews, and the WS upgrade. Regeneration: delete the file → new token at next boot `[design decision]` (old token dies; UI must re-enter).

### 6.2 Token lifecycle

Written once at first run; never stored in session files, audit rows, or `Settings`. **Printed once** (first boot, stdout/log) for the user to enter into the workspace; **after that, never logged** (masked per §8.1 rules). The UI holds it in `localStorage` and sends it on every request `[design decision]`.

### 6.3 Request checks

HTTP `/api/*` and `/previews/*`: `Authorization: Bearer <token>` (or `X-Workspace-Token` header) required; missing/incorrect → 401 (no 200-with-shape to avoid probing). Same-origin fetch is assumed but the token is mandatory regardless — defense in depth against localhost squatting `[design decision]`.

### 6.4 WS upgrade + Origin `[design decision]`

Browsers cannot set WS headers → token via `?token=` query on the upgrade; plus a **strict Origin check**: `Origin ∈ {http://127.0.0.1:<port>, http://localhost:<port>}` (fills 05 §1.10 `origin_allowed`). Token check first, then Origin; both must pass. The WS channel carries only server→client events (05 §1.1 — commands are HTTP), so a breach reads events but cannot issue commands.

### 6.5 Artifact previews

No separate auth: previews require the same `WorkspaceServerToken` (state: there is no per-artifact token). `GET /previews/...` serves stored artifact versions only (`artifact_versions.stored_rel_path`, 04 §1.4 — never arbitrary paths); names are sanitized at `version_file` (P2-16).

## 7. Runner hardening (06 §6)

Spawn env, every run (05 §2.1):

- **`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`** (02 §2; RE §2 env) — background agents disabled; belt-and-braces with the hook below.
- **`MCP_TOOL_TIMEOUT=30000`** (RE §2, claude-code-binary.md) — hung connector tools time out.
- Shared user `CLAUDE_CONFIG_DIR` — never isolated (02 §2).
- **`--permission-mode manual` only** — the literal is `"manual"` (05 §1.4); `bypassPermissions`/`acceptEdits` are **never** passed (02 §6; matches Cowork, which never enables `sessionBypassPermissionsMode`, RE §4).
- **PreToolUse Task hook**: matcher `Task`; input `run_in_background == true` → `permissionDecision:"deny"` ("Background agents disabled" — RE §2 hook analog). Registered alongside the path hook in the settings.json `hooks` array (same static-script mechanism + consent as §5.3) `[design decision]` (06 §6).
- **Teardown**: process-group kill on every exit path (05 §3.3, P1-7) — no orphaned `claude` subprocess keeps running under our env with our grants.
- **Scheduled runs**: connectors with `requiresOAuth` and not `oauthPreAuthDone` are excluded at spawn (`ConnectorRegistry.eligible_for_scheduled`, 05 §1.8; 02 §2) — a scheduled run never hits an unattended OAuth prompt.

## 8. MCP/connector security

### 8.1 Secrets `[design decision]`

Connector secrets (env vars, `headers` in compiled `--mcp-config`) never persist in session records: `Session.mcpConfig` stores server definitions **without** secret-bearing `env` values (04 §1.1 — secrets stay in the `connectors` table). The compiled per-session file `~/.co-work/tmp/mcp-config-<id>.json` (04 §3) is the only place secrets appear at spawn; it is written mode **0600** and deleted on session end (04 §3). Log masking: the loguru sink masks values under keys matching `(authorization|token|secret|api[_-]?key|headers)` case-insensitively in any logged dict — including `PermissionRecord.input` snapshots of connector tool calls `[design decision]`.

### 8.2 Tool matrix

The connector tool matrix tracks per-tool modes `always | ask | blocked` (05 §1.8). `always` tools feed `EffectivePolicy.allowed`; `blocked` tools feed the deny side (scheduled runs, §2.4); `ask` tools are denied at spawn for interactive runs unless the user approves (`approve_future`), and auto-allowed for scheduled runs iff selected into `task.allowedTools` (§2.4). Unlisted connector tools are denied at spawn (default-deny, §2.2). `--strict-mcp-config` is passed whenever a compiled file exists (02 §2) — other MCP sources cannot inject tools outside the matrix. Rogue-connector residual: §1.2 row 6.

## 9. Failure-closed guarantee

- `resolve_policy` raises → spawn **aborted** (`pending → failed`, 02 §6, 06 §4 row 3) — never spawn with an empty, partial, or guessed allowlist.
- `decide()` is **total**: any error in policy computation is converted at the boundary to `Deny` + `record(reason="policy computation error")` + `permission.notice` `[design decision]` — **deny, never allow**, on error. (This is the one sanctioned exception boundary per the security requirement; everything else fails fast, 02 §6.)
- Audit failure never reverses a decision: if `append_permission` raises, the decision already stands (CLI auto-denial is independent); the record attempt is logged and the session continues under 02 §6 rules.
- Hooks: **non-blocking by CLI design** (probe — exit-1/malformed hook output lets the tool proceed; only explicit `permissionDecision:"deny"` blocks, §5.3). No hook can *reverse* a decision or *force* an allow — at worst it silently fails open at path granularity. Compensation: the tool-level boundary (allowlist default-deny) does not depend on hooks; a hook outage is visible in the audit trail (policy-file writes are recorded per spawn) and in the session log `[design decision]`.
- `Auth.check_token` is a no-op stub by design (05 §1.10, mission §2); the token check (§6) is real.

## 10. Owned-by map

| Topic | Owner |
|---|---|
| Effective-allowlist merge rule (§2.2) | **07** (03 §6 line 75) |
| `WorkspaceServerToken` scheme + Origin check (§6) | **07** (03 §6 line 74; fills 05 §1.10) |
| Denial correlation mechanism (`tool_use` → decision mapping) | **05** §1.4/§2.2 (mission §5) |
| Hook mechanism + DENY rules + policy-file format (§5.3–5.4) | **07** (this doc); settings.json registration consent UX → 07/06; prd-local-files' per-spawn generation + Bash scan **superseded** (§5.3) |
| Task `run_in_background` hook content | **07** (§7); RunnerAdapter registers via §5.3 mechanism |
| Deletion audit scope | **07** (§4, decided here; 03 §6 line 85) |
| Deletion *approval* gate (`rw → rwd` analog) | prd-local-files (deferred, 03 §5) |
| Folder-grant UX/dialog flow + grant-time confinement UI | prd-local-files (RE §4 dialog analog, 03 §5) |
| Runner env + teardown mechanics | 06 §6, 05 §3.3 (shared with 07) |
| Connector OAuth pre-auth, tool inventory acquisition | prd-mcp-connectors (02 §2, 05 §1.8) |
| Artifact versioning / preview serving | prd-live-artifacts, 04 §1.4 |
