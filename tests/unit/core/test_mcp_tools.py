"""MCP connectors installed as company tools."""
from __future__ import annotations

import json

import pytest
import yaml

from onemancompany.core import config as config_mod
from onemancompany.core import mcp_tools


@pytest.fixture()
def tools_dir(tmp_path, monkeypatch):
    tdir = tmp_path / "tools"
    tdir.mkdir()
    monkeypatch.setattr(config_mod, "TOOLS_DIR", tdir)
    monkeypatch.setattr(config_mod, "DATA_ROOT", tmp_path)
    monkeypatch.setattr("onemancompany.core.store.mark_dirty", lambda *a, **k: None)
    return tdir


class TestParseCustom:
    def test_http_url(self):
        assert mcp_tools.parse_custom("https://mcp.example.com/mcp") == {"type": "http", "url": "https://mcp.example.com/mcp"}

    def test_sse_url(self):
        assert mcp_tools.parse_custom("https://x.io/sse")["type"] == "sse"

    def test_command_with_env(self):
        spec = mcp_tools.parse_custom("API_KEY=abc npx -y @acme/mcp --flag 'a b'")
        assert spec == {"command": "npx", "args": ["-y", "@acme/mcp", "--flag", "a b"], "env": {"API_KEY": "abc"}}

    def test_json_snippet(self):
        text = json.dumps({"mcpServers": {"acme": {"command": "node", "args": ["s.js"]}}})
        assert mcp_tools.parse_custom(text) == {"command": "node", "args": ["s.js"]}

    def test_empty(self):
        with pytest.raises(ValueError):
            mcp_tools.parse_custom("  ")


class TestConnectors:
    def test_custom_connector_moves_secrets_to_env(self, tools_dir, tmp_path, monkeypatch):
        monkeypatch.delenv("OMC_MCP_ACME_API_KEY", raising=False)
        tool_id = mcp_tools.create_custom("Acme", "API_KEY=s3cret npx -y @acme/mcp")
        data = yaml.safe_load((tools_dir / tool_id / "tool.yaml").read_text())
        assert data["type"] == "mcp"
        assert data["allowed_users"] == []  # nobody until granted
        assert data["mcp"]["env"]["API_KEY"] == "${OMC_MCP_ACME_API_KEY}"
        assert "s3cret" not in (tools_dir / tool_id / "tool.yaml").read_text()
        assert "OMC_MCP_ACME_API_KEY=s3cret" in (tmp_path / ".env").read_text()

    def test_grant_and_block(self, tools_dir, monkeypatch):
        monkeypatch.setenv("STRIPE_API_KEY", "rk_test_1")
        tool_id = mcp_tools.create_from_catalog("stripe")
        assert mcp_tools.servers_for("00005") == {}

        mcp_tools.update_access(tool_id, allowed_users=["00005"], disallowed_tools=["create_refund"])
        servers = mcp_tools.servers_for("00005")
        assert servers["stripe"]["headers"]["Authorization"] == "Bearer rk_test_1"
        assert mcp_tools.disallowed_for("00005") == ["mcp__stripe__create_refund"]
        assert mcp_tools.servers_for("00004") == {}
        assert mcp_tools.disallowed_for("00004") == []

    def test_reserved_names_are_renamed(self, tools_dir):
        tool_id = mcp_tools.create_custom("gmail", "https://x.io/mcp")
        assert tool_id != "gmail"

    def test_missing_secret_blocks_probe(self, tools_dir, monkeypatch):
        import asyncio

        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        tool_id = mcp_tools.create_from_catalog("notion")
        result = asyncio.run(mcp_tools.probe(tool_id))
        assert result["ok"] is False and "NOTION_TOKEN" in result["error"]

    def test_probe_blocks_sensitive_actions_by_default(self, tools_dir, monkeypatch):
        import asyncio

        tool_id = mcp_tools.create_custom("Shop", "https://shop.example/mcp")

        async def fake_list(spec):
            return [{"name": "search_orders", "description": ""}, {"name": "refund_payment", "description": ""},
                    {"name": "send_email", "description": ""}, {"name": "get_customer", "description": ""}]

        monkeypatch.setattr(mcp_tools, "_list_remote_tools", fake_list)
        result = asyncio.run(mcp_tools.probe(tool_id))
        assert result["ok"] is True
        assert result["disallowed_tools"] == ["refund_payment", "send_email"]

        # A later test keeps the CEO's choices
        mcp_tools.update_access(tool_id, disallowed_tools=[])
        asyncio.run(mcp_tools.probe(tool_id))
        assert mcp_tools.load_tool(tool_id)["disallowed_tools"] == []


