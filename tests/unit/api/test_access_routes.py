"""The CEO's access requests box: list, provide the key, done, refuse."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from onemancompany.api import routes
from onemancompany.core import access_desk, api_tools
from onemancompany.core import config as config_mod


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "TOOLS_DIR", tools)
    monkeypatch.setattr(config_mod, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
    monkeypatch.setattr("onemancompany.core.store.mark_dirty", lambda *a, **k: None)
    monkeypatch.setattr("onemancompany.core.store.load_employee",
                        lambda e: {"nickname": "Le Diplomate", "role": "Lead DevOps / SRE"})
    monkeypatch.setattr("onemancompany.agents.coo_agent._load_assets_from_disk", lambda: None)
    notify = AsyncMock(return_value=["00007"])
    monkeypatch.setattr(access_desk, "notify_requesters", notify)
    req, _ = access_desk.submit("00007", "GitHub", "lire la CI", kind="cli")
    access_desk.escalate(req["id"], what="Un jeton GitHub (lecture)", why="CI d'id_picture",
                         rights="Contents, Actions : lecture", setup={"preset": "github"})
    return req["id"], notify


@pytest.mark.asyncio
async def test_box_lists_cards_without_secrets(desk):
    rid, _notify = desk
    data = await routes.access_requests_list()
    assert data["waiting_ceo"] == 1
    card = data["requests"][0]
    assert card["id"] == rid and card["what"] == "Un jeton GitHub (lecture)"
    assert card["where_url"].startswith("https://github.com/settings")
    assert card["setup"]["cli"] == "gh" and card["requesters"][0]["label"] == "Le Diplomate (Lead DevOps / SRE)"


@pytest.mark.asyncio
async def test_provide_creates_the_tool_grants_and_resumes(desk):
    rid, notify = desk
    with pytest.raises(HTTPException):
        await routes.access_request_provide(rid, {"key": ""})
    out = await routes.access_request_provide(rid, {"key": "github_pat_SECRET123", "setup": {"name": "GitHub id_picture"}})
    assert out["status"] == "ok" and out["told"] == ["00007"]
    data = api_tools.load_tool(out["tool_id"])
    assert data["name"] == "GitHub id_picture" and data["allowed_users"] == ["00007"]
    assert "github_pat_SECRET123" not in str(out)
    notify.assert_awaited_once()
    assert (await routes.access_requests_list())["waiting_ceo"] == 0


@pytest.mark.asyncio
async def test_done_and_refuse(desk):
    rid, _notify = desk
    out = await routes.access_request_refuse(rid, {"reason": "pas tout de suite"})
    assert out["request"]["status"] == "refused"
    with pytest.raises(HTTPException):  # no longer waiting
        await routes.access_request_done(rid, {})
