"""request_api_key no longer collects keys in chat: it asks the CEO to grant API access."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_requests_access_without_collecting_a_key():
    from onemancompany.agents import common_tools

    with patch("onemancompany.core.api_tools.granted_apis", return_value=[]), \
         patch.object(common_tools, "notify_ceo") as notify:
        result = await common_tools.request_api_key.ainvoke(
            {"service_name": "stripe", "reason": "refunds", "employee_id": "00006"})
    assert result["status"] == "requested"
    assert "Tools" in notify.invoke.call_args.args[0]["message"]


@pytest.mark.asyncio
async def test_already_granted():
    from onemancompany.agents import common_tools

    apis = [{"api": "stripe_api", "name": "Stripe API"}]
    with patch("onemancompany.core.api_tools.granted_apis", return_value=apis):
        result = await common_tools.request_api_key.ainvoke(
            {"service_name": "stripe", "reason": "x", "employee_id": "00006"})
    assert result["status"] == "already_granted"


@pytest.mark.asyncio
async def test_requires_employee_id():
    from onemancompany.agents import common_tools

    result = await common_tools.request_api_key.ainvoke({"service_name": "s", "reason": "r", "employee_id": ""})
    assert "employee_id" in str(result)
