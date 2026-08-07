# Claude Desktop 1.1.673 — Cloud Bridge & Network Surface (Cowork)

Static reverse-engineering of the desktop main-process bundle
`/tmp/claude-asar/app/.vite/build/index.js` (3.29 MB minified, `appVersion 1.1.673`, commit `3478247a3718c7070905d2d43416a99816d3e2ca`),
preload `index.pre.js`, MCP runtime `mcp-runtime/nodeHost.js`, plus live logs
`~/Library/Logs/Claude/{main,claude.ai-web,mcp}.log`.

All byte offsets below are offsets into `index.js`.

---

## 0. Executive summary (bridge model)

The desktop's main process has **zero direct websocket / session connections to
Anthropic**. There is no `wss://` string anywhere in the bundle or logs. Cowork
works like this:

```
claude.ai web app (renderer, WebContentsView "claude.ai-web")
   │  owns auth cookies (sessionKey, lastActiveOrg), session state, model streaming
   │  the web app talks to Anthropic servers (a-api.anthropic.com, websockets etc.)
   ▼  Electron ipcMain.handle / webContents.send  (channel prefix $eipc_message$_<bridgeUuid>_$_<iface>_$_<method>)
main process  (index.js)
   │  LocalAgentModeSessionManager (f0e) — Cowork sessions
   │  Claude VM (Swift addon @ant/claude-swift) spawns claude-code 2.1.15 in a Linux VM
   │  MCP coordinator (Pye) — local + remote + internal servers
   ▼  HTTPS (oe.net.fetch) only to claude.ai REST endpoints, api.anthropic.com (OAuth), downloads.claude.ai
Anthropic servers
```

- The "brokered connection" is the **renderer ⇄ main IPC bridge**, identified by a
  build-scoped UUID: current build `959eec20-23e8-42d3-9584-6db3cb766339`
  (an older log from Jan 14 shows `5cdfc8ba-a6d1-4b8b-8a18-51a950827d77`).
  Interfaces seen: `claude.web` (LocalAgentModeSessions, ClaudeVM, Account, QuickEntry,
  WindowControl, Auth, LocalKBs, CustomPlugins, BrowserNavigation), `claude.settings`
  (AppConfig, MCP, Extensions, FilePickers, AppPreferences, AppFeatures, GlobalShortcut,
  Startup), `claude.hybrid` (DesktopIntl), `claude.internal.findInPage`. Every call is
  origin-validated against the claude.ai web content frame (`Fe(i)`/`fr(i)` → error
  `"... from '<url>' did not pass origin validation"`).
- The cloud session "reaches" local files because the **web app drives the desktop**:
  the renderer calls `LocalAgentModeSessions.start/sendMessage/stop` with
  `userSelectedFolders`, `egressAllowedDomains`, etc., and the main process mounts those
  folders into a Linux VM where a Claude Code binary runs (Cowork).
- The desktop identifies itself only via an **install-scoped UUID** `<userData>/ant-did`
  ("Installation ID"). No device registration request to any server was found in the
  main-process bundle (gap — see §8).

---

## 1. API host configuration

| Constant | Value | Location |
|---|---|---|
| `cze` (apiHost, production) | `https://api.anthropic.com` | index.js:1922945 |
| `Dme` (auth cookie domain) | `.claude.ai` | index.js:1922977 |
| `lze` (staging domain) | `localhost` | index.js:1922999 |
| `Br()` (base URL) | `https://claude.ai` (dev builds: `CLAUDE_AI_URL` env or `claudeAiUrl` in config) | index.js:1303223 |
| `Fme.production` oauth config | apiHost `cze`, clientId `9d1c250a-e61b-44d9-88ed-5944d1962f5e`, redirectUri `https://console.anthropic.com/oauth/code/callback`, scope `user:inference` | index.js:1923167 |
| `aze` (claude-code releases base) | `https://downloads.claude.ai/claude-code-releases` | index.js:1917299 |
| `mae` (app releases base) | `https://downloads.claude.ai` | index.js:2995751 |
| `Bie` (VM bundle base) | `https://downloads.claude.ai/vms/linux/<bundle_hash>` | index.js:2859795 |

