# PRD — Live Artifacts

> Writer: W4b | Status: written — pending review
> Capability dimension: artifact surfacing — detect, version, persist, stream, preview (mission §3.1 step 6; 03 §4c).
> Binding upstream: 04 §1.4 entity shapes (verbatim), 04 §3 on-disk layout; 05 §1.1 WS topics + preview route, 05 §1.6 ArtifactWatcher contract, 05 §1.5 EventBus; 06 §4 rows 9/10; 02 §5 browser-native embeds; 02 §2 spawn cwd.
> Citation keys: RE §N = docs/REVERSE_ENGINEERING_claude_cowork.md; RE session-lifecycle §N = docs/.assets/cowork-app-re/session-lifecycle.md; symbol-map §N = docs/.assets/cowork-app-re/symbol-map.md; RESEARCH §N = docs/RESEARCH_claude_cowork_kimi_work.md. `[design decision]` = local-first adaptation; `[invented]` = no evidence.

## 1. Current Behavior

### 1.1 What Cowork does (cloned surface)

- Deliverables are real files in the session outputs dir, mounted at `/sessions/<vm>/mnt/outputs`; a per-session `FileSystemWatcher` emits `fs_file_created` / `fs_file_deleted` events (RE §1, §10; symbol-map §3b payload `{type, sessionId, hostPath, fileName, timestamp}`).
- Watcher semantics: `fs.watch(dir, {recursive:false})`, initial scan seeding a known-files set, on-event `existsSync` + `statSync().isFile()` recheck, dotfiles skipped (RE session-lifecycle §5).
- Watcher lifecycle: started once after init (query enqueued); stopped on `result` and on `stopSession`; never restarted for later folders (RE session-lifecycle §5). Detection state (`fsDetectedFiles`) persisted on the session record (RE §2, session-lifecycle §5).
- Live artifacts in the UI = desktop-only interactive HTML dashboards with connector-driven refresh and version history; **versioning is server-side** for cloud sessions (RE §10; RESEARCH §1 — "every iteration saves a version; compare + restore"; connector refresh "without asking permission", RESEARCH §1). Deliverable file-types: docx/xlsx/pptx/PDF/txt/md/html/json/csv/images/ipynb/code (RESEARCH §1).
- Kimi analog: outputs written straight back into the mounted folder, no manual swapping (RESEARCH §1).

### 1.2 Gaps vs this clone (why this PRD exists)

- Cowork versions artifacts server-side/cloud (RE §10); we are local-first — versioning must live on the host (03 §4c `[design decision]`).
- Cowork's interactive HTML dashboards + connector refresh (RE §10, RESEARCH §1) are out of v1 scope (mission §4, this PRD §8).
- Cowork watches the first user-selected folder else the outputs dir (RE session-lifecycle §5); v1 watches the outputs dir only — granted-folder watching deferred (03 §4c `[design decision]`, this PRD §8).
- No local evidence for detection→UI latency, preview sandboxing, or version naming; those are `[invented]` below.

## 2. Desired Behavior

User story: *"As a user I want to see what the agent produced while it runs and open previous versions."*

Numbered flow (end-to-end, one session):

