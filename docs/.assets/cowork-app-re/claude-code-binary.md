# Claude Code binary inside Claude Desktop 1.1.673 (Cowork VM agent kernel) — static reverse engineering

Scope: how Claude Desktop discovers/manages the Claude Code binary, how it invokes it (host + in-VM "local-agent" mode), what the binary is, and the kernel→host contract. All app-side evidence is from `/tmp/claude-asar/app/.vite/build/index.js` (minified Electron main bundle, app 1.1.673); runtime evidence from `~/Library/Logs/Claude/main.log`; binary evidence from `/Users/rawhad/Library/Application Support/Claude/claude-code/2.1.15/claude`.

---

## 1. Binary discovery & management (app-managed, pinned per app version)

### 1.1 Path resolution

Class `oze` (minified) = the "CCD" (Claude Code Downloader). Constructor and targets:

```
const aze = "https://downloads.claude.ai/claude-code-releases"      // base URL
const sze = "linux-arm64"                                            // VM platform constant
class oze {
  storageDir   = join(app.getPath("userData"), "claude-code")        // host binary dir
  vmStorageDir = join(app.getPath("userData"), "claude-code-vm")     // in-VM (linux-arm64) binary dir
  requiredVersion = WCe().version; manifest = WCe().manifest
}
getHostTarget()  → { storageDir, platform: darwin-arm64|darwin-x64|win32-x64,
                     binaryName: claude|claude.exe, logPrefix: "[CCD]" }
getVMTarget()    → { storageDir: claude-code-vm, platform: "linux-arm64",
                     binaryName: "claude", logPrefix: "[ClaudeCodeManager-VM]" }
getBinaryPathForTarget(t, v) → <storageDir>/<version>/<binaryName>
```

Final on-disk layout (this machine):

```
~/Library/Application Support/Claude/claude-code/2.1.15/
├── claude       176,893,952 bytes  (darwin-arm64, Mach-O)
└── .verified    0 bytes (marker; empty)
```

### 1.2 Download trigger — NO runtime RELEASES.json check. Version + manifest are EMBEDDED in the app bundle

`WCe()` is a hardcoded JSON literal in the app JS:

```js
function WCe(){return JSON.parse('{"version":"2.1.15","manifest":{"version":"2.1.15",
"buildDate":"2026-01-21T21:27:03Z","platforms":{ ...checksums+sizes for 7 platforms... }}}')}
```

- `GET https://downloads.claude.ai/claude-code-releases/RELEASES.json` → **404 NoSuchKey** (verified). The only RELEASES.json the app fetches is the *app-updater* one: `https://downloads.claude.ai/releases/darwin/universal/RELEASES.json` (electron autoUpdater; logged at every launch, e.g. main.log:421).
- **Update cadence = app release cadence.** claude-code version bumps ship inside new desktop app builds (1.1.673 pins 2.1.15). Observed history (main.log): `Initialized with version 2.1.5` (Jan 20) → `2.1.8` (Jan 21) → `2.1.15` (Aug 5–6). Public claude-code was at **v2.1.223 on 2026-08-06** — the app pins a ~6.5-month-old build (binary `BUILD_TIME 2026-01-21T21:24:50Z`).
- Download is **lazy, on-demand**: logged `[CCD] Downloading from https://downloads.claude.ai/claude-code-releases/2.1.15/darwin-arm64/claude` at 21:07:23 Aug 6, immediately after MCP/LocalAgentModeSessionManager activity — triggered by IPC handler `Wrt`: renderer calls `getStatus()` (Ready/Updating/NotInstalled) then `prepare()` → `pl.prepare()` → `prepareForTarget(hostTarget)`.
- "Ready" test: `fs.access(bin, X_OK)` **and** existence of `<version>/.verified` marker file.
- Download flow (`downloadBinaryForTarget`): ensure dir → GET binary (streams to `<storageDir>/<version>/claude`) → log "Verifying checksum" → sha256 of file must equal `manifest.platforms[<platform>].checksum` (on failure: unlink + throw) → `chmod 0o755` → write empty `.verified` → log `Installed at <path>` → `cleanupOldVersionsForTarget` **deletes every other version dir** (`Removing old version: 2.1.8` at 21:07:28). Up to 3 retry attempts, backoff `1s * attempt` (Jan 21 log shows 3 consecutive failed attempts at 04:00/04:17/04:32 before eventual install — the 3-attempt loop per launch).

