# Claude Cowork — VM Layer Reverse Engineering

**Target**: Claude Desktop app 1.1.673 (build `index.js`, 3,289,071 bytes), VM rootfs image (`rootfs.img` v1.0.0 of the bundle), Apple Virtualization.framework Linux guest.
**Source**: `/tmp/claude-asar/app/.vite/build/index.js` (minified) + `/tmp/rootfs.ext4` (extracted to `/tmp/rootfs_out`, native Go binaries dumped to `/tmp/vmbin/`).
**Date**: 2026-08-06. All byte offsets are into the minified `index.js` file.

---

## 1. Executive summary

- The desktop app drives a **Linux VM (Ubuntu 22.04.5 ARM64) via the native addon `@ant/claude-swift`** (Swift framework bridge). The addon exposes two namespaces: `vm` (VM lifecycle/process control over vsock) and `desktop` (read open documents).
- The VM image (`rootfs.img`) is **fully self-contained and baked** for tooling but does **not** contain the Claude Code agent. **Claude Code (v2.1.15 for linux-arm64) is installed at boot by the app via `installSdk` → sdk-daemon writes it to `/usr/local/bin/claude`**.
- In-VM architecture: `sdk-daemon` (Go, systemd service) = vsock RPC bridge + MITM proxy + session-disk manager; `sandbox-helper` (Go, seccomp) + `/etc/srt-settings.json` = per-process network/filesystem sandbox (allowlist + mitm of *.anthropic.com); `@anthropic-ai/sandbox-runtime` (srt, npm) = process sandbox wrapper.
- Mount model: **`/sessions/<vm-process-name>/mnt/`** is created at runtime by sdk-daemon; each mount is a bind of a host directory (outputs, uploads, user-selected folders, `.knowledge/<id>`, shared cwd). The image ships an **empty** `/workspace` (uid 1000) and **no** `/sessions` — both are runtime constructs. Session data persists on **per-session virtio NVMe disks** formatted ext4 by the daemon.
- Bundle versioning: `pi = "8c56966fa5825aba21d51a59e8a505b849e14f41"` (bundle hash), rootfs.img.zst SHA-256 `fy = 6747d61d...d06d1`, download base `https://downloads.claude.ai/vms/linux/<hash>/`. VM image build date ≈ **2026-01-15** (filesystem mtimes), matching the "VM built ~2026-01-15" note.

---

## 2. App-side VM orchestration (byte offsets)

### 2.1 `@ant/claude-swift` module loading — `Uye` / `_i`

```
async function Uye   @ 2850032   — lazy singleton import of "@ant/claude-swift"
async function _i    @ 2850329   — returns (await Uye()).vm ?? null
_i.getCached         @ 2850360   — sync cached access
async function gQe   @ 2850374   — returns Uye() (full module, used for .on("guestConnectionChanged"))
```

- Logger prefix `[COWORK_VM]`, log level driven by `hQe` (verbose) — winston-based.
- On failure: `"[SwiftVM] Failed to load module: %o"` → returns `null` (callers fail with "Swift VM addon not available").
- Instance id: `Ha()` = `bi.randomUUID()` (reset `yQe()` on shutdown), used in telemetry `gr("lam_vm_...", {vm_instance_id: Ha()})`.

### 2.2 VM process abstraction — `_Qe` (CoworkVMProcess)

```
class _Qe extends Pa.EventEmitter @ 2850654
```

- Registry `fc = new Map` (id → process), active counter `Bw`, global emitter `YL` (also carries `networkStatus` / `guestConnectionChanged` events).
- **State**: `id` (uuid), `name`, `_killed`, `_exitCode`, `_wasKilled`, `_spawnConfirmed`, `_stdinBuffer[]`, `_stdin/_stdout` PassThrough streams.
- `setupStdinForwarding()` @ 2852448: `stdin.on("data")` → if `!_spawnConfirmed` **buffer** (`"Buffering stdin (spawn not yet confirmed)"`); else `_i().then(vm => vm.writeStdin(id, chunk))` (error → `emit("error")`). Buffer is flushed by `confirmSpawn()` → `flushBufferedStdin()` on the first `stdout`/`stderr` event from the VM (i.e. spawn confirmation is inferred from first output).
- `kill(signal)` @ ~2852100: sets `_wasKilled`, calls `vm.kill(id, signal)`, marks `_killed`.
- `setExited(code, signal)`: if was-killed → exitCode 0; emits `exit`; telemetry `lam_vm_process_exited`.
- `setError(err, telemetryName)`: emits `error`; telemetry `lam_vm_runtime_error`.
- `cleanup()`: removes from registry.

### 2.3 Spawn flow — `TQe` (createVMSpawnFunction) / `AQe`

