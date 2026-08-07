# Claude Cowork — Local Agent Mode (LocalAgentModeSessionManager) Session Lifecycle

**Static reverse-engineering · source: `/tmp/claude-asar/app/.vite/build/index.js` (3,289,071 bytes, minified)**
**App: Claude Desktop 1.1.673 · compiled 2026-08-06**

All byte offsets are absolute file offsets into `index.js`. Code snippets are verbatim (whitespace added for readability). Symbol names are the minified identifiers; real names recovered from log strings / module exports.

---

## 0. Symbol map (class location)

| Symbol | Real name | Offset | Notes |
|---|---|---|---|
| `class f0e` | `LocalAgentModeSessionManager` | **2904399** | extends `If.EventEmitter`; body 2904399–2946913 (~42.5 KB) |
| `const Is = new f0e` | singleton `localAgentModeSessionManager` | 2946910 | module export `NXe` at 2946913 |
| `ry` interface | `LocalAgentModeSessions` (IPC) | 142046 (register), handlers ~142300–150000 | channel prefix `$eipc_message$_959eec20-23e8-42d3-9584-6db3cb766339_$_claude.web_$_LocalAgentModeSessions_$_<method>` |
| `function Wat` | `createLocalAgentModeSessionsApi` | 3277085 | renderer-facing API impl (module `Gat` at 3280509) |
| — | main-process wiring | 3135833 | `ry.for(webContents).setImplementation({...})`, `p.on("event"...)` |
| `_M = "local_"` | session-id prefix | 2897251 | `sessionId = "local_" + uuid`; `Yie = "local_session_new"` (draft), `_Xe = "local-agent-mode-sessions"` (baseDir), `bXe = "local-sessions.json"` (legacy), `SXe = 3e4` (MCP timeout default) |
| `class ZQe` | `FileSystemWatcher` | 2875414 | |
| `class Pye` | `McpCoordinator` | 2809072 | `proxyManager=new PJe` (2806391), `internalManager=new EJe` (2796437), `localMcpManager` |
| `function GQe` | cowork MCP server factory | 2872011 | tools `request_cowork_directory`, `allow_cowork_file_delete` |
| `function DL` | `query()` (Claude Agent SDK 0.2.15) | 1913181 | `process.env.CLAUDE_AGENT_SDK_VERSION="0.2.15"` |
| `class OXe` | input stream (async-iterable queue) | 2903716 | |
| `function Xie` | `prepareFileUploads` | 2903212 | |
| `function IXe` | system-prompt builder | 2900655 | |
| `function aXe` | project-context sync | 2888864 | |
| `class yXe` | skills/plugins manager `i4` | 2891869 | baseDir `userData/local-agent-mode-sessions/skills-plugin/<org>/<account>` |
| `function FQe`/`i6` | VM startup | 2863152 / 2866479 | |
| `class _Qe` | `CoworkVMProcess` (fake child) | 2850654 | registry `fc` (Map id→proc), `Die=t=>fc.get(t)` at 2850637 |
| `function Uye` | load `@ant/claude-swift` | 2850038 | native VM addon; `_i()` → `addon.vm` |
| `function TQe` | `createVMSpawnFunction` | 2856761 | module `PQe` at 2858525 |
| `pi` | VM bundle version hash | 2858441 | `"8c56966fa5825aba21d51a59e8a505b849e14f41"` |
| `function Dye` | SDK env builder | 2813554 | |
| `Fme`/`Bme()` | OAuth config / env selector | 1923167 / 1923404 | `Bme()` returns `"production"` |
| `function qme` | OAuth token load (cache→refresh→exchange) | 1924534 | `mze` fresh exchange 1926513; `B5()` clear cache 1925826 |
| `class oze` | Claude Code downloader `pl` | 1917378 | manifest `WCe()` at 369631 → version **2.1.15** |
| `function Xie`/`kXe` | upload prep / file validation | 2903212 / 2903050 | |
| `function gr` | telemetry (`lam_*` events) | 2361095 | |
| `function qQe` | audit-log JSONL logger | 2868583 | |

Supporting validators (renderer contract): `cEe` startSession input (106143), `hle` start result `{sessionId}` (99007), `p9` session shape (100317), `vle` archive opts (102026), `gle` updateSession opts (102141), `QSe` getSession opts `{skipReplay}` (102235).

---

## 1. Session creation — `startSession` (offset 2914194)

IPC `start(info)` → `Wat.start` (3277085, maps fields 1:1) → `f0e.startSession(input)`.

### 1.1 Session id & resume detection

```
const r = e.sessionId ?? `${_M}${ri.randomUUID()}`,   // "local_" + uuid4
      i = !e.sessionId;                                // isFirstTurn = brand-new session
```

- Existing session + still initializing → **warn + return** (`isInitializing` guard).
- Existing session with live `query && inputStream` → **resume path**: `await this.sendMessage(r, e.message)` and return (message is routed to the live agent; no re-init).
- On resume: user folders re-filtered (`fs.existsSync`), `userSelectedProjectUuids` and `mountedKnowledgeBases` are copied from the persisted session into the start input.

### 1.2 VM process name

`a = jQe(usedNames)` (offset 2868041): generates `<adj>-<adj>-<scientist>` from docker-style word lists `dd` (2866726, 68 adjectives) + `Uie` (scientists), max length `BQe = 32` (2868034), unique across live sessions. This name **is the vmProcessName** and the `/sessions/<name>` VM root.

### 1.3 Initial in-memory session record (new session)

