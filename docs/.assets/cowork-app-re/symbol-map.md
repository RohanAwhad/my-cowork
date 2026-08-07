# Symbol Map — Claude Cowork (Local Agent Mode + Cowork VM)

**Target:** Claude Desktop 1.1.673 "custom lifetime build" (`commitHash 5a47b098`, `commitTimestamp 2026-01-22T18:12:14.000Z`, offset 369631)
**Source:** `/tmp/claude-asar/app/.vite/build/index.js` (3,288,493 chars, single-line minified, esbuild + module federation)
**Byte offsets cited throughout; all verified by python byte-offset search.**

Architecture in one paragraph: The desktop app runs a **Linux VM** (via the native addon `@ant/claude-swift`, codename `SwiftVM` / `CoworkVM`) and spawns **Claude Code CLI** (`claude`, v2.1.15 SDK, `CLAUDE_CODE_ENTRYPOINT=local-agent`) *inside* the VM per session. The renderer UI is served from the `claude.web` origin (all IPC channel names start `$eipc_message$959eec20-23e8-42d3-9584-6db3cb766339_$_claude.web_$_<Interface>_$_<method>`). `LocalAgentModeSessionManager` (`f0e`) is the orchestrator: auth → skills/plugins sync → prompt build → MCP server creation → VM process spawn (`CoworkVMProcess`) → SDK query (`DL`) → message/transcript plumbing → file watcher → telemetry (`lam_*`).

---

## 1. Module Regions Table

