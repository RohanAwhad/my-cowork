"""CLI entry point — ``python -m cowork`` starts the workspace server."""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from typing import Any

import uvicorn
from loguru import logger

from cowork import config
from cowork.connector_registry import ConnectorRegistry
from cowork.event_bus import EventBus, Topic
from cowork.logging_config import setup_logging
from cowork.scheduler_engine import SchedulerEngine
from cowork.session_manager import SessionManager
from cowork.storage import Storage
from cowork.workspace_server import _read_or_create_token, create_app


async def _run() -> None:
    setup_logging()

    storage = Storage(str(config.DB_PATH))
    await storage.init()

    event_bus = EventBus()

    async def _session_event_callback(event_type: str, payload: dict[str, Any]) -> None:
        event_bus.publish(Topic.SESSION, {"type": event_type, **payload})

    session_manager = SessionManager(storage, event_callback=_session_event_callback)

    scheduler = SchedulerEngine(
        storage=storage,
        create_session=session_manager.create_session,
        start_session=session_manager.start_session,
        publish=event_bus.publish,
    )
    scheduler.subscribe_session_events(event_bus)

    _connector_registry = ConnectorRegistry(storage=storage)

    now = datetime.now(UTC)
    await session_manager.reconcile(now)

    last_boot_val = await storage.get_setting("last_boot_at")
    if last_boot_val is not None:
        last_boot = datetime.fromisoformat(last_boot_val)
        if last_boot.tzinfo is None:
            last_boot = last_boot.replace(tzinfo=UTC)
        await scheduler.recover_missed(now, last_boot)
    await storage.set_setting("last_boot_at", now.isoformat())

    scheduler.start_tick_loop()

    server_token = _read_or_create_token()
    app = create_app(storage, session_manager, event_bus, server_token=server_token)

    port_val = await storage.get_setting("server_port")
    port = int(port_val) if port_val else 8765

    logger.info("cowork server starting on http://127.0.0.1:{}", port)
    print(f"Co-work server: http://127.0.0.1:{port}")
    print(f"Token: {server_token}")

    uv_config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(uv_config)

    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    serve_task = asyncio.create_task(server.serve())
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    done, _ = await asyncio.wait(
        [serve_task, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if shutdown_task in done:
        logger.info("shutdown signal received")
        server.should_exit = True
        await serve_task

    scheduler.stop_tick_loop()
    await storage.close()
    logger.info("cowork server stopped")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