```
{
  sessionId: r, processName: a,
  cwd: `/sessions/${a}`,
  userSelectedFolders: e.userSelectedFolders || [],
  query: null, inputStream: null,
  isRunning: true, isStopping: false,
  isFirstTurn: i,                      // = !e.sessionId
  initialMessage: e.message,
  messageBuffer: [],
  createdAt: s, lastActivityAt: s,
  model: e.model, isArchived: false, title: e.title,
  vmProcessName: a,
  initializationStatus: { step: "auth", message: "Authenticating...", isComplete: false },
  isInitializing: true,
  fsDetectedFiles: new Map,
  userSelectedProjectUuids: e.userSelectedProjectUuids,
  systemPrompt: e.systemPrompt, accountName: e.accountName, emailAddress: e.emailAddress,
  firstPartyConnectors: e.firstPartyConnectors,
}
```
→ `this.sessions.set(r, d); this.saveSession(d)` — **persisted before the VM even boots.**

The full state field list (accumulated, from constructor 2904433 / loadSessions 2909915 / saveSession 2911427):

`sessionId, processName, cliSessionId, cwd, userSelectedFolders, query, inputStream, isRunning, isFirstTurn, isStopping, messageBuffer, createdAt, lastActivityAt, model, isArchived, title, userApprovedFileAccessPaths, vmProcessName, vmProcessId, sharedCwdPath, error, initialMessage, slashCommands, mcqAnswers, enabledMcpTools, firstPartyConnectors, fsDetectedFiles (Map), fileDeleteApprovedMounts, mountedKnowledgeBases, knowledgeBaseMountPaths (Map), systemPrompt, accountName, emailAddress, userSelectedProjectUuids, projectContexts, activeMcpServers, remoteMcpServersConfig, kbToolReferences, initializationStatus, pendingUserMessageUuid, pendingUserMessageSentAt, pendingUserMessageHadResponse`

### 1.4 First user message buffered immediately

```
const o = r.replace(_M, ""),                      // "local_" prefix stripped
      c = ly(e.message, e.images),                // text + base64 images → content blocks
      l = { type:"user", uuid: e.messageUuid ?? ri.randomUUID(),
            session_id: o, parent_tool_use_id: null,
            message: { role:"user", content: c } };
u.messageBuffer.push(l); u.lastActivityAt = Date.now();
this.emit("event", {type:"message", sessionId:r, message:l});
this.auditLog(r, l);
this.emitInitializationStatus(r, "auth", "Authenticating...", false);
this.doSessionInitialization(r, e, a, i).catch(...)   // async, fire-and-forget
return r;                                            // IPC resolves immediately with sessionId
```

Note `session_id` in user messages = CLI session id (prefix-stripped id until the real CLI id arrives).

`ly()` (2810244): images → `{type:"image", source:{type:"base64", media_type, data}}` blocks; text appended as `{type:"text", text}` if non-empty.

---

## 2. Initialization sequence — `doSessionInitialization` (offset 2916475)

Telemetry: `lam_session_start_attempted {session_id, vm_instance_id:Ha(), is_resume, has_selected_folders, folder_count, mcp_server_count}`.

Step counter: `s` var starts `"auth"`, each timed step wraps `s=m` via closure `o(m)` that emits `lam_session_step_completed {step, duration_ms}` on completion. UI status via `emitInitializationStatus` (2906573 → `this.emit("event",{type:"initialization_status",...})`).

| # | status step emitted | message | timer name | work |
|---|---|---|---|---|
| 0 | `auth` | "Authenticating..." | `auth` | (already done in startSession) |
| 1 | `skills` | "Loading skills..." | `skills_sync` | parallel: `i4.syncSkills()` (skills plugin download), `Qg.syncPlugins()` (remote plugins, flag `2340532315`), `aXe(projectUuids...)` (project sync, only if projects selected) |
| 2 | `prompt` | "Preparing session..." | `prompt_build` | knowledge bases (feature flag `wZe("231807748")`): `e4().getKnowledgeBase()` + `listMcpResources()` per KB, mount names via `zQe` (slugify + dedupe); then `IXe({...})` system prompt builder |
| 3 | *(none)* | — | `mcp_setup` | `mcpCoordinator.createAllServers(...)` → all MCP servers; emit `local_mcp_servers` event |
| 4 | `query` | "Starting agent..." | `query_start` | `DL({prompt: inputStream, options})` — SDK query |
| 5 | `complete` | "" (isComplete: true) | — | emitted on **first streamed message** in `setupQueryHandlers` (2938064) |

### Auth step details

```
const y = Fme[Bme()];                       // production: {apiHost:"https://api.anthropic.com",
                                            //  clientId:"9d1c250a-e61b-44d9-88ed-5944d1962f5e",
                                            //  redirectUri:"https://console.anthropic.com/oauth/code/callback",
                                            //  scope:"user:inference", domain:".claude.ai"}
const _ = await qme(y);                     // oauth token
if (!_) throw "Unable to start session. You must be logged in to the desktop app."
```

`qme` (1924534): token cache key `"<clientId>:<orgId>"` from electron-store (`oauth:tokenCache`, `safeStorage`-encrypted) → cached → refresh via `POST {apiHost}/v1/oauth/token` (grant_type `refresh_token`, `hze` 1926007) → fresh PKCE exchange `mze` (1926513): reads `lastActiveOrg` + `sessionKey` cookies on the claude.ai domain, `POST {apiHost}/v1/oauth/<orgId>/authorize` with `Bearer sessionKey`, exchanges code. `B5()` (1925826) clears cache on 401.

