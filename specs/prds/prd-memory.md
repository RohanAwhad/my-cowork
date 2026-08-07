# PRD — Memory

> Writer: W4f (prd-memory) | Status: written — pending review
> Grounding: 01 §4 row 7, 02 §2 (config dir, spawn template), 03 §5 (dropped: `CoworkMemory`, knowledge bases), 04 §1.7 (Settings) + §3 (on-disk layout), 05 §1.1 (HTTP/WS surface) + §2.1 (SpawnSpec), 06 §2.3; RE §4, §5; security-model.md §7, §9.4, §10.1; web-endpoints-community.md (CoworkMemory EIPC surface).
> Scope amendment [design decision]: this PRD amends 01 §4 row 7 and 03 §5 — a minimal global memory store counts as "the basics"; knowledge bases remain deferred (03 §5, §7 below).

## 1. Current Behavior

- Cowork exposes `CoworkMemory` (EIPC, 2 methods: `readGlobalMemory` / `writeGlobalMemory`) — a global memory store shared with the MS-365 add-in; renderer-driven, main process is the local executor (RE §5 line ~160 — CoworkMemory EIPC table; web-endpoints-community.md).
- Cowork knowledge bases: `mcp__cowork__create_knowledge_base` tool (injected externally — `Xye()` returns `null` in the bundle, RE §4), KBs mounted **rw** at `/sessions/<vm>/mnt/.knowledge/<mountName>` with slugged mount names, `<knowledge_base>` blocks appended to the system prompt, `kb-file-changed` events forwarded to the renderer (security-model.md §7). Flagged gap: no in-bundle gate on the rw KB mount (security-model.md §10.1).
- Cowork has no `instructions`/`CLAUDE.md` preference key; folder instructions are absorbed in-VM by the CLI from the mounted `.claude` dir (`CLAUDE_CONFIG_DIR`, mounted rwd) (security-model.md §9.4).
- RH Co-work today: no Memory entity — 04 defines seven entities, none is Memory; mission §4 row 7 defers "memory store beyond basics" (global read/write memory, RE §5 `CoworkMemory`); 03 §5 drops `CoworkMemory` and knowledge bases, routing knowledge bases to **this PRD**. v1 persistence = session transcript + artifacts only.
- The runner already persists user memory natively: the CLI loads `~/.claude/CLAUDE.md` (user memory file) at every spawn because the shared user config dir is used (02 §2 — `CLAUDE_CONFIG_DIR` is never isolated).

## 2. Desired Behavior

User story: *"As a user I want the agent to remember facts across sessions."*

The agent remembers durable facts (user preferences, project decisions) across sessions via a **global workspace memory**; the user can view and edit it in the workspace; scheduled runs read the same memory. v1 scope is deliberately minimal: a file-based store with injection, no search, no history, no per-session isolation.

**Design decisions (binding for v1):**

