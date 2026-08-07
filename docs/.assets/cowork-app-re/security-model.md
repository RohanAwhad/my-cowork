# Claude Cowork — Security & Permission Model (Reverse-Engineered)

**Target**: Claude Desktop app **1.1.673**, bundled renderer/main-process bundle
`/tmp/claude-asar/app/.vite/build/index.js` (3,289,071 bytes, minified).
All offsets are **byte offsets** into that file. Snippets are verbatim.

The whole Cowork ("local agent mode") security model is split across **three trust
domains**:

| Domain | Enforced by | Evidence |
|---|---|---|
| **Host (Electron main)** | `LocalAgentModeSessionManager` (`f0e`, singleton `Is`, offset 2946328), permission engine (offset 2913082), path-validation gate `est`/`gbe` (offset 3283374), file-access consent `ybe` (offset 3285955) | dialog.showMessageBox, fs.realpath checks, `$eipc_message$` IPC with origin validation (`Fe(i)`) |
| **VM (native Swift addon `SwiftVM`)** | `_i()` → `sf.vm` (offset 2850335); `o.spawn(...)` w/ mounts+allowedDomains (offset 2858035); `o.mountPath` (offset 2873983); `o.addApprovedOauthToken` (offset 2857841) | `[SwiftVM] Failed to load module`; `o.spawn(e, processName, ...)` |
| **Server** | OAuth (offset 2915800 `qme(y)`), API host `y.apiHost` injected as `ANTHROPIC_BASE_URL` (offset 2920906) | `Dye({oauthToken:_,apiHost:y.apiHost})` |

Note: `createLocalKBsApi`/`knowledgeBaseManager` are **injected at runtime** — the
injection point `Xye()` (offset 2869043) returns `null` in this bundle, so KB
behavior is documented at the call sites, with the actual implementation external.

---

## 1. Path validation — `validateVMPathAccess` (minified `est`)

**Offsets**: 3283374 (function), 3283294 (blocklist arrays), 3283800 (`Xat`).

### 1.1 The exact blocklist arrays

```js
// offset 3283314 (verbatim, continues into the vbe array)
const Qat=new Set(["application/json","application/xml","application/javascript","application/typescript","image/svg+xml"]),
// offset 3283370:
vbe=[".exe",".com",".msi",".bin",".app",".dmg",".pkg",".jar"];
```

```js
// offset 3283680 — script-extension blocklist
const tst=[".sh",".bash",".zsh",".command",".bat",".cmd",".ps1",".vb",".jnlp",".js",".pl",".py",".rb",".scpt",".scptd",".applescript",".workflow"];
```

| Array | Purpose | Used for |
|---|---|---|
| `vbe` (8 binary exts) | blocked for **any** file access (VM path validation + `openLocalFile` + `gbe`) | `est`, `gbe` |
| `tst` (17 script exts) | blocked only for **`openLocalFile`** (opening with default app), **not** for reading | `gbe` |
| `Qat` (5 mime types) | treated as **text** in `_be` (read returns utf-8 instead of base64) | `_be` offset 3287010 |

### 1.2 First-segment extraction — `Xat`

```js
// offset 3283400
function Xat(t){if(!t.startsWith("/sessions/"))return null;const e=t.slice(10),r=e.indexOf("/"),
  i=r===-1?e:e.slice(0,r);return!i||i===".."||i==="."?null:i}
```
- Requires the literal `/sessions/` prefix.
- First path segment = the **vmProcessName**; `..`/`.`/empty → rejected.

### 1.3 The validation function `est` (full, verbatim)

```js
// offset 3283515
function est(t,e){
  if(!t.startsWith("local_"))throw K.warn(`validateVMPathAccess: rejected non-local session ${t}`),
    new Ci(`Invalid session: ${t}`,"INVALID_SESSION");            // 1. session-id prefix
  const r=Xat(e);if(!r)throw K.warn(`validateVMPathAccess: invalid VM path format: ${e}`),
    new Ci(`Invalid VM path format: ${e}`,"INVALID_PATH");        // 2. VM path shape
  const i=Is.getVMProcessName(t);if(!i||i!==r)throw K.warn(`validateVMPathAccess: vmProcessName mismatch for ${e}`),
    new Ci(`Session mismatch for path: ${e}`,"INVALID_SESSION");  // 3. bind path→session
  const n=me.posix.normalize(e),a=`/sessions/${r}/`;
  if(!n.startsWith(a))throw K.warn(`validateVMPathAccess: path traversal detected: ${e}`),
    new Ci(`Path traversal detected: ${e}`,"PATH_TRAVERSAL");     // 4. containment
  const s=me.extname(e).toLowerCase();
  if(vbe.includes(s))throw K.warn(`validateVMPathAccess: blocked binary file type ${s}: ${e}`),
    new Ci(`Blocked file type: ${s}`,"BLOCKED_EXTENSION");        // 5. binary ext
  return{vmProcessName:r,normalizedPath:n}
}
```

**Checklist (all host-side, fail-fast with `Ci` / `LocalFileAccessError` + code):**

1. Session id must start with `local_` (constant `_M="local_"`, offset 2897268).
2. VM path must be `/sessions/<name>/...` with sane first segment (`Xat`).
3. First segment must equal `Is.getVMProcessName(sessionId)` (offset 2943048) — binds a
   path to exactly one session; a path from session A cannot address session B's tree.
4. `posix.normalize` + `startsWith("/sessions/<name>/")` → traversal/escaping detection.
5. `vbe` extension check.