### Skills / plugins step

- `i4.syncSkills()` (2891869): fetches `https://claude.ai/api/organizations/<org>/skills/list-skills?include_wiggle_skills=true`, downloads `.skill` files into `userData/local-agent-mode-sessions/skills-plugin/<orgId>/<accountUuid>/skills/` + `manifest.json` delta sync.
- `Qg.syncPlugins()`: remote plugins (flag `Jg("2340532315")`); `Ud.getEnabledLocalPlugins()` (flag `Jg("1697423394")`) — local CLI plugins, deduped against remote (`"exists in both remote and local. Using remote."`).

### Knowledge bases (flag `231807748`)

```
for kb of r.selectedKnowledgeBases:
  bt = await Y.getKnowledgeBase(kb)      // Y = e4() → knowledgeBaseManager
  → {id: kbId, name}
  Y.listMcpResources(kb) → Z.set(mcpServerId, kbName)   // KB resources needing MCP servers
mounts = zQe(kbs)                        // slugify(name), dedupe -2, -3…
V.push({kbId, name, mountName, description})
```

### System prompt build — `IXe` (2900655)

Takes `{vmProcessName, userSelectedFolders, baseSystemPrompt, model, accountName, emailAddress, localPlugins, mountedKnowledgeBases, projectContexts}`. Replaces in `baseSystemPrompt`:

- `{{currentDateTime}}` → "Thursday, August 6, 2026"-style
- `{{cwd}}` → `/sessions/<vmProcessName>`
- `{{workspaceFolder}}` → `/sessions/<vm>/mnt/<basename(folder)>` or `/sessions/<vm>/mnt/outputs`
- `{{userSelectedFolders}}` → `   - Folder: /sessions/<vm>/mnt/<basename>` or ""
- `{{skillsDir}}` → `/sessions/<vm>/mnt/.skills`
- `{{modelName}}`, `{{accountName}}`, `{{emailAddress}}`
- `{{workspaceContext}}` → access statement (folder selected or not)
- `{{folderSelected}}` → "yes"/"no"
- Appends: `<attached_projects>` block (`sXe` 2890195, mount paths `/sessions/<vm>/mnt/.projects/<uuid>`), `<knowledge_base>` blocks (`/sessions/<vm>/mnt/.knowledge/<mountName>/`), skills instructions via `i4.generateSkillsSystemPrompt` (2895754: manifest skills + `Qg.getPluginSkillsForSystemPrompt` + local CLI plugins)
- Rewrites the "start a new task and select a folder" line → "use the request_cowork_directory tool to ask for which directory to work in"

Logs `Using system prompt (N chars)`.

### VM startup (eager, before prompt)

`R = i6().catch(throw)` — `startVM` (2866479 → `FQe` 2863152):
1. **1/4 download bundle + SDK**: `Wye(e)` bundle download (`https://downloads.claude.ai/vms/linux/<pi>` → `rootfs.img` in `userData/vm_bundles/claudevm.bundle/`, sha verified via `.origin` marker, warm-bundle promotion) + `pl.prepareForVM()` (Claude Code 2.1.15 → `userData/claude-code-vm/<version>/claude`, linux-arm64, from `https://downloads.claude.ai/claude-code-releases/<version>/linux-arm64/claude`, checksum-verified, `.verified` marker).
2. **2/4 load Swift VM**: `await import("@ant/claude-swift")` → `addon.vm`.
3. **3/4 boot**: `l.startVM(bundlePath, memoryGB=4)` (`LQe=4`).
4. **4/4 wait guest**: poll `isGuestConnected()` every `DQe=500ms` up to `jie=60000ms`; on success `l.installSdk(vmStorageSubpath, version)`; on timeout → VPN/network diagnostics (`ifconfig` utun/tun interfaces, `scutil --nc list`, bootpd, vmnet kexts) → error "VM connection timeout after 60 seconds" or VPN message.
- Single-flight: `Cg` promise; app-quit handler `cowork-vm-shutdown` → `l.stopVM()`.

### MCP setup — `Pye.createAllServers` (2809072)

```
createAllServers(sessionId, {mcpServers, remoteMcpServers, enabledMcpTools,
                             filterFilesystemMcp: true, firstPartyConnectors, vmPathContext})
  a = localMcpManager.createProxyServers(mcpServers minus ant.dir.ant.anthropic.filesystem)
  s = proxyManager.createProxyServers(remoteMcpServers)          // cloud-proxied, timeout $ie=6e4
  o = internalManager.createProxyServers(enabledMcpTools, firstPartyConnectors, vmPathContext)
  return {...s, ...o, ...a}
```
Internal servers (`EJe` 2796437): `mcp-registry` (search_mcp_registry / suggest_connectors), first-party connectors gated by `firstPartyConnectors.enabled_*` (`$x`=GDrive/"bananagrams", `Cx`=GCal/"foccacia", `Tx`=Gmail/"sourdough"), tool-level filtering via `enabledMcpTools` keys `local:<server>:<tool>`.

### Query start (step 4)

See §4. Then final state write:

