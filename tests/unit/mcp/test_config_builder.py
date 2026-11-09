"""Tests for MCP config builder."""

from __future__ import annotations

import json
from unittest.mock import patch

from onemancompany.tools.mcp.config_builder import build_mcp_config, write_mcp_config


# ---------------------------------------------------------------------------
# build_mcp_config
# ---------------------------------------------------------------------------

class TestBuildMcpConfig:
    def test_config_structure(self):
        """Config has the correct Claude MCP config format."""
        cfg = build_mcp_config("00002", task_id="t1", project_id="p1", project_dir="/tmp/proj")

        assert "mcpServers" in cfg
        assert "onemancompany" in cfg["mcpServers"]
        server = cfg["mcpServers"]["onemancompany"]
        assert "command" in server
        assert "-m" in server["args"]
        assert "onemancompany.tools.mcp.server" in server["args"]

        env = server["env"]
        assert env["OMC_EMPLOYEE_ID"] == "00002"
        assert env["OMC_TASK_ID"] == "t1"
        assert env["OMC_PROJECT_ID"] == "p1"
        assert env["OMC_PROJECT_DIR"] == "/tmp/proj"
        # OMC_TOOLS no longer exists — permissions resolved dynamically by registry
        assert "OMC_TOOLS" not in env

    def test_default_server_url(self):
        cfg = build_mcp_config("00002")
        assert cfg["mcpServers"]["onemancompany"]["env"]["OMC_SERVER_URL"] == "http://localhost:8000"

    def test_custom_server_url(self):
        cfg = build_mcp_config("00002", server_url="http://example.com:9000")
        assert cfg["mcpServers"]["onemancompany"]["env"]["OMC_SERVER_URL"] == "http://example.com:9000"

    def test_gmail_server_added_when_exists(self, tmp_path):
        """Gmail MCP server is added when the script file exists."""
        gmail_dir = tmp_path / "gmail"
        gmail_dir.mkdir()
        (gmail_dir / "mcp_server.py").write_text("# gmail mcp server")

        with patch("onemancompany.tools.mcp.config_builder.TOOLS_DIR", tmp_path):
            cfg = build_mcp_config("00002")

        assert "gmail" in cfg["mcpServers"]

    def test_gmail_server_omitted_when_missing(self, tmp_path):
        """Gmail MCP server is not added when the script file doesn't exist."""
        with patch("onemancompany.tools.mcp.config_builder.TOOLS_DIR", tmp_path):
            cfg = build_mcp_config("00002")

        assert "gmail" not in cfg["mcpServers"]


# ---------------------------------------------------------------------------
# write_mcp_config
# ---------------------------------------------------------------------------

class TestWriteMcpConfig:
    def test_writes_json_file(self, tmp_path):
        emp_dir = tmp_path / "00002"
        emp_dir.mkdir()
        with patch("onemancompany.tools.mcp.config_builder.EMPLOYEES_DIR", tmp_path), \
             patch("onemancompany.tools.mcp.config_builder.TOOLS_DIR", tmp_path):
            path = write_mcp_config("00002", task_id="t1")

        assert path.exists()
        data = json.loads(path.read_text())
        assert data["mcpServers"]["onemancompany"]["env"]["OMC_EMPLOYEE_ID"] == "00002"


class TestCompanyMcpServers:
    """config.yaml `mcp_servers`: explicitly granted connectors only."""

    def _cfg(self, monkeypatch, servers):
        from onemancompany.core import config as config_mod
        monkeypatch.setattr(config_mod, "load_app_config", lambda: {"mcp_servers": servers})

    def test_granted_to_everyone_without_employees(self, monkeypatch):
        self._cfg(monkeypatch, {"stripe": {"command": "npx", "args": ["-y", "@stripe/mcp"], "env": {"STRIPE_SECRET_KEY": "rk_test"}}})
        cfg = build_mcp_config("00004")
        assert cfg["mcpServers"]["stripe"] == {"command": "npx", "args": ["-y", "@stripe/mcp"], "env": {"STRIPE_SECRET_KEY": "rk_test"}}

    def test_restricted_to_listed_employees(self, monkeypatch):
        self._cfg(monkeypatch, {"stripe": {"command": "npx", "employees": ["00005"]}})
        assert "stripe" in build_mcp_config("00005")["mcpServers"]
        assert "stripe" not in build_mcp_config("00004")["mcpServers"]
        assert "employees" not in build_mcp_config("00005")["mcpServers"]["stripe"]

    def test_http_server_and_invalid_entries(self, monkeypatch):
        self._cfg(monkeypatch, {
            "remote": {"type": "http", "url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer x"}},
            "broken": {"args": ["x"]},
            "onemancompany": {"command": "evil"},
        })
        servers = build_mcp_config("00004")["mcpServers"]
        assert servers["remote"]["url"] == "https://mcp.example.com/mcp"
        assert "broken" not in servers
        assert servers["onemancompany"]["args"][-2:] == ["-m", "onemancompany.tools.mcp.server"]


def test_claude_session_uses_strict_mcp_config():
    import inspect
    from onemancompany.core import claude_session

    source = inspect.getsource(claude_session)
    assert '"--strict-mcp-config"' in source
    assert '"--setting-sources", "project,local"' in source


def test_mcp_server_gets_data_root():
    """The MCP server runs in the employee workspace: it needs the real data root."""
    from onemancompany.core.config import DATA_ROOT
    env = build_mcp_config("00004")["mcpServers"]["onemancompany"]["env"]
    assert env["OMC_DATA_ROOT"] == str(DATA_ROOT.resolve())