### 1.4 `gbe` — folder-confinement gate for `showFileInFolder`/`openLocalFile`

```js
// offset 3283880 (gbe start)
async function gbe(t,e,r){ // t = caller name, e = sessionId, r = host path
  if(!e.startsWith("local_"))throw ... "INVALID_SESSION";
  if(!me.isAbsolute(r))throw ... `Path must be absolute: ${r}`,"INVALID_PATH";
  const i=Is.getSession(e);if(!i)throw ... `Unknown session: ${e}`,"INVALID_SESSION";
  if(t!=="showFileInFolder"){
    const u=me.extname(r).toLowerCase(),h=vbe.includes(u),p=tst.includes(u);
    if(h||t==="openLocalFile"&&p)throw K.warn(`${t}: blocked ${h?"binary":"executable"} file type ${u}: ${r}`),
      new Ci(`Blocked file type: ${u}`,"BLOCKED_EXTENSION")       // binary for all; script only when opening
  }
  let n;try{n=await $t.realpath(r)}catch{throw ... `Failed to resolve path: ${r}`,"INVALID_PATH"}
  const a=Is.getSessionStorageDir(e),s=Is.getSharedCwdPath(e);let o;try{o=Is.getOutputsDir(e)}catch{}
  const c=[...i.userSelectedFolders??[], ...o?[o]:[], ...a?[me.join(a,"uploads")]:[],
           ...a?[me.join(a,".projects")]:[], ...s?[me.join(yn.homedir(),s)]:[]];
  let l=!1;
  for(const u of c)try{const h=await $t.realpath(u),p=me.relative(h,n);
    if(!me.isAbsolute(p)&&!p.startsWith("..")){l=!0;break}}catch{continue}
  if(!l)throw K.warn(`${t}: path ${r} resolves outside allowed folders`),
    new Ci(`Path is outside allowed folders: ${r}`,"PATH_NOT_ALLOWED");
  return r}
```

**Allowed host-folder roots** (realpath-normalized, suffix-containment check via
`me.relative(...) !isAbsolute && !startsWith("..")`):
- `userSelectedFolders` (every directory the user ever granted)
- session **outputs** dir
- session **uploads** dir (`<storage>/uploads`)
- session **`.projects`** dir
- `sharedCwdPath` (e.g. `~/Documents/Claude`, offset 2923040)

### 1.5 Per-file consent — `ybe` (dedup via `S3` pending map)

```js
// offset 3285955
const S3=new Map;
async function ybe(t,e,r,i){ // t=BrowserWindow, e=session, r=path, i="read"|"open"
  let n;if(r.startsWith("/sessions/"))n=me.posix.normalize(r);else try{n=await $t.realpath(r)}catch{...}
  if(Is.hasUserApprovedFileAccess(e,n)||i==="read"&&await Is.hasUserApprovedParentDirectoryAccess(e,n))return;
  const a=`${e}:${n}`,s=S3.get(a);
  if(s){if(!await s)throw new Ci(`User denied access to file: ${r}`,"USER_DENIED");return}
  const o=(async()=>{try{
    const l=i==="read"?"preview":"open";
    return (await oe.dialog.showMessageBox(t,{type:"question",buttons:["Cancel","Allow"],
      defaultId:1,cancelId:0,title:"File Access Request",
      message:`Allow Claude to ${l} this file?`,
      detail:`${r}\n\nThis will allow Claude to ${l} the file${i==="open"?" with your default application":""}.`}))
      .response===0 ? (K.info(...),!1) : (Is.recordUserFileAccessApproval(e,n),!0)
  }finally{S3.delete(a)}})();
  if(S3.set(a,o),!await o)throw new Ci(`User denied access to file: ${r}`,"USER_DENIED")}
```

- Reads auto-pass if a **parent** (outputs dir or any selected folder) was already
  approved (`hasUserApprovedParentDirectoryAccess`, offset 2934982).
- Concurrent requests for the same `session:path` share one dialog (map key `${e}:${n}`).
- Approval is recorded per-session in `userApprovedFileAccessPaths`
  (`recordUserFileAccessApproval`, offset 2935397) and **persisted** via `saveSession`.

### 1.6 The open/read/list entry points (`E3` module)

```js
// offset 3287930 (ast = readLocalFile)
async function ast(t,e,r){const i=decodeURIComponent(r),n=i.startsWith("/sessions/");
  let a=null;return n?a=est(e,i):await gbe("readLocalFile",e,i),
  await ybe(t,e,i,"read"),n&&a?nst(a.vmProcessName,a.normalizedPath,i):ist(i)}
// VM file → nst → vm.readFile (SwiftVM); host file → ist → fs.readFile
// offset 3287010 (_be): text-ish → utf-8 string; else base64
// offset 3288300 (sst = listFilesInFolder):
//   absolute path required; session must exist; path must be IN session.userSelectedFolders
//   (stricter than gbe!); dotfiles filtered; non-directory → []
// offset 3287010 (rst = openLocalFile): gbe("openLocalFile") + ybe(...,"open") then
//   shell.openPath / shell.showItemInFolder (for showFileInFolder)
```

---

## 2. Directory access tool — `GQe` / `request_cowork_directory`

**Offsets**: 2872549 (registration), 2873712 (mount flow), 2869050 (`Qye`/`XL`).

