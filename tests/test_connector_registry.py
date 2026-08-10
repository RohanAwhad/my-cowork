"""Tests for ConnectorRegistry — MCP connector management."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from cowork.connector_registry import ConnectorRegistry, _probe_tools_sync
from cowork.models import Connector, ConnectorStatus, Session
from cowork.storage import Storage


@pytest.fixture
async def storage() -> AsyncIterator[Storage]:
    s = Storage(":memory:")
    await s.init()
    yield s
    await s.close()


@pytest.fixture
def registry(storage: Storage) -> ConnectorRegistry:
    return ConnectorRegistry(storage)


def _make_session(**overrides: object) -> Session:
    defaults: dict[str, object] = {
        "prompt": "test",
        "outputs_dir": Path("/tmp/outputs"),
    }
    defaults.update(overrides)
    return Session(**defaults)  # type: ignore[arg-type]


# ------------------------------------------------------------------
# add_connector
# ------------------------------------------------------------------


class TestAddConnector:
    async def test_valid_name(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("my-server", "npx", ["-y", "server"])
        assert c.name == "my-server"
        assert c.command == "npx"
        assert c.args == ["-y", "server"]
        assert isinstance(c.id, UUID)

    async def test_name_with_underscores_digits(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("Server_01", "node", [])
        assert c.name == "Server_01"

    async def test_invalid_name_empty(self, registry: ConnectorRegistry) -> None:
        with pytest.raises(ValueError, match="Invalid connector name"):
            await registry.add_connector("", "cmd", [])

    async def test_invalid_name_starts_with_dash(self, registry: ConnectorRegistry) -> None:
        with pytest.raises(ValueError, match="Invalid connector name"):
            await registry.add_connector("-bad", "cmd", [])

    async def test_invalid_name_starts_with_underscore(self, registry: ConnectorRegistry) -> None:
        with pytest.raises(ValueError, match="Invalid connector name"):
            await registry.add_connector("_bad", "cmd", [])

    async def test_invalid_name_special_chars(self, registry: ConnectorRegistry) -> None:
        with pytest.raises(ValueError, match="Invalid connector name"):
            await registry.add_connector("bad@name", "cmd", [])

    async def test_invalid_name_too_long(self, registry: ConnectorRegistry) -> None:
        with pytest.raises(ValueError, match="Invalid connector name"):
            await registry.add_connector("a" * 65, "cmd", [])

    async def test_max_length_name(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("a" * 64, "cmd", [])
        assert len(c.name) == 64

    async def test_duplicate_name(self, registry: ConnectorRegistry) -> None:
        await registry.add_connector("dup", "cmd", [])
        with pytest.raises(ValueError, match="already exists"):
            await registry.add_connector("dup", "cmd2", [])

    async def test_env_stored(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("srv", "cmd", [], env={"KEY": "val"})
        assert c.env == {"KEY": "val"}

    async def test_requires_oauth(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("oauth-srv", "cmd", [], requires_oauth=True)
        assert c.requires_oauth is True
        assert c.oauth_pre_auth_done is False


# ------------------------------------------------------------------
# remove_connector
# ------------------------------------------------------------------


class TestRemoveConnector:
    async def test_remove(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("to-rm", "cmd", [])
        await registry.remove_connector(c.id)
        result = await registry.list_connectors()
        assert all(x.id != c.id for x in result)


# ------------------------------------------------------------------
# compile_mcp_config
# ------------------------------------------------------------------


class TestCompileMcpConfig:
    async def test_correct_json_shape(self, registry: ConnectorRegistry, tmp_path: Path) -> None:
        await registry.add_connector("srv1", "node", ["index.js"], env={"PORT": "3000"})
        await registry.add_connector("srv2", "python", ["-m", "mcp"])
        session = _make_session()

        with patch("cowork.connector_registry.TMP_DIR", tmp_path):
            with patch("cowork.connector_registry.mcp_config_path", lambda sid: tmp_path / f"mcp-config-{sid}.json"):
                result = await registry.compile_mcp_config(session)

        assert result is not None
        data = json.loads(result.read_text())
        assert "mcpServers" in data
        assert "srv1" in data["mcpServers"]
        assert data["mcpServers"]["srv1"]["command"] == "node"
        assert data["mcpServers"]["srv1"]["args"] == ["index.js"]
        assert data["mcpServers"]["srv1"]["env"] == {"PORT": "3000"}
        assert "srv2" in data["mcpServers"]
        assert "env" not in data["mcpServers"]["srv2"]

    async def test_file_permissions(self, registry: ConnectorRegistry, tmp_path: Path) -> None:
        await registry.add_connector("srv", "cmd", [])
        session = _make_session()

        with patch("cowork.connector_registry.TMP_DIR", tmp_path):
            with patch("cowork.connector_registry.mcp_config_path", lambda sid: tmp_path / f"mcp-config-{sid}.json"):
                result = await registry.compile_mcp_config(session)

        assert result is not None
        mode = os.stat(result).st_mode
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)

    async def test_disabled_excluded(self, registry: ConnectorRegistry, storage: Storage, tmp_path: Path) -> None:
        c = await registry.add_connector("disabled-srv", "cmd", [])
        await storage.update_connector(c.id, status=ConnectorStatus.DISABLED.value)
        session = _make_session()

        with patch("cowork.connector_registry.TMP_DIR", tmp_path):
            with patch("cowork.connector_registry.mcp_config_path", lambda sid: tmp_path / f"mcp-config-{sid}.json"):
                result = await registry.compile_mcp_config(session)

        assert result is None

    async def test_oauth_not_pre_authed_excluded(self, registry: ConnectorRegistry, tmp_path: Path) -> None:
        await registry.add_connector("oauth-srv", "cmd", [], requires_oauth=True)
        session = _make_session()

        with patch("cowork.connector_registry.TMP_DIR", tmp_path):
            with patch("cowork.connector_registry.mcp_config_path", lambda sid: tmp_path / f"mcp-config-{sid}.json"):
                result = await registry.compile_mcp_config(session)

        assert result is None

    async def test_none_when_empty(self, registry: ConnectorRegistry, tmp_path: Path) -> None:
        session = _make_session()

        with patch("cowork.connector_registry.TMP_DIR", tmp_path):
            with patch("cowork.connector_registry.mcp_config_path", lambda sid: tmp_path / f"mcp-config-{sid}.json"):
                result = await registry.compile_mcp_config(session)

        assert result is None


# ------------------------------------------------------------------
# probe_tools
# ------------------------------------------------------------------


class TestProbeTools:
    async def test_parse_tool_names(self, registry: ConnectorRegistry, storage: Storage) -> None:
        c = await registry.add_connector("probe-srv", "cmd", [])

        with patch("cowork.connector_registry._probe_tools_sync", return_value=["read_file", "write_file"]):
            result = await registry.probe_tools(c.id)

        assert result == ["read_file", "write_file"]
        updated = await storage.get_connector(c.id)
        assert updated is not None
        assert updated.tool_names == ["read_file", "write_file"]

    async def test_timeout_returns_empty(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("timeout-srv", "cmd", [])

        with patch("cowork.connector_registry._probe_tools_sync", side_effect=TimeoutError("probe timed out")):
            result = await registry.probe_tools(c.id)

        assert result == []

    async def test_oauth_pre_auth_set_on_success(self, registry: ConnectorRegistry, storage: Storage) -> None:
        c = await registry.add_connector("oauth-probe", "cmd", [], requires_oauth=True)

        with patch("cowork.connector_registry._probe_tools_sync", return_value=["some_tool"]):
            result = await registry.probe_tools(c.id)

        assert result == ["some_tool"]
        updated = await storage.get_connector(c.id)
        assert updated is not None
        assert updated.oauth_pre_auth_done is True

    async def test_probe_failure_contained(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("fail-srv", "cmd", [])

        with patch("cowork.connector_registry._probe_tools_sync", side_effect=RuntimeError("crash")):
            result = await registry.probe_tools(c.id)

        assert result == []

    async def test_nonexistent_connector(self, registry: ConnectorRegistry) -> None:
        result = await registry.probe_tools(uuid4())
        assert result == []


# ------------------------------------------------------------------
# set_tool_policy
# ------------------------------------------------------------------


class TestSetToolPolicy:
    async def test_valid_policies(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("policy-srv", "cmd", [])
        await registry.set_tool_policy(c.id, {"read": "always", "write": "blocked", "exec": "ask"})
        policies = await registry.get_tool_policies(c.id)
        assert policies == {"read": "always", "write": "blocked", "exec": "ask"}

    async def test_invalid_policy_value(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("bad-policy", "cmd", [])
        with pytest.raises(ValueError, match="Invalid policy"):
            await registry.set_tool_policy(c.id, {"read": "yolo"})

    async def test_replaces_previous(self, registry: ConnectorRegistry) -> None:
        c = await registry.add_connector("replace-srv", "cmd", [])
        await registry.set_tool_policy(c.id, {"read": "always", "write": "blocked"})
        await registry.set_tool_policy(c.id, {"exec": "ask"})
        policies = await registry.get_tool_policies(c.id)
        assert policies == {"exec": "ask"}


# ------------------------------------------------------------------
# get_spawn_flags
# ------------------------------------------------------------------


class TestGetSpawnFlags:
    def test_always_goes_to_allowed(self, registry: ConnectorRegistry) -> None:
        c = Connector(name="srv", command="cmd", args=[], tool_names=["read", "write"])
        policies = {c.id: {"read": "always", "write": "ask"}}
        allowed, denied = registry.get_spawn_flags([c], policies)
        assert "mcp__srv__read" in allowed
        assert "mcp__srv__write" not in allowed
        assert "mcp__srv__write" not in denied

    def test_blocked_goes_to_denied(self, registry: ConnectorRegistry) -> None:
        c = Connector(name="srv", command="cmd", args=[], tool_names=["dangerous"])
        policies = {c.id: {"dangerous": "blocked"}}
        allowed, denied = registry.get_spawn_flags([c], policies)
        assert "mcp__srv__dangerous" in denied
        assert "mcp__srv__dangerous" not in allowed

    def test_ask_goes_to_neither(self, registry: ConnectorRegistry) -> None:
        c = Connector(name="srv", command="cmd", args=[], tool_names=["interactive"])
        policies = {c.id: {"interactive": "ask"}}
        allowed, denied = registry.get_spawn_flags([c], policies)
        assert allowed == []
        assert denied == []

    def test_multiple_connectors(self, registry: ConnectorRegistry) -> None:
        c1 = Connector(name="s1", command="cmd", args=[])
        c2 = Connector(name="s2", command="cmd", args=[])
        policies = {
            c1.id: {"read": "always"},
            c2.id: {"write": "blocked"},
        }
        allowed, denied = registry.get_spawn_flags([c1, c2], policies)
        assert "mcp__s1__read" in allowed
        assert "mcp__s2__write" in denied


# ------------------------------------------------------------------
# eligible_for_scheduled
# ------------------------------------------------------------------


class TestEligibleForScheduled:
    def test_not_oauth(self, registry: ConnectorRegistry) -> None:
        c = Connector(name="s", command="cmd", args=[], requires_oauth=False)
        assert registry.eligible_for_scheduled(c) is True

    def test_oauth_not_pre_authed(self, registry: ConnectorRegistry) -> None:
        c = Connector(name="s", command="cmd", args=[], requires_oauth=True, oauth_pre_auth_done=False)
        assert registry.eligible_for_scheduled(c) is False

    def test_oauth_pre_authed(self, registry: ConnectorRegistry) -> None:
        c = Connector(name="s", command="cmd", args=[], requires_oauth=True, oauth_pre_auth_done=True)
        assert registry.eligible_for_scheduled(c) is True


# ------------------------------------------------------------------
# _probe_tools_sync (unit test for JSON-RPC parsing)
# ------------------------------------------------------------------


class TestProbeToolsSync:
    def test_parses_tools_list_response(self) -> None:
        init_resp = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        tools_resp = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "tool_a"}, {"name": "tool_b"}]},
        })
        stdout = f"{init_resp}\n{tools_resp}\n"

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = (stdout.encode(), b"")
            proc.stdin = MagicMock()
            proc.stdout = MagicMock()
            mock_popen.return_value = proc

            result = _probe_tools_sync("node", ["server.js"], {})

        assert result == ["tool_a", "tool_b"]

    def test_timeout_raises(self) -> None:
        import subprocess as sp

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.side_effect = [
                sp.TimeoutExpired("cmd", 30),
                (b"", b""),
            ]
            proc.kill = MagicMock()
            proc.stdin = MagicMock()
            proc.stdout = MagicMock()
            mock_popen.return_value = proc

            with pytest.raises(TimeoutError, match="timed out"):
                _probe_tools_sync("cmd", [], {})

    def test_empty_stdout(self) -> None:
        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = (b"", b"")
            proc.stdin = MagicMock()
            proc.stdout = MagicMock()
            mock_popen.return_value = proc

            result = _probe_tools_sync("cmd", [], {})

        assert result == []

    def test_no_tools_in_response(self) -> None:
        resp = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}})

        with patch("subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.communicate.return_value = (resp.encode(), b"")
            proc.stdin = MagicMock()
            proc.stdout = MagicMock()
            mock_popen.return_value = proc

            result = _probe_tools_sync("cmd", [], {})

        assert result == []