```
function TQe    @ 2856761  — factory: returns async spawn fn bound to a spawn-config
async function AQe @ 2857580 — performs the actual vm.spawn
```

- Config log: `"[Spawn:config] Creating spawn function for process=..., isResume=..., mounts=N (...), allowedDomains=N"`.
- On spawn: creates `_Qe` (uuid id, processName), sets up stdin forwarding, filters env (`undefined` values dropped; sensitive values not logged).
- `AQe` (offset 2857580):
  1. if env has `CLAUDE_CODE_OAUTH_TOKEN` → `await vm.addApprovedOauthToken(token)` — *token approved with the in-VM MITM proxy*.
  2. `await vm.spawn(id, processName, command, args, cwd, env?, additionalMounts, isResume, allowedDomains, sharedCwdPath)`
  3. `confirmSpawn()`; telemetry `lam_vm_process_spawned` (mount_count).
- `l_()` @ 2858453: `vm.isGuestConnected()`. Exported module `PQe` @ 2858574: `{createVMSpawnFunction, isVMGuestConnected}`. `IQe()` @ 2858674 returns `pi` (bundle version).

### 2.4 Event callbacks — `Vye` / `bQe`

```
function Vye @ 2853078 — memoized; async function bQe @ 2853118
```

- `vm.setEventCallbacks(stdoutFn, stderrFn, exitFn, errorFn, networkStatusFn)`:
  - stdout/stderr: `fc.get(processId)?.pushStdout(chunk)`
  - exit: `setExited(processId, exitCode, signal)`
  - error: `setError(processId, message)`
  - networkStatus: `De.info("[VM] Network status: ...")` + `YL.emit("networkStatus", status)` — statuses seen: `"CONNECTED"`, `"NOT_CONNECTED"` (used in `NQe` @ 2859480: shows `network_connection_failed` startup error after `Lie = 30s` if not connected).
- `r.on("guestConnectionChanged", ...)` @ 2853580:
  - `false` (disconnect):
    - if `lh()` (app in graceful-quit): cleanly `setExited(0, null)` all active processes.
    - else: **SIGKILL all active processes** (`setExited(null, "SIGKILL")`) — "Guest disconnected unexpectedly".
  - `true` (connect): closes idle notification for session.

### 2.5 VM lifecycle — `FQe` (startup), `i6` (startVM wrapper)

```
const jie = 60e3  @ 2863107 — guest-connection timeout (60s)
const DQe = 500   @ ~2863156 — poll interval (500ms)
const LQe = 4     @ ~2863156 — default memoryGB (4)
function FQe @ 2863158; async function i6 @ 2866479
```

**Step 1/4** (~2863190): `Promise.all([Wye(downloadBundle), pl.prepareForVM()])` — bundle download + host-side SDK (claude binary for linux-arm64) preparation in parallel; both must succeed.

**Step 2/4** (~2863400): `_i()` load Swift VM API; failure → telemetry `lam_vm_startup_failed` `failed_step:"swift_api"`.

**Step 3/4** (~2864115 → registers app-quit hook): registers `jl({name:"cowork-vm-shutdown", fn: stopVM})` (offset 2864115) then
`h = (options?.memoryGB) ?? LQe` (4 GB default); `await vm.startVM(bundlePath, memoryGB)`; UI status → `pp.Booting`. Telemetry `lam_vm_shutdown_completed` on quit.

**Step 4/4** (~2864380): poll `l_()` every 500ms up to 60s (progress log every 10s: `"Still waiting for guest connection..."`). On success:
```
C = pl.getVMStorageSubpath(); E = pl.getRequiredVersion();
await vm.installSdk(C, E)   // "[VM:start] Installing SDK: subpath=..., version=..."
```
UI → `pp.Ready`; telemetry `lam_vm_startup_completed`. On timeout:
- runs `xQe()` network diagnostics (VPN detection), fails with `"VM connection timeout after 60 seconds"`, telemetry `error_type: "vpn_routing_conflict" | "connection_timeout"`, `failed_step:"guest_connection"`.

**Network diagnostics** (`xQe` @ 2855732, `wQe` @ 2854193, `SQe` @ 2854450, `EQe` @ 2854745):
- `wQe`: runs `/sbin/ifconfig` → regex `^(utun\d+|ppp\d+|ipsec\d+|tun\d+):` (VPN interfaces).
- `SQe`: runs `/usr/sbin/scutil --nc list` → connected VPN names.
- `EQe`: comprehensive dump — ifconfig, pgrep bootpd, ifconfig -a, scutil --nwi, `kextstat -b com.apple.vmnet`, `log show --predicate "process == 'bootpd' OR subsystem CONTAINS 'vmnet'" --last 5m`.
- `CQe` @ 2856205: user-facing VPN warning string; `$Qe` @ 2856429: diagnostics formatting.

