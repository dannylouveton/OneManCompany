"""ask_ceo: multiple-choice questions to the CEO."""
from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, patch

import pytest

from onemancompany.agents import common_tools as ct

Q = [{"question": "Which host?", "header": "Host", "options": [
    {"label": "Scalingo", "description": "current", "recommended": True}, "Fly.io"]}]


def test_normalize_and_format():
    clean = ct._normalize_questions(Q)
    assert clean[0]["options"][1] == {"label": "Fly.io", "description": "", "recommended": False}
    text = ct.format_ceo_questions(clean, "We must choose.")
    block = re.search(r"```omc-questions\n(.+)\n```", text, re.S).group(1)
    assert json.loads(block)["questions"][0]["header"] == "Host"
    assert "Scalingo (recommended) — current" in text


@pytest.mark.parametrize("bad", [[], [{"question": "x", "options": ["a"]}], [{"options": ["a", "b"]}], "nope",
                                  [{"question": "q", "options": ["a", "b"]}] * 5])
def test_normalize_rejects(bad):
    with pytest.raises(ValueError):
        ct._normalize_questions(bad)


@pytest.mark.asyncio
async def test_outside_task_goes_to_ceo_channel(monkeypatch):
    monkeypatch.setattr(ct, "_validate_employee_id", lambda e: None)
    sent = {}

    async def fake_report(payload):
        sent.update(payload)
        return {"status": "ok", "channel": "oneonone"}

    with patch.object(ct, "report_to_ceo") as rep:
        rep.ainvoke = AsyncMock(side_effect=fake_report)
        result = await ct.ask_ceo.ainvoke({"questions": Q, "employee_id": "00004"})
    assert result["status"] == "asked"
    assert "```omc-questions" in sent["message"]


@pytest.mark.asyncio
async def test_invalid_questions_return_error(monkeypatch):
    monkeypatch.setattr(ct, "_validate_employee_id", lambda e: None)
    result = await ct.ask_ceo.ainvoke({"questions": [{"question": "x", "options": ["a"]}], "employee_id": "00004"})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_inside_task_creates_ceo_request(monkeypatch):
    from onemancompany.agents import tree_tools
    from onemancompany.core import vessel

    monkeypatch.setattr(ct, "_validate_employee_id", lambda e: None)
    monkeypatch.setattr(tree_tools, "_find_entry_for_task", lambda t: ("/proj", "/proj/tree.yaml"))
    calls = {}

    class FakeDispatch:
        @staticmethod
        def invoke(payload):
            calls.update(payload)
            return {"status": "dispatched", "node_id": "n1"}

    monkeypatch.setattr(tree_tools, "dispatch_child", FakeDispatch)
    token = vessel._current_task_id.set("task-1")
    try:
        result = await ct.ask_ceo.ainvoke({"questions": Q, "employee_id": "00007"})
    finally:
        vessel._current_task_id.reset(token)
    assert result == {"status": "asked", "request_node": "n1", "message": result["message"]}
    assert calls["target_employee_id"] == "00001" and "omc-questions" in calls["description"]
