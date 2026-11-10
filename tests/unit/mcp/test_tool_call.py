"""Tests for internal MCP tool-call API endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from onemancompany.api.routes import router
from onemancompany.core.tool_registry import ToolMeta, tool_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_test_tools():
    """Remove test tools after each test."""
    yield
    for name in list(tool_registry._tools.keys()):
        if name.startswith("test_") or name == "bad_tool":
            tool_registry._tools.pop(name, None)
            tool_registry._meta.pop(name, None)


@pytest.fixture(autouse=True)
def signed_caller(monkeypatch):
    """Requests in these tests come from OneManCompany's own tool bridge."""
    monkeypatch.setattr("onemancompany.core.secret_store.verify_caller", lambda emp, sig: True)


def _make_app():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInternalToolCall:
    @pytest.mark.asyncio
    async def test_missing_tool_name(self):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/internal/tool-call", json={
                "employee_id": "00002",
                "task_id": "t1",
                "tool_name": "",
                "args": {},
            })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/internal/tool-call", json={
                "employee_id": "00002",
                "task_id": "t1",
                "tool_name": "nonexistent_tool",
                "args": {},
            })
        # execute_tool returns error dict, not HTTP 404
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    @pytest.mark.asyncio
    async def test_tool_call_with_context(self):
        """Tool call sets context vars and invokes the tool."""
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.ainvoke = AsyncMock(return_value={"status": "ok", "data": "test"})

        tool_registry.register(mock_tool, ToolMeta(name="test_tool", category="base"))

        mock_vessel = MagicMock()
        mock_em = MagicMock()
        mock_em.get_handle.return_value = mock_vessel

        app = _make_app()
        with patch("onemancompany.core.vessel.employee_manager", mock_em):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/internal/tool-call", json={
                    "employee_id": "00002",
                    "task_id": "task123",
                    "tool_name": "test_tool",
                    "args": {"param1": "value1"},
                })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # employee_id auto-filled by execute_tool for MCP path
        mock_tool.ainvoke.assert_called_once_with({"param1": "value1", "employee_id": "00002"})

    @pytest.mark.asyncio
    async def test_tool_error_returns_error_dict(self):
        """Tool that raises an exception returns error dict, not 500."""
        mock_tool = MagicMock()
        mock_tool.name = "bad_tool"
        mock_tool.ainvoke = AsyncMock(side_effect=ValueError("something broke"))

        tool_registry.register(mock_tool, ToolMeta(name="bad_tool", category="base"))

        app = _make_app()
        with patch("onemancompany.core.vessel.employee_manager", MagicMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/internal/tool-call", json={
                    "employee_id": "00002",
                    "task_id": "t1",
                    "tool_name": "bad_tool",
                    "args": {},
                })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "something broke" in data["message"]


@pytest.mark.asyncio
async def test_unsigned_caller_is_rejected(monkeypatch):
    monkeypatch.setattr("onemancompany.core.secret_store.verify_caller", lambda emp, sig: False)
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/internal/tool-call", json={
            "employee_id": "00006", "task_id": "", "tool_name": "list_company_apis", "args": {},
        })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_caller_identity_overrides_employee_id_in_args():
    """An employee cannot act as another one by putting employee_id in args."""
    from langchain_core.tools import tool as lc_tool

    from onemancompany.core.tool_registry import execute_tool

    @lc_tool
    def test_whoami(employee_id: str = "") -> dict:
        """Return the caller."""
        return {"caller": employee_id}

    tool_registry.register(test_whoami, ToolMeta(name="test_whoami", category="base"))
    result = await execute_tool("00004", "test_whoami", {"employee_id": "00006"})
    assert result.get("caller") == "00004" or "00004" in str(result)


@pytest.mark.asyncio
async def test_current_task_wins_over_stale_task_id(monkeypatch):
    """A long-lived session sends the task id it started with; use the running one."""
    from types import SimpleNamespace

    from onemancompany.core import vessel

    seen = {}

    async def fake_execute(emp, name, args):
        seen["task"] = vessel._current_task_id.get()
        return {"ok": True}

    monkeypatch.setattr("onemancompany.core.tool_registry.execute_tool", fake_execute)
    monkeypatch.setattr("onemancompany.api.routes.execute_tool", fake_execute, raising=False)
    monkeypatch.setitem(vessel.employee_manager._current_entries, "00004", SimpleNamespace(node_id="new-task"))
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/internal/tool-call", json={
            "employee_id": "00004", "task_id": "old-task", "tool_name": "x", "args": {}})
    assert resp.status_code == 200 and seen["task"] == "new-task"


def test_hire_context_matches_batch_project(monkeypatch):
    from onemancompany.agents import recruitment
    from onemancompany.api import routes

    monkeypatch.setattr(routes, "_pending_coo_hire_queue", [
        {"role": "Agent de support", "project_id": "aaa/iter_001"},
        {"role": "Agent de support", "project_id": "bbb/iter_001"},
        {"role": "Lead DevOps", "project_id": "ccc/iter_001"},
    ])
    monkeypatch.setitem(recruitment._pending_project_ctx, "batch-1", {"project_id": "ccc/iter_001"})
    assert routes._take_coo_hire_ctx("batch-1")["role"] == "Lead DevOps"
    # No project known: the most recent request, never the oldest stale one
    assert routes._take_coo_hire_ctx("unknown")["project_id"] == "bbb/iter_001"
