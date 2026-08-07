# .assets — research provenance

Raw materials backing the reports in this directory. Everything here was generated during the 2026-08-06/07 research campaigns.

## cowork-app-re/ — Claude Cowork static RE (campaign 2)

- `symbol-map.md`, `session-lifecycle.md`, `vm-layer.md`, `cloud-bridge.md`, `security-model.md`, `claude-code-binary.md`, `web-endpoints-community.md` — the 7 agent deliverables (byte-offset cited into `index.js`)
- `*_extract.txt` set (bundle_eipc_surface, claudevm_interface, ipc_channels, plugins_reader, fileaccess, class_pretty, f0e_class, zat_handlecoworkvmapi, mainwin_wiring) — clean code-region extractions from the minified main bundle
- `scan.py ctx.py dump.py extract.py find.py grab.py x.py` + `term_offsets.json` — extraction tooling used to mine the bundle
- `agent_sdk_query.txt` — Agent SDK `query()` type surface (behavioral reference)

Regeneration:
- App bundle: `npx -y @electron/asar extract /Applications/Claude.app/Contents/Resources/app.asar /tmp/claude-asar` → `/tmp/claude-asar/app/.vite/build/index.js` (3.3 MB minified)
- VM rootfs: `dd if="~/Library/Application Support/Claude/vm_bundles/claudevm.bundle/rootfs.img" of=/tmp/rootfs.ext4 bs=512 skip=206848 count=20764639` then `/opt/homebrew/opt/e2fsprogs/sbin/debugfs`

Not kept (re-generable): npm tgzs, `pivot-app.js`, `connectors.html`, cloned repos (`claude-cowork-linux`, agent-sdk/package), `bin.strings.txt` (31 MB), raw `ctx_*.txt` context dumps.

## kimi-cowork-research/ — Claude Cowork vs Kimi Work product research (campaign 1)

- `breadth-*.md` ×4 (official docs, news/teardowns, github ecosystem, pricing/limits)
- `deepdive-*.md` ×3 (cowork internals + plugin format, clone blueprints, kimi-code/OpenClaw source)
- `fetch.sh`, `fetch-oc.sh` — repo fetch helpers

Not kept: GitHub tree/search JSONs, cloned source dirs (`src*`, `oc/`).