### 2.6 VM bundle manager

```
const RQe = "vm_bundles"         @ 2858699  — bundle root under userData
const kQe = "claudevm.bundle"    @ ~2858710 — bundle dir name
const Bie = https://downloads.claude.ai/vms/linux/${pi}  @ 2859795
const Hye = ["rootfs.img"]       @ 2859851
pi = "8c56966fa5825aba21d51a59e8a505b849e14f41"          @ 2856648
fy = "6747d61d16c37826dbdf885649853d98df606bebe2491707de01145dc75706d1" @ 2856695 (rootfs.img.zst SHA-256)
```

- Bundle paths: `Gye()` @ 2862677 = `userData/vm_bundles`; `u_()` @ 2862742 = `.../vm_bundles/claudevm.bundle`.
- **Integrity model** (`Kye` @ 2859870): each file must exist **plus** a `.origin` marker file whose content equals `pi`. States: `missing`, `origin_missing`, `version_mismatch` → re-download. On `version_mismatch` the old file is deleted first ("Deleting old rootfs.img to free disk space").
- **Download** (`MQe` @ 2860422, `Wye` @ 2862428): zstd HTTP download via electron `net.fetch`-style helper `Cl({..., transform: createZstdDecompress(), computeHash: true})` → **SHA-256 checked against `fy`** → `"Checksum mismatch for rootfs.img.zst"` throws. Writes `.rootfs.img.origin` after success. Temp dir `wvm-*` under tmpdir. Progress → renderer `dispatchDownloadProgress`. Telemetry `lam_vm_bundle_download_completed/failed` with `download_reason: missing|origin_missing|version_mismatch`.
- **Warm bundle** (`mbe` module): `Nat="warm"` @ 3271556, `H6()` @ 3271594 = `userData/vm_bundles/warm`; warm file name = `rootfs.img.zst.<sha>` (`D4="rootfs.img.zst."`). `Dat` @ 3271732: **fetch VM hash for a Claude release version** from `https://downloads.claude.ai/releases/darwin/universal/<version>/vm_hash` (40-hex). `Lat` @ 3272263: warm download of `rootfs.img.zst` for that SHA. `Fat` @ 3273108: cleanup of stale warm files. `Bat` (promoteWarmBundle) @ 3273551: stream-decompress warm file into the bundle's `rootfs.img` while hashing (digest must equal `fy`), then write `.rootfs.img.origin`; deletes the warm file. `jat` (maybeWarmDownloadForUpdate) @ 3274985: gated on `autoDownloadInBackground` (from YukonSilver config) and yukonSilver status `"supported"`; skips if hash == current `pi`.
- `qE()` @ 2862812: bundle-ready check; `Yye()` @ 2862875: download-in-progress; `Jye()` @ 2862907: delete bundle dir.
- **cleanupVMBundleIfUnsupported** (`Yat` @ 3281664): if yukonSilver status != "supported" → delete stale bundle (skips while download in progress).
- **Dev menu** (`zat` @ 3276123): "Start Cowork VM" (calls `i6` with progress logging), "Show Debug Window" / "Hide Debug Window" (`vm.showDebugWindow()/hideDebugWindow()`), "Stop Cowork VM" (`vm.stopVM()`).
- **Delete VM bundle** (`yet` @ 2965322): confirm dialog → stopVM → delete bundle → app relaunch. **Delete VM Sessions** (`_et`): dialog "Delete VM Sessions and Restart" → deletes local-agent-mode session data → relaunch.

### 2.7 Claude Code (SDK) manager — `oze` / `pl`

```
class oze @ 1917378; const pl = new oze @ 1922928
const aze = "https://downloads.claude.ai/claude-code-releases" @ 1917299
function WCe @ 369631 — embedded manifest
```

- Embedded manifest (`WCe`): **Claude Code v2.1.15**, buildDate **2026-01-21T21:27:03Z**; linux-arm64 binary checksum `20a520256b78aff56d4273d618c97965913e041a850fe6ceab9b714f57e39554`, size 210,961,746 (also darwin-arm64/x64, linux-x64, musl variants, win32-x64).
- Host storage: `userData/claude-code`; **VM storage: `userData/claude-code-vm`** (`vmStorageDir`), platform `linux-arm64`, binaryName `claude`.
- `binaryExistsForTarget`: requires executable + `.verified` marker file (both host & VM target).
- `downloadBinaryForTarget`: GET `<aze>/<version>/<platform>/claude` → sha256 verify against manifest → chmod 0755 → write `.verified` → cleanup old versions.
- `prepareForVM()`: prepares VM target; on success writes `.sdk-version` file containing the required version into `claude-code-vm/`.
- `getVMStorageSubpath()`: `vmStorageDir` relativized against `os.homedir()` (because the VM mounts the host home dir) — e.g. `Library/Application Support/Claude/claude-code-vm`.
- `getRequiredVersion()` → `2.1.15`.