| # | Module | Region (byte offsets in index.js) | What it does | Key symbols |
|---|--------|-----------------------------------|--------------|-------------|
| 1 | **IPC registry layer** (all `claude.web` interfaces) | 117883–160500 | eipc bridge: `setImplementation` wraps each method with origin validation (`Fe`) + arg/result validators. Contains all renderer-facing interfaces. | `g1e`(WindowControl @117883), `WS`(QuickEntry @119865), `nC`(LocalSessions @120822), `ry`(LocalAgentModeSessions @142229), `y1e`(AgentModeFeedback @159386), `E9/S9/w9/b9/M9/x9` WeakMap dispatchers |
| 2 | **ClaudeVM IPC interface** (`y0`) | 176234–180600 | Renderer-facing VM control channel. Methods: `download, getDownloadStatus, getRunningStatus, setYukonSilverConfig, startVM, deleteAndReinstall`. Events: `downloadProgress`, `downloadStatusChanged`, `runningStatusChanged`, `startupError`. | `M9` (WeakMap), dispatchers at 179722–180400; main-side impl = `Zat` (row 22) |
| 3 | **FileSystem IPC interface** | 164500–169000 | Host-file access for attached files. Methods: `browseFolder, getSystemPath, listFilesInFolder, openLocalFile, readLocalFile, whichApplication`. | backed by local-file-access gate (row 23) |
| 4 | **ClaudeCodeManager** (`oze`) | 1917378–1923300 | Downloads/verifies Claude Code SDK for **host** (storageDir `userData/claude-code`) and **VM** (vmStorageDir `userData/claude-code-vm`, target `linux-arm64`, binary `claude`, `.verified` marker). | `pl` singleton @1923173, `WCe` manifest (v2.1.15) @369631, `getVMStorageSubpath`, `getRequiredVersion`, `getVMBinaryPathIfReady`, `prepareForVM` |
| 5 | **OAuth token machinery** | 1923173–1924900 | Desktop OAuth client config + encrypted token cache. | `Fme` (production/staging config, clientId `9d1c250a-e61b-44d9-88ed-5944d1962f5e`), `Bme()=>"production"`, `qme` (load token for active org), `dze` (cacheKey=`clientId:orgId`), `jme="oauth:tokenCache"`, `pze` decrypt via `safeStorage` |
| 6 | **Telemetry emitter** `gr` | 2361095 | `async function gr(t,e)` → HTTP POSTs event to backend (EventLogging), catches + logs errors. Emits all `lam_*`/`local_*`/`desktop_*` events. | `gr`, `V7e` (POST), `U7e` (metadata), `Zn`/`$f` (org/account) |
| 7 | **Plugin content readers** (skills/commands/hooks/agents/mcp from plugin dirs) | 2618984–2622001 | Parse `.claude-plugin` layouts: markdown frontmatter, `.mcp.json` per mcp_server dir. | `lye`(skills) @2621572, `PZe`(commands) @2619936, `RZe`(hooks) @2620298, `$Ze`(agents) @2618984, `wne`(mcp_servers) @2620767, `TZe`/`OZe`/`AZe`/`NZe` (md parsers), `a_`/`s_`/`zB`/`VB`/`i_` (plugin-fs helpers) |
| 8 | **SettingsReader** (`cowork_settings.json`) | 2622001–2622600 | Reads `~/.claude/cowork_settings.json`; extracts `enabledPlugins` map. | `bN="[SettingsReader]"`, `MZe` (path), `DZe` (parse+debug log), `LZe` (enabledPlugins) |
| 9 | **LocalPluginsReader** (`BZe` → `Ud`) | 2622554–2626100 | Reads `~/.claude/cowork_plugins/installed_plugins.json`, filters enabled + scope (user/project/local), validates path inside plugins dir, translates VM→host paths, builds VM-side sdk paths. | `zi="[LocalPluginsReader]"`, `cy` (plugins dir), `wN` (installed_plugins.json), `FZe` (cache dir), `Sne="mnt/.claude/cowork_plugins/"`, `Ud` singleton @2625967; methods: `getAllLocalPlugins`, `getEnabledLocalPlugins`, `getLocalPluginPaths`, `getLocalPluginMcpServerConfigs`, `getLocalPluginSkills/Commands/Hooks/AgentsForDisplay`, `entryToPluginInfo`, `translateVMPathToHost`, `isValidPluginPath` |
| 10 | **PluginManager** (`XZe` → `Qg`) | 2631884–2636700 | Syncs org plugins from `Br()/api/organizations/<org>/plugins/<id>/download`; caches under `userData/local-agent-mode-sessions/plugins`. | `Qg` @2636648, `ql` (merge mcp configs: local plugin servers + remote `Qge` + prefs `qn`) @2636648, `Dw="manifest.json"`, `Hi="[PluginManager]"` |
| 11 | **Internal MCP manager** (`EJe`) | 2796437 | Built-in internal servers (`wJe` registry, e.g. serverName `Tx`; gmail stub `gmail_search` @2792142) proxied into SDK. | `EJe.createProxyServers`, `SJe`, `M0()` (registered names), `uJe`/`vJe` tool handlers |
| 12 | **Local MCP manager** (`e6`) | 2803595 | `local-mcp-server-cleanup` shutdown hook + per-server `Connection` class (request/notification via MessagePort; tools/list caching). | `e6.getSharedInstance`, `createProxyServers`, `getOrCreateConnection`, `getConnectedServersInfo`, `closeAll` |
| 13 | **Remote proxy MCP manager** (`PJe`) | 2806391 | Proxies remote-connector tools into SDK-local servers. | `PJe.createProxyServers`, `proxyToolCall`, `$ie=60000` timeout |
| 14 | **MCP coordinator** (`Pye`) | 2809078–2810200 | Session-level facade: creates all servers, filters filesystem MCP (`IJe="ant.dir.ant.anthropic.filesystem"`), dedupes. | `Pye.createAllServers` @2809201, `createMcpServer` @2810023, `getLocalMcpServersInfo`, `closeAll`, `t6` (server key: name or uuid) |
| 15 | **Session env builder** | 2813554–2813700 | Builds child-process env for Claude Code. | `Dye` (env factory: `CLAUDE_CODE_ENTRYPOINT=claude-desktop`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY=""`, `CLAUDE_CODE_OAUTH_TOKEN`, `DISABLE_AUTOUPDATER=1`, `CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL=true`), `zJe` (merge + PATH via `UJe`) |
| 16 | **VM logging + SwiftVM loader** | 2849096–2850300 | Winston logger `De` → `cowork_vm_node.log` (10MB rotate, logs dir) + console when `CLAUDE_ENABLE_LOGGING` or unpackaged; level from `COWORK_VM_DEBUG`. Loads addon `@ant/claude-swift`. | `De` (info/warn/error/debug/verbose), `hQe`, `jye`, `vQe`, `qye`, `Uye` (load), `_i()` (addon.vm), `_i.getCached`, `gQe`, `bS`/`Ha()` (per-process VM instance UUID), `yQe` (reset) |
| 17 | **CoworkVMProcess** | 2851200–2852700 | EventEmitter wrapping one VM guest process (Claude Code inside VM). Buffers stdout, tracks exit/kill, forwards stdin, spawn-confirmation handshake. | `pushStdout`, `setExited` (gr `lam_vm_process_exited`), `setError` (`lam_vm_runtime_error`), `kill`, `setupStdinForwarding`, `confirmSpawn`, `_spawnConfirmed`; id, `_stdin/_stdout/_startTime/_killed/_exitCode` |
| 18 | **Network diagnostics** | 2855738–2856500 | On guest-connect timeout: probe VPN (interfaces `wQe`, connected VPNs `SQe`) + connectivity `EQe`; produce user error. | `xQe`, `CQe` (VPN error string), `$Qe` (VPN warn string) |
| 19 | **VM spawn factory** | 2857100–2858600 | `TQe(e, ...)` returns a spawn function per session; `AQe` does the actual `vm.spawn(instanceId, processName, cmd, args, cwd, env, mounts, isResume, allowedDomains, sharedCwdPath)` + OAuth MITM approval (`addApprovedOauthToken`). | `TQe`, `AQe`, `l_()` (isGuestConnected), `PQe` module `{createVMSpawnFunction, isVMGuestConnected}` |
| 20 | **VM bundle manager** | 2858710–2860400 | Bundle state machine: download (`MQe`), status (`al` enum), paths, delete. | `RQe="vm_bundles"` (userData), `kQe="claudevm.bundle"`, `Gye`/`u_`/`Zye` (path helpers), `OQe`/`JL`/`jw`/`zye` (dispatch to renderer), `qE` (downloaded), `Yye` (downloading), `Jye` (delete), `Hye=["rootfs.img"]`, `Kye` (per-file status), `MQe` (download impl), `Bie="https://downloads.claude.ai/vms/linux/<ver>"` @2859801 |
| 21 | **VM startup** | 2862434–2866600 | `Wye`=download bundle (idempotent promise); `FQe`=4-step startup: (1) bundle+SDK download, (2) load Swift API, (3) `startVM(bundlePath, memoryGB=4)` + app-quit shutdown hook `cowork-vm-shutdown`, (4) poll guest connect (60000ms timeout @`jie`, 500ms poll @`DQe`), then `installSdk(vmStorageSubpath, version)`; `i6`=public startVM wrapper. | `FQe`, `i6` @2866485, `Wye` @2862434, `jie=6e4`, `DQe=500`, `LQe=4` (default GB), `qie` (hook once), `zye` (startupError dispatch), `QL` (online), `xQe` |
| 22 | **Process name + path utils** | 2868041–2869900 | `jQe`: unique VM process name from word lists (`dd` adjectives/adverbs, `Uie` nouns, max 32 chars). `XL`: path-containment test. `qQe`: per-session audit logger (`audit.jsonl` in session dir). | `dd`, `Uie`, `BQe=32`, `jQe`, `XL`, `Qye` (async realpath containment), `qQe` |
| 23 | **KB manager accessor** | 2869134–2869610 | Lazy-loaded Knowledge Base module. | `Xye` (dynamic import), `e4()`→`knowledgeBaseManager`, `UQe()`→`createLocalKBsApi`, `VQe` module |
| 24 | **VM↔host path translation** | 2869610–2871700 | `Vie`: slugify mount name (≤60 chars); `zQe`: dedupe KB mount names; `$g`: translate `/sessions/<vm>/mnt/<x>` → host paths (outputs/uploads/user folders/.knowledge); `t4`: deep-recursive translate (strings/arrays/objects). | `Vie`, `zQe`, `HQe`/`KQe` (path-segment guards), `$g` @2869949, `t4` @2870452, `zie` (encodeURIComponent join) |
| 25 | **CoworkDirectoryTool** (`GQe`) | 2871685–2875400 | Two SDK tools served in-VM: `request_cowork_directory` (native dialog via `oe.dialog` → `vm.mountPath(session, hostRel, name, "rw")`, adds folder to session, `getOutputsSubpath`) and `allow_cowork_file_delete` (re-mount `"rwd"` + `setFileDeleteApprovedForMount`). Packaged as MCP server via `rx({name:"cowork",version:"1.0.0",...})`. | `e0e` (VM path→`{name,subpath}`) @2871685, `GQe`, `Qy` (tool defs), `rx` (server builder) |
| 26 | **FileSystemWatcher** (`ZQe`) | 2875400–2877350 | Per-session `fs.watch` (non-recursive) on workspace dir; emits `fsEvent` (`fs_file_created` / `fs_file_deleted`). | `ZQe`, `startWatching`, `stopWatching`, `isWatching`, `getKnownFiles`, `dispose`; `t0e()` = `userData/pending-uploads` @2877349 |
| 27 | **ProjectSync** | 2888600–2890700 | `iXe`: sync one project (docs+files into session `.projects/<uuid>`, writes `metadata.json`); `aXe`: batch sync (first turn) or restore (resume); `sXe`: `<attached_projects>` prompt block. | `iXe`, `aXe`, `sXe` @2890195, `gM` (XML-escape), `lam_project_sync_failed` |
| 28 | **Skills plugin manager** (`yXe` → `i4`) | 2891869–2897304 | Syncs built-in skills plugin from `Br()/api/organizations/<org>/skills/download-dot-skill-file` to `userData/local-agent-mode-sessions/skills-plugin`; produces `<skills_instructions>` prompt + `<available_skills>` list. | `i4` singleton, `syncSkills`, `getPluginPath`, `pXe="local-agent-mode-sessions"`, `hXe="skills-plugin"`, `qw="skills"`, `Zie="manifest.json"`, `mXe=".claude-plugin"`, `vXe="plugin.json"`; template consts + `_M="local_"`, `Yie="local_session_new"`, `_Xe="local-agent-mode-sessions"`, `bXe="local-sessions.json"`, `wXe` (schema), `SXe=30000` @2897268 |
| 29 | **System prompt builder** (`IXe`) | 2900691–2902500 | Fills `{{currentDateTime}}`, `{{cwd}}`, `{{workspaceFolder}}`, `{{userSelectedFolders}}`, `{{skillsDir}}`, `{{modelName}}`, `{{accountName}}`, `{{emailAddress}}`; appends knowledge-base XML (`wZe("231807748")` template), skills, and swaps the "new task folder" explanation for the `request_cowork_directory` tool. | `IXe`, `PXe` (date), `oXe` (skill info), `cXe="[SkillsFetcher]"`, `wZe` (feature value) |
| 30 | **Uploads prep** | 2902729–2903716 | `kXe`: validate host file (inside home, regular file, realpath); `RXe`: dedupe filename w/ md5-8 suffix; `Xie`: copy/link into `<sessionStorage>/uploads` → `{uploadsDir, mappings:[{hostPath,vmPath}]}`. | `kXe`, `RXe`, `Xie`, `t0e` |
| 31 | **InputStream** (`OXe`) | 2903716–2904400 | Push-stream of user messages consumed by the SDK query (async iterable). | `OXe` (enqueue/done/`[Symbol.asyncIterator]`), `u0e` (dir→flat map helper) |
| 32 | **LocalAgentModeSessionManager** (`f0e`) — the Cowork core | 2904399–2946600 | Full session lifecycle in VM: start/resume/stop/archive, tool-permission queue, MCP wiring, message translate, file watch, audit logs, timeout health, persistence. See §2 for methods. | see §2; `Is` singleton + `NXe` module export @2946730 (`{LocalAgentModeSessionManager, localAgentModeSessionManager}`) |
| 33 | **OS utils / diagnostics** | 2946913–2966000 | `a6` (macOS version), `_0e` (stop VM before bundle delete), VM/session diagnostics JSON (`vmBundle`, `vmStatus`, `sdk`, `sessions`) @2964973. | `a6`, `_0e`, `SSe` (diagnostics builder) |
| 34 | **Notifications** | 3081584–3089900 | Idle-session + permission-request OS notifications (via `@ant/claude-swift` on macOS). | `Zrt` (tool→description) @3081584, `Grt`, `Jrt`→`oc` singleton, `Yrt` (swift loader), `useSwiftNotifications` |
| 35 | **Main-window API factories** | 3089213–3092400 | `Qrt`: LocalSessions main-side impl (cwd-based, host Claude Code); `Xrt`: WindowControl impl; `Aet` @2972300: AgentModeFeedback impl. | `Qrt`, `Xrt`, `Aet` |
| 36 | **Main window wiring** | 3135765–3136600 | Boot hook: sets `ry` (LocalAgentModeSessions) impl from `Wat`, forwards `p.on("event")→dispatchOnEvent`, `queryCompleted`→idle notification with `/local_sessions/<id>` nav, `focusedSessionChanged`→close idle notification; then `handleCoworkVMApi(webContents)` + `cleanupVMBundleIfUnsupported()`. Tool-permission requests also drive OS notifications via `Vd` (legacy manager). | `ry`, `NXe`, `Jat`, `oc`, `Zrt`, `Rf` (router dispatcher) |
| 37 | **Warm (background) VM download** | 3271838–3275600 | Pre-downloads `rootfs.img.zst` for a future bundle (`https://downloads.claude.ai/vms/linux/<sha>/rootfs.img.zst`) to `userData/vm_bundles/warm/`, verifies zstd checksum, promotes to `.origin`; gated by `autoDownloadInBackground` from `yukonSilver` config. | `Nat="warm"`, `D4="rootfs.img.zst."`, `H6`/`K6`/`Mat`, `Dat` (fetch VM hash from `downloads.claude.ai/releases/darwin/universal/<ver>/vm_hash`), `Lat` (download), `Fat` (list), `Oat` (hashing stream), `Uce` (zstd), `jat` (gate) |
| 38 | **Cowork VM menu + API impl** | 3276152–3282234 | Dev menu "Cowork VM" (Start/Show Debug Window/Hide/Stop). `Wat`: `createLocalAgentModeSessionsApi` (main-side impl of interface row 1, incl. trusted-folder prefs `localAgentModeTrustedFolders`, max 300, `Kat` trust check). `Zat`: `handleCoworkVMApi` (impl of `y0` ClaudeVM interface: `download`, `startVM`, `getDownloadStatus`, `getRunningStatus`, `setYukonSilverConfig`, `deleteAndReinstall`→stop VM, delete bundle, `Yf(!0)` relaunch). `Yat`: `cleanupVMBundleIfUnsupported` (delete bundle when `yukonSilver.status!=="supported"`). | `zat`, `Hat` module, `Kat`, `Wat`, `Gat` module `{createLocalAgentModeSessionsApi}`, `Zat`, `Yat`, `Jat` module `{cleanupVMBundleIfUnsupported, handleCoworkVMApi}`, `Ld` (trailing-slash strip) |
| 39 | **Local file access gate** | 3282234–3289000 | `Ci`=`LocalFileAccessError` (code: `INVALID_SESSION/INVALID_PATH/PATH_TRAVERSAL/BLOCKED_EXTENSION/USER_DENIED/FILE_READ_ERROR/FILE_OPEN_ERROR/VM_UNAVAILABLE`). `est` validates VM path `/sessions/<vm>/...`; `gbe` validates host paths against session selected folders/outputs/uploads/.projects/sharedCwd + consent dialog (`checkFileAccessConsent`, `S3` in-flight map, `tst` dangerous extensions list); `_be` encodes content (text vs base64, `I6` mime lookup, `Qat` text-mime set, `vbe` blocked binaries). Backs FileSystem IPC: `nst` (read via VM `vm.readFile`), `ist` (host read), `ast` (dispatch), `rst` (open/show), `sst` (listFilesInFolder). | `Ci`, `Qat`, `vbe`, `tst`, `Xat`, `est`, `gbe`, `_be`, `nst`, `ist`, `ast`, `rst`, `sst`, `I6` |

---

## 2. Symbol Dictionary (exhaustive)

### Core coworkers symbols (non-obvious minified names → meaning)
| Symbol | Offset | Meaning |
|---|---|---|
| `f0e` | 2904399 | **LocalAgentModeSessionManager** class (extends `If.EventEmitter`) — the Cowork core. |
| `Is` / `NXe` | 2946730 | Singleton instance + module `{LocalAgentModeSessionManager:f0e, localAgentModeSessionManager:Is}`. |
| `ry` | 142229 | IPC interface object **LocalAgentModeSessionManager** (renderer-facing; `for(wc).setImplementation(api)`; `getDispatcher`). |
| `Wat` / `Gat` | 3277169 / 3280571 | `createLocalAgentModeSessionsApi(manager, wc, getDispatcher)` main-side impl; module `Gat`. |
| `nC` | 120822 | IPC interface **LocalSessions** (legacy cwd-based mode; 21 methods + events). |
| `Qrt` | 3089213 | Main-side impl of LocalSessions. |
| `Vd` | ~2817500 | Legacy (CCD) LocalSessions manager used alongside `f0e`. |
| `y0` | 176234 | IPC interface **ClaudeVM** (VM control). |
| `Zat` / `Yat` / `Jat` | 3280571 / 3282100 / 3282234 | `handleCoworkVMApi` / `cleanupVMBundleIfUnsupported` / module. |
| `oze` / `pl` | 1917378 / 1923173 | ClaudeCodeManager class / singleton (VM+host SDK). |
| `Uye` / `_i` | 2850079 / 2850208 | Load `@ant/claude-swift`; `_i()` → addon `vm` API (spawn/mountPath/installSdk/readFile/stopVM/kill/showDebugWindow/addApprovedOauthToken/isGuestConnected/isDebugLoggingEnabled/setDebugLogging). |
| `Ha` / `bS` / `yQe` | 2850276 | VM instance UUID (per app run) getter / cache / reset. |
| `De` | 2849096 | Winston logger for VM subsystem (file `cowork_vm_node.log`). |
| `gr` | 2361095 | Telemetry emit (async, HTTP). |
| `Qy(t,e,r,i)` | 1912868 | Tool definition helper → `{name,description,inputSchema,handler}`. |
| `rx(t)` | 1912942 | MCP server builder → wraps `QVe` into `{type:"sdk",name,instance}`. |
| `QVe` | 1898587 | MCP server class (SDK-style, registers tools/resources/prompts; used by `rx`). |
| `DL({prompt,options})` | 1913181 | Claude Code SDK `query()` runner — builds the agent query (resolves `pathToClaudeCodeExecutable` from `__filename` when needed). |
| `OXe` | 2903716 | Input stream (async-iterable) feeding the query. |
| `IXe` | 2900691 | System prompt builder (template filling + KB + skills + workspace note). |
| `Pye` | 2809078 | MCP coordinator (see row 14). |
| `e6` | 2803595 | Local MCP server manager (shared singleton). |
| `PJe` | 2806391 | Remote connector proxy manager. |
| `EJe` | 2796437 | Internal MCP server manager. |
| `t6` | 2809078 | MCP server key: `name` if local/known (`M0()`), else `uuid`. |
| `IJe` | 2809078 | `"ant.dir.ant.anthropic.filesystem"` — filtered-out MCP extension. |
| `ZQe` | 2875400 | FileSystemWatcher (per-session). |
| `GQe` | 2872047 | CoworkDirectoryTool builder (tools `request_cowork_directory`, `allow_cowork_file_delete`). |
| `e0e` | 2871685 | VM path → `{name, subpath}` (folder resolution for permission UI). |
| `$g` | 2869949 | VM path → host path (single string). |
| `t4` | 2870452 | Recursive path translator (object/array/string). |
| `Vie` | 2869610 | Slugify (lowercase, `[^a-z0-9]+→-`, ≤60 chars). |
| `zQe` | 2869610 | KB mount-name dedupe (`{id, mountName}`). |
| `HQe`/`KQe` | 2869949 | `.`/`..`/empty segment guards. |
| `Xat` | 3282300 | Extract `<vmName>` from `/sessions/<vm>/...`. |
| `est` | 3282340 | Validate VM path access (`local_` session, vmProcessName match, no traversal, no blocked ext). |
| `gbe` | 3283900 | Host-path access validation + consent flow (selected folders/outputs/uploads/.projects/sharedCwd). |
| `Ci` | 3282234 | `LocalFileAccessError` (name/code). |
| `jQe` | 2868041 | Unique VM process name generator (e.g. `admiring-keen-mclean`; `dd`+`Uie` lists, ≤32). |
| `XL` | 2868419 | `isPathInside(child, parent)`. |
| `qQe` | ~2868480 | Audit-logger factory (`<dir>/audit.jsonl`). |
| `Xie`/`kXe`/`RXe` | 2903212/2902729/2902737 | Uploads prep / file validation / dedupe naming. |
| `t0e` | 2877349 | `userData/pending-uploads` path. |
| `OXe` siblings: `ly` | 2810110 | Message content builder (appends image blocks `{type:"image",source:{type:"base64",...}}`). |
| `Qie` | 2898402 | Replace `@/host/path` mentions with VM paths. |
| `TXe` | 2898402 | Regex-escape. |
| `AXe` | 2898556 | Error categorization (`sdk_binary_missing`, `seccomp_killed`, `sandbox_deps_missing`, `cli_stdout_pollution`, `vm_disconnected`, `filesystem_error`, `library_error`, …) from CLI stderr text. |
| `LXe`/`xXe`/`EXe` | ~2897500–2898100 | Permission prompt humanization: tool → action word (`Bash:"running"`, …) and arg → text. |
| `aXe`/`iXe`/`sXe` | 2888907/2888600/2890195 | ProjectSync batch/single/prompt. |
| `yXe`/`i4` | 2891869/2897304 | Skills plugin manager / singleton. |
| `XZe`/`Qg` | 2631884/2636648 | User plugins manager / singleton (remote plugins). |
| `BZe`/`Ud` | 2622554/2625967 | Local (cowork) plugins reader / singleton. |
| `MZe`/`DZe`/`LZe` | 2622001–2622500 | SettingsReader (cowork_settings.json path/parse/enabledPlugins). |
| `vi` / `jy` | 1307523 / 1307701 | **Desktop preferences get/set** (`qn().preferences`, persisted under key `"preferences"`, emits change events, validates via `vDe`). Used for `localAgentModeTrustedFolders`. |
| `Kat` | 3276837 | Trusted-folder check (normalized prefix containment) using `vi("localAgentModeTrustedFolders")`. |
| `Ld` | 3276837 | Strip trailing slashes. |
| `gJe` / `yJe` | 2792142 / ~2792300 | MCP directory bridge: resolve pending request (main↔renderer) / send to renderer. `Pp`=pending map, `Tye=10000`. |
| `Zrt` | 3081584 | Tool call → human description (checks `AskUserQuestion`, then keys `command,file_path,path,pattern,query,url,prompt,description`). |
| `Jrt`/`oc`/`Grt`/`hd` | 3082291+ | Swift notifications manager/singleton. |
| `Yrt` | 3082291 | macOS-only `@ant/claude-swift` loader for notifications. |
| `i6` | 2866485 | Public `startVM(options)` (dedupe in-flight `Cg`). |
| `FQe` | 2863158 | VM startup sequence (4 steps). |
| `Wye` | 2862434 | Bundle download (returns in-flight promise `Pd`; status via `jw(al.*)`). |
| `MQe` | ~2862300 | Download implementation (rootfs.img + `claudevm.bundle` etc, checksum via `fy` hash file, `Cl` fetch helper). |
| `Gye`/`u_`/`Zye` | 2859000–2859200 | Bundle dir / bundle path / alias. |
| `qE` | 2862812 | Bundle ready (all `Hye` files ready via `Kye`). |
| `Yye` | 2862884 | Download in progress. |
| `Jye` | 2862913 | Delete bundle dir. |
| `Bie` | 2859801 | `https://downloads.claude.ai/vms/linux/<version>` (bundle CDN base). |
| `jie`/`DQe`/`LQe` | 2863113–2863146 | Guest-connect timeout 60s / poll 500ms / default RAM 4GB. |
| `pp` | (used 2865366, 3281026) | VM running-status enum: `Ready`, `Offline`, `Booting`. |
| `al` | (used 2862434+) | VM download-status enum: `Ready`, `Downloading`, `NotDownloaded`. |
| `TQe`/`AQe`/`l_` | 2857100–2858600 | Spawn factory/impl/guest-connected check; `PQe` module. |
| `xQe`/`wQe`/`SQe`/`EQe` | 2855738+ | Network diagnostics / VPN interfaces / VPN connections / connectivity. |
| `CQe`/`$Qe` | 2856205/2856429 | VPN error/warn messages. |
| `ql` | 2636648 | Merged MCP config source (local plugins + `Qge` remote + prefs). |
| `KB` | 2636648 | Resolve merged MCP config to server list. |
| `Fme`/`Bme`/`qme` | 1923173+ | OAuth profile map / env selector / token loader. |
| `Dye`/`zJe` | 2813554 | Env builder / session env. |
| `WCe` | 369631 | Embedded Claude Code VM SDK manifest (v2.1.15, platform checksums; darwin-arm64 checksum `cc627c0e…`). |
| `SZe` | 2616572 | Feature-flag structured value reader (GrowthBook; parse with schema). |
| `wZe` | 2616451 | Feature-flag raw value reader. |
| `Jg` | 2616500 | Feature-flag boolean (`on`). |
| `bZe` | 2616500 | Feature listener (on/off). |
| `xs`/`oy` | ~2616000 | GrowthBook features map / emitter. |
| `Yf` | 2393291 | App quit/relaunch (`Yf(!0)` = relaunch; used by deleteAndReinstall). |
| `jy` (prefs) | 1307701 | see `vi` row. |
| `qn` | (used 1307523) | Preferences store accessor (`qn().preferences`). |
| `Bd` | (used 1307523) | Persist store key. |
| `HF` | (used 1307523) | Preference normalization/validation wrapper. |
| `mle` | 100267 | Validator: `initializationStatus` shape `{step,message,isComplete}`. |
| `YSe` | 100436 | Validator: project context `{uuid,name,mountPath,hostPath}`. |
| `p9` | 100460 | Validator: **session summary shape** (sessionId,cwd,userSelectedFolders,userSelectedProjectUuids,isRunning,model,createdAt,lastActivityAt,title,isArchived,homePath,folderExists,pendingToolPermissions,error,initialMessage,mcqAnswers,enabledMcpTools,initializationStatus,fsDetectedFiles,mountedProjects,localMcpServers,vmProcessName,…). |
| `cEe` | 106660 | Validator: `start` info (startSession payload incl. sharedCwdPath, selectedKnowledgeBases, egressAllowedDomains…). |
| `gle`/`vle`/`QSe`/`Sle`/`$le`/`Tle`/`xle`/`yEe`/`hle`/`mEe`/`ble`/`g0`/`_le`/`t1`/`p9` | 100267–160500 | eipc arg/result validators (respectively: updateSession opts / archive opts / getSession opts / getSupportedCommands opts / mcp server cfg / setMcpServers result / connectors / directory servers / start result / shareSession result / slash command / tool permission request / session event / image / session). |
| `Fe` | ~117883 | eipc origin validation (`senderFrame.url` check). |
| `zye` | 2859000 | Dispatch `startupError` to renderer. |
| `OQe`/`JL`/`jw` | 2858868–2859000 | Dispatch `downloadProgress` / `runningStatusChanged` / `downloadStatusChanged`. |
| `Se` | (used 2858868) | Main BrowserWindow reference. |
| `jye`/`hQe`/`vQe`/`qye` | 2849096 | Log level / VM-debug flag / file transport / transports array. |
| `a6` | 2946913 | macOS version parse. |
| `_0e` | ~2964700 | Stop VM before bundle deletion. |
| `SSe` | ~2964700 | Diagnostics JSON builder. |
| `qE`…`Kye`/`Hye` | 2859801–2862812 | Bundle readiness: file list `["rootfs.img"]`, per-file `{ready,reason}`. |
| `Oat`/`Uce`/`Cl` | 3274084+ | Hash-stream / zstd decompressor / download-with-progress helper. |
| `fy` | 3274084 (use) | Expected rootfs sha256 (read from hash file next to bundle). |
| `D4`/`Nat` | 3271838 | Warm file prefix `rootfs.img.zst.` / dir `warm`. |
| `Dat`/`Lat`/`Fat`/`jat`/`Mat`/`H6`/`K6` | 3271838–3275600 | Warm-download: fetch VM hash / download / list / gate / exists / paths. |
| `zat`/`Hat` | 3276152/3276837 | Dev menu builder / module. |
| `sst`/`nst`/`ist`/`ast`/`rst`/`ybe` | 3283900–3288500 | FileSystem IPC handlers: list / read-VM / read-host / read-dispatch / open-show / consent-check. |
| `_be`/`I6`/`Qat`/`vbe`/`tst` | 3284500–3288500 | File encode (text/base64) / mime lookup / text mime set / blocked binary exts / dangerous script exts. |
| `Xrt`/`Aet` | 3092139/2972300 | WindowControl / feedback-window main-side impls. |
| `Yrt`/`lnt` | 3149091 | claude-swift native QuickEntry init (macOS) & analytics forwarding (`zt.on("logAnalyticsEvent")→gr`). |
| `useCoworkPlugins` | 1684380 | (CLI SDK option) enable cowork plugins — part of agent SDK session opts, default `!1` in the bundled CLI SDK. |
| `teleportedSessionInfo` | 1684695 | (CLI SDK option) teleport resume info — SDK-internal, not desktop-specific. |

### `f0e` (LocalAgentModeSessionManager) method inventory
Constructor @2904399 (fields: `sessions Map, pendingPermissions Map, currentAccountId/OrgId, initPromise, draftSessionFolders, sessionAuditLoggers Map, focusedSessionId, timeoutCheckInterval, timedOutSessions Set, baseDir=_Xe, userDataPath, mcpCoordinator=new Pye, fileWatcher=new ZQe` + fsEvent listener + org-change listener + `startTimeoutDetection`).

- `initializeWithAccount`/`doInitialize` @2906964 — loads OAuth org/account, migrates + loads sessions.
- `setupOrgChangeListener` @2907100 — cookie `lastActiveOrg` change → re-init.
- `auditLog(sessionId, entry)` @2906964 — append JSONL via `qQe`.
- `emitInitializationStatus` @2906574 — emits `initialization_status`.
- `startTimeoutDetection` @2905405 — 60s interval; `lam_session_timeout` after 300s idle.
- `registerAppQuitHandler` @2906358 — `lam_session_app_quit` per running session.
- `getStorageDir` @2907965 — `userData/<baseDir>/<accountId>/<orgId>` (null until init).
- `getSessionFilePath`/`ensureStorageDir` @2907965.
- `getOutputsDir(sessionId, sharedCwdPath?)` @2907965 — `<home>/<sharedCwd>/outputs` or `<sessionDir>/outputs` (mkdir).
- `getClaudeConfigDir` @2908365 — `<sessionDir>/.claude` (mounted to `/sessions/<vm>/mnt/.claude`, `rwd`).
- `getSessionStorageDir` @2908851.
- `buildMountedProjects` @2908851 — `{uuid,name,mountPath,hostPath}`.
- `getVMPathContext`/`translateMessagePaths` @2908990 — VM-path rewrite of messages.
- `migrateLegacySessions` @2909119 — from `userData/local-sessions.json` into new per-account layout.
- `loadSessions` @2910192 — read `*.json`, filter deleted folders, rebuild `fsDetectedFiles` Map.
- `saveSession` @2911724 — persist subset (incl. `fsDetectedFiles`, `fileDeleteApprovedMounts`, `mountedKnowledgeBases`, `knowledgeBaseMountPaths`, `sharedCwdPath`, `mcqAnswers`, `firstPartyConnectors`…).
- `startSession` @2914759 — create/resume session record (`cwd=/sessions/<name>`, `vmProcessName=<name>`, initializationStatus `auth`), then `doSessionInitialization`.
- `doSessionInitialization` @2916571 — full pipeline: auth (`qme`) → `skills` (syncSkills) → user plugins (`Qg.syncPlugins`, flag 2340532315) → project sync (`aXe`) → CLI plugins (`Ud`, flag 1697423394) → `prompt` (`IXe`) → `mcp_setup` (`createAllServers`) → KB mount (`.knowledge/<mountName>`, `rw`) → `query` (`getVMSpawnFunction`, `getOutputsSubpath`, `GQe` cowork tool, `DL` query). Env: `CLAUDE_CODE_ENTRYPOINT:"local-agent"`, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS:"1"`, `CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS:"true"`, `CLAUDE_CONFIG_DIR:/sessions/<vm>/mnt/.claude`, `MCP_TOOL_TIMEOUT` (flag 1978029737). Mounts: user folder (or `outputs`) `rw`/`rwd`, `.claude` rwd, `.skills` ro, `.plugins` ro, `.local-plugins` ro, `uploads` ro, `.projects` ro, `.knowledge/<n>` rw. Sets `sharedCwdPath` (when requested: `<home>/Documents/Claude`), `allowedDomains`, `isResume`.
- `handleToolPermission` @2912553 — queues `{requestId,uuid, sessionId, toolName, input, suggestions}`, emits `tool_permission_request`, audit-log `permission_request`, resolves on response.
- `respondToToolPermission` @~2936500 — resolve pending by requestId.
- `canUseTool` closure @2920071 — adds `_folderName` for `mcp__cowork__allow_cowork_file_delete` (via `e0e`).
- `setMcpServers` @2945438 — add/remove via `createMcpServer`/`t6`, then `query.setMcpServers`.
- `setFirstPartyConnectors` @2946399; `setDraftSessionFolders` @2946399; `getSupportedCommands` @2946399 (from `slashCommands`).
- `startFileWatching`/`stopFileWatching` @2928265 — watch user folder or outputs dir.
- `sendMessage` @2929424 — buffers `{type:"user", uuid, session_id: cliSessionId, message}` + path rewrites.
- `setupQueryHandlers` @2938201 — consumes query iterator: maps init (`cliSessionId`, `slash_commands`), emits `message` events, audit-log, on `result` → `lam_session_turn_completed` + `lam_message_cycle_outcome` (healthy), kills VM process (`Die(vmProcessId).kill("SIGTERM")`), on error → `lam_session_query_error` + cycle unhealthy + 401→token cache clear.
- `stopSession` @~2931200 — `query.return()`, emits `close {code:0}`, `lam_session_stopped`.
- `archiveSession` @2932022 — stop + delete uploads + close audit logger + `archived` event + `lam_session_archived`.
- `getSession` @2932284 — summary shape (pending permissions, fsDetectedFiles, `Yie`=new-session pseudo-record).
- `getAllSessions` @2933889; `getFocusedSession`/`setFocusedSession` @2933357 (emits `focusedSessionChanged`).
- `hasUserApprovedFileAccess`/`hasUserApprovedParentDirectoryAccess`/`recordUserFileAccessApproval` @2934558.
- `addUserSelectedFolder` @2935245 (emits `session_updated`); `updateSession` @2935331 (title etc).
- `getBufferedMessages`/`getTranscript`/`repairTranscript`/`getRecoverableErrorMessage` ~2936500–2946000.
- `getVMSpawnFunction` @2943206 (`PQe.createVMSpawnFunction`); `getVMProcessName`/`getSharedCwdPath` @2943206; `shareSession` @2943206 (needs `cliSessionId`); `isVSCodeInstalled` @2938201 (protocol `vscode://`).

---

## 3. Event / Type Inventory

### 3a. `f0e` ("event" emitter, forwarded to renderer as `onEvent`)
| type | payload | offset |
|---|---|---|
| `initialization_status` | `{type, sessionId, initializationStatus:{step,message,isComplete}}`; steps: `auth, skills, skills_sync, prompt, prompt_build, mcp_setup, query, query_start, complete` | 2906574 |
| `message` | `{type, sessionId, message}` (SDK message envelope) | 2916150, 2940067 |
| `session_updated` | `{type, sessionId}` | 2916614, 2928265, 2935245 |
| `tool_permission_request` | `{type, sessionId, request:{requestId, sessionId, toolName, input, suggestions}}` | 2912553 |
| `local_mcp_servers` | `{type, sessionId, data: JSON.stringify({servers})}` | 2921435 |
| `close` | `{type, sessionId, code:0}` | 2931424 |
| `archived` | `{type, sessionId}` | 2932022 |
| `fs_file_created` / `fs_file_deleted` | `{type, sessionId, fsFile:{hostPath,fileName,timestamp}}` (re-emitted from FileSystemWatcher) | 2904825 |
| `queryCompleted` (EventEmitter, not via "event") | `(sessionId)` → main window idle notification | 2926960/3135765 |
| `focusedSessionChanged` (EventEmitter) | `(sessionId|null)` | 2933357 |

### 3b. FileSystemWatcher (`ZQe`) — `fsEvent`
`{type:"fs_file_created"|"fs_file_deleted", sessionId, hostPath, fileName, timestamp}` @2876342.

### 3c. ClaudeVM IPC events (renderer)
`downloadProgress(percent:number)`, `downloadStatusChanged(status: al)`, `runningStatusChanged(status: pp)`, `startupError(message:string)` @179722–180400.

### 3d. Telemetry events via `gr` (all payloads seen)
| event | payload | offset |
|---|---|---|
| `lam_vm_process_exited` | vm_instance_id, exit_code, duration_ms, was_killed | 2851848 |
| `lam_vm_runtime_error` | vm_instance_id, error_message | 2852064 |
| `lam_vm_process_spawn_failed` / `lam_vm_process_spawned` | vm_instance_id, is_resume, mount_count | 2857754/2858140 |
| `lam_vm_bundle_download_completed` / `_failed` | bundle_version, duration_ms, download_size_bytes, download_reason | 2862011 |
| `lam_vm_startup_failed` | vm_instance_id, bundle_version, duration_ms, error_type, is_fresh_download, failed_step, vpn_active, vpn_interfaces, connected_vpns | 2863793, 2866134 |
| `lam_vm_startup_completed` | vm_instance_id, bundle_version, duration_ms, is_fresh_download | 2865366 |
| `lam_vm_shutdown_completed` / `_failed` | vm_instance_id, bundle_version, duration_ms, trigger:"app_quit" | 2864332 |
| `lam_project_sync_failed` | session_id, project_uuid, error_message, is_first_turn | 2889490 |
| `lam_session_timeout` | session_id, cli_session_id, seconds_since_activity, had_any_response | 2905917 |
| `lam_session_app_quit` | session_id, cli_session_id, had_any_response, session_duration_seconds | 2906358 |
| `lam_session_start_attempted` | session_id, vm_instance_id, is_resume, has_selected_folders, folder_count, mcp_server_count | 2916571 |
| `lam_session_step_completed` | session_id, vm_instance_id, step, duration_ms | 2916941 |
| `lam_session_initialization_failed` | session_id, vm_instance_id, failed_step, error_message, duration_ms | 2928265 |
| `lam_session_stopped` / `lam_session_archived` | session_id, cli_session_id, vm_instance_id, total_turns, session_duration_ms | 2931424/2932022 |
| `desktop_local_agent_mode_session_initialized` | session_id, cli_session_id, vm_instance_id | 2938554 |
| `lam_session_turn_completed` | session_id, cli_session_id | 2940067 |
| `lam_message_cycle_outcome` | session_id, cli_session_id, user_message_uuid, cycle_health, had_first_response, seconds_to_outcome, error_message | 2940526 |
| `lam_session_query_error` | session_id, vm_instance_id, error_category, raw_output, error_message, is_startup_error, is_resume | 2941591 |
| `local_kb_session_mounted` | kb_count, total_file_count, total_size_bytes | 2927649 |
| `lam_vm_warm_download_started/completed/failed` | bundle_version, app_version, duration_ms, download_size_bytes, error_message | 3272383+ |
| `lam_vm_warm_promote_completed/failed` | bundle_version, duration_ms, failure_reason | 3274084+ |

### 3e. Renderer IPC channels registered (`setImplementation`)
`WindowControl` (resize, focus, setThemeMode), `QuickEntry` (setRecentChats, +onQuickEntrySubmit), `LocalSessions` (start, sendMessage, stop, archive, updateSession, getSession, getAll, getGitInfo, getGitDiff, getTranscript, openInVSCode, isVSCodeInstalled, getInstalledEditors, openInEditor, startPty, stopPty, resizePty, writePty, respondToToolPermission, checkTrust, saveTrust, setPermissionMode, getPermissionMode, getSupportedCommands, getPlanForSession, setMcpServers, importCliSession; events onEvent, onToolPermissionRequest), `LocalAgentModeSessions` (start, sendMessage, stop, archive, updateSession, getSession, getAll, getTranscript, respondToToolPermission, openOutputsDir, shareSession, setDraftSessionFolders, getSupportedCommands, getTrustedFolders, addTrustedFolder, removeTrustedFolder, isFolderTrusted, setMcpServers, setFirstPartyConnectors, setFocusedSession, respondDirectoryServers; events onEvent, onToolPermissionRequest), `AgentModeFeedback` (openFeedbackWindow), `ClaudeVM` (download, getDownloadStatus, getRunningStatus, setYukonSilverConfig, startVM, deleteAndReinstall; events downloadProgress, downloadStatusChanged, runningStatusChanged, startupError), `FileSystem` (browseFolder, getSystemPath, listFilesInFolder, openLocalFile, readLocalFile, whichApplication).

Renderer preloads in `.vite/renderer/{main_window,about_window,find_in_page,quick_window}` contain **zero** cowork symbols (verified by scan) — cowork UI lives on the remote `claude.web` origin via these eipc channels.

---

## 4. Config / Settings Surface

### Files & directories
| Path | Purpose | Offset |
|---|---|---|
| `~/.claude/cowork_settings.json` | SettingsReader; `enabledPlugins` map (plugin id → enabled bool) | 2622001–2622500 |
| `~/.claude/cowork_plugins/` (`cy`) | Local cowork plugins dir | 2622456 |
| `~/.claude/cowork_plugins/installed_plugins.json` (`wN`) | `{plugins: {<id>: [{installPath, scope: user\|project\|local, projectPath}]}}` | 2622456 |
| `~/.claude/cowork_plugins/cache` (`FZe`) | plugin cache; mounted to `/sessions/<vm>/mnt/.local-plugins` | 2622456/2924240 |
| `mnt/.claude/cowork_plugins/` (`Sne`) | VM-path prefix for plugin install paths | 2622456 |
| `userData/vm_bundles/` (`RQe`) + `claudevm.bundle` (`kQe`) | VM bundle (rootfs.img + origin hash) | 2858710 |
| `userData/vm_bundles/warm/` | background warm download cache | 3271838 |
| `userData/claude-code-vm/` | VM Claude Code SDK (linux-arm64, `.verified` marker) | 1917378 |
| `userData/claude-code/` | host Claude Code SDK | 1917378 |
| `userData/local-agent-mode-sessions/` | sessions base (`_Xe`); per-account/org subdirs; `<sessionId>.json` + `<sessionId>/audit.jsonl`, `uploads/`, `.projects/` | 2897268/2907965 |
| `userData/local-sessions.json` (`bXe`) | legacy session store, migrated once | 2897268 |
| `userData/pending-uploads/` (`t0e`) | pending uploads staging | 2877349 |
| `logs/cowork_vm_node.log` (`oe.app.getPath("logs")`) | VM subsystem log (10MB) | 2849096 |
| `cowork_vm_swift.log` | VM debug logging (menu item `Enable VM Debug Logging`) | 3002653 |
| prefs key `"preferences"` → `localAgentModeTrustedFolders` | trusted folder list (cap 300, `Ld`-normalized) | 1307523, 3279423 |

### Environment variables
| Env var | Value (VM sessions) | Offset |
|---|---|---|
| `CLAUDE_CODE_ENTRYPOINT` | `"local-agent"` (VM) / `"claude-desktop"` (host `Dye`) | 2921058 / 2813554 |
| `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` | `"1"` | 2921058 |
| `CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS` | `"true"` | 2921058 |
| `CLAUDE_CONFIG_DIR` | `/sessions/<vm>/mnt/.claude` | 2921058 |
| `MCP_TOOL_TIMEOUT` | from feature flag `1978029737`/`mcpToolTimeoutMs` (default 30000 via `SXe`/`wXe`) | 2921058, 2897268 |
| `CLAUDE_CODE_OAUTH_TOKEN` | injected + approved on VM MITM proxy (`addApprovedOauthToken`) | 2813554, 2858052 |
| `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY=""` | api host / empty key (OAuth flow) | 2813554 |
| `DISABLE_AUTOUPDATER` | `"1"` | 2813554 |
| `CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL` | `"true"` | 2813554 |
| `COWORK_VM_DEBUG` | `"1"` enables VM verbose logs | 2849096 |
| `CLAUDE_ENABLE_LOGGING` | console logging gate | 2849096 |

### Feature flags (GrowthBook, via `Jg`/`wZe`/`SZe`)
- `2340532315` — user plugins (remote `Qg`) sync + mounting (`/sessions/<vm>/mnt/.plugins`) @2917779/2918170
- `1697423394` — local CLI plugins (`Ud`) enabled + MCP configs @2917981/2636648
- `231807748` — knowledge-base system-prompt template (`{{kbList}}`) @2902071
- `1978029737` — `mcpToolTimeoutMs` @2921058
- `180602792` — claude-swift native events bridge @3149091
- `yukonSilver.status` (config, not flag) gates VM availability; `autoDownloadInBackground` gates warm download @3274844, 3282100

### MCP server names in-VM (allowedTools + created servers)
`mcp__mcp-registry__search_mcp_registry`, `mcp__mcp-registry__suggest_connectors`, `mcp__cowork__create_knowledge_base` (allowed by default); `mcp__cowork__allow_cowork_file_delete` + `request_cowork_directory` via local `cowork` server (`O.cowork=Ur` @2926521). VM mounts use modes `rw` / `rwd` (after delete approval) / `ro`.

---

## 5. Gaps / Unresolved

1. **`@ant/claude-swift` addon surface** — the native `vm` object's full method list is NOT in index.js (external addon). Seen calls only: `spawn`, `kill`, `mountPath`, `installSdk`, `stopVM`, `startVM`, `readFile`, `addApprovedOauthToken`, `isGuestConnected`, `showDebugWindow`/`hideDebugWindow`, `isDebugLoggingEnabled`/`setDebugLogging` (offsets 2858052–2865370, 3286500). Guest OS behavior (bubblewrap sandbox, seccomp, MITM proxy) only inferred from error-category strings @2899511.
2. **`request_cowork_directory` dialog flow** — dialog shown via `oe.dialog` (renderer `browseFolder` interface @164500) and `getOutputsSubpath`; exact dialog options (button labels, security-scoped bookmarks on macOS) not resolved — only the handler outcome is visible @2873579.
3. **`knowledgeBaseManager` internals** — `Xye` is a dynamic import (@2869134); KB sync, `generateMetadataFiles`, `getKBStats`, `createLocalKBsApi` are outside this bundle.
4. **`repairTranscript` / `getRecoverableErrorMessage` / `getTranscript` bodies** — exist in `f0e` @2936500–2946000 but were only partially read; exact JSON repair logic unresolved.
5. **`Qge` (remote MCP config fetch)** and `M0()` registered-server-name list — referenced @2636648/2809078; definitions live in other bundle chunks.
6. **`qx`/`Cn`/`c4` and other shared chunk symbols** used by `f0e` (`i4.generateSkillsSystemPrompt`, `pl.*`, `Ud.*`, `Qg.*`) — imported from module federation; only usage sites visible.
7. **Renderer UI logic** — the `claude.web` renderer bundle is remote; local `.vite/renderer/*` preloads contain zero cowork code (verified). Event payload consumption (`onEvent`, `onToolPermissionRequest`) unverified on the renderer side.
8. **`checkFileAccessConsent` dialog strings** — the consent `dialog.showMessageBox` text was truncated in extraction (@3283900–3284500); full button/`defaultId` semantics inferred only (`response===0` = approve).
9. **`sl a`/`Sl`/`LXe`-style helpers in legacy CCD manager** (region 2817000–2848000, the pre-VM LocalSessions twin) were not fully enumerated — same patterns, host-exec based, `sessionEnv` via `zJe`.
10. **VM network MITM proxy** — OAuth token approval implies a MITM proxy inside the VM; its ports/certs are in the addon, not the bundle.

### Reusable extraction recipe
```python
data = open('/tmp/claude-asar/app/.vite/build/index.js', encoding='utf-8', errors='replace').read()
def ctx(term, w=300):
    s = 0
    while True:
        i = data.find(term, s)
        if i == -1: return
        print(f'--- @{i} ---', data[max(0,i-w):i+len(term)+w])
        s = i + 1
```
