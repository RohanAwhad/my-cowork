# Claude Cowork — Client↔Server Protocol & Community RE: Web Endpoints

Research date: 2026-08-06 (UTC ~01:50). Researcher: deepresearch agent (web + code archaeology).

---

## 0. Executive summary

- **claude.ai is fully bot-gated** (Cloudflare managed challenge on `/` and `/login`; unauthenticated curl gets 403 + JS challenge, no HTML/JS bundles reachable). Direct bundle-grepping of the claude.ai web app was **not possible** — see §1 for the fallback and what we got instead.
- **The single best source is `johnzfitch/claude-cowork-linux`** — it ships the *extracted Claude Desktop asar bundle* (`index.js` in repo root, ~hundreds of KB of minified main-process code) plus 30 stub modules that document the entire local surface: EIPC channel format, session orchestration, path translation, scheduled-task namespaces, the Chrome-extension bridge (WebSocket), and the Office-addin bridge.
- **Concrete server endpoints confirmed from code** (see §7 inventory):
  - `wss://bridge.claudeusercontent.com` (+ `bridge-staging.claudeusercontent.com`) — Chrome extension & Office add-in bridge relay
  - `https://api.anthropic.com/v1/sessions[/{id}][/events]` — remote session sync (same surface as Claude Code remote sessions)
  - `https://claude.ai/desktop/callback`, `https://claude.ai/cowork/space/…` (space share links), `https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect`
  - `https://downloads.claude.ai/vms/linux/` (Cowork sandbox VM images), `https://downloads.claude.ai/claude-code-releases/`
  - `https://pivot.claude.ai/manifest.xml` (MS 365 add-in), admin API client paths `/v1/agents`, `/v1/environments`, `/v1/sessions`, `/v1/skills`, `/v1/vaults`, `/v1/memory_stores`, `/v1/files`, `/v1/oauth/device_authorization`, `/v1/oauth/token`