```
Ee.query=xe, Ee.inputStream=I, Ee.isRunning=true, Ee.cwd=B.cwd, Ee.sharedCwdPath=ne,
Ee.activeMcpServers=O, Ee.remoteMcpServersConfig=r.remoteMcpServers,
Ee.enabledMcpTools=r.enabledMcpTools, Ee.projectContexts=$,
Ee.initializationStatus={step:"query",...},
(!n) && (Ee.isFirstTurn=false, Ee.initialMessage=r.message, Ee.isArchived=false, Ee.error=void 0)
Ee.vmProcessId=we, Ee.mountedKnowledgeBases=ye, Ee.knowledgeBaseMountPaths=ue
this.saveSession(Ee)
```
KB watching: `Y.startWatching(kbId)` + `lam_kb_session_mounted` stats. First-turn message path rewriting + enqueue (see §7), `Ee.isInitializing=false`, `startFileWatching(...)` (§5), `saveSession` + `session_updated` event.

Error path: `lam_session_initialization_failed {failed_step: s, ...}` rethrow; caller marks `isRunning=false, isInitializing=false, error=d.message`, `saveSession`, `session_updated`.

---

## 3. Agent spawn — kernel launch

### 3.1 The SDK query call — `DL({prompt, options})` (1913181)

`DL` = bundled `@claude-agent-sdk` `query()`. It is called as `DL({prompt: I, options: B})` where `I = new OXe` (input stream) and `B` is the options object. The SDK builds a child-process launch (`FBe`) with the **custom spawn function** `B.spawnClaudeCodeProcess` — so "spawning" is a normal child_process-compatible contract (`{command, args, env, cwd}`) that is intercepted and routed into the Swift VM.

- `process.env.CLAUDE_AGENT_SDK_VERSION = "0.2.15"` (1913xxx)
- `pathToClaudeCodeExecutable: "/usr/local/bin/claude"` — the in-VM CLI path
- `executable: "node"`, entrypoint env `CLAUDE_CODE_ENTRYPOINT` (default `"sdk-ts"` unless overridden)
- String prompts are written as a user message; our prompt is the OXe stream → `U.streamInput(t)`.

### 3.2 Options object `B` (built at 2919568ff)

```
{
  cwd: `/sessions/<vmProcessName>`,
  model: r.model || "default",
  pathToClaudeCodeExecutable: "/usr/local/bin/claude",
  allowedTools: [ ... ],                    // see §4.1
  canUseTool: async (toolName, input, {suggestions}) => {...},   // see §4.3
  permissionMode: "default",
  settingSources: ["user"],
  includePartialMessages: true,
  hooks: { PreToolUse: [{matcher:"Task", hooks:[...]}] },          // see §4.4
  env: { ... },                              // see §3.3
  systemPrompt: X,
  mcpServers: O,                             // from createAllServers + O.cowork=Ur
  plugins: L,                                // skills + plugins as {type:"local", path}
  resume: q.cliSessionId,                    // only when resuming (isFirstTurn=false)
  additionalDirectories: [`/sessions/<vm>/mnt/<basename(folder)>`],
  spawnClaudeCodeProcess: spawnFn,           // Swift-VM spawn, see §3.4
}
```

### 3.3 Env vars (verbatim, built at 2919689ff)

```
env: {
  CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS: "true",
  CLAUDE_CONFIG_DIR: `/sessions/${i}/mnt/.claude`,          // i = vmProcessName
  ...Dye({ oauthToken: _, apiHost: y.apiHost }),            // spread FIRST, so the next
                                                            // two keys OVERRIDE its defaults
  CLAUDE_CODE_ENTRYPOINT: "local-agent",
  CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1",
  MCP_TOOL_TIMEOUT: String(SZe("1978029737","mcpToolTimeoutMs",SXe,wXe)),  // default 30000
}
```

`Dye` (2813554) contributes (then overridden where noted):
```
{ CLAUDE_CODE_ENTRYPOINT:"claude-desktop",          // ← overridden to "local-agent"
  ANTHROPIC_BASE_URL: apiHost,                      // "https://api.anthropic.com"
  ANTHROPIC_API_KEY: "",
  CLAUDE_CODE_OAUTH_TOKEN: t.oauthToken,            // desktop OAuth token injected
  DISABLE_AUTOUPDATER: "1",
  CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL: "true" }
```

### 3.4 Spawn interception — `TQe` (2856761)