### 2.8 Swift API surface (as called by the app)

| Method | Call sites | Notes |
|---|---|---|
| `vm.startVM(bundlePath, memoryGB)` | @ 2864260 | bundlePath = `claudevm.bundle` dir; default 4 GB |
| `vm.stopVM()` | @ 2864140, 2965162, 3280820 | shutdown hook + dev menu + delete flows |
| `vm.kill(processId, signal)` | `_Qe.kill` @ ~2852130 | |
| `vm.writeStdin(processId, data)` | flushBufferedStdin @ 2850920, setupStdinForwarding @ 2852448 | |
| `vm.spawn(processId, processName, command, args, cwd, env?, additionalMounts?, isResume?, allowedDomains?, sharedCwdPath?)` | @ 2857800 | |
| `vm.addApprovedOauthToken(token)` | @ 2857730 | approves CLAUDE_CODE_OAUTH_TOKEN with in-VM MITM proxy |
| `vm.mountPath(processId, subpath, name, mode)` | @ 2873453 (`"rw"`), @ 2874900 (`"rwd"`) | `request_cowork_directory` / `allow_cowork_file_delete` tools |
| `vm.installSdk(subpath, version)` | @ 2864570 | Step 4/4; subpath=`pl.getVMStorageSubpath()`, version=`pl.getRequiredVersion()` |
| `vm.isGuestConnected()` | `l_` @ 2858453 | 500ms poll |
| `vm.setEventCallbacks(...)` | `bQe` @ 2853118 | stdout, stderr, exit, error, networkStatus |
| `vm.showDebugWindow()` / `vm.hideDebugWindow()` | dev menu @ 3276305 | |
| `module.on("guestConnectionChanged", cb)` | @ 2853580 | via `gQe()` |
| `desktop.getOpenDocuments()` | @ 3137502 | returns docs w/ real filePath; app replaces filePath with random UUID keys before returning to renderer |
| (desktop) readOpenDocumentAsBase64 | @ 3137700 | app reads file at UUID-keyed path, base64-encodes |

Not directly observed in this bundle but implied by sdk-daemon RPC surface: `setDebugLogging`, `isDebugLoggingEnabled` (referenced by a `vmStatus:{isGuestConnected, debugLoggingEnabled}` status object @ ~2965200), `getBundlePath`-like APIs.

### 2.9 Renderer-facing IPC interfaces

- **`claude.web.ClaudeVM`**: `download()`, `startVM(options)` (memoryGB), `getDownloadStatus()` (al: Downloading|Ready|NotDownloaded), `getRunningStatus()` (pp: Booting|Ready|Offline), `setYukonSilverConfig(config)`, `deleteAndReinstall()` (stopVM → delete bundle → relaunch). Wired via `Zat` (handleCoworkVMApi) @ 3280640 with `y0` dispatcher.
- **`claude.web.ClaudeCode`**: `prepare()` (host-side claude binary prep, for local (non-VM) Claude Code usage).
- **`claude.web.OpenDocuments`**: `getOpenDocuments()`, `readOpenDocumentAsBase64(filePath)` — impl @ 3137655 via `h.desktop.getOpenDocuments()`; host paths are masked with `crypto.randomUUID()` keys.
- **`claude.web.LocalAgentModeSessions`**: `start`, `sendMessage`, `stop`, `archive`, `updateSession`, `getSession`, `getAll`, `getTranscript`, ... (@ 142242+; session manager `Wat` @ 3276790 wraps `e.startSession({...sharedCwdPath, egressAllowedDomains, userSelectedFolders...})`).

### 2.10 Session ↔ VM naming and path mapping

- VM process names: `jQe()` @ 2868041 — random `adjective-adjective-scientist` (e.g. `admiring-zen-archimedes`), ≤32 chars, unique across sessions (dedupe set from existing `processName`s @ 2914714). This name = `<vm-process-name>` in all `/sessions/<name>/...` paths.
- **`$g` (vm path → host path)** @ 2539440 (also referenced from 2869991): for `/sessions/<name>/`:
  - `mnt/outputs/...` → `sharedCwdPath/outputs/...` or `sessionStorageDir/outputs/...`
  - `mnt/uploads/...` → `sessionStorageDir/uploads/...`
  - `mnt/<basename-of-user-folder>/...` → that host folder (user-selected)
  - `mnt/.knowledge/<kbId>/...` → knowledgeBasePaths.get(kbId)
  - anything else → `~/<sharedCwdPath>/...`