**No websocket endpoints exist in the main process.** All streaming/session
websockets live inside the claude.ai web renderer (out of scope of this bundle;
claude.ai-web.log shows only `a-api.anthropic.com/v1/m*`, segment.io, statsig,
intercom — all web-app telemetry, no `wss://` captured in logs either).

### OAuth token plumbing (`Dye()`, `qme()`, `mze()`)

`Dye(t)` (index.js:2813554) is the env injector for spawned Claude Code:

```js
{ CLAUDE_CODE_ENTRYPOINT: "claude-desktop", ANTHROPIC_BASE_URL: t.apiHost,
  ANTHROPIC_API_KEY: "", CLAUDE_CODE_OAUTH_TOKEN: t.oauthToken,
  DISABLE_AUTOUPDATER: "1", CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL: "true" }
```

Token acquisition chain (`qme(config)` index.js:1924528):
1. Load `oauth:tokenCache` from electron-store `config.json` (`pze()` index.js:1923948),
   decrypted with `safeStorage.encryptString`/`decryptString` — i.e. **Keychain on macOS**
   (Electron "safeStorage" service), value stored base64.
   Cache keys: `` `${clientId}:${orgId}` `` (`dze()`); value `{token, refreshToken, expiresAt}`.
2. `lastActiveOrg` read from **cookie** `lastActiveOrg` on `.claude.ai` (`Zn()` index.js:1915614, UUID-validated `Xy`).
3. Cache hit → return. Expired + refreshToken → POST `${apiHost}/v1/oauth/token`
   `{grant_type:"refresh_token", client_id, refresh_token, expires_in: 365*24*60*60}`
   (`hze()` index.js:1926063).
4. Otherwise full PKCE exchange (`mze()` index.js:1926513):
   - reads cookies `lastActiveOrg` + `sessionKey` from `.claude.ai` (Electron session cookies)
   - POST `${apiHost}/v1/oauth/${org}/authorize` with `Authorization: Bearer <sessionKey>`,
     body `{response_type:"code", client_id, organization_uuid, redirect_uri, scope:"user:inference", state, code_challenge, code_challenge_method:"S256"}`
   - parses `code` from returned `redirect_uri`, then POST `${apiHost}/v1/oauth/token`
     `{grant_type:"authorization_code", ..., code_verifier}`.
   All with header `anthropic-version: 2023-06-01`.

The desktop therefore **reuses the web-app cookies** (`sessionKey`, `lastActiveOrg`)
rather than storing its own password. Tokens are persisted per-org in
`~/Library/Application Support/Claude/config.json` under `oauth:tokenCache`
(encrypted at rest via safeStorage; log: `[oauth] token cache location: <path>`).

The same token is (a) fed into the VM via `Dye` and (b) registered with the VM's
MITM proxy: `addApprovedOauthToken(CLAUDE_CODE_OAUTH_TOKEN)` before spawn
(index.js:2858798, `[Spawn:vm] OAuth token approved with MITM proxy`).

Env passthrough to Claude Code (index.js:2810929): only
`PATH, CLAUDE_CODE_ENTRYPOINT, CLAUDE_CODE_OAUTH_TOKEN, ANTHROPIC_API_KEY,
ANTHROPIC_BASE_URL, DISABLE_AUTOUPDATER` — stored encrypted in a second
electron-store `ccd-environment-config.json` (key `envVars`, safeStorage-encrypted).

---

## 2. The "Anthropic-brokered connection" (cloud session ⇄ desktop bridge)

There is **no agent-gw / relay / tunnel** in the main process. Greps for
`brokered`, `session-broker`, `agent-gw`, `relay`, `tunnel`, `WebSocket`,
`socket.io`, `deviceRegistration` all return nothing meaningful. The bridge is
**pure Electron IPC**, marshalled by a generated "eipc" layer:

- Channel format: `$eipc_message$_<bridgeUuid>_$_<interface>_$_<method>`
  (e.g. `..._$_claude.web_$_LocalAgentModeSessions_$_start`, index.js:3135759+).
- Dispatchers are per-WebContentsView (`ry.for(e.webContents).setImplementation(...)`,
  index.js:3135759). `Se` = the claude.ai WebContentsView; `Me` = main BrowserWindow.