`spawnFn(proc)` where proc = `{command, args, env, cwd}` (the SDK's child_process request):

```
id = uuid4; name = vmProcessName; Vye()          // init VM callbacks
proc = new _Qe(id, name); proc.setupStdinForwarding()
env filtered (drop undefined), then AQe(...):
  addon.vm.addApprovedOauthToken(CLAUDE_CODE_OAUTH_TOKEN)   // MITM proxy trust
  addon.vm.spawn(id, processName, command, args, env,
                 additionalMounts, isResume, allowedDomains, sharedCwdPath)
  proc.confirmSpawn()                            // flush buffered stdin
```

`_Qe` (2850654) is a fake child process: `stdin`/`stdout` PassThrough streams; `setupStdinForwarding` buffers stdin until `confirmSpawn`, then `vm.writeStdin(id, chunk)`; stdout arrives via `t.setEventCallbacks(stdoutCb, stdoutErrCb, exitCb, errorCb, networkCb)` (2853118); guest disconnect → SIGKILL all active processes (graceful quit → exit 0); `kill(signal)` → `vm.kill(id, signal)`; `Die(id)` (2850637) looks up the proc to SIGTERM it. Registry `fc`; telemetry `lam_vm_process_exited` / `lam_vm_process_spawned`.

`vmProcessId` capture: the spawn wrapper (2916200ff) sets `we = Vt.id` and `jr.vmProcessId = Vt.id` when the SDK returns a ChildProcess-like with `"id" in Vt`; `proc.on("error")` marks session failed.

### 3.5 VM mounts (additionalMounts, built 2923335ff) — host → `/sessions/<name>/mnt/...`

| VM path | Host source | Mode |
|---|---|---|
| `mnt/<basename(folder)>` | first user-selected folder (`me.relative(home, folder)`) | `rw` (or `rwd` if `fileDeleteApprovedMounts` contains its basename) |
| `mnt/outputs` | `<home>/<sharedCwdPath>/outputs` (shared cwd = `Documents/Claude`, created if missing) or `<sessionStorageDir>/outputs` | `rw`/`rwd` |
| `mnt/.claude` | `<sessionStorageDir>/.claude` (getClaudeConfigDir 2908364) | `rwd` |
| `mnt/.skills` | skills plugin dir (`userData/local-agent-mode-sessions/skills-plugin/<org>/<acct>`) | `ro` |
| `mnt/.plugins` | remote plugins dir (`Qg.getPluginsPath()`) | `ro` |
| `mnt/.local-plugins` | local plugins cache (`Ud.getPluginsCachePath()`) | `ro` |
| `mnt/uploads` | `<sessionStorageDir>/uploads` | `ro` |
| `mnt/.knowledge/<mountName>` | KB dir (per KB, `generateMetadataFiles` first) | `rw` |
| `mnt/.projects/<uuid>` | `<sessionStorageDir>/.projects/<uuid>` | `ro` |

`sharedCwdPath` (feature `r.sharedCwdPath !== undefined`): host path relative to home of `~/Documents/Claude` (mkdir recursive); becomes `cwd`-adjacent shared dir AND the outputs parent.

### 3.6 Prompt / input plumbing

- `I = new OXe` (2903716): `enqueue(msg)` / `done()` / `[Symbol.asyncIterator]()` — a hand-rolled async-iterable queue. This is the **inputStream**.
- `xe = DL({prompt: I, options: B})` — the **query** (async iterable of SDK stream events + `setMcpServers`, `interrupt()`, `return()` methods).
- First user message: `I.enqueue(tt)` where `tt` has `session_id = e.replace("local_","")` — the CLI learns its session id from the user message envelope. CLI session id maps back via the `init` stream event (§7).

---

## 4. Tool loop

### 4.1 Allowed tools (verbatim, 2919857)

```
allowedTools: ["Task","Bash","Glob","Grep","Read","Edit","Write","NotebookEdit",
  "WebFetch","TodoWrite","WebSearch","Skill",
  "mcp__mcp-registry__search_mcp_registry","mcp__mcp-registry__suggest_connectors",
  "mcp__cowork__create_knowledge_base"]
```
(plus whatever `mcpServers: O` adds — all local MCP tools, connector tools, and the cowork server's tools are namespaced `mcp__<server>__<tool>` by the SDK. Note `create_knowledge_base` is listed but the cowork server only ships 2 tools — a stale allowlist entry.)

### 4.2 cowork MCP server — `GQe` (2872011)

`O.cowork = Ur` where Ur = `GQe({sessionId, getVmProcessId, vmProcessName, addUserSelectedFolder, getUserSelectedFolders, getOutputsSubpath, setFileDeleteApprovedForMount, isFileDeleteApprovedForMount, addMountedKnowledgeBase, getKnowledgeBaseMountNames})`. Registered as SDK-integrated server `rx({name:"cowork", version:"1.0.0", tools:[...]})` (in-process, no stdio).

Tools:
1. **`request_cowork_directory`** — `dialog.showOpenDialog` (openDirectory|createDirectory, defaultPath home); must be inside home (`Qye` realpath containment); `vm.mountPath(procId, relPath, basename, "rw")`; `addUserSelectedFolder`; returns `/sessions/<vm>/mnt/<basename>`.
2. **`allow_cowork_file_delete`** — input `{file_path}` (VM path); resolves mount via `e0e` (2871685: basename match against user folders or "outputs"); `vm.mountPath(procId, subpath, name, "rwd")` (remount read-write-delete); persists `fileDeleteApprovedMounts` (session save). Description: "call this tool whenever a delete operation (such as rm) fails with 'Operation not permitted'".

### 4.3 Permission interception — `canUseTool` (2919885ff)

```
canUseTool: async (ke, Ue, {suggestions: Qe}) => {
  let ot = Ue;
  if (ke === "mcp__cowork__allow_cowork_file_delete") {
    const bt = this.sessions.get(e), Lt = Ue.file_path;
    let Pt = "workspace";
    if (Lt && bt?.vmProcessName) {
      const ir = me.relative(homedir, this.getOutputsDir(e, bt.sharedCwdPath));
      const Mr = e0e(Lt, bt.vmProcessName, bt.userSelectedFolders ?? [], ir);
      Mr && (Pt = Mr.name);
    }
    ot = { ...Ue, _folderName: Pt };        // annotate → UI shows which folder
  }
  return this.handleToolPermission(e, ke, ot, Qe)
}
```
`handleToolPermission` (2912546): uuid requestId → `pendingPermissions.set(id, {sessionId, toolName, input, suggestions, resolve})` → emit `{type:"tool_permission_request", sessionId, request}` → **await promise** (UI responds via `respondToToolPermission` 2913094). Audit-logged (`permission_request` / `permission_response`).

Decisions: `deny` → `{behavior:"deny", message:"User rejected <friendly> <input>. Please acknowledge…", interrupt:false}`; `once` → `{behavior:"allow", updatedInput}`; `always` → `{behavior:"allow", updatedInput, updatedPermissions: suggestions}`. `AskUserQuestion` allow + `_toolUseBlockId` → answers stored in `mcqAnswers`. Friendly verbs `EXe` (2897xxx): Bash→"running", Read→"reading", Write→"writing to", Edit→"editing", Glob/Grep→"searching", Task→"running task".

### 4.4 Hooks (2919925ff)

```
hooks: { PreToolUse: [{ matcher: "Task", hooks: [async ke => {
  if (ke.hook_event_name === "PreToolUse") {
    const Ue = ke.tool_input;
    if (Ue?.run_in_background) return { decision:"block", reason:"Background agents disabled" };
  }
  return {};
}]}]}
```
→ **background sub-agents are blocked** (matches `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`).

### 4.5 Permission modes

`permissionMode:"default"` + `settingSources:["user"]` — normal approval flow (no bypass). The UI's Manual/Auto/Skip modes live in the renderer; Auto-mode safety checks run renderer-side; `deny`/`once`/`always` decisions flow back through `respondToToolPermission`.

### 4.6 Tool-call bookkeeping

`setupQueryHandlers` (2938064): assistant `tool_use` blocks matching VM paths (`CXe`/`$Xe`) increment `kbToolReferences[toolName]` (KB usage stats for `local_kb_session_stats`). MCP updates mid-session: `setMcpServers` (2944978) → `query.setMcpServers(newMap)` + `enabledMcpTools` tool-key map persisted.

---

## 5. File watching

`startFileWatching(sessionId, firstUserFolder ?? null, sharedCwdPath)` (2928393):
- Target dir = **first user-selected folder**, else `getOutputsDir(sessionId, sharedCwdPath)` (host: `<home>/<sharedCwd>/outputs` or `<sessionStorageDir>/outputs`, mkdir recursive).
- `fileWatcher` = `ZQe` (2875414): `fs.watch(dir, {recursive:false})`; initial scan of top-level files → `knownFiles` Set; on fs event → `existsSync`+`statSync().isFile()`: new file → emit `fs_file_created {sessionId, hostPath, fileName, timestamp}`; gone → `fs_file_deleted`. Dotfiles skipped.
- Manager handler (constructor, 2904433): updates `session.fsDetectedFiles` Map + `saveSession`, re-emits `{type:"fs_file_created|deleted", sessionId, fsFile:{...}}`.
- **Watcher lifecycle**: started once after query enqueue (end of `doSessionInitialization`); stopped on `result` message, on `stopSession`, never restarted for later user folders (only the first folder/outputs).

---

## 6. Message flow

### 6.1 User message → agent

`sendMessage(sessionId, message, images, userSelectedFiles, messageUuid)` (2928743):
1. No session → throw; `isInitializing` → throw "Session is still initializing…".
2. **Cold path** (no `query || inputStream || cliSessionId`): `d = await ql()` (2636659: local-plugin MCP configs + stored MCP servers `Qge` + settings `mcpServers`) → restart via `startSession({message, sessionId, model, images, userSelectedFiles, messageUuid, mcpServers:d, remoteMcpServers: s.remoteMcpServersConfig, enabledMcpTools, systemPrompt, accountName, emailAddress})` → returns.
3. **Hot path**: 
   - `userSelectedFiles` → `Xie(files, sessionStorageDir, vmProcessName)` (2903212): uploads dir `<sessionStorageDir>/uploads`; each file validated (`kXe` 2903050: realpath inside home, regular file); dedupe names via `RXe` (md5-8 of path); files from `userData/pending-uploads` are **renamed** in, others **hard-linked** (`fs.link`, EEXIST tolerated); mapping `{hostPath, vmPath: /sessions/<vm>/mnt/uploads/<name>}`.
   - `u = u.replaceAll(hostPath, vmPath)` for every mapping — **host→VM path rewrite in the message text**.
   - `r = Qie(message, userSelectedFolders, vmProcessName)` (2898402): `@<absolute-folder-path>` mentions → `/sessions/<vm>/mnt/<basename>` (regex-escaped).
   - `ly(u, images)` → content blocks; envelope `{type:"user", uuid, session_id: cliSessionId, parent_tool_use_id:null, message:{role:"user", content}}`.
   - `messageBuffer.push`, `lastActivityAt=now`, `pendingUserMessageUuid=uuid`, `pendingUserMessageSentAt=now`, `pendingUserMessageHadResponse=false`; emit `message` event + audit log; **`inputStream.enqueue(p)`**.

### 6.2 Stream consumption — `setupQueryHandlers` (2938064)

`for await (const o of query)`: 
- First event → `emitInitializationStatus(sessionId, "complete", "", true)`.
- `translateMessagePaths` (2909169 → `t4` 2870651/`WQe` 2870869): **VM→host rewrite** of any `computer://` URLs and bare `/sessions/<vm>/mnt/…` paths in text (`$g` 2869xxx: outputs→`<home>/<sharedCwd>/outputs|storage/outputs`, uploads→storage/uploads, folder basename→folder, `.knowledge/<mount>`→KB path, else shared cwd; slug safety `KQe` rejects `.`/`..`).
- **`init` system message** (`subtype === "init"`): `cliSessionId = u.session_id` (maps UI session → CLI session), save; `slash_commands` → `session.slashCommands` (surface via `getSupportedCommands` 2946322); telemetry `desktop_local_agent_mode_session_initialized`.
- Assistant text: `getRecoverableErrorMessage` (2936695) maps API Error → friendly (image-too-large w/ size, PDF page limit, password-protected, prompt-too-long, 403/5xx); on recovery: rewrite content, `repairTranscript` (stub, returns false) → "Repair failed, clearing CLI session ID to start fresh": `cliSessionId=undefined, query=null, inputStream=null, isRunning=false, messageBuffer=[]`, save. Auth errors → `B5()` (clear oauth cache).
- Every message: `messageBuffer.push`, `lastActivityAt=now`; assistant + pending → `pendingUserMessageHadResponse=true`; emit `message`; non-stream events audit-logged (`c.type!=="stream_event"`).
- **`result` message** = turn end: telemetry `lam_session_turn_completed`, cycle-health `lam_message_cycle_outcome {cycle_health:"healthy", had_first_response, seconds_to_outcome}`, clear pending fields, `stopFileWatching`, emit `queryCompleted`, **`Die(vmProcessId)?.kill("SIGTERM")`** (VM process for this session is killed after every completed turn!).
- Iterator end: `query=null, inputStream=null, isRunning=false, saveSession`.
- Errors: `lam_session_query_error {error_category (AXe 2898556: sandbox_deps_missing, cli_stdout_pollution, vm_disconnected, filesystem_error, library_error, bridge_socket_error, network_error, json_parse_error, process_crashed, auth_error, unknown), is_startup_error: messageBuffer.length===0, is_resume}`, `lam_message_cycle_outcome` unhealthy, emit `{type:"error"}`, then `{type:"close", code:1}` (unless user-stopped → healthy outcome, no close). Reset query/inputStream/isRunning/isStopping + save.
- `sendMessage` while a turn is in flight simply enqueues (turn lifecycle is per `result`).

### 6.3 Images

`images` param shape `{mimeType, base64}[]` (validator `t1`); encoded as base64 content blocks (`ly` 2810244); same shape on both start and sendMessage paths.

### 6.4 isFirstTurn semantics

`isFirstTurn = !e.sessionId` (start-time). New sessions: initial message enqueued with prefix-stripped session_id; `initialMessage` recorded. On `result`/first query end: `isFirstTurn=false` persisted. Resume: skip skills/plugins sync for first turn only if `n` (isFirstTurn) — i.e. `n ? i4.syncSkills()… : Promise.resolve()`. Project sync: first turn → full API sync (`iXe` 2888xxx: GET `claude.ai/api/organizations/<org>/projects/<uuid>` + docs + files, concurrency 6); resume → restore from local `metadata.json` only.

---

## 7. Persistence

### 7.1 Storage layout

```
<userData>/local-agent-mode-sessions/            (_Xe, baseDir, 2897251)
  <accountUuid>/                                  (from $f() bootstrap: claude.ai/api/bootstrap)
    <orgId>/                                      (lastActiveOrg cookie; validated UUID rze)
      <sessionId>.json                            (per-session state, saveSession 2911427)
      <sessionId>/outputs/                        (getOutputsDir fallback, 2907964)
      <sessionId>/.claude/                        (CLAUDE_CONFIG_DIR host side, getClaudeConfigDir 2908364)
      <sessionId>/.claude/projects/<proj>/*.jsonl (CLI transcripts, read by getTranscript 2935856)
      <sessionId>/uploads/                        (user file uploads, hardlinks)
      <sessionId>/.projects/<uuid>/               (project sync: docs/, files/, metadata.json)
      <sessionId>/audit.jsonl                     (audit log, 50 MB max, qQe 2868583)
```
Legacy: `userData/local-sessions.json` array migrated to per-session files (`migrateLegacySessions` 2909337) then deleted.

### 7.2 saveSession (2911427)

Persisted fields: `sessionId, processName, cliSessionId, cwd, userSelectedFolders, createdAt, lastActivityAt, model, isArchived, title, userApprovedFileAccessPaths, vmProcessName, sharedCwdPath, error, initialMessage, slashCommands, mcqAnswers, enabledMcpTools, firstPartyConnectors, fsDetectedFiles (array, only if non-empty), fileDeleteApprovedMounts, mountedKnowledgeBases, systemPrompt, accountName, emailAddress`. `JSON.stringify(n, null, 2)`, writeFileSync. **The transcript itself is NOT in this file** — it lives in the CLI's `.claude/projects/` jsonl.

Load (`loadSessions` 2909915): rebuilds in-memory records with `query:null, inputStream:null, isRunning:false, isFirstTurn:false, messageBuffer:[]`; deleted folders filtered out.

### 7.3 session_updated events

Emitted (via `this.emit("event", {type:"session_updated", sessionId})`) on: init failure (2916441), post-init completion (2925188), spawn error (2925188 region), `addUserSelectedFolder` (2935xxx), `updateSession` (title). `getSession`/`getAll` return project shape: `{sessionId, cwd, userSelectedFolders, isRunning, createdAt, lastActivityAt, model, title, homePath, folderExists, pendingToolPermissions, error, initialMessage, mcqAnswers, enabledMcpTools, initializationStatus, fsDetectedFiles, userSelectedProjectUuids, mountedProjects, localMcpServers}` (+`isArchived` in getAll). getSession replays `bufferedMessages` via dispatcher unless `skipReplay`.

### 7.4 Archive semantics — `archiveSession` (2931553)

`stopSession(e, true)` → rm `<storageDir>/<id>/uploads` recursive → close+drop audit logger → `isArchived=true` → `saveSession` (record retained, marked archived) → emit `{type:"archived"}`; telemetry `lam_session_archived`. **No transcript/files deletion.**

### 7.5 shareSession (2943219)

Zips `{<cliSessionId>.jsonl, <cliSessionId>/…, metadata.json}` (`u0e` recursive dir walk, 2904399) with `Y5` (archiver, level 6) → `~/Downloads/transcript-<ts>.zip`.

### 7.6 Outputs dir — `getOutputsDir` (2907964)

`sharedCwdPath` present → `<home>/<sharedCwdPath>/outputs` (mkdir); else `<sessionStorageDir>/outputs`. `openOutputsDir` IPC → `shell.openPath`. Outputs mounted rw (rwd after delete approval).

---

## 8. Teardown

### 8.1 stopSession (2930192) — `stop` IPC

```
1. stopFileWatching
2. mounted KBs: stopWatching each, aggregate lam_local_kb_session_stats {file changes, counts}
3. isStopping = true
4. query.interrupt()          (catch)
5. inputStream.done()         (ends the async iterator)
6. vmProcessId → Die(id).kill("SIGTERM"); vmProcessId = undefined
7. query.return() (cleanup); query=null, inputStream=null, isRunning=false
8. emit {type:"close", code:0}
9. telemetry lam_session_stopped {total_turns (user msgs), session_duration_ms}
```
Session record + JSON **remain** (resumable). VM process for the session is SIGTERMed; the Swift VM itself stays booted (shared across sessions, `startVM` single-flight).

### 8.2 Natural end (result message)

Same cleanup minus explicit stop: stopFileWatching, `queryCompleted` event, SIGTERM the session's VM process, keep record. `query`/`inputStream` nulled when iterator completes (session becomes cold; next `sendMessage` re-initializes via `startSession` cold path).

### 8.3 App quit

- `registerAppQuitHandler` (2906097): `lam_session_app_quit` per running session.
- `cowork-vm-shutdown` (2863xxx): `vm.stopVM()` + `yQe()` resets instance id; guest disconnect during graceful quit → clean exit 0 for active processes (vs SIGKILL on unexpected disconnect).
- `startTimeoutDetection` (2905428): every 60 s, running session with `now-lastActivityAt > 300000` (5 min) and no pending permission → `timedOutSessions.add`, `lam_session_timeout`, warn. (Telemetry only — no auto-stop.)
- `setupOrgChangeListener` (2906785): `lastActiveOrg` cookie change → `initializeWithAccount` → **clears all sessions** for the new org.

### 8.4 What persists vs not

Persists: session JSON (full state), transcripts (`.claude/projects/*.jsonl`), uploads (until archive), outputs, projects, audit logs, VM bundle + Claude Code SDK (host cache), skills plugin dir. Does not persist: VM process (SIGTERM per session; VM shutdown on quit), file watcher, `pendingPermissions`, in-memory `messageBuffer` (replayed from CLI jsonl only in UI, and only buffered messages), query/inputStream handles.

---

## 9. Data-flow (creation order, end-to-end)

1. Renderer `start(info)` → IPC `LocalAgentModeSessions.start` → `Wat.start` → `startSession`.
2. `local_<uuid>` id; unique `vmProcessName`; in-memory record; **session JSON written** (empty-ish state).
3. First user message buffered + emitted + audit-logged; `initializationStatus=auth`.
4. Async init: oauth token (cache→refresh→PKCE) → skills/plugins sync + project sync (parallel) → KB resolution → system prompt build → **VM boot** (`downloads.claude.ai` bundle + Claude Code 2.1.15, Swift VM, guest wait 60 s, SDK install in guest) → MCP servers (local/remote/internal + cowork) → SDK `query()` with env/mounts/plugins/tools/hooks → **inputStream enqueued with rewritten message** → file watcher started → `session_updated`.
5. CLI reports `init` → `cliSessionId` + slash commands persisted; tool loop runs (canUseTool → permission IPC → respond → SDK allow/deny/updatePermissions; Task background blocked by hook).
6. Turn end `result` → watcher stop, VM process SIGTERM, cycle-health telemetry; session stays warm (query/inputStream kept).
7. Stop/archive/quit per §8.

---

## 10. Gaps / uncertain

- **`mcp__cowork__create_knowledge_base`** in allowedTools has no matching tool in the cowork server (only 2 tools defined) — likely stale or conditionally added elsewhere (not found).
- **SDK internals** (`UBe` stream wrapper, permission `suggestions` construction, `init` payload format beyond `session_id`/`slash_commands`) are in the bundled SDK at 1913xxx–1940xxx — not fully traced; `repairTranscript` is a stub returning `false`.
- **`isInitializing` during resume**: `sendMessage` → `startSession` resume path is guarded by `isInitializing` (duplicate-start warn) but `updateSession`/`setMcpServers` during init are unguarded (setMcpServers throws if no active query).
- **VM-side detail**: what `vm.spawn` does with `allowedDomains` (egress allowlist) and `sharedCwdPath`; `@ant/claude-swift` native API (spawn/installSdk/mountPath/kill/stopVM/writeStdin) is a closed binary — behaviors inferred from the JS call sites only.
- **pending-uploads** (`userData/pending-uploads`, `t0e` 2877349) producer not located (file drag-in path elsewhere in bundle).
- **Where Auto mode / safety review runs**: renderer-side (`sessionBypassPermissionsMode` seen in SDK state at 1684380 region) — exact gating not in this class.
- MCP server key strategy `t6` (local/first-party → name, remote → uuid) and `setMcpServers` delta behavior partially traced (2944978).
- Warm-bundle promotion (`mbe` module, `claudevm.bundle` warm download) details traced only partially (3273xxx–3277xxx).