- **D1 — v1 = file-based global memory at `~/.co-work/memory.md`** [design decision]. A plain UTF-8 markdown file in the workspace data root (04 §3 layout, extension). No SQLite entity: the file IS the store. Answers the 04 open question — no `Memory` entity in v1. Justification: the store is read/written by the agent's own tools (not by our code), so a file the CLI can address directly is the smallest correct surface; a DB row would add a translation layer with no benefit at this scale.
- **D2 — CLAUDE.md assessment**: `~/.claude/CLAUDE.md` IS the natural per-user memory mechanism for the claude CLI runner — it already loads at every spawn via the shared config dir (02 §2, security-model.md §9.4 analog). Workspace memory is a **separate, app-owned file**: the workspace must never write `~/.claude/CLAUDE.md` — that file is user-owned (settings, hooks, allowlists, personal instructions), and clobbering it would violate 02 §2's shared-config-dir contract. `~/.co-work/memory.md` complements it: user memory (CLAUDE.md) + workspace memory (memory.md) both reach the agent, neither overwrites the other.
- **D3 — injection via `--append-system-prompt`, NOT cwd-relative CLAUDE.md** [design decision]. Justification: spawn cwd = first granted folder else outputs dir (05 §2.1). A cwd-relative `CLAUDE.md` would (a) mutate user-visible state in the granted folder, (b) be detected by `ArtifactWatcher` as an artifact, (c) collide with the user's own project CLAUDE.md. `--append-system-prompt <text>` keeps memory app-owned and the session cwd clean. **Verified on `claude` 2.1.220 (probe, 2026-08-07)**: the flag exists and works — behavioral proof (model obeyed the injected instruction); it is **not visible in any stream-json event** (model-side only), so verification is behavioral at AC level, never stream-observable. **Requires an amendment of the binding spawn template (02 §2) and `SpawnSpec` (05 §2.1) — amended in parallel**; proposed shape in §3.3; owned by the 02/05 writers (this PRD is the capability owner and proposes the contract).
- **D4 — write-back via the agent's own tools**: spawn adds `--add-dir ~/.co-work`; the PreToolUse path-filter hook (02 §2, hook authored by 07-security) confines memory access to **exactly** `~/.co-work/memory.md` — the agent may Read/Edit/Write that one file and nothing else in `~/.co-work` (never `cowork.db`, never other sessions' trees) [design decision]. Without this confinement, `--add-dir ~/.co-work` would expose the whole data root. **Requires an amendment of the hook contract**: 07 §5.3 allowed-roots and prd-local-files §3.4 must include `~/.co-work/memory.md` in the allowed set — **amended in parallel: 07 §5.3 / prd-local-files §3.4**; everything else under `~/.co-work` stays blocked.
- **D5 — replace semantics, markdown format** [invented]: the agent rewrites sections via Edit/Write (outdated facts replaced in place). No append-only machinery, no app-side merge.
- **D6 — size cap 64 KB** [invented]: hard-enforced by the PreToolUse hook on Edit/Write to memory.md (resulting size > cap → block; the block is recorded via the prd-local-files hook-decisions ingestion — `hook-decisions.jsonl` → `PermissionRecord` — not 05 §1.4, which records `PermissionGate` policy decisions only), and the app refuses to inject an over-cap file at spawn (report-only notice, never silent truncation).
- **D7 — point-in-time snapshot at spawn** [design decision]: memory is read once per session when the runner spawns. The one-active-session invariant (02 §7, 06 §3) guarantees no concurrent writers on memory.md → race-free, no locking.
- **D8 — `Settings.memoryEnabled: bool = True`** toggle (04 §1.7 extension). Disabled → no injection, no `--add-dir ~/.co-work`; the file is left untouched.

**Consistency guarantee (SchedulerEngine):** memory is a single file read at spawn by the one run slot (02 §7). A scheduled run therefore observes exactly the facts the most recent interactive session left in `memory.md`; there is no per-run shadow copy, no caching layer, no read-forwrite serialization — consistency is a direct consequence of D7 + the one-active-session invariant. If a later phase lifts the single-slot invariant (06 §3 headroom), memory read/write must be re-examined for concurrency [design decision].

## 3. I/O contracts (types first)

### 3.1 The memory file (the store)

```python
MEMORY_PATH = Path.home() / ".co-work" / "memory.md"      # 04 §3 root extension [design decision]
MEMORY_SIZE_CAP_BYTES = 64 * 1024                          # [invented] (D6)

# format [invented]:
#   # Memory
#   ## <topic>            # one section per topic
#   - <fact>             # bullets; replace stale facts, keep under the cap
class MemorySnapshot(BaseModel):       # workspace view (§3.4)
    content: str
    sizeBytes: int
    modifiedAt: datetime | None        # file mtime; None = file does not exist yet
```

Read/write rules:
- **Read (app side)**: `SessionManager` reads the file at spawn (D7). Missing file → no injection, no error. Size > cap → skip injection + publish report-only notice (D6). The injected text is the file content verbatim, prefixed by a short instruction block telling the agent the file's path, the format, and the cap [invented].
- **Write (agent side)**: via Edit/Write under the hook-confined path (D4), under the cap (D6). Writes are immediate and durable — no flush, no transaction.
- **Write (user side)**: `PUT /api/memory` (below) or direct file edit outside the app; last-writer-wins; the app only ever reads at spawn (D7).

Injection example (composition in `start_session`) [invented]:

