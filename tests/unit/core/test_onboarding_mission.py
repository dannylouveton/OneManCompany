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
async def test_arrival_note_opens_a_visible_project(emp_dir, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from onemancompany.core import project_archive, vessel, conversation
    from onemancompany.agents import tree_tools
    from onemancompany.core.task_lifecycle import NodeType

    pdir = tmp_path / "proj"
    pdir.mkdir()
    saved, scheduled = {}, []
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: {"nickname": "Le Diplomate", "role": "SRE"})
    monkeypatch.setattr(om, "_lang", lambda: "fr")
    monkeypatch.setattr(project_archive, "create_named_project", lambda name: saved.setdefault("name", name) and "p1")
    monkeypatch.setattr(project_archive, "create_iteration", lambda *a: "iter_001")
    monkeypatch.setattr(project_archive, "get_project_dir", lambda pid: str(pdir))
    monkeypatch.setattr(vessel, "_save_project_tree", lambda d, tree: saved.setdefault("tree", tree))
    monkeypatch.setattr(tree_tools, "_add_to_project_team", lambda d, e: None)

    class Conv:
        async def get_or_create_project_conversation(self, *a):
            return SimpleNamespace(id="c1")

        async def push_system_message(self, *a, **k):
            return None

    monkeypatch.setattr(conversation, "get_conversation_service", lambda: Conv())
    monkeypatch.setattr(vessel, "employee_manager", SimpleNamespace(
        schedule_node=lambda emp, nid, path: scheduled.append((emp, nid)), _schedule_next=lambda emp: None))

    result = await om.launch_mission("00007", "Scalingo")
    assert result["status"] == "launched" and result["project_id"] == "p1"
    assert saved["name"] == "Prise de poste — Le Diplomate"
    tree = saved["tree"]
    root = tree.get_node(tree.root_id)
    assert root.node_type == NodeType.CEO_PROMPT
    node = tree.get_node(root.children_ids[0])
    assert node.employee_id == "00007" and "Scalingo" in node.description and str(pdir) in node.description
    assert scheduled == [("00007", node.id)]