1. `SessionManager.create_session` persists the session row (`pending`) and mkdirs `~/.co-work/sessions/<id>/outputs` **before spawn** (04 §3; RE §2 persistence-before-spawn). The outputs dir is session-private; nothing but the agent writes to it `[design decision]` (Cowork shares a cwd-adjacent outputs parent, RE session-lifecycle §7.6 — dropped, 04 §3).
2. Runner spawns; spawn cwd = first granted folder else outputsDir (05 §2.1). Without folder grants, all agent-written deliverable files land in the outputs dir.
3. Health check passes → `pending→running` → `SessionManager` calls `ArtifactWatcher.watch(session_id, outputs_dir)` (attach at running — RE session-lifecycle §5 starts the watcher once, post-init `[design decision]`; 05 §1.6 does not state attach timing). `watch` runs an **initial scan**: files already present are agent output by construction and are versioned immediately (they are seeded as known so their own fs events do not re-emit) `[design decision]` — RE seeds known-files and ignores them (RE session-lifecycle §5), but RE watches shared/user folders where pre-existing files must be ignored; our outputs dir is per-session and starts empty.
4. Agent writes a file into the outputs dir → `fs.watch` event → `existsSync`-style recheck (file still present, is a file) (RE session-lifecycle §5).
5. Name is sanitized at `version_file` (04 §1.4 P2-16): basename only; `..` segments, `/` separators, empty names, `.`/`..` rejected — **no copy, no row, error-level log** (04 §1.4).
6. Content hashed (sha256); identical hash → no-op (dedupe, §5) `[design decision]`. Otherwise: copy into `~/.co-work/sessions/<id>/artifacts/` as `<name>__v<N>_<hash8>.<ext>` (04 §3), write the `ArtifactVersion` row, upsert the `Artifact` row (new or `currentVersion`+1, `contentHash`, `sizeBytes`, `modifiedAt`) via `Storage` (single writer, 02 §7; 05 §1.9).
7. `ArtifactWatcher` publishes on `EventBus` `Topic.ARTIFACT`: `artifact.created {artifact}` (first version) or `artifact.updated {artifact, version}`; file vanished → `deletedAt` + `artifact.deleted {artifactId}` (05 §1.1/§1.6) + audit: `PermissionRecord(decision="deleted_observed", toolName="fs_delete", input={path: <absolute host path>}, reason="watcher observed deletion")` via `Storage.append_permission` (04 §1.5; 07 §4.1).
8. `WorkspaceServer` (ARTIFACT subscriber) pushes the message to the Browser over WS; UI shows the artifact live while the agent still runs.
9. Preview: UI requests `GET /previews/{session_id}/{artifact_id}/v{N}` (05 §1.1). The server resolves the file **from DB-stored `storedRelPath` only — never from client-supplied paths** (§3.5); content served with sniffed content-type; HTML previews render inside a script-disabled sandboxed iframe (§3.5) `[invented]`.
10. Agent emits `result` → `running→done` → `SessionManager` calls `stop_watching(session_id)`: **final scan + version pass first**, then all further fs events are dropped (05 §1.6 P2-12 — the CLI may write between `result` and the group kill, 05 §3.3).
11. Teardown (stdin EOF → SIGTERM → SIGKILL, 02 §2) completes; artifacts already versioned remain; the session list shows artifactCount (05 §1 `SessionSummary`).
12. On stop/failed paths (`running→stopped|failed`, including boot reconcile, 06 §2.1) `stop_watching` runs the same final-scan-then-drop sequence.

### 2.1 Behavioral rules (binding)

- Watcher failure never fails the session (06 §4 row 9); version-copy failure (ENOSPC etc.) never fails the session (06 §4 row 10).
- Events between `result` and the final scan are captured; events after the scan are dropped (step 10).
- Dotfiles are never detected (RE session-lifecycle §5); watch is non-recursive — subdirectories are not watched (RE §5; 05 §1.6).
- Publish never raises to the watcher; subscriber isolation per 05 §1.5.
- No change to permission semantics: artifact detection is read-only observation; deletion approval is not a v1 gate (03 §5; prd-local-files).

## 3. I/O Contracts (types first)

### 3.1 `ArtifactWatcher` (binding — 05 §1.6, signatures verbatim)

```python
def watch(session_id: UUID, outputs_dir: Path) -> None   # non-recursive, dotfiles skipped, initial scan (RE session-lifecycle §5)
def stop_watching(session_id: UUID) -> None              # on result/stop: final scan + version pass, then drop all fs events (P2-12)
def version_file(artifact: Artifact, fs_path: Path) -> ArtifactVersion  # copy → artifacts/ with hash+timestamp suffix [design decision] (04 §1.4); rejects `..` and `/` in names (P2-16)
```

- `watch` is idempotent per session; called by `SessionManager` at `pending→running` — attach timing mirrors RE's start-after-init (`startFileWatching` once, post query enqueue, RE session-lifecycle §5) `[design decision]` (05 §1.6 does not state attach timing; 03 §3 ownership: SessionManager decides when, ArtifactWatcher decides how). `stop_watching` called at `running→done|stopped|failed` (result handler, stop handler, error handler, boot reconcile, graceful shutdown — 06 §2.1/§2.2).
- `version_file` is the single choke point for sanitization (step 5) and versioning; it performs the copy and returns the new `ArtifactVersion`; callers persist via `Storage` (§3.3) then publish (§3.4).
- Per-path coalescing: fs.watch can emit multiple events per write (create/rename/change); a short debounce (100 ms `[invented]`) per relPath precedes hash+version. The final scan has no debounce.
- Deletion detection: event + `existsSync`-negative → mark `deletedAt`, publish `artifact.deleted`, and append the audit record `PermissionRecord(decision="deleted_observed", toolName="fs_delete", input={path: <absolute host path>}, reason="watcher observed deletion")` via `Storage.append_permission` (04 §1.5 — decision value added by the parallel amendment; 07 §4.1).
- Probe alignment: none — filesystem-only surface. Cross-check with prd-mcp-connectors: MCP connector tools execute inside the CLI and may write files that land in the outputs dir (spawn cwd, 05 §2.1); such files are detected exactly like any other artifact — the mcp PRD must not redirect connector outputs to a non-watched location.

