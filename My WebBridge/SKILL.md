---
name: my-webbridge
description: |
  My WebBridge lets an agent control a real browser (Chrome/Chromium) — navigate, click, fill, type, screenshot — via a local daemon at http://127.0.0.1:10087. Use when the user wants browser interaction, web automation, or page content reading.
---

# My WebBridge

Local browser bridge mirroring kimi-webbridge: agent → HTTP `/command` → daemon → WebSocket → extension → CDP.

## Commands

POST JSON to `http://127.0.0.1:10087/command`:

```json
{"action": "navigate", "args": {"url": "https://example.com", "newTab": true, "group_title": "My task"}, "session": "task-1"}
```

Every request carries a top-level `session`. One task = one session = one tab group.

## Tools

| Tool | Args | Returns |
|------|------|---------|
| `navigate` | `url`, `newTab`(bool), `group_title` | `{success, url, tabId, groupTitle}` |
| `find_tab` | `url`, `active`(bool) | `{success, url, tabId, borrowed}` |
| `snapshot` | — | `{url, title, tree}` with `@e` refs (accessibility tree, text only) |
| `click` | `selector` (@e ref or CSS) | `{success, tag, text}` |
| `fill` | `selector`, `value` | `{success, mode}` (works on input/textarea/contenteditable) |
| `evaluate` | `code` (async allowed) | `{type, value}` |
| `cdp` | `method`, `params` | raw CDP response |
| `screenshot` | `format`(png\|jpeg), `quality` | `{format, data(base64), sizeBytes}` |
| `mouse` | `type`(move\|press\|release\|click\|wheel), `x`, `y`, `button`, `deltaX`, `deltaY` | `{success}` |
| `type` | `text` | `{success, text}` |
| `list_tabs` | — | `{success, groupId, tabs:[{tabId,url,title,active}]}` |
| `close_tab` | — | `{success, closed}` |
| `close_session` | — | `{success, closed}` — closes the whole tab group |

Single-tab tools act on the session's current tab (the most recently opened/selected one).

## Daemon

```bash
cd daemon && .venv/bin/python daemon.py --port 10087
```

`GET /status` → `{running, version, extension_connected, ...}`. The extension auto-connects/retries on its own.

## Extension

Load unpacked via `chrome://extensions` → Developer mode → Load unpacked → `extension/` dir.