```js
// offset 2872549
function GQe(t){const e=Qy("request_cowork_directory",
  "Request access to a directory on the user's computer. This will show a directory picker dialog to the user, and if they select a directory, it will be mounted and made available to you. ... This is the primary way to gain file system access - don't ask users to 'start a new task' ...",
  {}, async()=>{
  const n=t.getVmProcessId(); if(!n)return{... "Session VM process not available. ..."};
  const a=yn.homedir(), s={title:"Select Directory to Share",
    properties:["openDirectory","createDirectory"],
    message:"Select a directory to share with the agent", defaultPath:a};
  const o=Me?await oe.dialog.showOpenDialog(Me,s):await oe.dialog.showOpenDialog(s);
  if(o.canceled||o.filePaths.length===0)return{... "Directory selection was cancelled by the user."};
  const c=o.filePaths[0],l=me.basename(c),
        u=me.relative(await $t.realpath(a),await $t.realpath(c));
  if(!await Qye(c,a))return{content:[{type:"text",
    text:`Selected directory "${c}" is outside the home directory and cannot be mounted.`}],isError:!0};
  const h=await _i(); if(!h)return{... "VM API not available. Cannot mount directory."};
  try{await h.mountPath(n,u,l,"rw");            // ← mountPath(processId, relSubpath, name, "rw")
    const p=`/sessions/${t.vmProcessName}/mnt/${l}`;
    return t.addUserSelectedFolder(t.sessionId,c),   // ← record for ALL future gbe checks
      {content:[{type:"text",text:`Successfully mounted directory.\n\nHost path: ${c}\nVM path: ${p}\n\nYou can now access files in this directory at ${p}`}]}}
  catch(p){return{... `Failed to mount directory: ${d}`}}})}
```

**Home-directory confinement — `Qye`**:

```js
// offset 2869030 (XL = path containment, Qye = realpath-based)
function XL(t,e){const r=Ce.relative(e,t);return!Ce.isAbsolute(r)&&!r.startsWith("..")}
async function Qye(t,e){return XL(await $n.realpath(t),await $n.realpath(e))}
// offset 2873712: if(!await Qye(c,a)) → "outside the home directory and cannot be mounted"
// a = os.homedir(), c = picked dir; BOTH realpath()ed → symlink escapes rejected.
```

- The dialog allows **creating** directories (`"createDirectory"`) and defaults to home.
- The **same** `Qye` check is reused by the renderer-side folder picker
  (offset 3139278): failure → error dialog *"The selected folder is outside your home directory."*.
- VM path template: **`/sessions/${vmProcessName}/mnt/${name}`** (name = basename).
- Mount mode is **`"rw"`** (read-write, but **not** delete-capable; see §3).
- `addUserSelectedFolder` (offset 2935633) persists the folder into the session and
  emits `session_updated` — this is what later authorizes `gbe` (read) and
  `hasUserApprovedParentDirectoryAccess` (parent-approval for reads).

---

## 3. File deletion — `allow_cowork_file_delete`

**Offsets**: 2874700 (registration), 2872223 (`e0e` mount resolution), 2924083 (mount mode), 2926167/2926344 (tracking).

```js
// offset 2874700 — tool description (abridged)
r=Qy("allow_cowork_file_delete",
  "Request permission to delete files in a directory. IMPORTANT: call this tool whenever a delete operation (such as rm) fails with 'Operation not permitted', rather than telling the user it is impossible. If approved, file deletion will be enabled.",
  {file_path: ie().describe("The VM path of the file you're trying to delete")},
  async({file_path:n})=>{
  const a=t.getVmProcessId(); if(!a)return{...};
  const s=e0e(n,t.vmProcessName,t.getUserSelectedFolders(),t.getOutputsSubpath());
  if(!s)return{... `Could not find mount for path: ${n}. Make sure the path is within a mounted directory.`};
  const o=await _i(); if(!o)return{... "VM API not available. Cannot modify mount permissions."};
  try{return await o.mountPath(a,s.subpath,s.name,"rwd"),   // ← re-mount as "rwd"
    t.setFileDeleteApprovedForMount(s.name),
    {content:[{type:"text",text:`File deletion is now enabled for the "${s.name}" folder.`}]}}
  catch(c){return{... `Failed to enable file deletion: ${l}`}}});
```

**`e0e` — VM path → host mount resolution** (offset 2872223):

```js
function e0e(t,e,r,i){const n=`/sessions/${e}/mnt/`;if(!t.startsWith(n))return null;
  const a=t.slice(n.length),s=a.indexOf("/"),o=s===-1?a:a.slice(0,s);
  for(const c of r)if(me.basename(c)===o){const l=me.relative(yn.homedir(),c).replaceAll("\\","/");
    return{name:o,subpath:l}}
  return o==="outputs"?{name:"outputs",subpath:i}:null}
```
→ deletion can only be granted for **user-selected folders or the outputs dir**.

**Per-mount tracking — `fileDeleteApprovedMounts`** (offset 2926167):

```js
setFileDeleteApprovedForMount:ct=>{const Vt=this.sessions.get(e);
  Vt&&(Vt.fileDeleteApprovedMounts||(Vt.fileDeleteApprovedMounts=[]),
  Vt.fileDeleteApprovedMounts.includes(ct)||Vt.fileDeleteApprovedMounts.push(ct),this.saveSession(Vt))},
isFileDeleteApprovedForMount:ct=>{... return ...fileDeleteApprovedMounts.includes(ct)}
```

**Where it feeds back — the mount-mode computation at session (re)spawn** (offset 2924083):