- The renderer-facing API surface for Cowork is `Wat` → `createLocalAgentModeSessionsApi`
  (index.js:3277085, exported 3280565): `start`, `sendMessage`, `stop`, `archive`,
  `updateSession`, `getSession` (replays buffered messages as `message` events),
  `getAll`, `getSupportedCommands`, `getTrustedFolders`, `addTrustedFolder`,
  `removeTrustedFolder`, `isFolderTrusted`, `setMcpServers`, `setFirstPartyConnectors`,
  `setFocusedSession`, `respondDirectoryServers`.
- Main→renderer events dispatched from the session manager (`p.on("event", …)`,
  `dispatchOnEvent({type: "message"|"queryCompleted"|"fs_file_created"|…})`).

### How a cloud session reaches local files

1. Renderer (web session UI) calls `start({sessionId, message, model, systemPrompt,
   mcpServers, remoteMcpServers, images, userSelectedFolders, userSelectedFiles,
   egressAllowedDomains, messageUuid, sharedCwdPath, enabledMcpTools,
   firstPartyConnectors, accountName, emailAddress, selectedKnowledgeBases,
   userSelectedProjectUuids})` (index.js:3277085).
2. `f0e.doSessionInitialization` (index.js:2904399+):
   - telemetry `lam_session_start_attempted` (vm_instance_id = `Ha()`, random UUID per app run, index.js:2856450);
   - auth via `qme()` (OAuth token, §1);
   - skills sync → `GET /api/organizations/<org>/skills/list-skills?include_wiggle_skills=true`
     + `…/skills/download-dot-skill-file?skill_id=…` (index.js:2890864,2891384), stored in
     `<userData>/local-agent-mode-sessions/skills-plugin/<org>/<account>/skills/`;
   - plugins sync (feature `2340532315`) → `GET …/plugins/list-plugins` + `…/plugins/<id>/download`
     (index.js:2631884+), stored `<userData>/local-agent-mode-sessions/plugins/<org>/<account>/`;
   - knowledge-base mounts from `Y.getKnowledgeBase*` → mounted `.knowledge/<mountName>` (rw);
   - **folder mounts** built in `getVMSpawnFunction` call (index.js:2923771): each selected
     folder → `/sessions/<vm>/mnt/<basename>` (`rw`, or `rwd` after user approves deletes),
     plus `.claude` (rwd, session config), `.skills` (ro), `.plugins` (ro), `.local-plugins`
     (ro), `uploads` (ro), `.projects` (ro), `outputs` (rw).
   - `allowedDomains: r.egressAllowedDomains` and `sharedCwdPath` (default
     `~/Documents/Claude`) passed to the VM spawner.
3. Spawn: `TQe`/`AQe` (index.js:2897350,2858587) via the Swift VM addon
   (`_i()` = `@ant/claude-swift`, see cowork_vm_node.log "Module loaded successfully"):
   `spawn(id, processName, command, args, cwd, env, mounts, isResume, allowedDomains, sharedCwdPath)`.
   Command: the bundled Claude Code binary at `/usr/local/bin/claude` **inside the VM**
   (pathToClaudeCodeExecutable in `B`, index.js:2919896); env = `Dye(...)` +
   `CLAUDE_CONFIG_DIR=/sessions/<vm>/mnt/.claude`, `CLAUDE_CODE_ENTRYPOINT=local-agent`,
   `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, `CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS=true`,
   `MCP_TOOL_TIMEOUT` (growthbook feature `1978029737`, default 30000 ms).
4. Message/event streaming back to the renderer via `emit("event", …)` → dispatcher.
   Session state persisted as JSON: `<userData>/local-agent-mode-sessions/<accountUuid>/<orgId>/<sessionId>.json`
   (`getSessionFilePath`, index.js:2904500); session ids prefixed `local_` (`_M="local_"`).

### Identity / registration

- Device identity: `<userData>/ant-did` — random UUID stored base64 (`Oet()`,
  index.js:2976586). Exposed as "Installation ID" (About dialog menu item
  "Copy Installation ID"). Used as **Sentry user.id** in the preload
  (index.js.pre `initialScope: {user: {id: LG()}}` with DSN
  `https://2f98127cbffe4740b1f767a2de77d23b@o1158394.ingest.us.sentry.io/4507368973008896`).
