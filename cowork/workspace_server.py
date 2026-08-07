"""WorkspaceServer — FastAPI HTTP/WS app (05 §1.1, 07 §6)."""

from __future__ import annotations

import mimetypes
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from loguru import logger
from pydantic import BaseModel

from cowork import config
from cowork.event_bus import EventBus, Topic
from cowork.models import (
    Connector,
    MemorySnapshot,
    ScheduledTask,
    SessionCreate,
    Settings,
)
from cowork.session_manager import SessionManager
from cowork.storage import Storage


class TaskCreate(BaseModel):
    name: str
    prompt: str
    cadence: Literal["hourly", "daily", "weekly", "weekdays", "manual"] | None = None
    cron_expr: str | None = None
    allowed_tools: list[str] = []


class TaskPatch(BaseModel):
    name: str | None = None
    prompt: str | None = None
    cadence: str | None = None
    cron_expr: str | None = None
    allowed_tools: list[str] | None = None
    status: str | None = None


class ConnectorCreate(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    tool_names: list[str] = []
    requires_oauth: bool = False


class MemoryUpdate(BaseModel):
    content: str


class SettingsUpdate(BaseModel):
    claude_version_pin: str | None = None
    server_port: int | None = None
    scheduler_tick_seconds: int | None = None
    spawn_health_timeout_seconds: int | None = None
    runner_no_event_timeout_minutes: int | None = None
    memory_enabled: bool | None = None
    scheduler_max_consecutive_failures: int | None = None
    log_level: str | None = None


def _read_or_create_token() -> str:
    token_path = config.SERVER_TOKEN_PATH
    token_path.parent.mkdir(parents=True, exist_ok=True)

    if token_path.is_file():
        return token_path.read_text(encoding="utf-8").strip()

    token = secrets.token_hex(32)
    token_path.write_text(token, encoding="utf-8")
    token_path.chmod(0o600)
    logger.info("workspace_server: generated new server token at {}", token_path)
    return token


def _check_token(
    request: Request,
    server_token: str,
    authorization: str | None = None,
    x_workspace_token: str | None = None,
) -> bool:
    if authorization is not None:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
            if token == server_token:
                return True

    if x_workspace_token is not None and x_workspace_token == server_token:
        return True

    return False


def _settings_to_dict(settings: Settings) -> dict[str, Any]:
    d = settings.model_dump(mode="json")
    d.pop("last_boot_at", None)
    return d


def _sandbox_headers(content_type: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    ct_lower = content_type.lower()
    if "html" in ct_lower or "svg" in ct_lower:
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return headers


def create_app(
    storage: Storage,
    session_manager: SessionManager,
    event_bus: EventBus,
    server_token: str | None = None,
) -> FastAPI:
    if server_token is None:
        server_token = _read_or_create_token()

    _token = server_token
    _ws_clients: list[WebSocket] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        await storage.init()
        now = datetime.now(UTC)
        await session_manager.reconcile(now)

        async def _ws_forwarder(payload: dict[str, Any]) -> None:
            dead: list[WebSocket] = []
            for ws in list(_ws_clients):
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                if ws in _ws_clients:
                    _ws_clients.remove(ws)

        for topic in Topic:
            event_bus.subscribe(topic, _ws_forwarder)

        yield

        _ws_clients.clear()
        await storage.close()

    app = FastAPI(lifespan=lifespan)

    # ---- Auth middleware ----

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path == "/health" or path.startswith("/static"):
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        ws_token = request.headers.get("x-workspace-token")

        if not _check_token(request, _token, auth_header, ws_token):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)

    # ---- Health ----

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ---- Session routes ----

    @app.post("/api/sessions")
    async def create_session(body: SessionCreate) -> Response:
        active = await session_manager.active_session()
        if active is not None:
            return JSONResponse(
                status_code=409,
                content={"detail": "A session is already running"},
            )
        session = await session_manager.create_session(body)
        return JSONResponse(
            status_code=201,
            content=session.model_dump(mode="json"),
        )

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        summaries = await session_manager.list_sessions()
        return [s.model_dump(mode="json") for s in summaries]

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: UUID) -> Response:
        session = await session_manager.get_session(session_id)
        if session is None:
            return JSONResponse(status_code=404, content={"detail": "Session not found"})
        return JSONResponse(content=session.model_dump(mode="json"))

    @app.post("/api/sessions/{session_id}/start")
    async def start_session(session_id: UUID) -> Response:
        await session_manager.start_session(session_id)
        session = await session_manager.get_session(session_id)
        if session is None:
            return JSONResponse(status_code=404, content={"detail": "Session not found"})
        return JSONResponse(content=session.model_dump(mode="json"))

    @app.post("/api/sessions/{session_id}/stop")
    async def stop_session(session_id: UUID) -> Response:
        await session_manager.stop_session(session_id)
        session = await session_manager.get_session(session_id)
        if session is None:
            return JSONResponse(status_code=404, content={"detail": "Session not found"})
        return JSONResponse(content=session.model_dump(mode="json"))

    @app.post("/api/sessions/{session_id}/archive")
    async def archive_session(session_id: UUID) -> Response:
        await session_manager.archive_session(session_id)
        session = await session_manager.get_session(session_id)
        if session is None:
            return JSONResponse(status_code=404, content={"detail": "Session not found"})
        return JSONResponse(content=session.model_dump(mode="json"))

    @app.get("/api/sessions/{session_id}/events")
    async def list_session_events(
        session_id: UUID,
        after_seq: int = Query(default=0),
    ) -> list[dict[str, Any]]:
        events = await storage.list_events(session_id, after_seq=after_seq)
        return [e.model_dump(mode="json") for e in events]

    # ---- Task routes ----

    @app.get("/api/tasks")
    async def list_tasks() -> list[dict[str, Any]]:
        tasks = await storage.list_tasks()
        return [t.model_dump(mode="json") for t in tasks]

    @app.post("/api/tasks")
    async def create_task(body: TaskCreate) -> Response:
        task = ScheduledTask(
            name=body.name,
            prompt=body.prompt,
            cadence=body.cadence,
            cron_expr=body.cron_expr,
            allowed_tools=body.allowed_tools,
        )
        task = await storage.insert_task(task)
        return JSONResponse(status_code=201, content=task.model_dump(mode="json"))

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: UUID, body: TaskPatch) -> Response:
        existing = await storage.get_task(task_id)
        if existing is None:
            return JSONResponse(status_code=404, content={"detail": "Task not found"})
        updates: dict[str, Any] = {}
        for field_name in ("name", "prompt", "cadence", "cron_expr", "allowed_tools", "status"):
            val = getattr(body, field_name)
            if val is not None:
                updates[field_name] = val
        if updates:
            task = await storage.update_task(task_id, **updates)
        else:
            task = existing
        return JSONResponse(content=task.model_dump(mode="json"))

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: UUID) -> Response:
        existing = await storage.get_task(task_id)
        if existing is None:
            return JSONResponse(status_code=404, content={"detail": "Task not found"})
        await storage.set_task_status(task_id, __import__("cowork.models", fromlist=["TaskStatus"]).TaskStatus.DISABLED)
        return JSONResponse(status_code=200, content={"detail": "Deleted"})

    @app.post("/api/tasks/{task_id}/run")
    async def run_task(task_id: UUID) -> Response:
        task = await storage.get_task(task_id)
        if task is None:
            return JSONResponse(status_code=404, content={"detail": "Task not found"})

        create = SessionCreate(
            prompt=task.prompt,
            allowed_tools=task.allowed_tools,
        )
        session = await session_manager.create_session(create, task_id=task.id)
        return JSONResponse(
            status_code=201,
            content=session.model_dump(mode="json"),
        )

    # ---- Connector routes ----

    @app.get("/api/connectors")
    async def list_connectors() -> list[dict[str, Any]]:
        connectors = await storage.list_connectors()
        return [c.model_dump(mode="json") for c in connectors]

    @app.post("/api/connectors")
    async def add_connector(body: ConnectorCreate) -> Response:
        connector = Connector(
            name=body.name,
            command=body.command,
            args=body.args,
            env=body.env,
            tool_names=body.tool_names,
            requires_oauth=body.requires_oauth,
        )
        connector = await storage.insert_connector(connector)
        return JSONResponse(status_code=201, content=connector.model_dump(mode="json"))

    @app.delete("/api/connectors/{connector_id}")
    async def delete_connector(connector_id: UUID) -> Response:
        existing = await storage.get_connector(connector_id)
        if existing is None:
            return JSONResponse(status_code=404, content={"detail": "Connector not found"})
        await storage.delete_connector(connector_id)
        return JSONResponse(status_code=200, content={"detail": "Deleted"})

    # ---- Artifact routes ----

    @app.get("/api/artifacts")
    async def list_artifacts(session_id: UUID = Query()) -> list[dict[str, Any]]:
        artifacts = await storage.list_artifacts(session_id)
        return [a.model_dump(mode="json") for a in artifacts]

    # ---- Permission routes ----

    @app.get("/api/permissions")
    async def list_permissions(session_id: UUID = Query()) -> list[dict[str, Any]]:
        permissions = await storage.list_permissions(session_id)
        return [p.model_dump(mode="json") for p in permissions]

    # ---- Settings routes ----

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        settings = Settings()
        setting_fields = [
            "claude_version_pin", "server_port", "scheduler_tick_seconds",
            "spawn_health_timeout_seconds", "runner_no_event_timeout_minutes",
            "memory_enabled", "scheduler_max_consecutive_failures", "log_level",
        ]
        for field_name in setting_fields:
            val = await storage.get_setting(field_name)
            if val is not None:
                field_info = Settings.model_fields[field_name]
                anno = field_info.annotation
                if anno is bool or (hasattr(anno, "__args__") and bool in getattr(anno, "__args__", ())):
                    setattr(settings, field_name, val.lower() in ("true", "1", "yes"))
                elif anno is int or (hasattr(anno, "__args__") and int in getattr(anno, "__args__", ())):
                    setattr(settings, field_name, int(val))
                else:
                    setattr(settings, field_name, val)
        return _settings_to_dict(settings)

    @app.put("/api/settings")
    async def put_settings(body: SettingsUpdate) -> dict[str, Any]:
        for field_name, val in body.model_dump(exclude_none=True).items():
            if field_name == "last_boot_at":
                continue
            await storage.set_setting(field_name, str(val))
        return await get_settings()

    # ---- Memory routes ----

    @app.get("/api/memory")
    async def get_memory() -> dict[str, Any]:
        memory_path = config.MEMORY_PATH
        if not memory_path.is_file():
            now = datetime.now(UTC)
            snap = MemorySnapshot(content="", size_bytes=0, modified_at=now)
            return snap.model_dump(mode="json")

        content = memory_path.read_text(encoding="utf-8")
        stat = memory_path.stat()
        snap = MemorySnapshot(
            content=content,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )
        return snap.model_dump(mode="json")

    @app.put("/api/memory")
    async def put_memory(body: MemoryUpdate) -> Response:
        memory_enabled_val = await storage.get_setting("memory_enabled", "true")
        if memory_enabled_val is not None and memory_enabled_val.lower() in ("false", "0", "no"):
            return JSONResponse(
                status_code=409,
                content={"detail": "Memory is disabled in settings"},
            )

        content_bytes = body.content.encode("utf-8")
        if len(content_bytes) > config.MEMORY_SIZE_CAP_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"Content exceeds {config.MEMORY_SIZE_CAP_BYTES} byte cap"
                },
            )

        memory_path = config.MEMORY_PATH
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(body.content, encoding="utf-8")

        stat = memory_path.stat()
        snap = MemorySnapshot(
            content=body.content,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )
        return JSONResponse(content=snap.model_dump(mode="json"))

    # ---- Preview serving ----

    @app.get("/previews/{session_id}/{artifact_id}/v{version}")
    async def preview_artifact(
        session_id: UUID,
        artifact_id: UUID,
        version: int,
    ) -> Response:
        artifact = await storage.get_artifact(artifact_id)
        if artifact is None or str(artifact.session_id) != str(session_id):
            return JSONResponse(status_code=404, content={"detail": "Artifact not found"})

        session_dir = config.session_dir(str(session_id))
        file_path = session_dir / "artifacts" / artifact.rel_path

        if not file_path.exists():
            return JSONResponse(status_code=404, content={"detail": "Artifact file not found"})

        resolved = file_path.resolve()
        base = session_dir.resolve()
        if not str(resolved).startswith(str(base)):
            return JSONResponse(status_code=403, content={"detail": "Path traversal denied"})

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        headers = _sandbox_headers(content_type)
        return FileResponse(
            path=str(resolved),
            media_type=content_type,
            headers=headers,
        )

    # ---- WebSocket ----

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket, token: str = Query()) -> None:
        if token != _token:
            await websocket.close(code=1008, reason="Unauthorized")
            return

        await websocket.accept()
        _ws_clients.append(websocket)
        logger.debug("ws client connected, total={}", len(_ws_clients))

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in _ws_clients:
                _ws_clients.remove(websocket)
            logger.debug("ws client disconnected, total={}", len(_ws_clients))

    # ---- Static files + index ----

    static_dir = Path(__file__).parent.parent / "static"

    @app.get("/")
    async def index() -> Response:
        index_path = static_dir / "index.html"
        if index_path.is_file():
            return FileResponse(str(index_path))
        return JSONResponse(content={"detail": "No UI available"})

    if static_dir.is_dir():
        from starlette.staticfiles import StaticFiles

        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