```js
const Qe=ke?me.basename(ke):"outputs",
      bt=(((d=Ue==null?void 0:Ue.fileDeleteApprovedMounts)==null?void 0:d.includes(Qe))??!1)?"rwd":"rw",
      Lt=ke?{[Qe]:{path:me.relative(yn.homedir(),ke),mode:bt}}:{outputs:{path:...,mode:bt}};
```

**State machine**: default mount mode `rw` → agent calls `allow_cowork_file_delete`
→ `mountPath(...,"rwd")` on the live VM **and** persists mount name in
`fileDeleteApprovedMounts` → on every resume/spawn the mount is created `rwd`.
Approval is **per-mount-name, per-session, persisted in session JSON**.

---

## 4. Uploads — `Xie` / `prepareUploads` (host → VM staging)

**Offsets**: 2903050 (`RXe`), 2903130 (`kXe`), 2903666 (`Xie`), 2877358 (`t0e`), 3140088 (pasted files).

```js
// offset 2903050 — dedup name: md5(content) 8-hex suffix before extension
function RXe(t,e,r){if(!r.has(t))return t;const i=ri.createHash("md5").update(e).digest("hex").slice(0,8),
  n=t.lastIndexOf(".");if(n===-1)return`${t}-${i}`;const a=t.slice(0,n),s=t.slice(n);return`${a}-${i}${s}`}

// offset 2903130 — host-file validation (per file)
async function kXe(t){try{const e=await $t.realpath(t),r=yn.homedir(),i=me.relative(r,e);
  if(me.isAbsolute(i)||i.startsWith(".."))return K.warn(`[prepareUploads] Rejected file outside home directory: ${t}`),null;
  const n=await $t.lstat(t);return n.isFile()?e:(K.warn(`[prepareUploads] Rejected non-regular file: ${t} (isDirectory=..., isSymlink=...)`),null)}
  catch(e){return null}}          // lstat → symlinks are NOT followed for classification

// offset 2903666 — the staging routine
async function Xie(t,e,r){const i=me.join(e,"uploads");await $t.mkdir(i,{recursive:!0});
  const n=new Set;try{const o=ve.readdirSync(i);for(const c of o)n.add(c)}catch{}
  const a=[],s=t0e();  // t0e() = <userData>/pending-uploads (offset 2877358)
  for(const o of t){const c=o.startsWith(s),l=await kXe(o);if(!l)continue;
    const u=me.basename(l),h=RXe(u,l,n);n.add(h);const p=me.join(i,h);
    if(c)await $t.rename(l,p);        // files from pending-uploads → MOVE into session
    else try{await $t.link(l,p)}catch(d){if(d.code!=="EEXIST")throw d}  // else HARDLINK
    a.push({hostPath:o,vmPath:`/sessions/${r}/mnt/uploads/${h}`})}
  return{uploadsDir:i,mappings:a}}
```

- Destination: `<sessionStorage>/uploads/` (mounted into VM at `/sessions/<vm>/mnt/uploads/` **mode `ro`**, offset 2924970).
- **Dedup by md5 of file content** — same content → `name-<hash8>.ext` suffix.
- **`rename`** for files already staged in `pending-uploads` (pasted/dropped files, `savePastedFile` offset 3140088 writes `<uuid>-<name>` there), **hardlink** for arbitrary user-picked files — no copy, no mutation of the original.
- **Rejected**: paths outside `realpath(home)` (symlink escapes blocked), non-regular files (dirs, symlinks).
- **Message rewriting**: `sendMessage` and init-time replace host paths with VM paths in the message text: `for(const{hostPath:g,vmPath:m}of v)u=u.replaceAll(g,m)` (offset 2930117) — the agent only ever sees `/sessions/<vm>/mnt/uploads/<name>`.
- The uploads mount is `ro` — the agent **cannot modify or delete** originals through it.

---

## 5. Trusted folders — `Kat` / `localAgentModeTrustedFolders`

**Offsets**: 3277530 (`Ld`, `Kat`), 3279805 (`addTrustedFolder`), 3280078 (`removeTrustedFolder`), 3280144 (`getTrustedFolders`), 3280660 (`isFolderTrusted`), 1307666 (`vi`/`jy`), 369225 (schema), 1305466 (defaults).

```js
// offset 3277530 — prefix matching semantics
function Ld(t){return t.replace(/[\\/]+$/,"")}                    // strip trailing slashes
function Kat(t){const e=vi("localAgentModeTrustedFolders")??[],r=Ld(t);
  return e.some(i=>{const n=Ld(i);return r===n||r.startsWith(n+Ce.sep)})}
```

- **Semantics**: a folder is trusted if it **equals** a trusted entry or is a **strict
  descendant** (`trusted + path.sep` prefix). Parent-trusts-child, not vice versa.
- **Persistence**: settings key `localAgentModeTrustedFolders` in the Electron store
  `preferences` object:
  - reader: `vi = t => {const e=qn().preferences??{}; return HF(e)[t]}` (offset 1307400; zod-validated)
  - writer: `jy=async(t,e)=>{...; const i={...qn().preferences??{},[t]:e}; await Bd("preferences",i)}` (offset 1307666)
  - schema: `localAgentModeTrustedFolders: qe(ie()).optional()` (offset 369225); default `[]`, alongside `secureVmFeaturesEnabled:!0` (offset 1305466).
- **Cap**: 300 entries, FIFO eviction (`o=o.slice(-s)`), dedup on trailing slashes.
- Exposed to renderer via `LocalAgentModeSessions` IPC interface
  (`getTrustedFolders`/`addTrustedFolder`/`removeTrustedFolder`/`isFolderTrusted`,
  offsets 152764–155351) — every call validated by `$eipc_message$` **origin validation** (`Fe(i)`, sender-frame URL check).
