"""Onboarding charter, first mission and weekly round for new hires."""
from __future__ import annotations

import pytest

from onemancompany.core import onboarding_mission as om


@pytest.fixture()
def emp_dir(tmp_path, monkeypatch):
    from onemancompany.core import config

    monkeypatch.setattr(config, "EMPLOYEES_DIR", tmp_path)
    monkeypatch.setattr(config, "load_workflows", lambda: {
        "onboarding_charter": "# Charter\n1. Take ownership.",
        "onboarding_mission": "Welcome {nickname} ({role}). Why: {context}. Work in {workspace}.",
    })
    (tmp_path / "00007").mkdir()
    return tmp_path / "00007"


def test_old_charter_copy_is_removed(emp_dir):
    (emp_dir / "work_principles.md").write_text(
        "# My principles\n- be kind\n\n<!-- onboarding-charter:start -->\n# Charter\n<!-- onboarding-charter:end -->\n")
    assert om.remove_charter("00007")
    text = (emp_dir / "work_principles.md").read_text()
    assert text == "# My principles\n- be kind\n"
    assert not om.remove_charter("00007")


def test_render_mission_fills_placeholders():
    out = om.render_mission("Hi {nickname}, {context}", {"nickname": "Le Diplomate", "context": ""})
    assert out == "Hi Le Diplomate, —"


@pytest.mark.asyncio
async def test_onboard_respects_settings_and_never_raises(emp_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(om, "_settings", lambda: {"mission": True, "weekly": False})

    async def boom(emp, ctx):
        calls.append((emp, ctx))
        raise RuntimeError("tree error")

    monkeypatch.setattr(om, "launch_mission", boom)
    result = await om.onboard("00007", "Scalingo + n8n")
    assert calls == [("00007", "Scalingo + n8n")] and "tree error" in result["error"]


@pytest.mark.asyncio
async def test_force_runs_everything(emp_dir, monkeypatch):
    monkeypatch.setattr(om, "_settings", lambda: {"mission": False, "weekly": False})

    async def fake_launch(emp, ctx):
        return {"status": "launched"}

    monkeypatch.setattr(om, "launch_mission", fake_launch)
    monkeypatch.setattr(om, "start_weekly", lambda emp: {"status": "ok"})
    result = await om.onboard("00007", force=True)
    assert result["mission"]["status"] == "launched"
    # The weekly round is the employee's own initiative unless the company imposes it
    assert "weekly" not in result


@pytest.mark.asyncio
async def test_arrival_note_assigns_nothing_from_the_top(emp_dir, monkeypatch):
    pushed = []
    monkeypatch.setattr("onemancompany.api.routes._push_adhoc_task", lambda emp, desc, *a, **k: pushed.append((emp, desc)) or "n1")
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: {"nickname": "Le Diplomate", "role": "SRE"})
    result = await om.launch_mission("00007", "Scalingo")
    assert result == {"status": "launched", "node_id": "n1"}
    assert pushed[0][0] == "00007" and "Le Diplomate" in pushed[0][1] and "Scalingo" in pushed[0][1]