class TestClaudeCodeImport:
    def test_lists_without_secrets_and_imports(self, tools_dir, tmp_path, monkeypatch):
        cfg = tmp_path / "home"
        cfg.mkdir()
        (cfg / ".claude.json").write_text(json.dumps({"mcpServers": {
            "shop": {"type": "stdio", "command": "/usr/bin/node", "args": ["/srv/shop/index.js"], "env": {"TOKEN": "abc"}},
            "remote": {"type": "http", "url": "https://r.example/mcp"},
        }}))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))

        listed = {s["name"]: s for s in mcp_tools.claude_code_servers()}
        assert listed["shop"]["has_secrets"] is True and "abc" not in json.dumps(listed)
        assert listed["remote"]["summary"] == "https://r.example/mcp"

        tool_id = mcp_tools.import_claude_code_server("shop")
        data = mcp_tools.load_tool(tool_id)
        assert data["source"] == "claude_code" and data["source_name"] == "shop"
        assert data["mcp"]["env"]["TOKEN"].startswith("${OMC_MCP_SHOP_")
        assert {s["name"]: s for s in mcp_tools.claude_code_servers()}["shop"]["installed"] is True


class TestSessionIntegration:
    def test_config_builder_and_blocked_tools(self, tools_dir, monkeypatch):
        from onemancompany.tools.mcp.config_builder import build_mcp_config, disallowed_mcp_tools_for

        monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
        tool_id = mcp_tools.create_custom("Shop", "https://shop.example/mcp")
        mcp_tools.update_access(tool_id, allowed_users=["00004"], disallowed_tools=["refund_payment"])

        shop = build_mcp_config("00004")["mcpServers"]["shop"]
        assert shop["args"][-2:] == ["connector", "shop"]
        assert "url" not in shop and "headers" not in shop  # secrets stay in the launcher
        assert "shop" not in build_mcp_config("00003")["mcpServers"]
        assert disallowed_mcp_tools_for("00004") == ["mcp__shop__refund_payment"]


class TestPersonalActions:
    def test_personal_list_overrides_shared_one(self, tools_dir):
        tool_id = mcp_tools.create_custom("Shop", "https://shop.example/mcp")
        mcp_tools.update_access(tool_id, allowed_users=["00004", "00006"], disallowed_tools=["refund_payment", "send_email"])
        mcp_tools.update_access(tool_id, employee_actions={"00006": ["send_email"]})

        assert mcp_tools.disallowed_for("00004") == ["mcp__shop__refund_payment", "mcp__shop__send_email"]
        assert mcp_tools.disallowed_for("00006") == ["mcp__shop__send_email"]

        # Back to the shared settings
        mcp_tools.update_access(tool_id, employee_actions={"00006": None})
        assert mcp_tools.disallowed_for("00006") == ["mcp__shop__refund_payment", "mcp__shop__send_email"]
        assert "employee_actions" not in mcp_tools.load_tool(tool_id)

    def test_empty_personal_list_allows_everything(self, tools_dir):
        tool_id = mcp_tools.create_custom("Shop", "https://shop.example/mcp")
        mcp_tools.update_access(tool_id, allowed_users=["00006"], disallowed_tools=["refund_payment"],
                                employee_actions={"00006": []})
        assert mcp_tools.disallowed_for("00006") == []


class TestNoSecretsInSessionConfig:
    def test_config_file_never_contains_connector_secrets(self, tools_dir, monkeypatch):
        import json as _json
        from onemancompany.tools.mcp.config_builder import build_mcp_config

        monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
        monkeypatch.setenv("STRIPE_API_KEY", "rk_live_supersecret")
        tool_id = mcp_tools.create_from_catalog("stripe")
        mcp_tools.update_access(tool_id, allowed_users=["00005"])
        dumped = _json.dumps(build_mcp_config("00005"))
        assert "rk_live_supersecret" not in dumped
        assert '"connector", "stripe"' in dumped