```
--append-system-prompt:
Workspace memory file: /Users/<user>/.co-work/memory.md
Keep it current: add durable user/project facts, replace stale ones, stay under 64 KB.

# Memory
## Coding style
- 2-space indent
## Tools
- user prefers uv over pip
```

Failure behavior: a missing file is not an error (normal first run); an unreadable file (permissions/IO) surfaces per 02 §6 fail-fast — the exception fails the session, it is never swallowed; memory is advisory, and a memory-read failure is treated like any other pre-spawn error (06 §4 row 3 path). Agent writes to memory.md are ordinary tool calls — captured by the transcript (05 §2.2); hook blocks are ingested via the prd-local-files hook-decisions path (`hook-decisions.jsonl` → `PermissionRecord`), not 05 §1.4; no extra audit rows [design decision].

### 3.2 Settings (04 §1.7 extension — no schema change)

```python
class Settings(BaseModel):
    # ... existing fields (04 §1.7) ...
    memoryEnabled: bool = True          # D8; stored via existing settings(key,value)
```

### 3.3 Spawn injection (`SpawnSpec` extension — amendment applied in parallel, 05 §2.1)

```python
class SpawnSpec(BaseModel):
    # ... existing fields (05 §2.1) ...
    append_system_prompt: str | None = None   # D3 → CLI arg --append-system-prompt <text>; None = omit
    add_dirs: list[Path]                      # existing; gains ~/.co-work when memoryEnabled (D4)
```

Composition (at `start_session`): `append_system_prompt = memory_block` when `memoryEnabled` and the file exists and ≤ cap; else `None`. `add_dirs` appends `~/.co-work` exactly when `append_system_prompt` is set. SchedulerEngine needs **no code change** — scheduled runs enter the same `start_session` path (mission §3.2) and therefore read the same memory (consistency criterion 4).

### 3.4 Workspace surface (05 §1.1 extension)

| Route | Method | In | Out |
|---|---|---|---|
| `/api/memory` | GET | — | `MemorySnapshot` (file read at request time; view is read-only in UI) |
| `/api/memory` | PUT | `{content: str}` | 204; 400 if `len(content) > MEMORY_SIZE_CAP_BYTES`; 409 if `memoryEnabled=false` [invented] |

UI: minimal read-only view + edit field, "memory" section in the workspace [invented]. The view renders the markdown as preformatted text (no converter libraries — 02 §5 dependency policy); the edit field is a plain textarea writing raw markdown via PUT. No new WS topic [design decision]: memory.md is not watched (adding a watcher for one file is not worth it in v1); the UI re-fetches via GET on navigation/manual refresh; the view may go stale mid-session and that is accepted.

### 3.5 Explicitly unchanged interfaces

`EventBus` topics (05 §1.5), `Storage` tables (04 §2), artifact pipeline (03 §4c), teardown protocol (05 §3.3): no memory-related changes. The memory notice reuses the existing `permission.notice`-style report-only channel (05 §1.1).

## 4. Component touchpoints

| Component | Change | Detail |
|---|---|---|
| `SessionManager` | Reads memory at spawn, builds injection | `start_session`: load file (D7) → compose `memory_block` → set `append_system_prompt` + `add_dirs` on the spec (03 §4a path) |
| `RunnerAdapter` | Passes new args through | `--append-system-prompt` and `--add-dir ~/.co-work` from `SpawnSpec` (02 §2 template + 05 §2.1 amendments, applied in parallel, D3) |
| `PermissionGate` / 07 | Hook rule for memory.md | PreToolUse path-filter: allow Read/Edit/Write on `~/.co-work/memory.md` only; block everything else under `~/.co-work`; Edit/Write resulting size > cap → block (D4, D6). Hook content authored by 07-security [design decision] |
| `WorkspaceServer` | GET/PUT `/api/memory` + UI section | 05 §1.1 route table extension (§3.4) |
| `Storage` | Settings row only | `memoryEnabled` via existing `get_setting`/`set_setting`; no new table |
| `SchedulerEngine` | None | Same spawn path ⇒ same memory (consistency) |
| `ArtifactWatcher` | None | memory.md lives outside outputs dirs; never watched |

