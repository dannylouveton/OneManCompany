"""request_api_key never collects keys: it files an access request handled by the COO."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from onemancompany.core import config as config_mod


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "TOOLS_DIR", tmp_path / "tools")
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: {"nickname": "Le Héron", "role": "Support"})
    monkeypatch.setattr("onemancompany.agents.common_tools.load_employee", lambda e: {"name": e})
    return tmp_path


@pytest.mark.asyncio
async def test_files_an_access_request_for_the_coo(desk):
    from onemancompany.agents import common_tools

    pushed = []
    with patch("onemancompany.core.api_tools.granted_apis", return_value=[]), \
         patch("onemancompany.api.routes._push_adhoc_task", lambda emp, desc, *a, **k: pushed.append((emp, desc))):
        result = await common_tools.request_api_key.ainvoke(
            {"service_name": "stripe", "reason": "refunds", "employee_id": "00006"})
    assert result["status"] == "requested" and result["to"] == "00003"
    assert pushed[0][0] == "00003" and "Access request" in pushed[0][1] and "refunds" in pushed[0][1]
    assert "key" not in result.get("message", "").lower().split("api")[0]  # no key asked in chat


@pytest.mark.asyncio
async def test_already_granted(desk):
    from onemancompany.agents import common_tools

    apis = [{"api": "stripe_api", "name": "Stripe API", "writes": "not allowed"}]
    with patch("onemancompany.core.api_tools.granted_apis", return_value=apis):
        result = await common_tools.request_api_key.ainvoke(
            {"service_name": "stripe", "reason": "x", "employee_id": "00006"})
    assert result["status"] == "already_granted"


@pytest.mark.asyncio
async def test_requires_employee_id(desk):
    from onemancompany.agents import common_tools

    result = await common_tools.request_api_key.ainvoke({"service_name": "s", "reason": "r", "employee_id": ""})
    assert "employee_id" in str(result)
