"""Access desk tools: employees ask, the COO grants / escalates / refuses."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from onemancompany.agents import access_tools
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
    people = {"00007": {"nickname": "Le Diplomate", "role": "Lead DevOps / SRE"}, "00003": {"role": "COO"}}
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: people.get(e, {}))
    monkeypatch.setattr("onemancompany.agents.common_tools.load_employee", lambda e: people.get(e, {"name": e}))
    monkeypatch.setattr(access_tools, "_fr", lambda: True)
    monkeypatch.setattr(access_desk, "_lang", lambda: "fr")
    monkeypatch.setattr(access_desk, "post_to_thread", AsyncMock())
    return tmp_path


def _task_node(node_id="n_req", node_type="task"):
    return SimpleNamespace(id=node_id, node_type=node_type, project_id="p1/iter_001", hold_reason="",
                           project_dir="")


@pytest.mark.asyncio
async def test_request_in_a_project_task_goes_to_the_coo_and_waits(desk, monkeypatch):
    monkeypatch.setattr(access_tools, "_task_context", lambda: ("/x/task_tree.yaml", "p1/iter_001", _task_node()))
    dispatched = []

    class FakeDispatch:
        @staticmethod
        def invoke(args):
            dispatched.append(args)
            return {"status": "dispatched", "node_id": "n_coo"}

    monkeypatch.setattr("onemancompany.agents.tree_tools.dispatch_child", FakeDispatch)
    result = await access_tools.request_access.ainvoke({
        "service": "Scalingo", "reason": "vérifier les sauvegardes", "kind": "cli",
        "blocked": "test de restauration", "employee_id": "00007"})
    assert result["status"] == "requested" and "End your turn" in result["message"]
    access_desk.post_to_thread.assert_awaited_once()  # the request shows in the project thread
    assert access_desk.post_to_thread.await_args.args[0] == "p1/iter_001"
    assert "Demande d'accès : Scalingo" in access_desk.post_to_thread.await_args.args[2]
    assert dispatched[0]["target_employee_id"] == "00003" and dispatched[0]["title"] == "Accès : Scalingo"
    assert "grant_access" in dispatched[0]["description"] and "escalate_access_request" in dispatched[0]["description"]
    req = access_desk.list_requests()[0]
    assert req["requesters"][0]["coo_node"] == "n_coo" and req["requesters"][0]["task_id"] == "n_req"

    # A retry in the same task does not send a second request while the COO works on it
    monkeypatch.setattr(access_tools, "_node_active", lambda tree, node: node == "n_coo")
    again = await access_tools.request_access.ainvoke({
        "service": "scalingo", "reason": "idem", "employee_id": "00007"})
    assert again["status"] == "already_requested" and len(dispatched) == 1


@pytest.mark.asyncio
async def test_validation(desk, monkeypatch):
    monkeypatch.setattr(access_tools, "_task_context", lambda: ("", "", None))
    result = await access_tools.request_access.ainvoke({"service": "", "reason": "x", "employee_id": "00007"})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_coo_escalates_and_its_task_waits(desk, monkeypatch):
    req, _ = access_desk.submit("00007", "n8n", "voir les exécutions en erreur", project_id="p1/iter_001")
    node = _task_node("n_coo")
    monkeypatch.setattr(access_tools, "_task_context", lambda: ("/x/task_tree.yaml", "p1/iter_001", node))
    monkeypatch.setattr("onemancompany.core.task_tree.save_tree_async", lambda path: None)
    bad = await access_tools.escalate_access_request.ainvoke({
        "request_id": req["id"], "what_to_create": "Une clé d'API n8n", "why": "erreurs", "auth": "weird"})
    assert bad["status"] == "error"
    out = await access_tools.escalate_access_request.ainvoke({
        "request_id": req["id"], "what_to_create": "Une clé d'API n8n", "why": "Le Diplomate surveille les erreurs",
        "minimal_rights": "lecture", "base_url": "https://n8n.example.com/api/v1",
        "auth": "header:X-N8N-API-KEY:{key}", "employee_id": "00003"})
    assert out["status"] == "sent_to_ceo" and "End your turn" in out["message"]
    assert node.hold_reason == f"access_request={req['id']},no_watchdog=1"
    card = access_desk.get_request(req["id"])["card"]
    assert card["setup"]["auth_name"] == "X-N8N-API-KEY" and card["by"] == "COO"
    posted = access_desk.post_to_thread.await_args.args
    assert posted[0] == "p1/iter_001" and "boîte" in posted[2]  # the card is announced in the project thread


@pytest.mark.asyncio
async def test_coo_grants_an_existing_connector_and_restarts_sessions(desk, monkeypatch):
    folder = desk / "tools" / "photonet"
    folder.mkdir()
    (folder / "tool.yaml").write_text(yaml.safe_dump({"id": "photonet", "name": "Photonet", "type": "mcp",
                                                      "mcp": {"command": "node"}, "allowed_users": ["00006"]}))
    req, _ = access_desk.submit("00007", "Photonet", "lire les commandes")
    stop = AsyncMock(return_value=1)
    monkeypatch.setattr(access_desk, "reconcile", AsyncMock(return_value=0))
    with patch("onemancompany.core.claude_session.stop_employee_daemons", stop):
        out = await access_tools.grant_access.ainvoke({
            "request_id": req["id"], "target_employee_id": "00007", "tool_id": "photonet", "employee_id": "00003"})
    assert out["status"] == "granted" and "Accès accordé" in out["for_the_employee"]
    assert "mcp__photonet__" in out["for_the_employee"]
    data = yaml.safe_load((folder / "tool.yaml").read_text())
    assert data["allowed_users"] == ["00006", "00007"] and data["grants"]["00007"]["granted_by"] == "COO"
    stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_coo_refuses(desk, monkeypatch):
    monkeypatch.setattr(access_desk, "reconcile", AsyncMock(return_value=0))
    req, _ = access_desk.submit("00007", "Stripe", "rembourser", access="write")
    out = await access_tools.refuse_access.ainvoke({"request_id": req["id"], "target_employee_id": "00007",
                                             "reason": "le support s'en charge", "employee_id": "00003"})
    assert out["status"] == "refused" and "le support s'en charge" in out["for_the_employee"]
    listed = access_tools.list_access_requests.invoke({"status": "all"})
    assert listed["requests"][0]["status"] == "refused"


def test_coo_tool_grant_keeps_api_key_definition(desk, monkeypatch):
    """grant_tool_access on an API key tool used to rewrite tool.yaml without its API settings."""
    from onemancompany.agents import coo_agent
    from onemancompany.core.state import OfficeTool, company_state

    tool_id = api_tools.create_api_tool("Intercom", "https://api.intercom.io", "secret_key_99999")
    monkeypatch.setitem(company_state.tools, tool_id, OfficeTool(id=tool_id, name="Intercom", description="",
                                                                 added_by="CEO", folder_name=tool_id,
                                                                 allowed_users=[]))
    coo_agent.grant_tool_access.invoke({"tool_id": tool_id, "target_employee_id": "00007"})
    data = api_tools.load_tool(tool_id)
    assert data["type"] == "api_key" and data["api"]["base_url"] == "https://api.intercom.io"
    assert data["allowed_users"] == ["00007"] and data["grants"]["00007"]["granted_by"] == "COO"
    coo_agent.revoke_tool_access.invoke({"tool_id": tool_id, "target_employee_id": "00007"})
    assert api_tools.load_tool(tool_id)["allowed_users"] == []


@pytest.mark.asyncio
async def test_coo_opens_a_need_mentioned_in_a_report(desk, monkeypatch):
    """A need written in a report goes to the desk, in the employee's project thread, not to the CEO."""
    node = _task_node("n_onb")
    monkeypatch.setattr(access_tools, "_latest_project_task", lambda emp: ("/p/task_tree.yaml", "p1/iter_001", node))
    added = []
    monkeypatch.setattr(access_tools, "_add_desk_task",
                        lambda tree_path, parent, brief, title: added.append((tree_path, parent.id, brief, title)) or "n_coo")
    out = await access_tools.open_access_request.ainvoke({
        "target_employee_id": "00007", "service": "Scalingo", "kind": "cli",
        "reason": "revérifier en direct la base et les sauvegardes", "employee_id": "00003"})
    assert out["status"] == "opened" and out["coo_task"] == "n_coo" and out["project_id"] == "p1/iter_001"
    tree_path, parent_id, brief, title = added[0]
    assert (tree_path, parent_id, title) == ("/p/task_tree.yaml", "n_onb", "Accès : Scalingo")
    assert "Opened by:" in brief and "grant_access" in brief
    req = access_desk.list_requests()[0]
    entry = req["requesters"][0]
    assert entry["task_id"] == "n_onb" and entry["coo_node"] == "n_coo" and entry["opened_by"]
    posted = access_desk.post_to_thread.await_args.args
    assert posted[0] == "p1/iter_001" and "Demande ouverte par" in posted[2]

    # Same need again: already at the desk, nothing new
    monkeypatch.setattr(access_tools, "_node_active", lambda tree, n: n == "n_coo")
    again = await access_tools.open_access_request.ainvoke({
        "target_employee_id": "00007", "service": "scalingo", "reason": "idem", "employee_id": "00003"})
    assert again["status"] == "already_requested" and len(added) == 1


