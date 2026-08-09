from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

VERSION = "0.1.0"
DEFAULT_PORT = 10087
COMMAND_TIMEOUT_SECONDS = 120.0

log = logging.getLogger("my-webbridge")

app = FastAPI(title="My WebBridge daemon")

extension_ws: Optional[WebSocket] = None
pending: dict[str, asyncio.Future] = {}
started_at = time.time()


class CommandRequest(BaseModel):
    action: str
    args: dict = Field(default_factory=dict)
    session: str = "default"


@app.get("/status")
def status() -> dict:
    return {
        "running": True,
        "version": VERSION,
        "port": DEFAULT_PORT,
        "extension_connected": extension_ws is not None,
        "uptime_seconds": int(time.time() - started_at),
    }


@app.post("/command")
async def command(req: CommandRequest) -> dict:
    if extension_ws is None:
        return {"ok": False, "error": "no extension connected"}
    request_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    pending[request_id] = fut
    await extension_ws.send_text(
        json.dumps(
            {
                "type": "tool_call",
                "requestId": request_id,
                "payload": {"tool": req.action, "args": req.args, "session": req.session},
            }
        )
    )
    try:
        payload = await asyncio.wait_for(fut, timeout=COMMAND_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        pending.pop(request_id, None)
        return {"ok": False, "error": "extension timed out"}
    if isinstance(payload, dict) and payload.get("error"):
        return {"ok": False, "error": payload["error"]}
    return {"ok": True, "data": payload}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    global extension_ws
    await ws.accept()
    old = extension_ws
    if old is not None and old is not ws:
        try:
            await old.close(code=1001, reason="replaced")
        except Exception:
            pass
    extension_ws = ws
    log.info("extension connected")
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "hello":
                await ws.send_text(
                    json.dumps(
                        {"type": "hello_ack", "payload": {"daemonVersion": VERSION}}
                    )
                )
            elif mtype == "tool_result":
                fut = pending.pop(msg.get("responseToRequestId"), None)
                if fut is not None and not fut.done():
                    fut.set_result(msg.get("payload", {}))
            elif mtype == "pong":
                pass
            else:
                log.warning("unhandled ws message type: %s", mtype)
    except WebSocketDisconnect:
        pass
    finally:
        if extension_ws is ws:
            extension_ws = None
            log.info("extension disconnected")


async def ping_loop() -> None:
    while True:
        await asyncio.sleep(30)
        if extension_ws is not None:
            try:
                await extension_ws.send_text(json.dumps({"type": "ping"}))
            except Exception:
                pass


@app.on_event("startup")
async def startup() -> None:
    asyncio.get_running_loop().create_task(ping_loop())


def main() -> None:
    parser = argparse.ArgumentParser(description="My WebBridge daemon")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