- **`e0e` (vm path → mount descriptor)** @ 2871685: parses `/sessions/<name>/mnt/` → `{name, subpath}` where subpath is host-path relative to homedir (for `mountPath` calls).
- **`Xat`/`est`** @ 3282582/3282737: `validateVMPathAccess` — enforces `/sessions/<vmProcessName>/` prefix, session must start `local_`, blocks `.exe/.com/.msi/.bin/.app/.dmg/.pkg/.jar` reads; script-ext list `tst` (sh/bash/zsh/js/py/...) for execution permissions.
- Shared CWD: `sharedCwdPath` defaults to **`~/Documents/Claude`** (created host-side @ 2922608); fallback mount name "workspace" (@ 2920271). `getOutputsDir` @ 2907965: `~/<sharedCwdPath>/outputs` (created).
- Cowork tools (`GQe` @ 2871685 area): `request_cowork_directory` → dialog picker (must be inside homedir, `Qye` realpath check) → `mountPath(id, relpath, basename, "rw")` → appears at `/sessions/<name>/mnt/<basename>`; `allow_cowork_file_delete` → re-mount with mode `"rwd"` (w = write, d = allow delete).

---

## 3. Rootfs inventory (`/tmp/rootfs.ext4` → `/tmp/rootfs_out`)

### 3.1 OS & identity

- Ubuntu **22.04.5 LTS (Jammy)**, `/etc/os-release` (symlink → /usr/lib/os-release); kernel `6.8.0-90-generic` ARM64 in /boot (initrd 165 MB, grub). `/etc/debian_version` oddity: `bookworm/sid` (base image artifact).
- **hostname `claude`**, machine-id `2ab48afa64e34889ac3c1d80eca0e7e8`.
- Image is a **cloud-init (NoCloud) Ubuntu cloud image**: `/var/lib/cloud/instances/claude-1` (instance-id `claude-1`), datasource `DataSourceNoCloud [seed=/dev/vda]` — **the app feeds cloud-config via a vda seed disk at runtime**. Baked default first-boot config: user `ubuntu`/`ubuntu` (plain_text_passwd), ssh_pwauth true, `sudo ALL=(ALL) NOPASSWD` — content in `/var/lib/cloud/instances/claude-1/cloud-config.txt`.
- Network (baked network-config.json): `enp0s1`, DHCP4+DHCP6, MAC `52:54:00:12:34:56`.
- **Users** (/etc/passwd): standard + `ubuntu` (uid 1000, /home/ubuntu, bash), `lxd` (999). No root password changes; `/root/.ssh/authorized_keys` and `/home/ubuntu/.ssh/authorized_keys` are **empty files** (image hygiene).
- File-date fingerprint: base layer 3-Dec-2025 (pkgs), cowork runtime bake-in **15-Jan-2026 00:12–00:54**, node binary 12-Jan-2026, claude manifest buildDate 21-Jan-2026 (app-side).
- **1196 dpkg packages**. Notables: bubblewrap, bindfs, open-vm-tools, snapd + snaps (core20, lxd), cloud-init, byobu, ufw, ffmpeg, ghostscript, imagemagick-6, poppler-utils, tesseract-ocr(eng/osd), pandoc, latexmk, libreoffice (writer/calc/impress/draw/math/core), fonts (dejavu, liberation, noto-mono, urw-base35, texgyre...), build-essential, binutils-aarch64, e2fsprogs, dosfstools, bcache/btrfs tools.

### 3.2 Baked-in cowork runtime (all created 2026-01-15)