- Account/org resolution: `GET ${Br()}/api/bootstrap` → `{account:{uuid,…}}` (`$f()`,
  cached; index.js:2620492). Org id from `lastActiveOrg` cookie (`Zn()`).
- **No server-side device registration endpoint found in the main bundle** — the
  "trusted device" concept, if any, lives in the web app (renderer). Gap (see §8).

---

## 3. DXT extension servers

DXT = Desktop eXTension packaging; `.dxt` and `.mcpb` are the two bundle extensions
(`L7e`: temp file `dxt-download-…` `.dxt`/`.mcpb`, index.js:2595400). MCPB bundles
carry an embedded PKCS7 signature delimited by `MCPB_SIG_V1` / `MCPB_SIG_END`
(verified via `security verify-cert -p codeSign` on darwin, `sB()` index.js:2610200).
Manifest header version for version listings: `x-mcpb-manifest-version: 0.4` (`cF`,
index.js:390087).

**Endpoints** (base `https://claude.ai/api/organizations/<org>/dxt`, `qB()` index.js:2612256):

| Endpoint | Purpose | Location |
|---|---|---|
| `GET …/dxt/blocklist` | extension blocklist (fetched on startup + every 6h; persisted `<userData>/extensions-blocklist.json`) | `tZe`/`aZe`/`oZe` index.js:2603753, 2604710, 2605041 |
| `POST …/dxt/can_install` | org allowlist check per extension (hash + manifest) | `rZe` index.js:2603922, `cZe` index.js:2605568 |
| `GET …/dxt` | directory base (`getDirectoryUrl` for renderer) | `qB` index.js:2612256 |
| `GET …/dxt/extensions?search=&limit=&offset=&platform=` | search directory | `k_e` index.js:3159532 |
| `GET …/dxt/extensions/<id>` | extension metadata | `R_e` |
| `GET …/dxt/extensions/<id>/versions` | versions (header `x-mcpb-manifest-version: 0.4`) | `N_e` |
| `GET …/dxt/extensions/<id>/versions/<ver>` | specific version metadata | `O_e` |
| `GET …/api/organizations/<org>` | organization settings (allowlist enabled flag) | `nZe`/`iZe` index.js:2604100+ |

Directory responses cached in-memory 5 min (`Gse`, `_nt=60e3*5`).

**Allowlist cache** (index.js:2602347+): keys `dxt:allowlistCache:<org>`
(safeStorage-encrypted blob in `config.json`), `dxt:allowlistEnabled:<org>`,
`dxt:allowlistLastUpdated:<org>`; legacy global keys `dxt:allowlistEntries`,
`dxt:allowlistEntriesLastUpdated`, `dxt:allowlistCache` are deleted on startup.

**MDM gating** (index.js:1308464, `Ll()`): `isDesktopExtensionEnabled` /
`isDxtEnabled` (alias), `isDesktopExtensionDirectoryEnabled`/`isDxtDirectoryEnabled`,
`isDesktopExtensionSignatureRequired`/`isDxtSignatureRequired`, plus
`isLocalDevMcpEnabled`, `isClaudeCodeForDesktopEnabled`, `secureVmFeaturesEnabled`,
`disableAutoUpdates`, `autoUpdaterEnforcementHours` — read from macOS defaults
(`defaults read …`), Windows registry HKCU/HKLM, or `claude_desktop_config.json`.
`fh()`/`jB()` gate DXT on MDM flag **and** growthbook feature `isDxtEnabled`/`isDxtDirectoryEnabled`.