- **Scope**: this list is *presentational* (UI trust state for folder picker). It is
  **not** consulted by the file-access gates (`gbe`, `ybe`); those use
  `userSelectedFolders`/`userApprovedFileAccessPaths` instead (see Gaps).

---

## 6. Permissions engine (tool permission requests)

Two near-identical engines exist; the cowork one (offset 2913082) additionally
writes an **audit trail**. `ApprovalRequest` is minified to a plain object `s`.

### 6.1 `handleToolPermission` (cowork, offset 2913082)

```js
async handleToolPermission(e,r,i,n){const a=ri.randomUUID(),
  s={requestId:a,sessionId:e,toolName:r,input:i,suggestions:n},
  o=this.sessions.get(e);
  return this.auditLog(e,{type:"system",subtype:"permission_request",uuid:a,
    session_id:o==null?void 0:o.cliSessionId,tool_name:r,tool_input:i}),
  new Promise(c=>{this.pendingPermissions.set(a,{sessionId:e,toolName:r,input:i,suggestions:n,resolve:c});
    const l={type:"tool_permission_request",sessionId:e,request:s};
    this.emit("event",l),K.info(`Emitted tool permission request ${a} for ${r} in session ${e}`)})}
```

- Each request: `{requestId, sessionId, toolName, input, suggestions}`; resolver held
  in `pendingPermissions` map; emitted as **`tool_permission_request`** event.
- `suggestions` = permission updates the caller wants applied if the user picks "always"
  (from `canUseTool` hooks; e.g. the wrapper at offset 2920819 passes
  `{...Ue,_folderName:Pt}` suggestions for `allow_cowork_file_delete`).

### 6.2 `respondToToolPermission` — the decision state machine (offset 2913700)

```js
async respondToToolPermission(e,r,i){const n=this.pendingPermissions.get(e);if(!n){...return}
  this.pendingPermissions.delete(e);const a=r;let s;
  switch(a){
    case"deny":{const c=xXe(n.input);
      s={behavior:"deny",message:`User rejected ${EXe(n.toolName)} ${c}. Please acknowledge this and suggest alternative approaches.`,interrupt:!1};break}
    case"once":s={behavior:"allow",updatedInput:i??n.input};break;
    case"always":{s={behavior:"allow",updatedInput:n.input,updatedPermissions:n.suggestions};break}
    default:s={behavior:"deny",message:"Unknown decision"}}
  const o=this.sessions.get(n.sessionId);
  if(this.auditLog(n.sessionId,{type:"system",subtype:"permission_response",uuid:e,
      session_id:o==null?void 0:o.cliSessionId,tool_name:n.toolName,decision:a,granted:s.behavior==="allow"}),...)
  n.resolve(s)}
```

| Decision | Result | Effect |
|---|---|---|
| `deny` | `behavior:"deny"`, interrupt message (tool+param via `xXe`) | tool call blocked; agent instructed to suggest alternatives |
| `once` | `behavior:"allow"` (+ optional edited input `i`) | one-time allow, **no persistence** |
| `always` | `behavior:"allow"` + `updatedPermissions: suggestions` | suggestions (tool+input rules) applied by the **SDK/CLI permission layer** as persistent overrides — the engine itself keeps no allowlist |
| unknown | deny | fail closed |

**Audit**: every request+response is appended to `<sessionStorage>/audit.jsonl`
(logger `qQe`, offset 2869110; writer `auditLog`, offset 2906964; file
`audit.jsonl`, 50 MB max, tailing rotate; entries carry `_audit_timestamp`).

### 6.3 Session permission flags

`sessionBypassPermissionsMode` and `sessionTrustAccepted` exist only in the **SDK
session-state defaults** (offset 1684635, both `false`). The cowork engine never
sets them to true in this bundle — i.e. **no bypass mode is reachable from Cowork
tool flow**; every tool goes through `canUseTool` → `handleToolPermission`.

### 6.4 Notification flow — `showPermissionRequestNotification` (offset 3084591)

```js
async showPermissionRequestNotificationAsync(e){var g,m;
  if(!this.isInitialized){K.warn("NotificationService not initialized, skipping notification");return}
  const{requestId:r,sessionId:i,toolName:n,description:a,cwd:s,sessionTitle:o}=e;
  const c=this.mainView?.webContents?.getURL()??"";
  if(this.isAppFocusedAndVisible()&&c.includes(i)){K.debug("Skipping permission notification - user is viewing this session",...);return}
  const u=Lse(n), ... v=this.buildPermissionBody(u,a);
  this.useSwiftNotifications&&ii ? ii.notifications.show({id:`permission-${r}`,title:p,subtitle:d,body:v,
      threadId:"claude-code-permissions",userInfo:{type:"permission_request",sessionId:i,requestId:r},
      categoryId:"PERMISSION_REQUEST"})
    : this.showElectronNotificationWithTitle(e,p)}
```

- Skipped when the app is focused **and** the session is already on screen.
- macOS Swift notifications (`@ant/claude-swift`, category `PERMISSION_REQUEST`);
  Electron fallback with an **"Allow once"** action button (offset 3085233) that
  resolves to `allow_once`; click → navigate to `/claude-code-desktop/<session>`.
