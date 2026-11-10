"""Access desk: employees ask, the COO decides, the CEO only supplies keys."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import yaml

from onemancompany.core import access_desk, api_tools
from onemancompany.core import config as config_mod

KEY = "tok_ABCDEF123456"


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "TOOLS_DIR", tools)
    monkeypatch.setattr(config_mod, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
    monkeypatch.setattr("onemancompany.core.store.mark_dirty", lambda *a, **k: None)
    people = {"00007": {"nickname": "Le Diplomate", "role": "Lead DevOps / SRE"},
              "00006": {"nickname": "Le Héron", "role": "Support"}}
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: people.get(e, {}))
    monkeypatch.setattr(access_desk, "_lang", lambda: "fr")
    monkeypatch.setattr(access_desk, "post_to_thread", AsyncMock())
    return tmp_path


def _scalingo_request(emp="00007", access="read"):
    req, created = access_desk.submit(emp, "Scalingo API", "vérifier les sauvegardes", access=access,
                                      kind="cli", blocked="test de restauration")
    return req, created


def test_one_open_request_per_service(desk):
    first, created = _scalingo_request()
    assert created and first["status"] == "open" and first["key"] == "scalingo"
    second, created = access_desk.submit("00006", "scalingo", "voir les logs", kind="api")
    assert not created and second["id"] == first["id"]
    assert [q["employee"] for q in second["requesters"]] == ["00007", "00006"]
    assert sorted(second["kinds"]) == ["api", "cli"]
    # Asking again updates the entry; a write request is never downgraded
    access_desk.submit("00007", "Scalingo", "déployer #204", access="write")
    again, _ = access_desk.submit("00007", "Scalingo", "relire", access="read")
    entry = next(q for q in again["requesters"] if q["employee"] == "00007")
    assert entry["access"] == "write" and entry["reason"] == "relire"
    with pytest.raises(ValueError):
        access_desk.submit("00007", "", "x")
    with pytest.raises(ValueError):
        access_desk.submit("00007", "GitHub", "")


def test_coo_grants_an_existing_key_with_minimum_rights(desk):
    tool_id = api_tools.create_api_tool("Intercom", "https://api.intercom.io", KEY)
    api_tools.update_access(tool_id, rules={"read_only": False, "allowed_writes": [], "approval": False})
    req, _ = access_desk.submit("00006", "Intercom", "lire les conversations")
    assert access_desk.matching_tools("Intercom")[0]["tool_id"] == tool_id

    result = access_desk.grant(req["id"], "00006", tool_id, access="read", by="COO")
    data = api_tools.load_tool(tool_id)
    assert data["allowed_users"] == ["00006"]
    # Personal rules: read-only even though the shared rules allow every write
    assert api_tools.effective_rules(data, "00006")["read_only"] is True
    assert data["grants"]["00006"]["reason"] == "lire les conversations"
    assert data["grants"]["00006"]["granted_by"] == "COO"
    assert data["grant_history"][-1]["event"] == "granted"
    assert result["request"]["status"] == "done"
    assert api_tools.request(tool_id, "00006", "POST", "/conversations/1/reply")["status"] == "denied"
    with pytest.raises(ValueError):
        access_desk.grant(req["id"], "00099", tool_id)


def test_escalation_needs_a_usable_setup(desk):
    req, _ = _scalingo_request()
    with pytest.raises(ValueError):
        access_desk.escalate(req["id"], what="", why="x")
    with pytest.raises(ValueError):  # a key with no API address and no CLI could not be used
        access_desk.escalate(req["id"], what="Un jeton", why="sauvegardes", setup={})
    with pytest.raises(ValueError):
        access_desk.escalate(req["id"], what="Un jeton", why="x", setup={"preset": "nope"})
    out = access_desk.escalate(req["id"], what="Un jeton d'API Scalingo", why="Le Diplomate vérifie les sauvegardes",
                               rights="lecture", setup={"preset": "scalingo"})
    assert out["status"] == "waiting_ceo"
    assert out["card"]["where_url"] == "https://dashboard.scalingo.com/account/tokens"
    assert out["card"]["setup"]["cli"]["command"] == "scalingo"
    assert out["card"]["setup"]["exchange"]["url"].startswith("https://auth.scalingo.com")
    assert out["requesters"][0]["status"] == "validated"
    assert [r["id"] for r in access_desk.waiting_for_ceo()] == [req["id"]]


def test_ceo_provides_the_key(desk, tmp_path):
    req, _ = _scalingo_request(access="write")
    late, _ = access_desk.submit("00006", "Scalingo", "logs", kind="api")  # joins, not yet seen by the COO
    access_desk.escalate(req["id"], what="Un jeton d'API Scalingo", why="sauvegardes", setup={"preset": "scalingo"})
    access_desk.submit("00006", "Scalingo", "logs encore", kind="api")  # after escalation: COO must validate
    done, tool_id = access_desk.provide(req["id"], KEY, overrides={"name": "Scalingo Photonet"})

    data = api_tools.load_tool(tool_id)
    assert KEY not in (tmp_path / "tools" / tool_id / "tool.yaml").read_text()
    assert api_tools.load_tool(tool_id)["name"] == "Scalingo Photonet"
    assert data["cli"]["command"] == "scalingo" and data["api"]["auth"]["exchange"]
    assert data["allowed_users"] == ["00007"]  # only the requester the COO validated
    assert api_tools.effective_rules(data, "00007")["read_only"] is False  # asked for write
    assert done["status"] == "done" and done["resolution"]["tool_id"] == tool_id
    statuses = {q["employee"]: q["status"] for q in done["requesters"]}
    assert statuses == {"00007": "granted", "00006": "new"}
    with pytest.raises(ValueError):  # no longer waiting
        access_desk.provide(req["id"], KEY)


def test_new_key_for_an_existing_tool(desk):
    tool_id = api_tools.create_api_tool("GitHub", "https://api.github.com", "old_key_0000")
    req, _ = access_desk.submit("00007", "GitHub", "CI", kind="api")
    access_desk.escalate(req["id"], what="Nouveau jeton", why="l'ancien a expiré", tool_id=tool_id)
    _done, same = access_desk.provide(req["id"], KEY)
    assert same == tool_id
    from onemancompany.core.secret_store import get_secret_store

    assert get_secret_store().get(api_tools.load_tool(tool_id)["secret"]) == KEY


def test_done_without_key_and_refusals(desk):
    req, _ = access_desk.submit("00007", "GitHub org", "inviter le compte bot", kind="account")
    access_desk.escalate(req["id"], what="Inviter agent-bot dans l'organisation", why="CI", deliverable="action")
    done = access_desk.done_without_key(req["id"], "invitation envoyée")
    assert done["status"] == "done" and done["requesters"][0]["status"] == "granted"
    assert "invitation envoyée" in access_desk.outcome_text(done, done["requesters"][0])

    other, _ = access_desk.submit("00006", "Stripe", "rembourser", access="write")
    with pytest.raises(ValueError):
        access_desk.refuse(other["id"], "00006", "")
    refused = access_desk.refuse(other["id"], "00006", "passe par le support Stripe", by="COO")
    assert refused["status"] == "refused"
    text = access_desk.outcome_text(refused, refused["requesters"][0])
    assert text.startswith("Accès refusé") and "passe par le support Stripe" in text

    third, _ = access_desk.submit("00006", "Notion", "notes")
    access_desk.escalate(third["id"], what="Une clé Notion", why="notes", setup={"base_url": "https://api.notion.com/v1"})
    out = access_desk.refuse_by_ceo(third["id"], "pas maintenant")
    assert out["status"] == "refused" and out["requesters"][0]["note"] == "pas maintenant"


def test_outcome_text_tells_how_to_use_it_and_to_resume(desk):
    req, _ = _scalingo_request()
    access_desk.escalate(req["id"], what="Jeton", why="x", setup={"preset": "scalingo"})
    done, tool_id = access_desk.provide(req["id"], KEY)
    text = access_desk.outcome_text(done, done["requesters"][0])
    assert "Accès accordé" in text and f'api_request(api="{tool_id}"' in text and "run_cli" in text
    assert "test de restauration" in text and "lecture seule" in text


@pytest.mark.asyncio
async def test_notify_resumes_the_coo_task_or_tells_the_employee(desk):
    req, _ = _scalingo_request()
    access_desk.submit("00006", "Scalingo", "logs")
    access_desk.set_coo_node(req["id"], "00007", "node_coo_1")
    access_desk.escalate(req["id"], what="Jeton", why="x", setup={"preset": "scalingo"})
    done, _ = access_desk.provide(req["id"], KEY)

    pushed = []
    manager = type("M", (), {"resume_held_task": AsyncMock(return_value=True), "_current_entries": {}, "_schedule": {}})()
    with patch("onemancompany.core.vessel.employee_manager", manager), \
         patch("onemancompany.api.routes._push_adhoc_task", lambda emp, text, *a, **k: pushed.append((emp, text))):
        told = await access_desk.notify_requesters(done)
    assert told == ["00007", "00006"]
    manager.resume_held_task.assert_awaited_once()
    assert manager.resume_held_task.await_args.args[:2] == ("00003", "node_coo_1")
    assert pushed and pushed[0][0] == "00006"  # no COO task to resume: told directly


def test_requests_for_tool_and_storage(desk, tmp_path):
    req, _ = _scalingo_request()
    access_desk.escalate(req["id"], what="Jeton", why="x", setup={"preset": "scalingo"})
    _done, tool_id = access_desk.provide(req["id"], KEY)
    assert access_desk.requests_for_tool(tool_id)[0]["id"] == req["id"]
    stored = yaml.safe_load((tmp_path / "access_requests.yaml").read_text())
    assert stored[0]["history"][0]["event"] == "requested"
    assert KEY not in (tmp_path / "access_requests.yaml").read_text()
    assert access_desk.get_request(req["id"])["requesters"][0]["label"] == "Le Diplomate (Lead DevOps / SRE)"


def test_rpc_api_and_limited_writes(desk):
    """Telegram acts with GET too: no free reads; the COO limits writes to sending messages."""
    req, _ = access_desk.submit("00007", "Telegram bot", "envoyer les alertes", access="write")
    access_desk.escalate(req["id"], what="Un bot Telegram", why="alertes", setup={"preset": "telegram"},
                         allowed_writes=["post /sendMessage"])
    done, tool_id = access_desk.provide(req["id"], "123456:ABCDEF_bot_token")
    data = api_tools.load_tool(tool_id)
    assert data["api"]["rpc"] is True and data["api"]["auth"]["in"] == "path"
    assert api_tools.effective_rules(data, "00007")["allowed_writes"] == ["POST /sendMessage"]
    assert api_tools.decide(data, "00007", "POST", "/sendMessage")[0] == "allowed"
    assert api_tools.decide(data, "00007", "GET", "/sendMessage")[0] == "denied"
    assert api_tools.decide(data, "00007", "POST", "/deleteMessage")[0] == "denied"
    assert done["status"] == "done"


@pytest.mark.asyncio
async def test_reconcile_resumes_tasks_waiting_on_a_request_decided_elsewhere(desk):
    req, _ = access_desk.submit("00007", "n8n", "exécutions en erreur")
    access_desk.set_coo_node(req["id"], "00007", "node_coo_n8n")
    access_desk.escalate(req["id"], what="Une clé n8n", why="x", setup={"preset": "n8n", "base_url": "https://n8n.example.com/api/v1"})
    access_desk.refuse(req["id"], "00007", "passe par Scalingo", by="EA")  # decided outside the COO's task
    entry = type("E", (), {"node_id": "node_coo_n8n"})()
    manager = type("M", (), {"resume_held_task": AsyncMock(return_value=True), "_schedule": {"00003": [entry]}})()
    with patch("onemancompany.core.vessel.employee_manager", manager):
        assert await access_desk.reconcile() == 1
    args = manager.resume_held_task.await_args.args
    assert args[:2] == ("00003", "node_coo_n8n") and "passe par Scalingo" in args[2]
    empty = type("M", (), {"resume_held_task": AsyncMock(), "_schedule": {}})()
    with patch("onemancompany.core.vessel.employee_manager", empty):
        assert await access_desk.reconcile() == 0
    empty.resume_held_task.assert_not_awaited()



def _tree_with_waiting_task(tmp_path):
    """A project tree: the Diplomate's task waits for the COO's access task (its child)."""
    from onemancompany.core.task_lifecycle import NodeType, TaskPhase
    from onemancompany.core.task_tree import TaskTree

    tree = TaskTree(project_id="p1/iter_001")
    root = tree.create_root(employee_id="00001", description="Projet")
    root.node_type = NodeType.CEO_PROMPT
    asker = tree.add_child(parent_id=root.id, employee_id="00007", description="Vérifier les sauvegardes",
                           acceptance_criteria=[])
    asker.set_status(TaskPhase.PROCESSING)
    asker.set_status(TaskPhase.HOLDING)
    asker.result = "__HOLDING:awaiting_children,no_watchdog=1\nJ'attends l'accès Scalingo."
    asker.hold_reason = "awaiting_children,no_watchdog=1"
    coo = tree.add_child(parent_id=asker.id, employee_id="00003", description="Access request …", acceptance_criteria=[])
    coo.set_status(TaskPhase.PROCESSING)
    coo.set_status(TaskPhase.COMPLETED)
    path = tmp_path / "proj" / "task_tree.yaml"
    path.parent.mkdir(parents=True)
    return tree, asker, coo, str(path)


@pytest.mark.asyncio
async def test_decision_resumes_the_same_task_without_review(desk, tmp_path, monkeypatch):
    from onemancompany.core.task_lifecycle import TaskPhase
    from onemancompany.core.vessel import ScheduleEntry, employee_manager

    tree, asker, coo, path = _tree_with_waiting_task(tmp_path)
    req, _ = access_desk.submit("00007", "Scalingo", "sauvegardes", kind="cli", blocked="test de restauration",
                                task_id=asker.id, project_id="p1/iter_001", tree_path=path)
    access_desk.set_coo_node(req["id"], "00007", coo.id)
    tool_id = api_tools.create_api_tool("Scalingo", "", KEY, cli={"preset": "scalingo"})
    access_desk.grant(req["id"], "00007", tool_id, access="read")
    assert access_desk.is_access_node(coo.id) and not access_desk.is_access_node(asker.id)

    scheduled = []
    monkeypatch.setattr("onemancompany.core.task_tree.save_tree_async", lambda p: None)
    monkeypatch.setattr(employee_manager, "schedule_node", lambda emp, nid, p: scheduled.append((emp, nid)))
    monkeypatch.setattr(employee_manager, "_schedule_next", lambda emp: None)
    monkeypatch.setattr(employee_manager, "_publish_node_update", lambda emp, node: None)
    monkeypatch.setattr(employee_manager, "_log_node", lambda *a, **k: None)
    await employee_manager._on_access_decided(tree, coo, asker, ScheduleEntry(node_id=coo.id, tree_path=path))

    assert coo.status == TaskPhase.FINISHED.value  # accepted without a review round
    assert asker.status == TaskPhase.PENDING.value and asker.hold_reason == ""
    assert scheduled == [("00007", asker.id)]  # the same task goes back to the Diplomate
    assert asker.result.startswith("J'attends l'accès Scalingo.")
    assert "[Accès décidé" in asker.result and "run_cli" in asker.result and "test de restauration" in asker.result
    assert access_desk.get_request(req["id"])["requesters"][0]["delivered_at"]


@pytest.mark.asyncio
async def test_task_left_waiting_is_resumed_by_reconcile(desk, tmp_path, monkeypatch):
    from onemancompany.core.task_lifecycle import TaskPhase
    from onemancompany.core.vessel import employee_manager

    tree, asker, coo, path = _tree_with_waiting_task(tmp_path)
    coo.set_status(TaskPhase.ACCEPTED)
    coo.set_status(TaskPhase.FINISHED)
    req, _ = access_desk.submit("00007", "GitHub", "CI", task_id=asker.id, project_id="p1/iter_001", tree_path=path)
    access_desk.set_coo_node(req["id"], "00007", coo.id)
    access_desk.refuse(req["id"], "00007", "pas maintenant", by="EA")
    monkeypatch.setattr("onemancompany.core.task_tree.get_tree", lambda p: tree)
    (tmp_path / "proj" / "task_tree.yaml").write_text("x")
    reruns = []
    monkeypatch.setattr(employee_manager, "rerun_waiting_task",
                        lambda t, node, p, note: reruns.append((node.id, note)) or True)
    monkeypatch.setattr(employee_manager, "_schedule", {})
    assert await access_desk.reconcile() == 1
    assert reruns[0][0] == asker.id and "pas maintenant" in reruns[0][1]
    assert await access_desk.reconcile() == 0  # delivered once