### 3.2 Entities (binding — 04 §1.4, verbatim contract; the PRD adds no fields)

```python
class Artifact(BaseModel):
    id: UUID
    sessionId: UUID
    name: str
    relPath: str                           # path relative to session outputsDir
    sizeBytes: int
    currentVersion: int = 1
    contentHash: str                       # sha256 of latest version
    createdAt: datetime
    modifiedAt: datetime
    deletedAt: datetime | None = None

class ArtifactVersion(BaseModel):
    id: int
    artifactId: UUID
    version: int                           # 1..N
    storedRelPath: str                     # <sessions>/<id>/artifacts/<name>__v<N>_<hash8>.<ext> (04 §3)
    contentHash: str
    sizeBytes: int
    createdAt: datetime
```

- `relPath` = the fs event's path relative to `outputs_dir` (always a bare filename in v1 — non-recursive watch).
- `storedRelPath` is absolute-path-free; preview resolution anchors it under `~/.co-work/sessions/<id>/artifacts/` (§3.5).

### 3.3 `Storage` (binding — 05 §1.9)

```python
async def record_artifact_detection(session_id: UUID, artifact: Artifact, version: ArtifactVersion | None = None) -> Artifact  # combined artifact-detection transaction method on Storage (05 §1.9); version=None ⇒ deletion-only update
async def list_artifacts(session_id: UUID) -> list[Artifact]
```

- One public method = one transaction (05 §1.9). The combined artifact-detection transaction method on Storage (05 §1.9) subsumes `insert_artifact`/`add_version`/`update_artifact` — artifact row + version row are committed atomically per detection (row-level consistency: no artifact without its v1 version). `version=None` carries only the `deletedAt` update; `version` present carries upsert + new version.

### 3.4 `EventBus` + WS (binding — 05 §1.1/§1.5)

| Topic | Message | Payload | Publisher → Subscribers |
|---|---|---|---|
| ARTIFACT | `artifact.created` | `{artifact}` | ArtifactWatcher → WorkspaceServer (WS push) |
| ARTIFACT | `artifact.updated` | `{artifact, version}` | ArtifactWatcher → WorkspaceServer |
| ARTIFACT | `artifact.deleted` | `{artifactId}` | ArtifactWatcher → WorkspaceServer |

- WS is server→client only (05 §1.1); after a client disconnect/reconnect the UI re-syncs via `GET /api/artifacts?session_id=` (05 §1.1; 06 §5 row 5).

### 3.5 Preview serving (WorkspaceServer; 05 §1.1 route)

Route: `GET /previews/{session_id}/{artifact_id}/v{N}` — `{session_id}` and `{artifact_id}` are UUIDs; `{N}` is an int ≥ 1.

Path resolution rules (binding):

1. **DB-only resolution.** Look up `ArtifactVersion` (join `Artifact` by `artifact_id`, filter `version = N`, `session_id`). No client-supplied path is ever used; the route takes ids only. Lookup miss → 404. `Artifact.deletedAt` does **not** gate previews: versions are immutable (§5), so prior versions stay listable/previewable after deletion — only the artifact row is marked and `artifact.deleted` emitted.
2. **Containment check.** `stored = (~/.co-work/sessions/<session_id>/artifacts/ / version.storedRelPath).resolve()`; assert `stored` is inside the artifacts dir (`is_relative_to`), and the file exists and is a regular file — else 404. Defense in depth for a DB-corruption or tampering case `[invented]`.
3. **Content-type sniffing** (extension map, magic-byte confirm): `html/htm` → `text/html` (magic: leading `<!doctype`/`<html`); `pdf` → `application/pdf` (magic `%PDF-`); `md|txt|log|json|csv|tsv|yaml|yml|toml|xml|py|js|ts|sh|ipynb` → `text/plain; charset=utf-8` (ipynb is JSON); `png|jpg|jpeg|gif|webp` → image magic + `image/*`; `svg` → `image/svg+xml` (script-bearing; sandbox applies, §3.5 item 4); everything else (incl. RE §4 blocklist extensions `.exe .com .msi .bin .app .dmg .pkg .jar`) → `application/octet-stream` + `Content-Disposition: attachment` — never rendered `[design decision]` (RE §4 extension blocklists adapted from VM-path validation to preview serving).
4. **Sandboxing (choice, `[invented]`)**: `text/html` and `image/svg+xml` are served with `X-Content-Type-Options: nosniff` + `Content-Security-Policy: sandbox; default-src 'none'` and rendered by the UI inside an iframe with `sandbox=""` — **no `allow-scripts`, no `allow-same-origin`, no `allow-top-navigation`, no `allow-forms`**. Consequence: scripts written by the agent **never execute**; HTML renders statically. Rationale: workspace origin holds `WorkspaceServerToken`-gated state (07) and artifact content is untrusted — interactive JS dashboards (RESEARCH §1, RE §10) are deliberately out of v1 scope (§8). PDF embeds use browser-native `<embed>` per 02 §5 (RESEARCH Gotchas — sandboxed iframes render PDFs blank).
5. Binary previews (docx/xlsx/pptx) are **not** converted in v1 (02 §5 — no converter libraries); served as octet-stream downloads. `fileReader`-style converters (RESEARCH §1) are out of scope.

