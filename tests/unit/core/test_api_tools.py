"""API keys as company tools, used through the relay."""
from __future__ import annotations

import json

import httpx
import pytest

from onemancompany.core import api_tools
from onemancompany.core import config as config_mod


@pytest.fixture()
def env(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setattr(config_mod, "TOOLS_DIR", tools)
    monkeypatch.setattr(config_mod, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
    monkeypatch.setattr("onemancompany.core.store.mark_dirty", lambda *a, **k: None)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json={"echo": "secret_key_123456 should be redacted", "ok": True},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    return tools, calls


def _make(env_tools):
    tool_id = api_tools.create_api_tool("Shop API", "https://api.shop.example/v1", "secret_key_123456",
                                        docs_url="https://docs.shop.example")
    return tool_id


def test_key_stored_in_secret_store_not_in_tool_yaml(env, tmp_path):
    tools, _ = env
    tool_id = _make(tools)
    assert "secret_key_123456" not in (tools / tool_id / "tool.yaml").read_text()
    assert "secret_key_123456" in (tmp_path / ".env").read_text()
    assert api_tools.load_tool(tool_id)["allowed_users"] == []


def test_https_required(env):
    with pytest.raises(ValueError):
        api_tools.create_api_tool("Bad", "http://evil.example", "k")


def test_access_and_read(env):
    tools, calls = env
    tool_id = _make(tools)
    assert api_tools.request(tool_id, "00006", "GET", "/orders")["status"] == "denied"

    api_tools.update_access(tool_id, allowed_users=["00006"])
    result = api_tools.request(tool_id, "00006", "GET", "/orders", {"limit": 5})
    assert result["status"] == "done"
    assert calls[-1]["url"] == "https://api.shop.example/v1/orders"
    assert calls[-1]["headers"]["Authorization"] == "Bearer secret_key_123456"
    assert "secret_key_123456" not in json.dumps(result)  # redacted from the response
    assert api_tools.read_log(tool_id)[0]["decision"] == "allowed"


def test_path_cannot_escape_base(env):
    tools, calls = env
    tool_id = _make(tools)
    api_tools.update_access(tool_id, allowed_users=["00006"])
    for bad in ("https://evil.example/x", "//evil.example", "/../admin"):
        assert api_tools.request(tool_id, "00006", "GET", bad)["status"] == "error"
    assert calls == []


def test_writes_read_only_then_allowed_pattern_with_approval(env):
    tools, calls = env
    tool_id = _make(tools)
    api_tools.update_access(tool_id, allowed_users=["00006"])
    assert api_tools.request(tool_id, "00006", "POST", "/orders/1/refund")["status"] == "denied"

    api_tools.update_access(tool_id, rules={"read_only": True, "allowed_writes": ["post /orders/*/reply"], "approval": True})
    assert api_tools.request(tool_id, "00006", "POST", "/orders/1/refund")["status"] == "denied"
    pending = api_tools.request(tool_id, "00006", "POST", "/orders/1/reply", body={"text": "hi"})
    assert pending["status"] == "pending_approval"
    assert calls == []
    assert [p["id"] for p in api_tools.list_pending(tool_id)] == [pending["request_id"]]

    done = api_tools.resolve_request(tool_id, pending["request_id"], approve=True)
    assert done["status"] == "done" and calls[-1]["json"] == {"text": "hi"}
    assert api_tools.list_pending(tool_id) == []
    assert api_tools.find_request(pending["request_id"])["status"] == "done"


def test_reject_and_personal_rules(env):
    tools, calls = env
    tool_id = _make(tools)
    api_tools.update_access(tool_id, allowed_users=["00004", "00006"],
                            employee_rules={"00006": {"read_only": False, "approval": False}})
    assert api_tools.request(tool_id, "00004", "DELETE", "/orders/1")["status"] == "denied"
    assert api_tools.request(tool_id, "00006", "DELETE", "/orders/1")["status"] == "done"

    api_tools.update_access(tool_id, employee_rules={"00006": {"read_only": False, "approval": True}})
    pending = api_tools.request(tool_id, "00006", "PATCH", "/orders/2", body={"x": 1})
    rejected = api_tools.resolve_request(tool_id, pending["request_id"], approve=False)
    assert rejected["status"] == "rejected"

    api_tools.update_access(tool_id, employee_rules={"00006": None})
    assert api_tools.request(tool_id, "00006", "DELETE", "/orders/1")["status"] == "denied"


def test_query_param_auth(env):
    tools, calls = env
    tool_id = api_tools.create_api_tool("Q", "https://q.example", "kkkkkkkkk1", auth_in="query", auth_name="apikey", auth_format="{key}")
    api_tools.update_access(tool_id, allowed_users=["00006"])
    api_tools.request(tool_id, "00006", "GET", "/x")
    assert calls[-1]["params"]["apikey"] == "kkkkkkkkk1"


def test_granted_apis_summary(env):
    tools, _ = env
    tool_id = _make(tools)
    api_tools.update_access(tool_id, allowed_users=["00006"], rules={"read_only": True, "allowed_writes": ["POST /a/*"]})
    [api] = api_tools.granted_apis("00006")
    assert api["api"] == tool_id and "POST /a/*" in api["writes"] and "secret" not in json.dumps(api)
    assert api_tools.granted_apis("00004") == []


def test_agent_sandbox_settings(tmp_path, monkeypatch):
    from onemancompany.core import claude_session

    monkeypatch.setattr(config_mod, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
    s = claude_session.agent_sandbox_settings()
    env = str(tmp_path / ".env")
    assert s["sandbox"]["enabled"] and s["sandbox"]["allowUnsandboxedCommands"] is False
    assert env in s["sandbox"]["filesystem"]["denyRead"]
    assert str(tmp_path) in s["sandbox"]["filesystem"]["allowWrite"]
    assert f"Read(/{env})" in s["permissions"]["deny"]

    monkeypatch.setattr(config_mod, "load_app_config", lambda: {"agent_sandbox": {"enabled": False}})
    assert claude_session.agent_sandbox_settings() is None
