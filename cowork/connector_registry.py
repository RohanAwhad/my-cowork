"""ConnectorRegistry — MCP connector management and spawn-time config compilation.

Spec refs: 05 §1.8, 03 §3.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger

from cowork.config import TMP_DIR, mcp_config_path
from cowork.models import Connector, ConnectorStatus, Session
from cowork.storage import Storage

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_NAME_MAX_LEN = 64

_VALID_POLICIES = frozenset({"always", "ask", "blocked"})

_PROBE_TIMEOUT_S = 30


class ConnectorRegistry:
    """Config store + per-session --mcp-config compiler."""

    def __init__(
        self,
        storage: Storage,
        publish: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._storage = storage
        self._publish = publish

    def _emit(self, payload: dict[str, Any]) -> None:
        if self._publish is not None:
            asyncio.create_task(self._publish(payload))

    async def add_connector(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        requires_oauth: bool = False,
    ) -> Connector:
        if not _NAME_RE.match(name) or len(name) > _NAME_MAX_LEN:
            raise ValueError(
                f"Invalid connector name: must match {_NAME_RE.pattern} and be <= {_NAME_MAX_LEN} chars"
            )

        existing = await self._storage.list_connectors()
        if any(c.name == name for c in existing):
            raise ValueError(f"Connector with name '{name}' already exists")

        connector = Connector(
            name=name,
            command=command,
            args=args or [],
            env=env or {},
            requires_oauth=requires_oauth,
        )
        connector = await self._storage.insert_connector(connector)
        logger.info("connector_registry.add name={} id={}", name, connector.id)

        tools = await self.probe_tools(connector.id)
        if tools:
            logger.debug("connector_registry.add probe found {} tools", len(tools))

        self._emit({"type": "connector.updated", "connector": connector.model_dump(mode="json")})
        return connector

    async def remove_connector(self, connector_id: UUID) -> None:
        logger.info("connector_registry.remove id={}", connector_id)
        await self._storage.delete_connector(connector_id)
        self._emit({"type": "connector.updated", "connectorId": str(connector_id), "removed": True})

    async def list_connectors(self) -> list[Connector]:
        return await self._storage.list_connectors()

    async def compile_mcp_config(self, session: Session) -> Path | None:
        """Build mcpServers JSON and write to tmp dir. Caller deletes when session ends."""
        connectors = await self._storage.list_connectors()
        servers: dict[str, dict[str, Any]] = {}

        for c in connectors:
            if c.status == ConnectorStatus.DISABLED:
                continue
            if c.requires_oauth and not c.oauth_pre_auth_done:
                continue
            entry: dict[str, Any] = {"command": c.command, "args": c.args}
            if c.env:
                entry["env"] = c.env
            servers[c.name] = entry

        if not servers:
            return None

        config = {"mcpServers": servers}
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        out_path = mcp_config_path(str(session.id))
        out_path.write_text(json.dumps(config, indent=2))
        os.chmod(out_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        logger.debug("connector_registry.compile_mcp_config path={}", out_path)
        return out_path

    async def probe_tools(self, connector_id: UUID) -> list[str]:
        connector = await self._storage.get_connector(connector_id)
        if connector is None:
            logger.error("connector_registry.probe_tools connector not found id={}", connector_id)
            return []

        try:
            tool_names = await asyncio.to_thread(
                _probe_tools_sync, connector.command, connector.args, connector.env
            )
        except Exception:
            logger.opt(exception=True).error(
                "connector_registry.probe_tools failed id={}", connector_id
            )
            return []

        await self._storage.update_connector(connector_id, tool_names=tool_names)

        if connector.requires_oauth and tool_names:
            await self._storage.update_connector(connector_id, oauth_pre_auth_done=True)

        logger.info("connector_registry.probe_tools id={} found={}", connector_id, len(tool_names))
        return tool_names

    async def set_tool_policy(self, connector_id: UUID, matrix: dict[str, str]) -> None:
        for policy in matrix.values():
            if policy not in _VALID_POLICIES:
                raise ValueError(f"Invalid policy '{policy}': must be one of {sorted(_VALID_POLICIES)}")

        db = self._storage._db
        cid = str(connector_id)
        await db.execute("DELETE FROM connector_tools WHERE connector_id = ?", (cid,))
        for tool_name, policy in matrix.items():
            await db.execute(
                "INSERT INTO connector_tools (connector_id, tool_name, policy) VALUES (?, ?, ?)",
                (cid, tool_name, policy),
            )
        await db.commit()

        connector = await self._storage.get_connector(connector_id)
        if connector is not None:
            self._emit({"type": "connector.updated", "connector": connector.model_dump(mode="json")})
        logger.info("connector_registry.set_tool_policy id={} tools={}", connector_id, len(matrix))

    async def get_tool_policies(self, connector_id: UUID) -> dict[str, str]:
        db = self._storage._db
        cid = str(connector_id)
        cur = await db.execute(
            "SELECT tool_name, policy FROM connector_tools WHERE connector_id = ?", (cid,)
        )
        rows = await cur.fetchall()
        return {r["tool_name"]: r["policy"] for r in rows}

    def get_spawn_flags(
        self, connectors: list[Connector], policies: dict[UUID, dict[str, str]]
    ) -> tuple[list[str], list[str]]:
        allowed: list[str] = []
        denied: list[str] = []

        for c in connectors:
            connector_policies = policies.get(c.id, {})
            for tool_name, policy in connector_policies.items():
                mcp_tool = f"mcp__{c.name}__{tool_name}"
                if policy == "always":
                    allowed.append(mcp_tool)
                elif policy == "blocked":
                    denied.append(mcp_tool)

        return allowed, denied

    def eligible_for_scheduled(self, connector: Connector) -> bool:
        return not connector.requires_oauth or connector.oauth_pre_auth_done


def _probe_tools_sync(
    command: str,
    args: list[str],
    env: dict[str, str],
) -> list[str]:
    """Run JSON-RPC 2.0 initialize + tools/list against an MCP server process."""
    proc_env = {**os.environ, **env}
    proc = subprocess.Popen(
        [command, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=proc_env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    initialize_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cowork", "version": "0.1.0"},
        },
    })
    initialized_notif = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    })
    tools_list_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    })
    shutdown_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "shutdown",
        "params": {},
    })

    payload = "\n".join([initialize_req, initialized_notif, tools_list_req, shutdown_req]) + "\n"

    try:
        stdout_bytes, _ = proc.communicate(input=payload.encode(), timeout=_PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise TimeoutError("MCP probe timed out")

    tool_names: list[str] = []
    for line in stdout_bytes.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2 and "result" in msg:
            tools = msg["result"].get("tools", [])
            tool_names = [t["name"] for t in tools if isinstance(t, dict) and "name" in t]
            break

    return tool_names