## 4. Component Touchpoints

| Component | Role |
|---|---|
| `SessionManager` | Calls `watch()` at `pending→running` (post health check); calls `stop_watching()` at `running→done|stopped|failed` (result/stop/error handlers), boot reconcile (06 §2.1), graceful shutdown (06 §2.2). Lifecycle policy owner; watcher work never blocks session transitions. |
| `ArtifactWatcher` | Detection, sanitization, versioning, `Storage` writes, `EventBus` publish. Failure containment: fs errors logged + watch stopped per-dir, session continues (06 §4 row 9); ENOSPC → copy skipped + logged (06 §4 row 10). |
| `Storage` | Combined artifact-detection transaction method (05 §1.9, §3.3) + `list_artifacts`; single writer owner (02 §7); one txn per detection. |
| `EventBus` | `Topic.ARTIFACT`; publish never raises; subscriber isolation (05 §1.5). |
| `WorkspaceServer` | WS push of `artifact.*`; `GET /previews/...` (DB-only resolution + containment + sniffing + sandbox headers, §3.5); `GET /api/artifacts?session_id=` (05 §1.1). |
| `RunnerAdapter` | Indirect: spawn `cwd` = first granted folder else outputsDir (05 §2.1) — artifacts appear in outputs only when no grants; `result`→kill window is the reason for the final scan (P2-12). |
| `PermissionGate` | None for detection (read-only observation). Watcher-observed deletions are audited as `PermissionRecord(decision="deleted_observed", ...)` appended by `ArtifactWatcher` via `Storage.append_permission` (04 §1.5; 07 §4.1) — recorded, never gated. |

## 5. Versioning scheme `[design decision]` (vs RE §10 server-side)

- **Suffix**: `<name>__v<N>_<hash8><ext>` (04 §1.4 binding) where `hash8` = first 8 hex chars of sha256 and `<ext>` is the original extension (with dot; empty when the name has none). The `v<N>` component guarantees uniqueness per version; `hash8` disambiguates same-version re-detections. The timestamp lives in `ArtifactVersion.createdAt` / `Artifact.modifiedAt`, not the filename (04 §1.4 — the "timestamp suffix" is the row timestamp `[design decision]`).
- **First detection** → `Artifact(currentVersion=1)` + `ArtifactVersion(version=1)` + `artifact.created`.
- **Overwrite with different content** → `currentVersion += 1`, new `ArtifactVersion(version=N+1)`, `contentHash`/`sizeBytes`/`modifiedAt` updated, `artifact.updated` with the new version. Previous versions are immutable: `artifacts/` copies are never rewritten.
- **Overwrite with identical content** → no-op (no new version, no event) — hash dedupe prevents churn from touch-style writes `[invented]`.
- **Deletion** → `deletedAt` set, rows retained; versions remain previewable until archive. Version rows are never garbage-collected in v1 (archive semantics: 04 §4.1 `archived` keeps transcript + artifacts).

## 6. Acceptance Criteria (testable)