**MCPB / Chrome native host bridge**: `oL="com.anthropic.claude_browser_extension"`,
binary `chrome-native-host` (`NY`, installed to `Contents/Resources/Helpers/`),
manifest JSON `com.anthropic.claude_browser_extension.json` written into
Chrome/Brave/Edge/Opera `NativeMessagingHosts` dirs (index.js:1313057+,
`cpe()`/`lpe()`). This powers the internal MCP server **"Claude in Chrome"** (`Uy`,
index.js:1313065) with tools `javascript_tool`, `tabs_context_mcp`, … (executes JS in
the user's browser page). Chrome-extension ID `qy` = `ope` (see §8).

---

## 4. mcp-registry (`search_mcp_registry` / `suggest_connectors`)

Internal MCP server `"mcp-registry"` (`XB`, alias `"mcp-registry-internal"` `bJe`;
index.js:2793312) registered in `wJe` alongside `gdrive`/`gcal`/`gmail`/`osascript`/
`Claude in Chrome` via `EJe` (InternalMcpServerManager, index.js:2796437).

Tools:
- `search_mcp_registry({keywords: string[]})` → results trimmed to 10, each
  `{name, description: oneLiner, tools: up to 8 tool names, url, iconUrl,
  directoryUuid, connected}` (index.js:2795632).
- `suggest_connectors({directoryUuids})` → `{connectors: [{name, description, url,
  iconUrl, directoryUuid}]}`.

**The desktop does not call the registry API directly.** `yJe` (search, index.js:2792317)
and `_Je` (lookup by uuids, index.js:2792902) are the `[mcpDirectoryBridge]`:
they dispatch events `{type:"directory_servers_search"|"directory_servers_lookup",
sessionId, data:{requestId, keywords|uuids}}` **to the renderer** via
`ry.getDispatcher(Se.webContents).dispatchOnEvent(...)`, pending map `Pp` with 10 s
timeout (`Tye=1e4`). The renderer (claude.ai web) performs the actual registry HTTP
query and answers through `respondDirectoryServers(requestId, results)` →
`gJe` (index.js:2792142, exposed at 3280565). So the registry endpoint (likely
`…/api/mcp-directory/…` or web-side `claude.ai` internal) is **not visible in this
bundle** — it lives in the web app (gap, §8). Connector data shape consumed:
`{uuid, name, oneLiner, url, iconUrl, toolNames[], isConnected}` (per the mapping in
the tool handler). The system prompt for Cowork sessions pre-registers both tools
(`allowedTools` list, index.js:2919896).

---

## 5. Connectors at runtime

### Internal 1P connectors (Google)

Internal servers (index.js:2796437+): `gdrive` (`$x`), `gcal` (`Cx`), `gmail` (`Tx`),
each with hidden alias `<name>-1p-internal` and a `firstPartyConnectors` gate:

```js
if (c.serverName===$x && !i.enabled_bananagrams) skip; // gdrive
if (c.serverName===Cx && !i.enabled_foccacia) skip;     // gcal
if (c.serverName===Tx && !i.enabled_sourdough) skip;    // gmail
```

`firstPartyConnectors` is supplied by the **renderer** per session
(`setFirstPartyConnectors`, session model field `firstPartyConnectors` — shape
`{enabled_bananagrams?, enabled_foccacia?, enabled_sourdough?}` booleans,
validated by `xle` index.js:105937).

Tool calls:
- **gdrive** (real): `google_drive_search` → GET
  `${Br()}/api/organizations/${org}/sync/mcp/drive/search?query=&n=` ;
  `google_drive_fetch` → GET
  `${Br()}/api/organizations/${org}/sync/mcp/drive/document/<id>` (index.js:2789565,
  `pJe`; 30 s timeout `xie=3e4`, `Cie` fetch wrapper). Logged in main.log:
  "MCP Server connection requested for: gdrive".
- **gcal** (`google_calendar_list_events`) and **gmail** (`gmail_search`) are **stubs**
  ("… integration is not yet implemented.") in this build (index.js:2796000, 2797600).

**There is no local OAuth storage for connectors and no callbackPort in the desktop
bundle** — Google connector OAuth lives server-side (org `sync/mcp/*` API); the
desktop only proxies REST calls with session-cookie-authenticated `oe.net.fetch`.
Connector `directoryUuid` values from the registry (§4) are forwarded to the renderer
for the Connect-button flow (web-side OAuth).

### Remote MCP servers (cloud-hosted connectors)

`remoteMcpServers: [{uuid, name, tools: [{name, description, inputSchema}]}]` come from
the renderer per session. `PJe` (ProxyMcpServerManager, index.js:2806391) wraps each as
a local MCP server; tool calls go to:

```
POST ${Br()}/api/organizations/<org>/mcp/servers/<serverUuid>/tools/call
body: {tool_name, arguments}
```

60 s timeout (`$ie=6e4`); response normalized from `structuredContent` / `toolResult` /
`content[]` (text, image, resource). Server-side connectors therefore execute in
Anthropic's cloud, not locally.

### Local (user-configured) MCP

`localMcpManager` (`e6`, index.js:2803595) spawns user MCP servers from
`claude_desktop_config.json`/`config.json` mcpServers. Remote-only exception: the
filesystem server `ant.dir.ant.anthropic.filesystem` is filtered out of local mounts
(`filterFilesystemMcp`, index.js:2810900) because the VM provides its own FS.
MCP servers run via Electron UtilityProcess; node servers load through
`mcp-runtime/nodeHost.js` (MessagePort-bridged stdio wrapper).

---

## 6. Telemetry

- **Events** (`gr(name, props)` index.js:2361095 → `V7e` index.js:2360044):
  `POST ${Br()}/api/event_logging/batch` with headers
  `Content-Type: application/json`, `x-service-name: claude_desktop`; body
  `{events:[{event_type:"TelemetryEvent", event_data:{event_name, timestamp,
  user_properties:{user_id:<account uuid or "anonymous">},
  metadata:{product_surface:"claude-desktop", app_version, commit_hash, platform,
  arch, organization_id, ...props}}}]}`. This is Anthropic's own event-logging
  endpoint (not Mixpanel/Segment).
- **lam_\* events** (Cowork/local-agent-mode), 24 in bundle:
  `lam_session_start_attempted`, `lam_session_step_completed`, `lam_session_turn_completed`,
  `lam_message_cycle_outcome`, `lam_session_query_error`, `lam_session_timeout`,
  `lam_session_stopped`, `lam_session_archived`, `lam_session_initialization_failed`,
  `lam_session_app_quit`, `lam_project_sync_failed`, `lam_vm_bundle_download_completed|failed`,
  `lam_vm_warm_download_started|completed|failed`, `lam_vm_warm_promote_completed|failed`,
  `lam_vm_startup_completed|failed`, `lam_vm_process_spawned|exited`,
  `lam_vm_shutdown_completed|failed`. Sample payload in main.log:1494
  (commit_hash, platform, arch, organization_id, bundle_version `8c56966f…`, duration_ms, download_reason).
  Other events: `desktop_initial_activation`, `desktop_quick_entry_show`,
  `desktop_mcp_unexpected_close` (main.log).
- **Feature flags**: GrowthBook at `GET ${Br()}/api/desktop/features`
  (index.js:2614966; log: "loaded 245 features"). Gates used: `1697423394`
  (local CLI plugins), `2340532315` (remote plugins), `1978029737` (mcpToolTimeoutMs),
  `isDxtEnabled`, `isDxtDirectoryEnabled`. Refresh on account change + periodic.
- **Sentry**: DSN `https://2f98127cbffe4740b1f767a2de77d23b@o1158394.ingest.us.sentry.io/4507368973008896`
  in preload index.pre.js, `initialScope.user.id` = ant-did install UUID, `beforeSend`
  strips request bodies. Debug id `97eed861-fc6c-4e76-920b-d11b64dcca12`. main-window.log
  shows renderer-side Sentry failing to reach the main process (main process does not
  init Sentry).
- **Renderer-only** (claude.ai-web.log): `api.segment.io`, `statsig.anthropic.com/v1/rgstr`,
  `api-iam.intercom.io/messenger/web/ping`, `a-api.anthropic.com/v1/m.*` — web-app stack.

---

## 7. Update mechanism

### Claude Code binary (CCD — `ClaudeCodeDownloader`, class `oze` index.js:1917378)

- **Version is hardcoded at build time**, not resolved from the network:
  `WCe()` (index.js:369631) returns an embedded JSON manifest
  `{"version":"2.1.15","manifest":{"version":"2.1.15","buildDate":"2026-01-21T21:27:03Z",
  "platforms":{darwin-arm64:{checksum: sha256hex, size: 176893952}, darwin-x64, linux-arm64, linux-x64,…}}}`
  → download URL `https://downloads.claude.ai/claude-code-releases/2.1.15/<platform>/claude`
  (main.log:2237 confirms). Earlier app builds embedded 2.1.5/2.1.8 (main.log:1278,1603).
- Flow (`prepareForTarget`): if `<userData>/claude-code/<platform>/<version>/claude` missing →
  download via `oe.net.request` with session cookies (`useSessionCookies:!0`) through
  `Cl()` (sha256-capable pipeline), verify checksum, chmod 755, write `.verified`,
  `cleanupOldVersionsForTarget` removes other versions. 3 attempts with 1s·i backoff
  (observed `ERR_QUIC_PROTOCOL_ERROR` retries, main.log:1503).
- VM variant: `<userData>/claude-code-vm/` + `.sdk-version` file (`prepareForVM`),
  same version 2.1.15 (linux target).
- The binary is used by quick-query (`zJe` env, `getBinaryPathIfReady`) and, inside the
  VM, mounted at `/usr/local/bin/claude`.

### App auto-update (electron-updater, index.js:2994343+)

- Feed URL: darwin `https://downloads.claude.ai/releases/darwin/universal/RELEASES.json`
  (`serverType:"json"`), win32 `https://downloads.claude.ai/releases/win32/<arch>` (`Mtt()`);
  URL logged masked (`Ott()` strips query). Logged every ~6h: "Checking for updates".
- Gated by MDM `disableAutoUpdates`/`autoUpdaterEnforcementHours`.
- Installed check via `app.isPackaged` + `update.exe` presence on win32 (`F0e`).

### VM bundle (SecureVM)

- VM rootfs pinned by hash `pi = "8c56966fa5825aba21d51a59e8a505b849e14f41"`
  (index.js:2856639; identical to `bundle_version` in the failure telemetry, main.log:1494).
  URLs: `https://downloads.claude.ai/vms/linux/<hash>/rootfs.img.zst` (+ `rootfs.img`,
  `Bie`/`Hye` index.js:2859795), hash probe
  `https://downloads.claude.ai/releases/darwin/universal/<ver>/vm_hash`, warm-download
  cache in `<userData>/…/warm/` with `.zst.` shards (`K6`/`Mat`, index.js:3271787+).

---

## Endpoint table (main process only)

| Method | URL | Purpose | Code location |
|---|---|---|---|
| POST | `https://api.anthropic.com/v1/oauth/token` | refresh + code exchange (PKCE) | index.js:1926063, 1927824 |
| POST | `https://api.anthropic.com/v1/oauth/<org>/authorize` | device-less authorize w/ sessionKey cookie | index.js:1927169 |
| GET | `https://claude.ai/api/bootstrap` | account bootstrap (`account.uuid`) | index.js:2620492 |
| GET | `https://claude.ai/api/desktop/features` | growthbook feature flags | index.js:2614966 |
| POST | `https://claude.ai/api/event_logging/batch` | telemetry (x-service-name: claude_desktop) | index.js:2360044 |
| GET | `…/api/organizations/<org>/dxt/blocklist` | DXT blocklist (6h poll) | index.js:2603753 |
| POST | `…/api/organizations/<org>/dxt/can_install` | allowlist check | index.js:2603922 |
| GET | `…/api/organizations/<org>/dxt/extensions*` | directory search/metadata (x-mcpb-manifest-version: 0.4) | index.js:3159532 |
| GET | `…/api/organizations/<org>` | org settings (allowlistEnabled) | index.js:2604100 |
| GET | `…/api/organizations/<org>/skills/list-skills?include_wiggle_skills=true` | enabled skills | index.js:2890864 |
| GET | `…/api/organizations/<org>/skills/download-dot-skill-file?skill_id=` | skill content | index.js:2891384 |
| GET | `…/api/organizations/<org>/plugins/list-plugins` | user plugins | index.js:2632200 |
| GET | `…/api/organizations/<org>/plugins/<id>/download` | plugin content | index.js:2632500 |
| POST | `…/api/organizations/<org>/mcp/servers/<uuid>/tools/call` | remote (cloud) MCP tool call | index.js:2806391 |
| GET | `…/api/organizations/<org>/sync/mcp/drive/search?query=&n=` | Google Drive search | index.js:2789565 |
| GET | `…/api/organizations/<org>/sync/mcp/drive/document/<id>` | Google Drive fetch | index.js:2789565 |
| GET | `https://downloads.claude.ai/claude-code-releases/<ver>/<plat>/claude` | Claude Code binary | index.js:1917378 |
| GET | `https://downloads.claude.ai/releases/darwin/universal/RELEASES.json` | app updates | index.js:2995751 |
| GET | `https://downloads.claude.ai/vms/linux/<hash>/rootfs.img[.zst]` | VM bundle | index.js:2859795, 3272528 |
| GET | `https://downloads.claude.ai/releases/darwin/universal/<ver>/vm_hash` | VM hash probe | index.js:3271787 |
| IPC | `$eipc_message$_959eec20-23e8-42d3-9584-6db3cb766339_$_claude.web_$_LocalAgentModeSessions_$_*` | Cowork session bridge | index.js:3135759, 3277085 |
| IPC | `…_$_claude.settings_$_Extensions_$_*`, `…_$_MCP_$_*`, `…_$_claude.web_$_ClaudeVM_$_*` | settings/VM surface | index.js:820446+, 815734+ |

Websockets: **none in main process**. `wss://` never appears in the bundle or any log.

---

## Token storage mechanics (summary)

| Secret | Store | Protection |
|---|---|---|
| Anthropic OAuth (per org) | `~/Library/Application Support/Claude/config.json` key `oauth:tokenCache` (map `clientId:orgId → {token, refreshToken, expiresAt}`) | `safeStorage` encrypt → Keychain (macOS), base64 |
| sessionKey / lastActiveOrg | Electron cookie jar (`.claude.ai`) — shared with web renderer | Chrome/Electron cookie DB (encrypted) |
| CCD env (incl. token passthrough) | `config`-adjacent store `ccd-environment-config.json` key `envVars` | `safeStorage`, base64 |
| DXT allowlist cache | `config.json` key `dxt:allowlistCache:<org>` | `safeStorage`, base64 |
| Connector OAuth (Google) | **not local** — server-side, accessed via `sync/mcp/*` | — |
| ant-did (install ID) | `<userData>/ant-did` (base64 UUID) | plaintext |
| Local agent trusted folders | `config.json` `localAgentModeTrustedFolders` | plaintext |
| Sessions | `<userData>/local-agent-mode-sessions/<acct>/<org>/<session>.json` | plaintext (contains message history, not tokens) |

---

## Gaps / open questions

1. **Registry API endpoint** (`directory_servers_search`) is resolved by the renderer —
   the desktop never holds it. To capture: instrument the web view network layer or
   extract the web bundle from the asar renderer dirs (not included in this analysis).
2. **Device registration / "trusted device"** — nothing in the main bundle; the
   `ant-did` install id is only used for Sentry + the About dialog. If Cowork pairs
   devices server-side, that logic is renderer-side.
3. **Claude in Chrome extension ID** (`qy`, minified `ope`) — the value is
   `dngcpimnedloihjnnfngkgjoidhnaolf` for the *other* extension id constants (`EDe`);
   the exact `qy` value is obfuscated at index.js:1313057 (could be resolved by
   dynamic analysis or by reading the shipped native-host manifest).
4. **gcal/gmail connectors are stubs** in 1.1.673 — only gdrive is live; expect
   renderer-mediated implementations in later builds.
5. **wss endpoints for sessions/events** exist only in the web renderer
   (claude.ai-web.log shows only `a-api.anthropic.com/v1/m*` POSTs; no WS captured).
6. `WCe()` version pinning means Claude Code updates ship with the app release —
   no server-driven version discovery for CCD was found.
7. The eipc bridge UUID rotates per build (observed `959eec20…` vs `5cdfc8ba…`),
   so any automation keying on the channel prefix must discover it at runtime
   (it is visible in main-process `ipcMain.handle` registrations).
