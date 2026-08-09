# My WebBridge

A minimal kimi-webbridge-style local browser bridge: an LLM agent (or any HTTP client) drives a real browser through a local daemon and a Chrome extension over CDP.

```
agent ──HTTP /command──► daemon (127.0.0.1:10087) ◄──WebSocket── extension (in Chrome)
                            │ requestId correlation            │ chrome.debugger / CDP
                            └────────── tool_result ◄──────────┘
```

- `daemon/` — FastAPI + uvicorn: `POST /command`, `GET /status`, WS `/ws` (single extension client, hello/hello_ack, requestId matching, 120 s timeout)
- `extension/` — Manifest V3: WS client with reconnect backoff, 16 tools (navigate, snapshot, click, fill, evaluate, cdp, screenshot, mouse, type, network, upload, save_as_pdf, tab mgmt)
- `SKILL.md` — tool contract for agents

## Run it

```bash
cd daemon
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python daemon.py --port 10087
```

Load `extension/` unpacked in Chrome (chrome://extensions → Developer mode → Load unpacked). Then:

```bash
curl -X POST http://127.0.0.1:10087/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"navigate","args":{"url":"https://example.com","newTab":true,"group_title":"demo"},"session":"demo"}'
```

## Roadmap

- [ ] Restore automated e2e test (Playwright: auto-load extension, YouTube search + video playback in tab group) — removed, was not fully green (MV3 SW idle-kill mid-command, YouTube shadow-DOM selectors)
- [ ] Fix MV3 service-worker idle-kill mid-command (keepalive alone didn't solve it)
- [ ] WS origin check on `/ws` (reject non-extension origins, kimi-style)
- [x] Missing tools: `network`, `upload`, `save_as_pdf`
- [ ] opencode skill auto-registration (daemon installs SKILL.md into opencode like kimi does for Claude Code/Codex/OpenClaw/Hermes)

Differences from kimi-webbridge (deliberate): port 10087 (10086 is taken by the real Kimi daemon), no origin check on WS (loopback only), screenshot returns base64 instead of a file path.