| Component | Path | Description |
|---|---|---|
| **sdk-daemon** | `/usr/local/bin/sdk-daemon` (6,684,824 B, static Go ARM64, stripped) | vsock RPC daemon; systemd unit `/etc/systemd/system/sdk-daemon.service` (enabled in multi-user.target.wants): `ExecStart=/usr/local/bin/sdk-daemon`, User=root, Restart=always, RestartSec=3, `Environment=HOME=/root`, "Claude SDK Daemon - vsock RPC bridge for process management" |
| **sandbox-helper** | `/usr/local/bin/sandbox-helper` (2,097,304 B, static Go, mode 0700 root) | seccomp/BPF + netlink sandbox enforcer; reads `/etc/srt-settings.json` |
| **srt-settings.json** | `/etc/srt-settings.json` (owned by ubuntu:1000) | network allowlist: registry.npmjs.org, npmjs.com(.org), yarnpkg, pypi.org, files.pythonhosted.org, github.com, archive/security.ubuntu.com, api.anthropic.com, `*.anthropic.com`, anthropic.com, crates.io, index/static.crates.io, statsig.anthropic.com, sentry.io (`*.sentry.io`); `allowLocalBinding: true`; **mitmProxy {socketPath: /var/run/mitm-proxy.sock, domains: [*.anthropic.com, anthropic.com]}**; filesystem `{denyRead:[], allowWrite:["/"], denyWrite:[]}` |
| **Node.js** | `/usr/bin/node` — **v22.22.0** (120,592,136 B), npm 10.9.4 / npx / corepack symlinks (13-Jan-2026) | `nodejs` → node symlink + `/etc/profile.d/nodejs.sh` (15-Jan-2026): PATH `NPM_CONFIG_PREFIX=/usr/local/lib/node_modules_global` |
| **srt (npm)** | `/usr/local/lib/node_modules_global/lib/node_modules/@anthropic-ai/sandbox-runtime` **v0.0.28** | Anthropic Sandbox Runtime; `srt` bin symlink; Linux vendor: bubblewrap-based (`vendor/seccomp/{arm64,x64}` prebuilt helpers) |
| **npm globals** | marked, markdown-toc, ts-node, tsx, typescript, graphviz, docx, pdf-lib, pdfjs-dist, pptxgenjs, sharp + `@anthropic-ai/sandbox-runtime` | doc/slide generation + TS toolchain |
| **Python tool stack** | `/usr/local/lib/python3.10/dist-packages` (556 MB): camelot 1.0.9, fonttools 4.61.1, numpy 2.2.6, pandas 2.3.3, matplotlib, opencv 4.12, onnxruntime, magika 0.6.3, markitdown 0.1.4, pdfplumber 0.11.9, pypdfium2, pikepdf, pypdf, pdfminer.six, tabula-py, pytesseract, pdf2image, img2pdf, pdfkit, reportlab, xlsxwriter, openpyxl, python-docx, python-pptx, odfpy, unoserver 3.6 (LibreOffice bridge), pyoo, seaborn, sympy, beautifulsoup4, lxml, requests, Wand | pip-installed 15-Jan-2026 00:47–00:48; console scripts in `/usr/local/bin` (markitdown, magika, camelot, unoconvert...) |
| **uv** | `/home/ubuntu/.local/bin/uv` + `uvx` (v0.9.25, cargo-dist) + `env`/`env.fish` PATH hook (sourced from `.zshrc`) | `.config/uv/uv-receipt.json`; empty uv cache under `/root/.cache/uv` (CACHEDIR.TAG) |
| **CLI refs** | `/usr/local/bin/normalizer` (charset_normalizer entry), pyftsubset/ttx etc. | pip entry points |
| Shell env | `/home/ubuntu/.npmrc` (`cache=/home/ubuntu/.npm`, `prefix=/usr/local/lib/node_modules_global`), `.bashrc`/`.profile` (15-Jan), `.zshrc` → uv env, `.config/fish`, `.config/uv` | |
| `/etc/profile.d/apps-bin-path.sh` | 21-Nov-2025 | snap XDG paths |
| `/etc/hosts` | stock (localhost + IPv6) — **no proxy entries**; proxy is the vsock-level mitm, not env-configured | |
| `/etc/fstab` | only `LABEL=cloudimg-rootfs` + UEFI vfat — **no session mounts baked** | |

### 3.3 What is NOT in the image (runtime-provided)

- ❌ No `claude`/`claude-code` binary anywhere (find `*claude*` → only cloud-init instance dir). No `/usr/local/bin/claude` — sdk-daemon expects it there post-`installSdk` (string `/usr/local/bin/claude`).
- ❌ No `/sessions`, no `/workspace` content (dir exists, empty, owned 1000:1000), no `.claude` dirs in /root or /home/ubuntu.
- ❌ No `srt`-style session dirs, no user data, no transcripts (`[daemon] loading transcripts from %s` is a runtime path).
- ❌ No claude-code npm global; no CLAUDE_* env in profile.
- ❌ /opt, /srv empty.

---

## 4. Mount model — `/sessions/<name>/mnt/`

**Confirmed by both sides:**

**sdk-daemon logs (strings in binary):**
- `[process:%s] created mnt directory at %s`
- `[daemon] mounting subpath for user %s (uid=%d, mode=%s): %s -> %s`
- `[daemon] mounting shared cwd for user %s (uid=%d): %s -> %s`
- `shared cwd source path does not exist: %s` / `shared cwd bind mount failed: %w: %s` / `[process:%s] mounted shared cwd at %s` / `[process:%s] unmounted %s`
- `bind mount failed: %w: %s` / `failed to create mount point %s: %w` / `failed to chown/chmod mount point`
- `path not within allowed directory: %s` (paths outside `/sessions` rejected)
- `main.mountSubpath`, `main.mountSubpathForUser`, `main.mountSharedCwdForUser`, `main.mountSharedDirectory`, `AddProcessMount`, `cleanupMounts` (Go funcs); RPC `MountPath{Params,Result}`, `MountConfig{mountName, mountPoint, mode, subpath, additionalMounts}` (json tags `mountName`, `mountPoint`, `mode`, `subpath`, `additionalMounts`)

