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


def test_charter_added_once_and_refreshed(emp_dir, monkeypatch):
    from onemancompany.core import config

    (emp_dir / "work_principles.md").write_text("# My principles\n- be kind\n")
    assert om.apply_charter("00007")
    assert om.apply_charter("00007")
    text = (emp_dir / "work_principles.md").read_text()
    assert text.count("Take ownership") == 1 and text.startswith("# My principles")

    monkeypatch.setattr(config, "load_workflows", lambda: {"onboarding_charter": "# Charter v2"})
    om.apply_charter("00007")
    text = (emp_dir / "work_principles.md").read_text()
    assert "Charter v2" in text and "Take ownership" not in text and "be kind" in text


def test_render_mission_fills_placeholders():
    out = om.render_mission("Hi {nickname}, {context}", {"nickname": "Le Diplomate", "context": ""})
    assert out == "Hi Le Diplomate, —"


@pytest.mark.asyncio
async def test_onboard_respects_settings_and_never_raises(emp_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(om, "_settings", lambda: {"charter": False, "mission": True, "weekly": False})

    async def boom(emp, ctx):
        calls.append((emp, ctx))
        raise RuntimeError("tree error")

    monkeypatch.setattr(om, "launch_mission", boom)
    result = await om.onboard("00007", "Scalingo + n8n")
    assert calls == [("00007", "Scalingo + n8n")] and "tree error" in result["error"]
    assert not (emp_dir / "work_principles.md").exists()


@pytest.mark.asyncio
async def test_force_runs_everything(emp_dir, monkeypatch):
    monkeypatch.setattr(om, "_settings", lambda: {"charter": False, "mission": False, "weekly": False})

    async def fake_launch(emp, ctx):
        return {"status": "launched"}

    monkeypatch.setattr(om, "launch_mission", fake_launch)
    monkeypatch.setattr(om, "start_weekly", lambda emp: {"status": "ok"})
    result = await om.onboard("00007", force=True)
    assert result["charter"] is True and result["mission"]["status"] == "launched" and result["weekly"] == "ok"