@pytest.mark.asyncio
async def test_open_for_unknown_or_already_equipped_employee(desk, monkeypatch):
    out = await access_tools.open_for_employee("00042", "Scalingo", "x")
    assert out["status"] == "error"
    monkeypatch.setattr(access_tools, "_already_granted", lambda *a: [{"api": "scalingo"}])
    out = await access_tools.open_for_employee("00007", "Scalingo", "x")
    assert out["status"] == "already_granted"


@pytest.mark.asyncio
async def test_open_without_project_task_goes_to_the_coo_as_a_separate_task(desk, monkeypatch):
    monkeypatch.setattr(access_tools, "_latest_project_task", lambda emp: ("", "", None))
    pushed = []
    monkeypatch.setattr("onemancompany.api.routes._push_adhoc_task", lambda emp, text, **k: pushed.append((emp, text)))
    out = await access_tools.open_for_employee("00007", "n8n", "exécutions en erreur", opened_by="le CEO")
    assert out["status"] == "opened" and pushed[0][0] == "00003" and "n8n" in pushed[0][1]
    access_desk.post_to_thread.assert_not_awaited()


def test_latest_project_task_and_desk_task(desk, tmp_path, monkeypatch):
    from onemancompany.core.task_tree import TaskTree

    pdir = tmp_path / "proj" / "iterations" / "iter_001"
    pdir.mkdir(parents=True)
    tree = TaskTree(project_id="proj/iter_001")
    root = tree.create_root(employee_id="00001", description="Prise de poste")
    child = tree.add_child(parent_id=root.id, employee_id="00007", description="note", acceptance_criteria=[])
    child.project_id = "proj/iter_001"
    child.project_dir = str(pdir)
    tree_path = pdir / "task_tree.yaml"
    tree.save(tree_path)
    sys_tree = tmp_path / "x_tree.yaml"
    TaskTree(project_id="_sys_1").save(sys_tree)
    monkeypatch.setattr("onemancompany.core.store.load_task_index",
                        lambda emp: [{"node_id": child.id, "tree_path": str(tree_path)},
                                     {"node_id": "zz", "tree_path": str(sys_tree)}])
    found_path, project_id, node = access_tools._latest_project_task("00007")
    assert found_path == str(tree_path) and project_id == "proj/iter_001" and node.id == child.id

    scheduled = []
    monkeypatch.setattr("onemancompany.agents.tree_tools._add_to_project_team", lambda d, e: None)
    monkeypatch.setattr("onemancompany.core.vessel.employee_manager.schedule_node",
                        lambda emp, nid, path: scheduled.append((emp, nid, path)))
    monkeypatch.setattr("onemancompany.core.vessel.employee_manager._schedule_next", lambda emp: None)
    monkeypatch.setattr("onemancompany.core.task_tree.save_tree_async", lambda path: None)
    coo_node = access_tools._add_desk_task(str(tree_path), node, "brief", "Accès : Scalingo")
    from onemancompany.core.task_tree import get_tree

    added = get_tree(str(tree_path)).get_node(coo_node)
    assert added.parent_id == child.id and added.employee_id == "00003" and added.project_id == "proj/iter_001"
    assert scheduled == [("00003", coo_node, str(tree_path))]