## 5. Acceptance criteria (testable)

1. **Cross-session recall**: session A tells the agent a fact (e.g. "user prefers 2-space indent"); the agent updates `memory.md` (observable in the file). Session B, with a fresh prompt not mentioning the fact, demonstrates recall (agent cites or uses the fact from injected memory).
2. **User CLAUDE.md untouched**: `~/.claude/CLAUDE.md` mtime and size are identical before and after sessions A and B.
3. **Cap enforced**: an Edit/Write to memory.md that would exceed 64 KB is blocked (hook), and the block is recorded via the prd-local-files hook-decisions ingestion (`hook-decisions.jsonl` → `PermissionRecord`); `PUT /api/memory` with over-cap content returns 400; an over-cap file present at spawn is not injected and a report-only notice surfaces.
4. **Scheduled runs share memory**: a scheduled run spawned after a prior interactive session wrote a fact can read/use that fact (same spawn path, no scheduler code change).
5. **Restart survival**: app restart → `memory.md` persists on disk (04 §3 root) and is still injected into the next session; no boot reconcile involvement (06 §2.1).
6. **Toggle**: `memoryEnabled=false` → no `--append-system-prompt` and no `--add-dir ~/.co-work` at spawn; `PUT /api/memory` returns 409; the file is not modified.
7. **UI round-trip**: GET returns current file content; PUT persists content that the next session observes via injection.

## 6. Out of scope (v1)

- **Knowledge bases** (deferred to v2 — §7 below; 03 §5)
- **Per-connector memory** (e.g. connector-specific facts, RE §5 shared-store extent)
- **Memory search / RAG** (file is injected whole, ≤ 64 KB; no retrieval)
- **Memory versioning / history** (no versions table, no diff; cf. Artifact versioning, 04 §1.4)
- **Per-session memory isolation toggle** (one global store in v1; the file is visible to every session)
- **Memory sharing with external surfaces** (Cowork shares the store with the MS-365 add-in, RE §5 — no local analog exists)
- **`Memory` SQLite entity** (answered in D1: file, not DB)

## 7. v2 — Knowledge bases (deferred, 03 §5)

Deferral state: knowledge bases are dropped from v1 per 03 §5; this PRD owns the deferred detail. What v2 needs (cloned from RE §4 + security-model.md §7, adapted to host-native):

- **KB store**: per-KB directory (e.g. `~/.co-work/knowledge/<id>/` [design decision — replaces the `.knowledge/<mountName>` bind-mount analog, RE §4]), slugged names (`zQe` slugger analog, security-model.md §7).
- **Tools**: a `create_knowledge_base` tool + KB read tool — v1 has no in-app MCP client (03 §3), so v2 ships a bundled local MCP server registered via `ConnectorRegistry` (`--mcp-config`, 02 §2) exposing the KB tool surface [design decision].
- **Session access**: KB dirs enter the session via `--add-dir` + the PreToolUse path-filter hook (02 §2 primitives) — the host-native analog of the `rw` mount (security-model.md §7).
- **Prompt injection**: `<knowledge_base>`-block analog appended to the spawn (`--append-system-prompt` pattern generalizes, D3) [design decision].
- **Change surfacing**: `kb-file-changed`-analog events → EventBus → workspace (security-model.md §7; v2 KB watcher).
- **Fix the Cowork gap**: Cowork mounts KBs rw with no in-bundle approval gate (security-model.md §10.1) — v2 gates every KB write through the path-filter hook and the audit trail by construction (host-native enforcement, 02 §6 fail-closed) [design decision].

## 8. Open questions

1. Should the injected memory block include an instruction to keep the file under the cap, or is the hook alone sufficient? [invented — UX choice, default: both]
2. memory.md lifecycle: created by the app on first write (SessionManager, 04 §3 creation-owner pattern) vs first agent write [design decision — default: app creates on first `start_session` when enabled].

OQ1 (closed): `--append-system-prompt` verified on `claude` 2.1.220 (probe, 2026-08-07) — exists and works; model-side only, not stream-observable (D3). The 02 §2 template and 05 §2.1 `SpawnSpec` amendments are applied in the parallel round; no gating question remains.