- **MCPB and DXT decoded** (from the asar bundle, not from docs): MCPB = signed MCP-plugin bundle file (PKCS#7, `MCPB_SIG_V1`/`MCPB_SIG_END` markers, cert-chain verify, `manifest.json` with `manifest_version`); DXT = "desktop extension" — the legacy manifest field `dxt_version` (deprecated → `manifest_version`), and `.dxt` is a plugin file extension. **Neither is a client↔server transport protocol.** §4.
- **`@ant/claude-for-chrome-mcp` does not exist on the public npm registry (404)**; likely a private/internal package. The Chrome bridge protocol itself is fully documented in the bundle (§3.4).
- **Claude Code v2.1.15 is public**: exists as GitHub tag `v2.1.15` on `anthropics/claude-code` and as npm `@anthropic-ai/claude-code@2.1.15` (476 published versions, latest 2.1.223 on 2026-08-06). `downloads.claude.ai/claude-code-releases/` returns 404 for a directory listing; no `manifest.json`/`RELEASES.json`/`latest.json` at those paths (the CLI updater uses a different mechanism).
- **Connectors directory is a Webflow CMS marketing page**, no public JSON API found at `claude.com/connectors/*.json` (all 404). The *server-side* MCP connector feature is documented at `platform.claude.com/docs/en/agents-and-tools/mcp-connector` (Messages API `mcp_servers` + `mcp_toolset`, beta header `mcp-client-2025-11-20`).

---

## 1. claude.ai web app — unauthenticated visibility

### 1.1 Direct fetch results
| URL | Result |
|---|---|
| `https://claude.ai/` | **403** — Cloudflare "Just a moment…" managed challenge (nonce'd script, `challenges.cloudflare.com`, zone `claude.ai`). No app HTML, no `<script src>` bundle references. |
| `https://claude.ai/login` | **403** — same challenge (redirects to `/login?__cf_chl_tk=…`) |
| `https://claude.ai/connectors/notion.json` (probe) | **403** — gated |

So: **unauthenticated, we can see NOTHING of the web app's JS bundles.** No `/api/cowork`, `/cowork/tasks`, `/artifacts`, `/scheduled`, `/sessions` paths could be grepped from claude.ai itself.

### 1.2 Fallback evidence (what we did get)
Instead of claude.ai, we obtained **Claude's own web-app code** via two side doors that are *not* gated:

1. **`pivot.claude.ai` — the Microsoft 365 add-in** (Claude in Excel/Word/PowerPoint). Its Office manifest (`https://pivot.claude.ai/manifest.xml`, `Id 4e2fd29d-dad0-40b3-af3c-a16e347a5ddc`, v1.0.0.12, `<AppDomain>https://claude.ai</AppDomain>`) points to `https://pivot.claude.ai/?m=unified-1.0.0.12`. The app bundle (`/m-addin/assets/index-DXlFthJP.js`, ~7.5 MB) is the add-in build of the claude.ai codebase and contains:
   - URLs: `https://claude.ai/customize/connectors`, `https://claude.ai/customize/skills`, `https://claude.ai/downloads`, `https://claude.ai/settings/integrations`, staging twin `https://claude-ai.staging.ant.dev`
   - An **admin/management API client** with paths: `/v1/agents?beta=true`, `/v1/environments?beta=true`, `/v1/files?beta=true`, `/v1/memory_stores?beta=true`, `/v1/messages?beta=true`, `/v1/messages/count_tokens`, `/v1/models`, `/v1/oauth/device_authorization`, `/v1/oauth/token`, `/v1/sessions?beta=true`, `/v1/skills?beta=true`, `/v1/user_profiles?beta=true`, `/v1/vaults?beta=true` (these mirror the public **Claude Code Admin API** surface; `v1/sessions` here = agent-session management)
   - Cowork references: memory entries "saved by other Claude products (e.g. Cowork) … read-only here — use `memory_read` with the listed path"; product-tag list `["excel","powerpoint","word","outlook","desktop","cowork"]` (i.e. the add-in and Cowork share the same user memory store).
   - *Not found in this bundle:* `/api/cowork`, `/cowork/tasks`, `/artifacts`, `/scheduled` REST paths. The add-in speaks the standard anthropic API client surface, not the cowork REST surface.

2. **The extracted Claude Desktop asar bundle** (in `johnzfitch/claude-cowork-linux/index.js`) — main-process code, which is where all the *bridge/VM/session* logic lives (see §2–§3). This is the closest we got to the app's server-side contract.

### 1.3 Recommended next step (needs the user's logged-in session)
Devtools capture from a real logged-in claude.ai session is the only way to enumerate the web REST surface (`/api/cowork/…`, artifacts API, scheduled tasks, spaces). Targets to capture:
- Network tab filter: `cowork`, `artifact`, `scheduled`, `task`, `session`, `space`, `ws://`/`wss://`
- App Storage → LocalStorage/IndexedDB for endpoint/config keys (e.g. API base URLs, feature flags)
- The Cowork UI (claude.ai/cowork) session list view + artifact open + scheduled-task create/run

---

## 2. Community RE repos — full inventory

### 2.1 `johnzfitch/claude-cowork-linux` — the core RE repo ⭐406 stars / 79 forks / 370 commits
Repo: `https://github.com/johnzfitch/claude-cowork-linux` (MIT, AUR: `claude-cowork-linux`). Tagline: *"Run Claude Desktop's Cowork mode natively on Linux — no macOS or VM required."*

**What it reverse-engineered:** Claude Desktop's Cowork = the normal Electron app running a **sandboxed Linux VM** (Apple Virtualization framework) containing the Claude Code CLI, with a folder mounted at `/sessions/<name>/mnt/<folder>`. The repo stubs the two native modules and runs the CLI directly on the host Linux:

| Component | Original | Stub |
|---|---|---|
| `@ant/claude-swift` | macOS Swift addon w/ Virtualization.framework | JS: `vm.setEventCallbacks()`, `vm.startVM()` (no-op), `vm.spawn()` (delegates to `session_orchestrator.js`), `vm.kill()`, `vm.writeStdin()`, `vm.mountPath()`, `vm.installSdk()`, `vm.addApprovedOauthToken()` |
| `@ant/claude-native` | macOS `.node` native module | JS: `AuthRequest` (opens system browser), safe-fs shim (`openRootDir`/`*Beneath` since asar 1.22209.x), platform helpers |

**The `vm.spawn()` contract** (from `stubs/@ant/claude-swift/js/index.js`):
```
spawn(id, processName, command, args, options, envVars, additionalMounts, isResume, allowedDomains, sharedCwdPath)
```
- The asar passes `--resume <sessionId>` args, `additionalMounts` (mount-name → host-path map), and `CLAUDE_CODE_OAUTH_TOKEN` env var.
- CLI stdout is line-buffered JSON: `{"type":"stream_event",…}`, `{"type":"result", num_turns, is_error, subtype:"success"}`, `{"type":"assistant"}`, `{"type":"message", message:{role}}` (parsed by `stream_protocol.js` — this is the Claude Code SDK stream protocol).

**Path translation** (the famous part):
| VM path (macOS) | Host path (Linux stub) |
|---|---|
| `/usr/local/bin/claude` | resolved: `$CLAUDE_CODE_PATH` → `~/.config/Claude/claude-code-vm/{version}/claude` → `~/.local/bin/claude` → mise/asdf shims → linuxbrew… |
| `/sessions/…` | `~/.config/Claude/local-agent-mode-sessions/sessions/…` (install creates `/sessions` symlink, 700 perms) |
| session mounts | `…/sessions/<name>/mnt/<folder> → <host folder>` symlink, plus `.claude`, `.skills`, `uploads/` |

**Platform spoofing** (server-side gate): headers sent by the app:
```
'Anthropic-Client-OS-Platform': 'darwin'
'Anthropic-Client-OS-Version': '14.0'
```
Server checks platform-gate → desktop enables Cowork. The gate function is minified per build (`xPt()` in v1.1.3963, `wj()` in older); `enable-cowork.py` patches it to return `{status:"supported"}` unconditionally (marker `/*cowork-patched*/`). Also: `/setup-cowork` route returns "Unsupported platform: linux-x64" when unpatched (COMPAT.md 1.6608.2 row).

**Server endpoints / config it documents** (see §7 for the consolidated table):
- `https://downloads.claude.ai/releases/darwin/universal/<ver>/Claude-<sha>.dmg` (Desktop DMG; COMPAT.md pins `1.6259.1` with CDN URL + SHA-256)
- `https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect` (installer's "latest" redirect — present in `fetch-dmg.js` / stub URL lists)
- `https://downloads.claude.ai/vms/linux/` — the VM bundle location pattern (stub URL validation list)
- `https://downloads.claude.ai/claude-code-releases/` — CLI binary release root
- `https://claude.ai/desktop/callback` (+ staging `https://claude-ai.staging.ant.dev/desktop/callback`) — OAuth callback
- OAuth origins allowlist: `claude.ai`, `auth.anthropic.com`, `accounts.anthropic.com`, `console.anthropic.com`
- `https://api.anthropic.com` + `https://api-staging.anthropic.com` — API base URLs
- **`/v1/sessions` remote-session API** (see §2.2)
- `https://claude.ai/cowork/space/` — space share/deep-link root (in bundle URL list)

**Version history** (COMPAT.md — useful to correlate server-side behavior changes):
| Asar | Status | Notes |
|---|---|---|
| 1.6259.1 | OK (2026-05-14) | v5.1.0 baseline |
| 1.6608.2 | PARTIAL | `/setup-cowork` says "Unsupported platform: linux-x64" |
| 1.19367.0 | OK (2026-07-15) | split-entry build (`index.pre.js` + chunked) |
| 1.20186.0 | PARTIAL | AUR pending |
| 1.22209.x | PARTIAL | CoworkSpaces file ops `(path)` → `(spaceId, path)`; artifacts/uploads moved to native safe-fs (`openRootDir`+`*Beneath`) |
| 1.24012.1 | PARTIAL | **`DeviceRegistry.signCreateSessionBind` throws "device not registered (no row-PK for this account)" → "Couldn't link this session to a computer"** — i.e. the server now requires a device-identity binding before session linking. `BuddyBleTransport.reportState` appeared (stubbed no-op). |

### 2.2 Remote session sync API (server-side!) — from `stubs/cowork/sessions_api.js`
The stub reimplements the client the asar uses to sync sessions with Anthropic's servers:
- Base: `https://api.anthropic.com`, headers `anthropic-version: 2023-06-01`, `anthropic-beta: oauth-2025-04-20,ccr-byoc-2025-07-29`
- `GET /v1/sessions` — list remote sessions
- `GET /v1/sessions/{remoteSessionId}` — fetch one (returns `remoteSessionId` + access token; field aliases observed: `remoteSessionId`/`sessionId`/`session_id`/`id`, `sessionAccessToken`/`session_ingress_token`/`accessToken`)
- `POST /v1/sessions` — create (payload carries `cwd`, `localSessionId`, `model`, `permissionMode`, `title`, `userSelectedFolders`, `organizationUuid`)
- `POST /v1/sessions/{id}/events` — post `{events:[…]}`
- `ensureSession(context)` logic: reuse stored `remoteSessionId`+token → fetch existing → create new. `permissionMode` values incl. `'default'`.
- Auth: token or auth-file-descriptor; `organizationUuid` header support.
- This is the same remote-session surface Claude Code uses (session ingress), so it's the best-documented server API for "cloud sessions".

### 2.3 Other community repos (GitHub API search, 2026-08-06)
Search "cowork anthropic" / "claude desktop cowork" (sorted by stars, total ~190 / ~281 hits):

| Repo | Stars | Relevance to RE |
|---|---|---|
| `eigent-ai/eigent` | 14,761 | Open-source Cowork *alternative* (BYOK). Not a protocol RE. |
| `composio-community/open-claude-cowork` | 4,318 | "Open source version of Cowork" — Electron + **Claude Agent SDK** (`claude-provider.js`, SSE streaming, `server/server.js` port 3001). Confirms desktop Cowork behavior is built on the Agent SDK loop, not a bespoke protocol. |
| `DevAgentForge/Open-Claude-Cowork` | 3,391 | Alternative, BYOK. |
| `anthropics/claude-desktop-buddy` | 2,518 | **Official Anthropic** reference for the Bluetooth BLE "Buddy" API (`BuddyBleTransport` — see the `BuddyBleTransport_$_reportState` channel in the asar). Useful for the Bluetooth device-pairing surface of Desktop. |
| `OpenCoworkAI/open-cowork` | 1,980 | Alternative (Claude Code + MCP + Skills), BYOK. |
| `johnzfitch/claude-cowork-linux` | 406 | **The RE repo. See §2.1.** |
| `HarmonicSecurity/claudit-sec` | 293 | Security-audit tool for Claude Desktop/Code: MCP servers, extensions, plugins, **connectors, scheduled tasks, permissions** — reads the same on-disk state the desktop writes. Useful for the local data model. |
| `kuse-ai/kuse_cowork` | 751 | Alternative. |
| `abhinaykrupa/cowork-to-code-bridge` | 11 | "Bridges Claude Cowork to Claude Code" — worth a skim for how people wire cowork sessions to local CLIs. |
| `DRVBSS/cowork-migrate` | 37 | Migrates Cowork sessions between Macs — documents the on-disk session layout. |
| `JesperLive/ClaudeFix` | 22 | Windows VM fix ("VirtioFS mount failed: bad address") — confirms Windows Cowork uses a VM too (VirtioFS). |
| `techtoboggan/claude-desktop-hardened-linux` | 10 | Linux packaging of Desktop incl. Cowork (Local Agent Mode). |

**Writeups**: search-engine access was bot-blocked (DDG challenge, Bing challenge, grep.app Vercel checkpoint). No standalone web writeup ("claude cowork reverse engineering") could be fetched; the only substantive writeups live **inside the johnzfitch repo docs** (`docs/FAQ.md`, `docs/OAUTH-COMPLIANCE.md`, `docs/extensions.md`, `docs/releases/`, `COMPAT.md`).

---

## 3. The desktop ↔ bridge protocol (from the extracted asar bundle)

The bundle `index.js` in the repo is the real Claude Desktop main-process code (EIPC UUID `97efbacf-9a70-4725-958b-ceaf6257bcc7`). Everything in this section is **direct evidence from that code**.

### 3.1 EIPC — Electron IPC channel format
```
$eipc_message$_<uuid>_$_<namespace>_$_<Interface>_$_<method>
```
- namespaces observed: `claude.web`, `claude.hybrid`, `claude.settings`
- Every handler enforces renderer origin validation (sender frame URL check).
- 362 distinct `Interface_$_method` entries extracted; namespaces by count:

| Interface | # methods | Highlights |
|---|---|---|
| `LocalAgentModeSessions` | 28+ | `start`, `getAll`, `getTranscript`, `shareSession`, `setDraftSessionFolders`, `getSupportedCommands`, `getTrustedFolders`/`addTrustedFolder`/`isFolderTrusted`, `setMcpServers`, `replaceRemoteMcpServers`, `replaceEnabledMcpTools`, `mcpCallTool`, `mcpReadResource`, `mcpListResources`, `getSessionsForScheduledTask`, `respondToToolPermission`, `syncSkills`, `respondDirectoryServers`, `respondPluginSearch`, `setFocusedSession`, `openOutputsDir`, **12 `*Bridge*` methods** (see 3.4), events: `onEvent`, `onToolPermissionRequest`, `onCoworkFromMain`, `onRemoteSessionStart`, `onBridgePermissionPreflight` + `sessionsBridgeStatus` store |
| `CoworkSpaces` | 21 | `getAllSpaces`, `getSpace`, `createSpace`, `updateSpace`, `deleteSpace`, `addFolderToSpace`, `removeFolderFromSpace`, `addProjectToSpace`, `addLinkToSpace`, `copyFilesToSpaceFolder`, `createSpaceFolder`, `listFolderContents`, `openFile`, `readFileContents`, `getAutoMemoryDir`, `classifySessions`, `onSpaceEvent` |
| `ClaudeVM` | 10 | `isSupported`, `startVM`, `download`, `getDownloadStatus`, `getRunningStatus`, `deleteAndReinstall`, `checkVirtualMachinePlatform`, `apiReachability` (store), `isProcessRunning`, `getSupportStatus` |
| `CoworkScheduledTasks` | 9 | `createScheduledTask`, `updateScheduledTask`, `updateScheduledTaskFileContent`, `updateScheduledTaskStatus`, `removeApprovedPermission`, `clearChromePermissions`, `getAllScheduledTasks`, `getScheduledTaskFileContent`, `onScheduledTaskEvent` |
| `CCDScheduledTasks` | 8 | same minus `clearChromePermissions` (Claude Code Desktop task surface) |
| `ComputerUseTcc` | 7 | macOS TCC grants: `getState`, `requestAccess`, `requestScreenRecording`, `revokeGrant`, `getCurrentSessionGrants`, `openSystemSettings`, `requestAccessibility` |
| `FileSystem` | 6 | (in stubs) |
| `ClaudeCode` | 3 | `prepare`, `getStatus`, `checkGitAvailable` |
| `CoworkMemory` | 2 | `readGlobalMemory`, `writeGlobalMemory` (shared memory store — same store the pivot add-in reads) |
| misc | — | `Account`, `Auth` (`doAuthInBrowser`), `AppConfig`, `AppPreferences`, `AutoUpdater`, `BrowserNavigation`, `BuddyBleTransport` (`reportState`), `ChromeExtension` (`installExtension`, `isInstalled`, `restartChrome`), `DesktopIntl`, `MainWindowTitleBar`, `QuickEntry`, `Startup`, `WindowControl`, `AppFeatures` (incl. `setIsDxtAutoUpdatesEnabled`), `AgentModeFeedback` |

### 3.2 Scheduled tasks (server-side state, local execution)
Scheduled tasks = `.claude/scheduled_tasks/<id>.json` on disk; **creation is renderer-only** (the `shouldAutoApprovePermission(scheduledTaskId, …)` gate auto-approves tools for scheduled-task runs). The RE project's `scheduled_task_gate.js` blocks any *bridge-reachable* mutation via these suffixes:
- Mutating: `…_$_createScheduledTask`, `updateScheduledTask`, `updateScheduledTaskFileContent`, `updateScheduledTaskStatus`, `removeApprovedPermission`, `CoworkScheduledTasks_$_clearChromePermissions`
- Read-only: `…_$_getAllScheduledTasks`, `getScheduledTaskFileContent`, `onScheduledTaskEvent`, `LocalAgentModeSessions_$_getSessionsForScheduledTask`
- Whether scheduled tasks sync to a server REST API is **unverified** (no REST path found; the tasks live on disk and are triggered by the local app).

### 3.3 Permissions model (matches Agent SDK)
- `permissionMode` values `'default' | 'acceptEdits' | 'bypassPermissions' | 'plan' | 'dontAsk' | 'auto'` (SDK type), plus `allowDangerouslySkipPermissions`, `permissionPromptToolName`.
- Tool permission flow: renderer → `LocalAgentModeSessions_$_onToolPermissionRequest` event → user decision → `respondToToolPermission(requestId, decision)`.

### 3.4 Chrome-extension bridge (connector routing!) — full wire protocol
Two transports in the bundle:

**(a) WebSocket relay to Anthropic's servers** — used when the extension is *not* local:
- Endpoints (chosen by env/`To()` staging check):
  - `wss://bridge.claudeusercontent.com` (production)
  - `wss://bridge-staging.claudeusercontent.com` (staging)
  - `ws://localhost:8765` (dev)
- Connect: `new WebSocket('<bridgeUrl>/chrome/<userId>')`, then send `{type:"connect", client_type, oauth_token}` (or `dev_user_id`).
- Messages (JSON): client→server: `connect`, `list_extensions`, `pairing_request {request_id, client_type}`, `tool_call {tool_use_id, client_type, tool, args, target_device_id, permission_mode, allowed_domains, handle_permission_prompts, session_scope}`, `permission_response {request_id, allowed}`, `ping`/`pong`.
- Server→client: `paired`, `waiting`, `peer_connected {deviceId}`, `peer_disconnected {deviceId}`, `routing_ack {tool_use_id, routed_to, target_connected_at, extension_sockets, mcp_sockets}`, `extensions_list {extensions:[{deviceId,name,osPlatform,connectedAt}]}`, `pairing_response {request_id, device_id, name}`, `tool_result`, `permission_request {tool_use_id, request_id, tool_type, url, action_data}`, `notification {method, params}`, `error`.
- So **bridge.claudeusercontent.com is a real server-side relay/router** for browser tools (tabs/JS execution) and MCP sockets between the desktop and the Chrome extension — the closest thing to documented "connector routing" transport. The `routing_ack` even reports `extension_sockets` and `mcp_sockets` counts (server-side routing state).

**(b) Local Unix socket to `chrome-native-host`** (native messaging):
- Socket dir `claude-mcp-browser-bridge-*`, mode 0700/0600 enforced; 4-byte little-endian length-prefixed JSON frames.
- Method: `execute_tool {client_id, tool, args, session_scope}`; `setPermissionMode` no-op.
- Native host manifest `com.anthropic.claude_browser_extension.json`; registry keys for Chrome/Brave/Edge/Chromium/Arc/Vivaldi/Opera (Windows).
- Chrome extension IDs found in bundle: `dihbgbndebgnbjfmelmegjepbnkhlgni` (vnt), `fcoeoabgfenejglbffodgkkbkcdhcgfn` (F2e), `dngcpimnedloihjnnfngkgjoidhnaolf`; store page `https://chrome.google.com/webstore/detail/<id>`, product "Claude in Chrome".
- Browser MCP tool set exposed to the model: `javascript_tool` (javascript_exec), `read_page` (accessibility tree, ref_id/depth/max_chars), `find` (natural language), `form_input`, `computer` (mouse/keyboard/screenshots), plus `tabs_context_mcp` for tab context.

**(c) Office add-in bridge** (same host):
- `OFFICE_ADDIN_BRIDGE_URL` env override; prod/staging same `bridge*.claudeusercontent.com`; dev `wss://localhost:8766`.
- OAuth scope for the add-in: `user:inference user:office`.

---

## 4. MCPB / DXT / @ant/claude-for-chrome-mcp

### 4.1 MCPB — definitively *not* a bridge protocol
From the asar bundle (`index.js`):
- File extension check: `e.endsWith(".dxt") || e.endsWith(".mcpb")` in the plugin-file filter (alongside `.skill`).
- Signature format: `MCPB_SIG_V1` … `MCPB_SIG_END` markers wrapping a PKCS#7 detached signature; verified against a certificate chain (`chain.pem` in temp dir `mcpb-verify-*`); unsigned files → `{status:"unsigned"}`; verified → cert-chain check (`"Failed to verify MCPB file"`).
- Contents: `manifest.json` (validated by zod-like schemas; fields: `dxt_version` (deprecated) **or** `manifest_version` — "Either 'dxt_version' (deprecated) or 'manifest_version' must be provided" — plus `name`, `license`, `compatibility`, `user_config`, `privacy_policies` (URL), `_meta`), and an `mcp_config` / `server` entry.
- "Claude Desktop does not currently support MCPB manifest version X. This may be supported in a future update."
- Log prefix `[McpbParsing]`; `isMcpb: true` flag on parsed plugins; path-traversal checks on MCPB sources.
- **Conclusion: MCPB = a signed, distributable MCP-plugin bundle file (`.mcpb`)** — the plugin distribution format (the "MCP bridge" misread). It is local-file packaging, not a client↔server wire protocol.

### 4.2 DXT — "desktop extension"
- Manifest field `dxt_version` (legacy) → replaced by `manifest_version`. (`AppConfig_$_setIsDxtAutoUpdatesEnabled` also exists — auto-update of desktop-extension plugins.)
- `.dxt` = a plugin bundle file extension alongside `.mcpb`/`.skill`.
- **Conclusion: DXT = the older Claude Desktop extension/plugin manifest+package format ("desktop extension").** No wire-protocol meaning. (grep.app/DDG/Bing corroboration was bot-blocked; this is from the bundle itself.)

### 4.3 @ant/claude-for-chrome-mcp
- `https://registry.npmjs.org/@ant/claude-for-chrome-mcp` → **404** (not public; scoped private or unpublished).
- npm search "claude-for-chrome" → no such public package.
- The same-named capability is implemented inside the asar (`ChromeExtension` EIPC interface + `chrome-native-host` + bridge WS, §3.4). **If the user has access to the private @ant registry / GitHub org, that package is the chrome-bridge MCP surface** (browser MCP server bridging desktop ↔ extension).

---

## 5. Anthropic Agent SDK `query()` — behavioral reference (Desktop builds on this)

Source: npm `@anthropic-ai/claude-agent-sdk@0.3.223` (2026-08-06), `sdk.d.ts` (types are the contract; docs at `platform.claude.com/docs/en/agent-sdk`).

### 5.1 Key `query()`/`Options` fields (exact from .d.ts)
- `tools?: string[]` — tool names (opposite: `disallowedTools?: string[]`)
- `allowedTools?: string[]` — auto-execute without approval (note: passing `'Skill'` here is deprecated → use `skills`)
- `canUseTool?: CanUseTool` — custom permission handler called before each tool; signature `(toolName, input, options: {signal: AbortSignal, suggestions?: PermissionUpdate[], blockedPath?: string, decisionReason?: string, prompt?: string, …})` → `PermissionResult` (with `updatedPermissions`, `permissionDecision` incl. `'allowOnce'|'allowAlways'|'deny'|…`); "the same toolUseID as `canUseTool`" is surfaced to permission prompts
- `permissionMode?: 'default' | 'acceptEdits' | 'bypassPermissions' | 'plan' | 'dontAsk' | 'auto'` (+ `allowDangerouslySkipPermissions` guard for bypass; `planModeInstructions` for plan-mode workflow text; `permissionPromptToolName` routes prompts through an MCP tool)
- `hooks?: …` (PreToolUse/PostToolUse/… — `SDKHookCallbackRequest` in control plane; hooks also load from settings sources)
- `mcpServers?: Record<string, McpServerConfig>` — `McpServerConfig` variants: `{type:'command', command, args, env}`, `{type:'http', url, headers, tools?}`, **`{type:'claudeai-proxy', url, id, timeout}`** ← the **cloud-connector type**: "claude.ai MCP cloud connectors are not auto-fetched or connected. Only gates auto-fetched connectors — a claudeai-proxy server passed explicitly … still follows the normal MCP config trust flow." This is how desktop/CLI route OAuth'd claude.ai connectors to the agent loop.
- `settingSources?: ('user'|'project'|'local'|'managed'|'plugin'|'agent'|'cli-args')[]` — "Pass `[]` to disable filesystem settings (SDK isolation mode). Must include `'project'` to load CLAUDE.md files."
- `managedSettings?: Settings` (policy tier), `strictMcpConfig?: boolean` (ignore .mcp.json/settings/plugins MCP; = `--strict-mcp-config`)
- `model?: string`, `systemPrompt?`, `outputFormat?` (json_schema), `pathToClaudeCodeExecutable?`, `resume?`/`continue?`, `cwd?`, `forkSession?`, `agents?` (subagents), `skills?: string[]|'all'`, `plugins?: PluginConfig[]` (can skip `mcpServers` of plugin: "the engine loads skills/hooks/agents/commands from this plugin but does NOT read its .mcp.json or manifest mcpServers")
- Session/stream surface: `query()` emits `stream_event`-style SDK messages (system/assistant/user/result), `setPermissionMode()`, `setMcpPermissionModeOverride(serverName, 'default'|'auto'|null)`, `listMcpServers()`, control requests incl. `can_use_tool`, `set_mcp_servers`, `reload_plugins`, `reload_skills`, `get_plan`, `request_user_dialog`, etc. (SDKControl*Request union, §sdk.d.ts:3804)
- `PermissionMode` also carries `'auto'` (auto-classify) — the mode Cowork's scheduled tasks effectively use.
- The SDK binary talks to the bundled Claude Code CLI over stdio JSON-RPC (`bridge.d.ts`/`bridge.mjs` — "bridge" here = SDK↔CLI channel, distinct from the chrome/office bridges).

### 5.2 Why this matters for RE
Cowork's local loop **is** Claude Code (spawned with `--resume`, `additionalMounts`, OAuth token, line-buffered JSON-RPC stream events). Any "cloud session" the server provides (`/v1/sessions`) is orthogonal: it's the *sync/ingress* layer, while the agent loop runs locally. `claudeai-proxy` is the connector bridge into the loop.

---

## 6. Connectors registry + MCP connector

### 6.1 `claude.com/connectors` (directory)
- Fetchable unauthenticated (200, ~617 KB) — it's a **Webflow-hosted static marketing page** (`cdn.prod.website-files.com/…/claude-brand.*.js`, jQuery, GSAP). Content: connector cards with name/category/date/"Works with: Claude | Claude Code"/capabilities (Interactive, Read & write, Read) + filters (use case, etc.). ~17 pages of connectors (10x Genomics … AppFolio Realm-X … Affinity, Airtable, Amplitude, GitHub-class entries, etc.). FAQ notes: connectors are third-party MCP servers, OAuth presented during connect; "MCP Directory Terms and Conditions".
- **No public JSON API found** (all probed 404): `claude.com/connectors/<x>.json`, `/connectors/api/connectors`, `/api/connectors`, `claude.ai/connectors/<x>.json` (403/gated). Directory data lives in the Webflow CMS collection (client-side populated via Webflow's CMS API — we did not extract the collection id; `data-wf-page="68c38b30d0db3f9e465132f7"`).
- Working links from the page: `claude.com/docs/connectors/building/submission` (submit your own), i18n variants (`/de/connectors`, etc.).

### 6.2 Server-side MCP connector (Messages API) — docs confirmed
`platform.claude.com/docs/en/agents-and-tools/mcp-connector.md` (fetched):
- Beta header **`mcp-client-2025-11-20`** (older `mcp-client-2025-04-04` deprecated). Not on Bedrock/GCP; AWS/Foundry beta.
- Messages API body: `mcp_servers: [{type:"url"|"oauth", url, name, authorization_token}]` + `tools: [{type:"mcp_toolset", mcp_server_name, tools?: ["*"|names], disabled_tools?, tools_config?: {<name>: {…}}}]`.
- Supports Streamable HTTP + SSE transports; **local STDIO not supported** (server-side feature).
- This is the server-side cousin of the SDK `claudeai-proxy` connector client.

### 6.3 How connectors flow to Cowork/Desktop (inferred, from bundle+SDK)
OAuth'd connector → claude.ai account → auto-fetched into CLI/SDK sessions as `claudeai-proxy` MCP servers (opt-out flag exists in Settings: "When true in any settings source, claude.ai MCP cloud connectors are not auto-fetched or connected"); Desktop Settings shows `claude.ai/settings/integrations` and `claude.ai/customize/connectors`. **The exact claude.ai REST endpoint that serves the connector list/tokens was not observable** (auth-gated) — a logged-in devtools capture of `claude.ai/customize/connectors` is needed.

---

## 7. Consolidated endpoint inventory (verified vs unverified)

### Verified from code/bundle (this research)
| Endpoint | Purpose | Evidence |
|---|---|---|
| `wss://bridge.claudeusercontent.com` (+`-staging.`) | Chrome-extension & Office-addin relay (paths `/chrome/<userId>`, office scope) | asar bundle (`To()` staging switch, `connect` handshake) |
| `ws://localhost:8765`, `wss://localhost:8766` | dev bridges (chrome / office) | bundle |
| `https://api.anthropic.com/v1/sessions`, `/v1/sessions/{id}`, `POST /v1/sessions/{id}/events` | remote session sync/ingress | `sessions_api.js` (RE repo) |
| `https://api.anthropic.com` (base) | API (beta `oauth-2025-04-20,ccr-byoc-2025-07-29`) | `sessions_api.js` |
| `https://claude.ai/desktop/callback` | desktop OAuth callback | bundle; `fetch-dmg.js`/stubs |
| `https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect` | Desktop DMG latest redirect | repo URL lists |
| `https://downloads.claude.ai/releases/darwin/universal/<ver>/Claude-<sha>.dmg` | pinned DMG CDN | COMPAT.md |
| `https://downloads.claude.ai/vms/linux/` | Cowork sandbox VM image root | stub URL validation lists |
| `https://downloads.claude.ai/claude-code-releases/` | Claude Code CLI release root | bundle + repo |
| `https://claude.ai/cowork/space/` | space share-link root | bundle URL list |
| `https://pivot.claude.ai/manifest.xml`, `/?m=unified-1.0.0.12`, `/m-addin/assets/*` | MS 365 add-in (Claude in Office) | fetched 200 |
| `/v1/agents, /v1/environments, /v1/sessions, /v1/skills, /v1/vaults, /v1/memory_stores, /v1/files, /v1/oauth/{device_authorization,token}, /v1/messages…` | admin/agent API client (add-in bundle) | pivot-app.js |
| `https://claude.ai/customize/connectors`, `/customize/skills`, `/settings/integrations`, `/downloads` | web routes referenced by desktop/addin | pivot-app.js |
| `https://auth.anthropic.com`, `accounts.anthropic.com`, `console.anthropic.com` (+ `/oauth/code/callback`) | auth origins | claude-native stub allowlist |
| `https://claude-ai.staging.ant.dev/desktop/callback`, `api-staging.anthropic.com` | staging twins | bundle/stubs |

### Unverified / blocked (needs logged-in session or private access)
- claude.ai web app bundles (Cloudflare) — therefore **all claude.ai REST: `/api/cowork/*`, artifacts API, scheduled-task API, spaces API, connector API**.
- Whether scheduled tasks sync to a server endpoint (no REST path found; local file execution only).
- The exact connector directory JSON (Webflow CMS; no public endpoint found).
- `@ant/claude-for-chrome-mcp` and `@ant/claude-swift`/`@ant/claude-native` packages (private npm org — 404 on public registry).
- `downloads.claude.ai/claude-code-releases/` directory listing + `manifest.json`/`RELEASES.json`/`latest.json` → all 404 (updater uses a different scheme; the GitHub/npm releases are public though).
- Web writeups (DDG/Bing/grep.app all bot-gated on this run).

---

## 8. Claude Code releases — 2.1.15 public or private?

- **Public.** GitHub `anthropics/claude-code`: tag **`v2.1.15`** exists (tags are dense: v2.1.104…v2.1.223, latest **v2.1.223** published 2026-08-06T00:52:37Z).
- npm `@anthropic-ai/claude-code`: **`2.1.15` is a valid published version** (476 versions total, oldest 0.2.100).
- `downloads.claude.ai/claude-code-releases/` itself: no directory listing, no `manifest.json`, `RELEASES.json`, `latest.json`, `releases.json` at that root (all 404 — the CLI's update channel isn't a static file at those names; it likely uses a different manifest path or is fetched only by the CLI with specific headers).
- Relevance to Cowork: the Desktop asar downloads the CLI into `~/.config/Claude/claude-code-vm/{version}/claude`; the bundle also references the same release root, so the desktop-bundled CLI version is trackable via that path pattern once the app is installed.

---

## 9. Suggested next moves (highest yield → lowest)

1. **Devtools capture from a logged-in claude.ai session** (§1.3) — enumerates `/api/cowork`, artifacts, scheduled tasks, spaces, connector fetch, and any `wss://` (e.g. agent-session websockets) with headers.
2. **Install the desktop app on macOS** and (a) `launch-devtools.sh`-style IPC tap (or `CLAUDE_COWORK_IPC_TAP=1` on the Linux port) to record the EIPC traffic during: creating a scheduled task, running a Cowork session, connecting a connector, opening a space; (b) record `curl` calls from main process (the app shells out to `curl` for `/v1/sessions`) to capture auth headers and org UUID.
3. **Check the private `@ant/*` registry** if user has access: `@ant/claude-for-chrome-mcp`, `@ant/claude-swift`, `@ant/claude-native` (the swift addon is the VM/bridge contract).
4. **Watch the johnzfitch repo** (issue #161 tracks `DeviceRegistry.signCreateSessionBind` — the server-side device-identity check that currently breaks session linking on 1.24012.1; that code path will reveal the "link session to computer" API).
5. **Webflow CMS extraction** for the connectors directory: from the logged-in page HTML, grab `data-wf-collection` for the connector collection and query Webflow's CMS API (public per-site endpoint) to get the full connector JSON.

## 10. Method notes / reliability flags

- Everything labeled "asar bundle" is from `index.js` in `johnzfitch/claude-cowork-linux@master` (extracted `.vite/build/index.js` of a recent Claude Desktop release). Minified identifiers rot per build (`xPt()` vs `wj()` platform gate) — treat symbol names as ephemeral.
- `bridge.claudeusercontent.com` protocol details are from the *client* side only; the server side of the relay (auth of `connect`/`oauth_token`, routing tables) is unobserved.
- Search-engine corroboration failed (bot challenges); single-source claims above are marked accordingly.