- Body: `buildPermissionBody` = `"Allow Claude to ${Run|Read|Write|Edit|Search|Fetch|...} ${truncated-100}?"` (offset 3085902).
- Renderer wiring (offset 3137263): `h.type==="tool_permission_request"&&h.request` →
  description via `Zrt(toolName,input)` (extracts `command/file_path/path/pattern/query/url/prompt/description`, offset 3081584) → `oc.showPermissionRequestNotification(...)`.
- Renderer responses come back over IPC `respondToToolPermission(requestId, decision, updatedInput?)` (offset 3277700 region, `Wat` interface).

### 6.5 Cowork tool wrapping (`canUseTool`, offset 2920514)

```js
canUseTool:async(ke,Ue,{suggestions:Qe})=>{let ot=Ue;
  if(ke==="mcp__cowork__allow_cowork_file_delete"){const bt=this.sessions.get(e),Lt=Ue.file_path;
    let Pt="workspace"; if(Lt&&(bt!=null&&bt.vmProcessName)){
      const ir=me.relative(yn.homedir(),this.getOutputsDir(e,bt.sharedCwdPath)),
            Mr=e0e(Lt,bt.vmProcessName,bt.userSelectedFolders??[],ir);
      Mr&&(Pt=Mr.name)} ot={...Ue,_folderName:Pt}}
  return this.handleToolPermission(e,ke,ot,Qe)},
permissionMode:"default", settingSources:["user"], includePartialMessages:!0,
```

- `permissionMode: "default"` → every tool call prompts.
- Only **these** tools are enabled in the SDK query (offset 2920501):
  `["Task","Bash","Glob","Grep","Read","Edit","Write","NotebookEdit","WebFetch","TodoWrite","WebSearch","Skill","mcp__mcp-registry__search_mcp_registry","mcp__mcp-registry__suggest_connectors","mcp__cowork__create_knowledge_base"]`
  (note: the cowork directory/delete tools are MCP tools on the `cowork` server `O.cowork=Ur` — `rx({name:"cowork",version:"1.0.0",tools:[request_cowork_directory, allow_cowork_file_delete]})`, offset 2875904).

---

## 7. Knowledge bases — `create_knowledge_base`

**Offsets**: 2869043 (`Xye` = `null` stub), 3143340 (wiring), 2927846 (mounting), 2928007 (telemetry), 2902348 (prompt), 2869871 (`Vie` slugger, `zQe` mount naming), 2931119 (stats telemetry).

- **Registration**: the MCP tool `mcp__cowork__create_knowledge_base` is allowed in
  `allowedTools`; the tool itself is created by **`createLocalKBsApi`**, an injected
  factory:
  ```js
  // offset 3143340
  const{getKnowledgeBaseManager:a,getCreateLocalKBsApi:s}=await Promise.resolve().then(()=>VQe),
        [o,c]=await Promise.all([a(),s()]);
  o&&c?(w_.for(e.webContents).setImplementation(c(t)),
    o.on("kb-file-changed",h=>{...dispatchOnLocalKBFileChanged(h)}),
    o.on("kb-list-changed",()=>{...dispatchOnLocalKBListChanged()}))
    : w_.for(e.webContents).setImplementation({list:()=>[],get:()=>null,
      create:()=>{throw new Error("LocalKBs not available in this build")},...})
  ```
  In this bundle `Xye()` **returns `null`** (offset 2869043), so the real KB manager
  (indexer/mounter) is **external** (separate module/plugin injected at runtime).
- **Mounting into the VM** (session init, offset 2927846):
  ```js
  for(const ke of V){const Ue=await Y.getKnowledgeBasePath(ke.kbId);
    if(Ue){await Y.generateMetadataFiles(ke.kbId);
      const Qe=me.relative(yn.homedir(),Ue);
      he[`.knowledge/${ke.mountName}`]={path:Qe,mode:"rw"};   // ← READ-WRITE mount
      ye.push(ke.kbId),ue.set(ke.mountName,Ue),
      K.info(`[LocalAgentModeSessionManager] Mounting KB ${ke.kbId} at /mnt/.knowledge/${ke.mountName}`)}
    else K.warn(`... KB ${ke.kbId} not found, skipping mount`)}
  ```
  → KBs are mounted **`rw`** at `/sessions/<vm>/mnt/.knowledge/<mountName>` —
  notably **wider** than uploads (`ro`).
- **Mount-name generation**: `zQe` slugifies name/id (`Vie`: lowercase, non-alnum→`-`,
  ≤60 chars, dedup `-2` suffix; offsets 2869871/2870700).
- **Prompt injection** (offset 2902348): `<knowledge_base>` blocks
  `<id>/<name>/<description>/<location>/sessions/<vm>/mnt/.knowledge/<mountName>/` appended
  to the system prompt.
- **Telemetry** (offset 2928007): `gr("local_kb_session_mounted",{kb_count,total_file_count,total_size_bytes})`
  via `Y.getKBStats(kbId)` → `{fileCount,totalSize}`; and `startWatching(kbId)` per KB
  (emits `kb-file-changed` → forwarded to renderer). Periodic stats:
  `gr("local_kb_session_stats",{kb_count,total_kb_file_changes,kbs_with_changes,...})` (offset 2931119).
- VM path mapping: `.knowledge/<mountName>/...` resolves back to host via
  `knowledgeBasePaths` map (`$g`, offset 2871150).

---

## 8. Session isolation (VM-side design)

**Offsets**: 2850335 (`SwiftVM` load), 2857004 (`TQe` spawn config), 2858035 (spawn call), 2923900–2925100 (mounts map), 2899359 (seccomp classifier), 2854109 (guest), 2920911 (env), 2915800 (`Starting local session ${e} in /home/${i}`).