### 1.3 VM target ("prepareForVM")

- Same manifest, platform `linux-arm64` → `claude-code-vm/<version>/claude`; after install writes `.sdk-version` file containing the version string.
- `getVMStorageSubpath()` = path relative to `app.getPath("home")` (e.g. `Library/Application Support/Claude/claude-code-vm`).
- **Not present on this machine** (`claude-code-vm/` doesn't exist) — the VM-side binary is only downloaded lazily when the Cowork VM starts (`Step 1/4: Downloading bundle + SDK...`, in parallel with the VM rootfs download).
- In-VM install: Swift addon `installSdk(subpath, version)` copies it into the guest, resulting in `/usr/local/bin/claude` inside the VM (see §3).

### 1.4 Why 2.1.15 vs 2.1.8

The desktop team pins a tested SDK version per app release (embedded manifest, §1.2). 2.1.15 build date 2026-01-21 equals the 2.1.8-era app build date (app commit timestamp `2026-01-22T18:12:14.000Z` from `cle` metadata) — i.e. 1.1.673 launched with 2.1.8 in early sessions and the 2.1.15 pin was introduced in the same app line; the binary update happens silently on next prepare. No self-update: `DISABLE_AUTOUPDATER=1` is forced into the env of every spawned session (§2.2).

---

## 2. Invocation contract

### 2.1 Host-side sessions (claude-desktop entrypoint)

Env built by `zJe(t)` (per host session):

```js
Dye(t) => {
  CLAUDE_CODE_ENTRYPOINT: "claude-desktop",
  ANTHROPIC_BASE_URL: t.apiHost,          // https://api.anthropic.com (production)
  ANTHROPIC_API_KEY: "",                  // empty — OAuth is used instead
  CLAUDE_CODE_OAUTH_TOKEN: t.oauthToken,  // from encrypted token cache ("oauth:tokenCache", safeStorage)
  DISABLE_AUTOUPDATER: "1",
  CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL: "true"
}
```
Plus `PATH` extracted via a utility-process shell worker (`shellPathWorker.js`) and stored user env vars from `ccd-environment-config` electron-store (safeStorage-encrypted; allowlist `OJe = [PATH, CLAUDE_CODE_ENTRYPOINT, CLAUDE_CODE_OAUTH_TOKEN, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, DISABLE_AUTOUPDATER]`).

Auth: the app's OAuth flow — clientId `9d1c250a-e61b-44d9-88ed-5944d1962f5e`, scope `user:inference`, tokens at `api.anthropic.com/v1/oauth/token` (refresh grant), cached per org in safeStorage.

### 2.2 In-VM sessions (local-agent entrypoint) — the Cowork kernel

Built in `LocalAgentModeSessionManager.startSession` (offset ~2920874):

```js
B = {
  cwd: `/sessions/${vmName}`,                      // VM name = "adj-adj-scientist" e.g. admiring-brave-turing
  model, pathToClaudeCodeExecutable: "/usr/local/bin/claude",   // the binary from §1.3, inside the guest
  allowedTools: ["Task","Bash","Glob","Grep","Read","Edit","Write","NotebookEdit","WebFetch","TodoWrite",
                 "WebSearch","Skill","mcp__mcp-registry__search_mcp_registry","mcp__mcp-registry__suggest_connectors",
                 "mcp__cowork__create_knowledge_base"],
  canUseTool: (tool, input, {suggestions}) => this.handleToolPermission(...),   // permission mode "default"
  settingSources: ["user"],
  includePartialMessages: true,
  hooks: { PreToolUse: [{ matcher: "Task", hooks: [block run_in_background → "Background agents disabled"] }] },
  env: {
    CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS: "true",
    CLAUDE_CONFIG_DIR: `/sessions/${vmName}/mnt/.claude`,        // session config dir inside VM
    ...Dye({oauthToken, apiHost}),                                // ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY:"" / CLAUDE_CODE_OAUTH_TOKEN / DISABLE_AUTOUPDATER:1
    CLAUDE_CODE_ENTRYPOINT: "local-agent",
    CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1",
    MCP_TOOL_TIMEOUT: <growthbook "mcpToolTimeoutMs" default>
  },
  spawnClaudeCodeProcess: <VM spawn function, §2.3>
}
```

**Command line** (SDK `FBe`/`ProcessTransport.initialize` builds it): base args
`--output-format stream-json --verbose --input-format stream-json`, then optionals — `--max-turns`, `--model`, `--allowedTools <csv>`, `--mcp-config <json>`, `--permission-mode default`, `--setting-sources user`, `--include-partial-messages`, `--add-dir /sessions/<vm>/mnt/<folder>`, `--plugin-dir /sessions/<vm>/mnt/.skills` (skills) and/or `/sessions/<vm>/mnt/.plugins/<id>`, `--resume <cliSessionId>` when resuming. Because `/usr/local/bin/claude` has no `.js/.ts` extension (`BBe` native-binary check), it's spawned directly (no `node`/`bun` wrapper).

**Protocol**: the SDK query object (`DL({prompt, options})`) drives the child via **stream-json over stdin/stdout**; messages enqueued into a `queue`-backed async iterator (class `OXe`), consumed by `setupQueryHandlers`.

**Kernel-side entrypoint handling** (inside the binary itself): `th8()` only *sets* `CLAUDE_CODE_ENTRYPOINT` if absent (mcp / claude-code-github-action / sdk-cli / cli); since the app pre-sets `local-agent`, the CLI resolves client type to `"local-agent"` (telemetry `client_type`, user-agent `claude-cli/2.1.15 (external, local-agent)`, billing header `x-anthropic-billing-header: cc_version=2.1.15.<x>; cc_entrypoint=local-agent`, `isLocalAgentMode: env==="local-agent"`). The binary also honors `CLAUDE_CODE_USE_COWORK_PLUGINS` (env) and a hidden `--cowork` CLI flag on plugin commands → switches plugin dir `plugins/` → `cowork_plugins/` and `settings.json` → `cowork_settings.json`.

### 2.3 VM spawn transport (Swift addon `@ant/claude-swift`)

`createVMSpawnFunction` (`TQe`) → wrapper `_Qe` (an EventEmitter with `stdin`/`stdout` PassThrough streams + stdin buffering until `confirmSpawn()`):

- `AQe` (spawn): `o.addApprovedOauthToken(env.CLAUDE_CODE_OAUTH_TOKEN)` — "OAuth token approved with MITM proxy" (the addon runs an HTTPS proxy to validate token + API traffic), then `o.spawn(id, processName, command, args, cwd, env, additionalMounts, isResume, allowedDomains, sharedCwdPath)`.
- `_Qe.setupStdinForwarding`: every chunk → `addon.writeStdin(id, chunk)` (buffered until spawn confirmed).
- stdout/exit/error come back via `setEventCallbacks(onStdout, onStderr, onExit, onError, onNetworkStatus)` registered once in `bQe()`.

---

## 3. Binary inspection

### 3.1 File identity

```
path: ~/Library/Application Support/Claude/claude-code/2.1.15/claude
size: 176,893,952 bytes (168.7 MiB)
type: Mach-O 64-bit executable arm64 (MH_MAGIC_64, EXECUTE, NOUNDEFS, DYLDLINK, TWOLEVEL,
      BINDS_TO_WEAK, PIE, MH_HAS_TLV_DESCRIPTORS)
sha256: cc627c0ef5ae192c05d002f273e637d867692090bd23effd5ef520690db95e71
linked dylibs: only system — libicucore.A.dylib, libresolv.9.dylib, libc++.1.dylib, libSystem.B.dylib
runs:  "2.1.15 (Claude Code)"  (--version)
```

It is a **Bun v1.3.6 standalone single-file executable** (`strings` contains `Bun v1.3.6` / `bun-v1.3.6`; the embedded JS references `isRunningWithBun`; a 490k-line embedded JS bundle). Not a node wrapper, not the npm artifact.

### 3.2 Embedded identity strings

- `VERSION:"2.1.15"`, `BUILD_TIME:"2026-01-21T21:24:50Z"`, `PACKAGE_URL:"@anthropic-ai/claude-code"`, `README_URL:"https://code.claude.com/docs/en/overview"`, ISSUES → github.com/anthropics/claude-code.
- User agents: `claude-cli/<ver> (external, ${CLAUDE_CODE_ENTRYPOINT}...)` + `claude-code/<ver>`.
- First-party markers: `CLAUDE_CODE_USE_COWORK_PLUGINS`, `cowork_plugins`, `cowork_settings.json`, hidden `--cowork` flag on plugin/marketplace commands (this binary is a custom Anthropic build with cowork support compiled in).
- `/sessions/ws/` string is unrelated to the VM — it's the cloud API websocket `https://api.anthropic.com/v1/sessions/ws/<id>/subscribe` for remote sessions.
- ~90 `CLAUDE_CODE_*` env vars recognized, including `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, `CLAUDE_CODE_SESSION_ACCESS_TOKEN`, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`, `CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL`.
- No `lam_*`/`/sessions/<name>/mnt` strings: the VM filesystem layout is purely a host-side mount abstraction — the kernel sees a normal POSIX FS.

### 3.3 Version comparison table

| artifact | source | size (bytes) | sha256 | notes |
|---|---|---|---|---|
| App binary 2.1.15 darwin-arm64 (on disk) | downloads.claude.ai/claude-code-releases/2.1.15/darwin-arm64/claude | 176,893,952 | `cc627c0e...db95e71` | Bun v1.3.6 standalone, BUILD_TIME 2026-01-21T21:24:50Z, cowork-enabled |
| Same URL, remote (HEAD, x-goog-stored-content-length) | GCS (x-goog-generation 1769032024370748) | 176,893,952 | (md5 `iQuoXpMou6zUL19PWkVE6A==`) | **identical file still served**; embedded manifest checksum matches on-disk file exactly |
| Manifest entry darwin-arm64 (embedded in app) | app 1.1.673 `WCe()` | 176,893,952 | `cc627c0ef5ae192c05d002f273e637d867692090bd23effd5ef520690db95e71` | = on-disk binary (verification passed in log) |
| Manifest darwin-x64 | embedded | 182,910,464 | `ddf08312...b828648` | |
| Manifest **linux-arm64 (VM kernel)** | embedded | 210,961,746 | `20a520256b78aff56d4273d618c97965913e041a850fe6ceab9b714f57e39554` | downloaded to `claude-code-vm/2.1.15/claude` on VM start |
| Manifest linux-x64 | embedded | 218,009,452 | `37f8e874...e862d` | |
| Manifest linux-arm64-musl / linux-x64-musl | embedded | 206,324,010 / 210,996,956 | `942082b4...` / `a0fa8313...` | |
| Manifest win32-x64 | embedded | 228,773,024 | `39a8d1cc...b932` | |
| Public npm `@anthropic-ai/claude-code@2.1.15` | registry.npmjs.org | cli.js = 11,331,020 (71.2 MB unpacked) | cli.js `4c0f2e7c...f5481f8` | **node bundle, not Bun**; BUILD_TIME 2026-01-21T21:24:26Z (24 s earlier) — same source, different artifact; also contains cowork_plugins markers |
| Public GitHub releases | anthropics/claude-code | ~75–90 MB tarballs | — | latest 2026-08-06: **v2.1.223**; v2.1.15 tag exists (2026-01-21, no assets — npm-only era) |

Takeaways: (1) the app binary is a *third build flavor* (Bun-compiled, cowork-enabled) distinct from npm cli.js and native installers; (2) checksums prove on-disk binary = embedded manifest expectation = still-served GCS object; (3) 2.1.15 is ~6.5 months behind public head — the app does not chase releases.

---

## 4. Kernel → host contract (path mapping, outputs, permissions)

### 4.1 Mounts (host → VM)

`getVMSpawnFunction({processName, additionalMounts, isResume, allowedDomains, sharedCwdPath})` — mounts are `{ mountName: { path: <home-relative host path>, mode: "rw"|"ro"|"rwd" } }`, realized inside the guest under `/sessions/<vmName>/mnt/<mountName>` by the Swift addon (`mountPath` / `spawn` args):

| VM path | host path | mode |
|---|---|---|
| `/sessions/<vm>/mnt/<folder-basename>` | user-selected folder (first = workspace) | rw, **rwd** if `fileDeleteApprovedMounts` contains it |
| `/sessions/<vm>/mnt/outputs` | `~/Documents/Claude/outputs` (shared CWD) **or** `<sessionStorage>/outputs` | rw/rwd |
| `/sessions/<vm>/mnt/.claude` | `<sessionStorage>/.claude` (= `CLAUDE_CONFIG_DIR`) | rwd |
| `/sessions/<vm>/mnt/.skills` | `local-agent-mode-sessions/skills-plugin/<orgId>/<accountUuid>/skills` | ro |
| `/sessions/<vm>/mnt/.plugins` | `local-agent-mode-sessions/plugins/<org>/<acct>` | ro |
| `/sessions/<vm>/mnt/.local-plugins` | `~/.claude/cowork_plugins/cache` | ro |
| `/sessions/<vm>/mnt/uploads` | `<sessionStorage>/uploads` | ro |
| `/sessions/<vm>/mnt/.knowledge/<mountName>` | knowledge-base dirs | rw |
| `/sessions/<vm>/mnt/.projects` | `<sessionStorage>/.projects` | ro |

Session storage base: `~/Library/Application Support/Claude/local-agent-mode-sessions/<accountUuid>/<orgUuid>/<sessionId>/` with `outputs/`, `.claude/`, `uploads/`, `.projects/`, `audit.jsonl`. Plugin/skills roots live under `local-agent-mode-sessions/{plugins,skills-plugin}/...`.

### 4.2 Output streams & tool results

- Guest process stdout (stream-json messages) flows: Swift addon callback → `_Qe.stdout` PassThrough → SDK `ProcessTransport` → async iterator → `setupQueryHandlers` per message: push to `messageBuffer`, emit `{type:"message", sessionId, message}` to renderer (also audit-logged to `audit.jsonl`).
- `system/subtype=init` message carries `session_id` → mapped as `cliSessionId` (used for `--resume`, transcripts, sharing).
- `kJe` detects assistant `Write` tool_use with `file_path` matching `/[/\\]\.claude[/\\]plans[/\\][^/\\]+\.md$/` → `planPath` surfaced to UI.
- Auth errors (401/unauthorized) in stream → app clears the OAuth token cache (`B5()`).
- Transcripts for UI/sync are read from host: `<sessionStorage>/.claude/projects/<proj>/<cliSessionId>.jsonl`, each line run through `translateMessagePaths` (VM→host).

### 4.3 VM→host path translation (in message content)

- `$g(vmPath, ctx)`: `/sessions/<vm>/mnt/outputs/…` → sharedCWD/`outputs/…`; `mnt/uploads/…` → session uploads; `mnt/<basename>/…` → matching user-selected folder; `mnt/.knowledge/<kb>/…` → KB dir; else (sharedCWD) `~/Documents/Claude/<rest>`.
- `WQe`/`t4` recursively rewrite those in strings and `computer://` URIs.
- `e0e(vmPath, vmName, folders, outputsSubpath)` = inverse (host-side mount lookup) — used by the delete-permission tool.
- Host→VM pre-translation on input: `Qie` rewrites `@<hostFolder>` → `/sessions/<vm>/mnt/<basename>` in user messages; file uploads copy/link into `pending-uploads` → session `uploads/` (hardlink; VM path `/sessions/<vm>/mnt/uploads/<file>`).
- File watcher on the workspace/outputs dir emits `fs_file_created` / `fs_file_deleted` events to the renderer (host paths) so new output files appear in the UI.

### 4.4 Permissions

- `canUseTool` → `handleToolPermission` → emits `tool_permission_request` (renderer dialog + native notification) → user decision → `respondToToolPermission`: `deny` → `{behavior:"deny", interrupt:true}`; `once` → `{behavior:"allow", updatedInput}`; `always` → `{behavior:"allow", updatedInput, updatedPermissions}`.
- The in-VM kernel gets *two special cowork MCP tools* (registered on the `cowork` MCP server v1.0.0, wired in main process as `O.cowork`):
  1. `request_cowork_directory` — native macOS folder picker; selected dir must be inside `$HOME` (`Qye` realpath check); `mountPath(vmProcId, homeRelPath, basename, "rw")` → returns VM path `/sessions/<vm>/mnt/<basename>`; folder added to `userSelectedFolders`.
  2. `allow_cowork_file_delete` — input `file_path` (VM path) → `e0e` lookup → `mountPath(..., "rwd")` upgrade + `fileDeleteApprovedMounts` persisted on the session.
- Delete outside approved mounts fails with EPERM inside the guest ("Operation not permitted") — that's the documented trigger for tool #2.

### 4.5 VM lifecycle

`i6`/`FQe` start: Step 1/4 download VM bundle + SDK (`prepareForVM`, §1.3) → Step 2/4 load `@ant/claude-swift` → Step 3/4 `startVM(bundlePath, memoryGB)` → Step 4/4 poll `isGuestConnected()` (30 s timeout, VPN diagnostics) → `installSdk(homeRelSubpath, version)` → guest now has `/usr/local/bin/claude`. VM rootfs: `https://downloads.claude.ai/vms/linux/<bundle-id>/rootfs.img.zst`, bundle-id `8c56966fa5825aba21d51a59e8a505b849e14f41`, zstd stream, sha256 `6747d61d16c37826dbdf885649853d98df606bebe2491707de01145dc75706d1`, staged in `~/Library/Application Support/Claude/vm_bundles/claudevm.bundle/` with `.origin` markers. VM shutdown hooks on app quit (`stopVM`).

---

## 5. Evidence index (file:offset / log lines)

- Downloader class + embedded manifest: index.js offset 1917338 (`const aze=...class oze`), `WCe()` at 369631.
- Host env builder `zJe`/`Dye`: 2813577. Env allowlist `OJe`: 2810948.
- Local-agent query config (cwd/pathToClaudeCodeExecutable/allowedTools/hooks/env): 2920874.
- SDK command-line builder (`FBe.initialize`, base args `--output-format stream-json --verbose --input-format stream-json`): 1693102, 1697552 (`BBe` native check).
- VM spawn (`TQe`/`AQe`/`_Qe`, oauth MITM approval, callbacks): 2858531–2858710.
- VM startup (`FQe` Step 1/4–4/4, bundle URL/checksum, `installSdk`): 2863467.
- Mount table construction: 2923726. Hostify `$g`: 2871685–2872011 (`e0e`, `GQe` cowork server).
- Message flow `setupQueryHandlers` + cliSessionId mapping + auth-error token reset: 2839494; plan-path regex `RJe`: 2810454; path rewrite `WQe`/`t4`: 2870651.
- Permission flow: 2821215 (`handleToolPermission`, `respondToToolPermission`), renderer/notification hook 3136699.
- Logs (main.log): 2.1.15 download/install/cleanup 2237–2245; "Initialized with version 2.1.15" 1961; 2.1.8 history 1425–1650; app Update URL 421 etc.
- Binary strings dump: `/tmp/opencode/deepresearch/cowork_app_re-M3KQ/bin.strings.txt` (490,633 lines); npm 2.1.15 tarball unpacked under the same dir.

### Open items
- `claude-code-vm/` absent locally — VM never booted on this machine; linux-arm64 checksum table above is from the embedded manifest only.
- The `@ant/claude-swift` addon binary (`cowork_vm_swift`/`cowork_vm_node` names referenced) is a native module, not inspected here.