**App side:**
- VM path shape `$g`/`e0e`: `/sessions/<vm-process-name>/mnt/<mountName>/...` where mountName ∈ {`outputs`, `uploads`, `<basename of user-selected host folder>`, `.knowledge/<kbId>`, ...}; subpaths are host-relative paths (bind source), mode ∈ {`rw`, `rwd`} (d = delete enabled).
- `request_cowork_directory` result text: "Mounted directory: Host path: ... → VM path: /sessions/<name>/mnt/<basename>".
- Spawn carries `additionalMounts` + `sharedCwdPath`; default shared cwd `~/Documents/Claude`, mounted as default folder name `workspace`.

**Baked vs runtime:** `/sessions/` **does not exist in the image** — created by sdk-daemon at process spawn (`created mnt directory at %s`). The daemon bind-mounts host dirs into it; the host side also has per-session storage (`sessionStorageDir`, `outputs/`, `uploads/`).

**Session disks (persistence):** separate virtio **NVMe** disks, one per session:
- `main.findNonRootNVMeDisk`, `[daemon] could not find non-root NVMe disk: %v`, `no non-root NVMe disk found`, `[daemon] found session disk %s (root is %s)`, `/dev/nvme0n1`, `/dev/nvme1n1`
- `[daemon] formatting session disk %s with ext4` / `[daemon] session disk already formatted as %s` / `[daemon] session disk formatted successfully` / `failed to format session disk: %w` / `no valid session disk could be found` / `[daemon] session disk already mounted at %s` / `[daemon] session disk %s not found, skipping`
- `failed to read sessions directory: %w` / `[daemon] skipping non-session directory: %s` → daemon enumerates `/sessions` at boot and re-mounts disks for resume (`LoadTranscripts`, `.claude` + `*.jsonl` globs — transcripts read from session disks).

**Other mounts:** `/mnt/.virtiofs-root` (virtiofs root), `[daemon] waiting for IPv4 route` / `[daemon] IPv4 route is available`, `/proc/net/route`, smol-bin update device `/smol/bin` (`MountSmolBin`/`UnmountSmolBin`, `[updater] found smol-bin device: %s` — used to self-update sdk-daemon: `[daemon] restarting to apply sdk-daemon update`), `[daemon] root device is %s`.

---

## 5. In-VM runtime behavior (sdk-daemon & sandbox-helper, from binary strings)

**sdk-daemon** (`sdk-daemon/internal/logger` module path; env `SDK_DAEMON` / `SDK_DAEMON_DEBUG`; startup log `[daemon] connected, waiting for commands`; vsock RPC with net/rpc-style messages; `[rpc] ready event sent`):
- RPC surface (Go net/rpc types): `Spawn{Params,Result}`, `Kill`, `Stdin`, `StdoutEvent{Params}`, `StderrEvent{Params}`, `ExitEvent{Params}`, `IsRunning{Params,Result}`, `MountPath{Params,Result}`, `InstallSdk{Params,Result}` (`sdkSubpath`), `AddApprovedOauthToken{Params,Result}`, `ReadFile{Params,Result}`, `LoadTranscripts{Params,Result}`, `NetworkStatusEvent{Params}`; events `OnLoadTranscripts`, `OnInstallSdk`, `OnMountPath`.
- Process mgmt: `process with name %q already running (id: %s)`, `process %s already exited`, `[process:%s] started PID %d`, `[process:%s] sending %s to PID %d`, `[process:%s] %s read error: %v`, `[process:%s] stdin not available`, user creation per process: `useradd` / `HOME=%s` / `USER=%s` / `useradd failed: %w: %s` / `UID %d already in use by user %s` / `[daemon] user recovery complete: recovered=%d skipped=%d failed=%d` / `/etc/passwd` / `lookup user after creation`.
- **InstallSdk**: writes binary (host sends it; `failed to read/write SDK binary`, `SDK binary not found at %s`, `SDK version %s not verified at %s` — mirror of host `.verified`), target path **`/usr/local/bin/claude`**, installs MITM CA into system trust store (`/usr/sbin/update-ca-certificates`, `update-ca-certificates failed: %w: %s`), spawn env `CLAUDE_CODE_TMPDIR=%s`, `LOGNAME=`.
- **MITM proxy**: `SDK Daemon MITM CA (Ephemeral)`, `[proxy] ephemeral CA generated (expires: %s)`, `[proxy] MITM proxy started on %s` (socket `/var/run/mitm-proxy.sock` per srt-settings), `[proxy] allowing CONNECT to: %s`, `[proxy] blocking request - invalid or missing bearer token` (+ `407 Proxy Authentication Required`, `bearer`, `ENABLE_CONNECT_PROTOCOL`, websockets), `[proxy] CA certificate installed to system trust store`; approved-token map (AddApprovedOauthToken). → **In-VM Claude Code's api.anthropic.com traffic is MITM'd by the daemon; requests require the host-approved OAuth bearer token.**
- Reads/writes `/etc/srt-settings.json` (`read srt-settings: %w`, `write srt-settings: %w`, `failed to update srt-settings: %w`) — daemon can update the allowlist (e.g. from spawn `allowedDomains`).
- Network status: `CONNECTED` / `NOT_CONNECTED` events (matches app `networkStatus` callback).