- **One VM process per session**: `vmProcessName` (minified `i`), session ids `local_*`
  (`_M="local_"`, offset 2897268); unique-name generator caps at 100 attempts
  (offset 2868700, name = `<slug>-<n>`).
- **Spawn** (host → native): `o.spawn(processId, processName, cmd, args, cwd, env, mounts, additionalMounts, isResume, allowedDomains, sharedCwdPath)` (offset 2858035).
  CLI cwd: `/sessions/<name>`; executable `/usr/local/bin/claude` (offset 2920310);
  session user home: **`/home/<name>`** (offset 2915780).
- **OAuth**: `CLAUDE_CODE_OAUTH_TOKEN` is pre-approved into the VM's **MITM proxy**
  (`addApprovedOauthToken`, offset 2857841) — the token never reaches the CLI directly;
  the proxy authenticates on its behalf.
- **Egress**: `allowedDomains` = `egressAllowedDomains` (from session start input, offset 106908, `string[]`) passed to the VM spawn — **enforced VM-side** (native); there is **no host-side domain validation** in this bundle. `allowedDomains=0` is logged at spawn (`allowedDomains=0`, offset 2857004). MitM proxy + domain allowlist ⇒ egress control is part of the native VM.
- **Mount matrix** (session spawn, offset 2923900 ff.) — the host mounts each as `{path: relativeTo(home), mode}`:

| VM path | Host source | Mode | Purpose |
|---|---|---|---|
| `/mnt/<firstSelectedFolderName>` (or `outputs`) | user-selected folder | `rw` → `rwd` if in `fileDeleteApprovedMounts` | workspace (offset 2924083) |
| `/mnt/.claude` | `<storage>/.claude` | `rwd` | `CLAUDE_CONFIG_DIR` (config, sessions, projects, CLAUDE.md) |
| `/mnt/.skills` | skills plugin dir | `ro` | plugins/skills (offset 2923950) |
| `/mnt/.plugins` | remote plugins dir | `ro` | (offset 2923960) |
| `/mnt/.local-plugins` | local plugin cache | `ro` | (offset 2924040) |
| `/mnt/uploads` | `<storage>/uploads` | `ro` | uploads staging (offset 2924970) |
| `/mnt/.projects/<uuid>` | `<storage>/.projects/<uuid>` | `ro` | attached project contexts (offset 2924980) |
| `/mnt/.knowledge/<mountName>` | KB root | `rw` | knowledge bases (offset 2927870) |

  → **Writable by the agent**: user-selected folder (rw/rwd), `.claude`, KBs.
  **Read-only**: skills, plugins, uploads, projects.
- **No `unprivileged`/uid/user switching in this bundle**: no evidence of per-session
  Unix user, no chroot. Isolation = mount namespacing + native VM. `seccomp` appears
  only in the SDK **error classifier** (`apply-seccomp`+`Killed` → `seccomp_killed`,
  offset 2899359) — i.e. seccomp exists **inside the VM runtime**, enforced natively.
- **Guest**: VM boot waits for guest connection (offset 2865437); `guestConnectionChanged`
  drives clean shutdown (offset 2854109). `Disconnected from guest` → `vm_disconnected`
  (offset 2899980).
- **Workspace perms**: outputs dir auto-created (offset 2907965); shared CWD
  `~/Documents/Claude` created if `sharedCwdPath` requested (offset 2923040).