1. **Mid-run appearance < 1 s `[invented SLO]`**: while a session runs, write a file to `outputs/`; the UI receives `artifact.created` over WS and `GET /api/artifacts?session_id=` returns it within 1 s of the write.
2. **Sanitization**: create files named `../evil.txt` and `sub/dir.txt` in `outputs/`; neither is copied to `artifacts/`, no artifact row is created, no event published, and an error-level log line names each rejected path (04 §1.4 P2-16).
3. **Versioning**: overwrite `report.md` twice with different content → `currentVersion=3`, three `ArtifactVersion` rows, two `artifact.updated` messages; `GET /previews/.../v1` returns the original bytes and `/v3` the latest.
4. **Dedupe**: rewrite identical content → no new version, no event.
5. **Final scan (P2-12)**: write a file between the `result` event and process kill → it is versioned by `stop_watching`'s final scan; a write issued after the final scan completes is never versioned and no event is published.
6. **Preview safety**: `GET /previews/{sid}/{aid}/v1` for an HTML artifact whose content contains `<script>` — served with `sandbox=""` CSP header + `nosniff`; rendered in the UI iframe, the script does not execute (assert via DOM: no `window` state set by it, no network request).
7. **No client paths**: `GET /previews/../api/...`-style traversal attempts return 404; non-UUID path params (typed `UUID` in the route signature) are rejected by FastAPI validation with **422**, never resolved; resolution uses DB `storedRelPath` only (§3.5.1–2).
8. **Watcher failure (06 §4 row 9)**: delete `outputs/` mid-session → watcher logs the error, stops that watch; the session continues to `done`; already-versioned artifacts remain queryable.
9. **ENOSPC (06 §4 row 10)**: with `artifacts/` on a full volume, a version copy is skipped + logged; the session continues; the gap is visible in the log.
10. **Deletion**: delete a versioned file from `outputs/` → `artifact.deleted` published, `deletedAt` set, rows retained; prior versions still listable and `GET /previews/.../v1` still serves; a `PermissionRecord(decision="deleted_observed")` exists in the audit trail (04 §1.5; 07 §4.1).
11. **Scope**: dotfiles (`.hidden`) and files in a subdir of `outputs/` are never detected; no fs error is raised.

## 7. Failure behavior (consolidated, binding — 06 §4)

| # | Failure | Behavior |
|---|---|---|
| 1 | outputsDir deleted mid-session | Log + stop watching that dir; session continues; versioned artifacts remain (06 §4 row 9) |
| 2 | Disk full (ENOSPC) on version copy | Copy skipped + logged; session continues; the file is never versioned — transcript/log notes the gap (06 §4 row 10) |
| 3 | Sanitization rejection (`..`, `/`, empty) | Rejected before any copy; error-level log; no row, no event (04 §1.4) |
| 4 | EventBus publish failure | Cannot happen to the publisher — `publish()` never raises; a raising subscriber is detached after 3 failures (05 §1.5) |
| 5 | Storage write failure | Surfaces (fail fast, 02 §6); session status reflects failure per its own path; artifact row/version are atomic per detection (§3.3) |
| 6 | Preview source missing (DB row exists, file gone) | 404 (regular-file check, §3.5.2) |

## 8. Out of Scope (v1)

- **Granted-folder watching** — Cowork watches the first user-selected folder else outputs (RE session-lifecycle §5); v1 watches outputs only (03 §4c `[design decision]`); folder-level artifact detection → prd-local-files.
- **Connector refresh for live artifacts** — Cowork live artifacts re-query connectors on open with a manual refresh (RESEARCH §1, RE §10); requires the interactive-dashboard surface → prd-mcp-connectors.
- **Interactive HTML dashboard widgets** — script-executing dashboards, "Edit with Claude" inline editing, annotation refinement, Pin-to-Desktop (RESEARCH §1); v1 previews are script-disabled by construction (§3.5).
- **Server-side/cloud versioning, org sharing** (RESEARCH §1 — org-internal links, Team/Enterprise only; RE §10 server-side storage) — local-first; versioning §5 is host-only (02 §1).
- **Artifact search** — no full-text or filename search surface in v1; `GET /api/artifacts?session_id=` only (05 §1.1).
- **Sub-second incremental streaming of partial files** — a file mid-write is versioned once per settled write (debounce, §3.1); no streaming of growing files.
- **Binary conversion previews** — docx/xlsx/pptx served as downloads, not rendered (02 §5, §3.5.5).
- **Deletion approval gate** — `rwd`-style semantics (RE §4) → prd-local-files. Watcher-observed deletions are **recorded, not gated**: `PermissionRecord(decision="deleted_observed", ...)` (04 §1.5; 07 §4.1).
- **Watcher resume across restarts** — `--resume` is not in the spawn template (06 §2.4); a stopped session keeps its artifact rows and never re-watches.

## 9. Open questions

- Archive/disk policy: `archived` sessions keep `artifacts/` forever; is there a size/age reclamation rule? → prd-agent-sessions or a settings knob `[invented — flag]`.
- Version copy size guard: no cap in v1; a giant artifact (e.g. multi-GB) is copied wholesale on every change. Cap (e.g. skip versioning above N MB with a log) → flag for review.
- Debounce window (100 ms `[invented]`) on slow filesystems may double-version a large file; the hash-dedupe (§5) makes this harmless — confirm at integration.