**sandbox-helper**: seccomp + cBPF (`golang.org/x/net/bpf`, `golang.org/x/sys/unix`, SockFilter) + netlink; `--settings` flag; `/etc/srt-settings.json`; used by sdk-daemon (`/usr/local/bin/sandbox-helper` referenced) to enforce per-process network/filesystem policy; also clone/mount-namespace ops (`failed to unshare mount namespace`, `Cloneflags`, `Chroot`, `/proc/self/uid_map`, `setgroups`).

**srt (npm, v0.0.28)**: library + CLI (`srt`) wrapping processes with bubblewrap + network filtering — used by Claude Code in-VM for its bash/tool sandboxing (the repo is anthropic-experimental/sandbox-runtime; keywords: sandbox-exec/seatbelt/bubblewrap/network-filtering).

---

## 6. Q&A

**Where does the in-VM Claude Code runtime live — baked or installed?**
→ **Installed at boot.** The image contains only supporting tooling (Node v22.22.0, srt, sandbox-helper, sdk-daemon, python doc stack). At each VM boot, Step 4/4 of startup calls `vm.installSdk(vmStorageSubpath, "2.1.15")`: the app has prepared `~/Library/Application Support/Claude/claude-code-vm/2.1.15/claude` (sha256 `20a52025...`, downloaded from `downloads.claude.ai/claude-code-releases/2.1.15/linux-arm64/claude`, `.verified` marker); the sdk-daemon receives the subpath, copies the binary into the VM (`/usr/local/bin/claude`), verifies it, installs its MITM CA into the guest trust store, and writes an `.sdk-version` file. The binary itself is mounted into the VM through the host-home virtiofs share (`getVMStorageSubpath` returns the home-relative path), so installSdk is effectively a copy + verify + CA-install step.

**Mount model summary:**
- Baked in image: `/workspace` (empty, uid 1000) — fallback shared-cwd mountpoint; everything else (`/sessions`, per-session ext4 disks, bind mounts, `smol-bin`, mitm socket) is created/mounted at runtime by sdk-daemon.

---

## 7. Gaps / open questions

1. **`@ant/claude-swift` native addon internals** (startVM/stopVM/VirtualMachine API): the JS only sees the exported surface. The vsock RPC protocol between the app and sdk-daemon is inferred from Go type names; exact wire format (net/rpc codec) unverified.
2. **smol-bin device**: mechanism the app uses to update sdk-daemon in place (virtio disk with new binary + hash) — app-side trigger code not located in this bundle slice.
3. **YukonSilver config**: server-fetched feature flag (`autoDownloadInBackground`, `supported`/`unavailable`); the flag's origin endpoint not traced (renderer delivers it via `setYukonSilverConfig`).
4. **Cloud-config seed disk (/dev/vda)**: runtime user-data content (what the app injects at boot beyond the baked default `ubuntu`/`ubuntu`) not observed — only the baked default exists in the image.
5. **Exact claude-code launch command** (`/usr/local/bin/claude` args/env at spawn) — spawn params are passed per-session from `LocalAgentModeSessionManager` (offset 2926xxx); full option map (allowedDomains, additionalMounts, isResume) is summarized but the complete option-building code for `B`/`DL` wasn't fully expanded in this pass.
6. **Network egress at the VM edge**: the allowlist (npm/pypi/github/etc.) suggests package downloads are allowed through; whether there's an additional host-side filtering layer for non-anthropic traffic is unclear (mitm only covers *.anthropic.com).
7. `/etc/debian_version` = `bookworm/sid` on an Ubuntu 22.04 image (base-image artifact) — harmless but unexplained.
8. sandbox-helper vs srt split: sandbox-helper (Go, seccomp at daemon level) vs srt (npm, bubblewrap, per-process) — exact call graph (daemon → sandbox-helper for every Spawn?) not confirmed; sdk-daemon strings show it executing `/usr/local/bin/sandbox-helper`.

---

## 8. Key artifact locations

- `/tmp/rootfs_out` — full rootfs extract
- `/tmp/vmbin/sdk-daemon`, `/tmp/vmbin/sandbox-helper` — dumped native binaries
- `/tmp/claude-asar/app/.vite/build/index.js` — app bundle (offsets above)