- **Env injected into the CLI** (offset 2920880):
  `CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS:"true"`, `CLAUDE_CONFIG_DIR:/sessions/<i>/mnt/.claude`,
  `CLAUDE_CODE_ENTRYPOINT:"local-agent"`, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS:"1"`,
  `MCP_TOOL_TIMEOUT`, plus `Dye(...)` → `ANTHROPIC_BASE_URL:<server apiHost>`,
  `ANTHROPIC_API_KEY:""`, `CLAUDE_CODE_OAUTH_TOKEN`, `DISABLE_AUTOUPDATER:"1"`,
  `CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL:"true"` (offset 2813577).
- **Hooks**: `PreToolUse` blocks `Task.run_in_background` — "Background agents disabled" (offset 2921060).
- **File watcher**: `ZQe` watches the workspace dir (offset 2876030) emitting
  `fs_file_created`/`fs_file_deleted` events; dotfiles ignored.
- **Audit file**: per-session `audit.jsonl` (50 MB, tailable) in session storage (offset 2869110).
- **Session persistence**: `<userData>/<baseDir>/<accountId>/<orgId>/<sessionId>.json`
  (`getStorageDir`, offset 2907612) — approvals, mounts, KBs, `fileDeleteApprovedMounts`,
  `userApprovedFileAccessPaths` all persist here.

---

## 9. Trust & safety flows

### 9.1 Trusted-folder UX
`isFolderTrusted`/`addTrustedFolder`/`getTrustedFolders` (offsets 3280144–3280840, IPC 152764–155351) back the renderer folder picker; the picker enforces the same home confinement as the tool (`Qye`, offset 3139278) and can auto-trust. Prefix semantics `Kat` (§5).

### 9.2 Workspace trust (separate "Claude Code desktop" engine, `pM="local_"` offset 2816022)
- `checkWorkspaceTrust` (offset 2822600): trusted iff `nYe(cwd)` — global `bypassPermissionsModeAccepted` **or** any ancestor dir has `hasTrustDialogAccepted` in settings `projects` (offset 2639803).
- `startSession` throws `XJe`/`WorkspaceTrustError` if untrusted (offset 2823400).
- `saveWorkspaceTrust` → `Cne` writes `hasTrustDialogAccepted:!0` (offset 2640300).
- **The cowork engine does NOT use workspace trust** — its trust surface is folder
  selection + per-file consent + per-mount delete approval instead.

### 9.3 Deletion protection ("explicit permission before permanent delete")
- Default mount mode `rw` (not `rwd`) — `rm` inside the VM fails with "Operation not permitted" until the agent calls `allow_cowork_file_delete`, which re-mounts **that mount only** as `rwd` and records it (offsets 2924083, 2926167).
- Uploads/`.projects`/skills/plugins are permanently `ro` — undeletable and unmodifiable from the VM.

### 9.4 Instruction injection (the agent's knowledge of its own permissions)
System-prompt builder `IXe` (offset 2900661) substitutes:
- `{{cwd}}` → `/sessions/<vm>`
- `{{workspaceFolder}}` → `/sessions/<vm>/mnt/<firstFolder>` else `mnt/outputs`
- `{{workspaceContext}}` →
  `"Claude has access to the folder the user selected and can read and modify files in it."`
  **or** `"Claude does not have access to the user's files. Claude has a temporary working folder where it can create new files for the user to download."`
- `{{folderSelected}}` → `yes|no`; `{{userSelectedFolders}}`, `{{skillsDir}}`,
  `{{modelName}}`, `{{accountName}}`, `{{emailAddress}}`, `{{currentDateTime}}`
- Appends: attached-projects block (offset 2891056), `<knowledge_base>` blocks (§7),
  skills system prompt (offset 2902480), and the prompt fragment
  `[use the request_cowork_directory tool to ask for which directory to work in]`
  (offset 2902950).
- **Global/folder instructions**: no `instructions`/`CLAUDE.md` key exists in
  Cowork preferences; folder instructions are absorbed **inside the VM** by the CLI
  from the mounted `.claude` dir (`CLAUDE_CONFIG_DIR=/sessions/<i>/mnt/.claude`,
  mounted `rwd` from `<storage>/.claude`). `systemPrompt` param (user-defined, e.g.
  from renderer) is passed through verbatim into `IXe` (offset 2919600).

### 9.5 Session lifecycle guards
- `stopSession` on quit; VM bundle hash pins `pi="8c56966..."`, `fy="6747d61..."` (offset 2857000, integrity).
- Startup gates: `isClaudeCodeForDesktopEnabled` (org policy, offset 2952650), `secureVmFeaturesEnabled` (user pref, default true, offset 1305466/2952954), platform (no Windows ARM64 / macOS only VM, offset 2952800).
- IPC boundaries: all `LocalAgentModeSessions` methods behind `$eipc_message$` handlers with sender-frame origin validation (offset 153441 ff.).

---

## 10. Gaps / enforced elsewhere / unknowns

1. **KB implementation external**: `create_knowledge_base` tool body, indexing logic,
   `getKBStats` internals, `generateMetadataFiles` are **not in this bundle**
   (`Xye()` → `null`, offset 2869043). Only the mount (`rw`!), prompt injection and
   telemetry call sites are visible. **Highest-value gap**: KB directories are
   mounted `rw` without an in-bundle approval gate.
2. **Egress enforcement is native**: `allowedDomains` is passed to `SwiftVM.spawn`
   (offset 2858035); no host-side domain list validation, no JS enforcement of
   network policy, no per-connection allowlist logic visible.
3. **Seccomp/uid confinement**: no per-session uid/user creation or chroot in JS;
   `seccomp_killed` only surfaces in the error classifier (offset 2899359). Real
   syscall policy lives in the VM bundle (separate download: `vm_bundles/claudevm.bundle`,
   offset 2863200).
4. **"always" persistence lives in the SDK/CLI**: `respondToToolPermission("always")`
   returns `updatedPermissions:suggestions` to the CLI process; the desktop engine
   keeps no own always-allow store. The CLI's own permission store (inside the VM,
   `.claude` config) is not inspectable from this bundle.
5. **Trusted-folder list ≠ authorization**: `localAgentModeTrustedFolders` is not
   consulted by `gbe`/`ybe`; authorization state is `userSelectedFolders` +
   `userApprovedFileAccessPaths` + `fileDeleteApprovedMounts` (per-session JSON).
6. **`sessionBypassPermissionsMode`/`sessionTrustAccepted`** are SDK defaults only
   (offset 1684635); nothing in cowork toggles them — if the SDK session were resumed
   with a previously-set bypass, this bundle would not see it.
7. **Folder trust auto-add on mount?**: `request_cowork_directory` calls
   `addUserSelectedFolder` (session state) but **not** `addTrustedFolder` (settings);
   renderer-side picker may add trust separately (offset 3139278).
8. **Shared CWD `~/Documents/Claude`** is auto-created and is a permanent host-side
   allow-root for `gbe` (offset 3284700 list) — implicit trust surface.
9. **Session JSON on disk** stores approvals + tokens-adjacent data (`CLAUDE_CODE_OAUTH_TOKEN`
   is env-only); audit trail in `audit.jsonl`; no in-bundle encryption of session files.
10. **MCP servers**: user/remote MCP servers proxied (`filterFilesystemMcp:!0`
    drops filesystem MCP servers, offset 2921620; `ProxyMcpServerManager` offset 2807105);
    MCP tools available to subagents (`CLAUDE_CODE_ALLOW_MCP_TOOLS_FOR_SUBAGENTS:"true"`).
