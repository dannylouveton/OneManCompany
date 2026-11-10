"""report_up: reports go one level up the hierarchy."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from onemancompany.agents import common_tools as ct


@pytest.mark.parametrize("emp, profile, expected", [
    ("00004", {}, "00001"),
    ("00003", {}, "00004"),
    ("00002", {}, "00004"),
    ("00007", {"department": "Engineering", "role": "Lead DevOps / SRE"}, "00003"),
    ("00006", {"department": "Support client", "role": "Agent de support"}, "00003"),
    ("00008", {"department": "Marketing", "role": "Growth"}, "00005"),
    ("00009", {"department": "Ressources humaines", "role": "Recruteur"}, "00002"),
])
def test_manager_of(monkeypatch, emp, profile, expected):
    monkeypatch.setattr(ct, "load_employee", lambda e: profile)
    assert ct.manager_of(emp) == expected


@pytest.mark.asyncio
async def test_report_goes_to_manager_not_ceo(monkeypatch):
    monkeypatch.setattr(ct, "_validate_employee_id", lambda e: None)
    monkeypatch.setattr(ct, "load_employee", lambda e: {"department": "Engineering", "nickname": "Le Diplomate"})
    pushed = []
    monkeypatch.setattr("onemancompany.api.routes._push_adhoc_task", lambda emp, desc, *a, **k: pushed.append((emp, desc)))
    result = await ct.report_up.ainvoke({"message": "Backups checked.", "employee_id": "00007"})
    assert result == {"status": "sent", "to": "00003"}
    assert "Backups checked." in pushed[0][1] and "report_up" in pushed[0][1]


@pytest.mark.asyncio
async def test_ea_reports_to_ceo(monkeypatch):
    monkeypatch.setattr(ct, "_validate_employee_id", lambda e: None)
    with patch.object(ct, "report_to_ceo") as rep:
        rep.ainvoke = AsyncMock(return_value={"status": "ok", "channel": "oneonone"})
        result = await ct.report_up.ainvoke({"message": "Weekly summary", "employee_id": "00004"})
    assert result["to"] == "00001"
