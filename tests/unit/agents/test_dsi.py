"""The DSI: runs the access desk and the vault once the company has one."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from onemancompany.agents import access_tools, vault_tools
from onemancompany.core import access_desk
from onemancompany.core import config as config_mod
from onemancompany.core import vault


class _Store:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set_many(self, values):
        self.values.update(values)


PEOPLE = {
    "00003": {"nickname": "Le Forgeron", "role": "COO"},
    "00007": {"nickname": "Le Diplomate", "role": "Lead DevOps / SRE", "department": "Engineering"},
    "00009": {"nickname": "La Clé", "role": "DSI", "department": "Direction"},
}


@pytest.fixture()
def company(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "TOOLS_DIR", tmp_path / "tools")
    (tmp_path / "tools").mkdir()
    monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
    monkeypatch.setattr("onemancompany.core.store.mark_dirty", lambda *a, **k: None)
    people = dict(PEOPLE)
    monkeypatch.setattr("onemancompany.core.store.load_all_employees", lambda: people)
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: people.get(e, {}))
    monkeypatch.setattr("onemancompany.agents.common_tools.load_employee", lambda e: people.get(e, {"name": e}))
    store = _Store()
    monkeypatch.setattr("onemancompany.core.secret_store.get_secret_store", lambda: store)
    monkeypatch.setattr(access_desk, "post_to_thread", AsyncMock())
    monkeypatch.setattr(access_tools, "_fr", lambda: True)
    return people


def test_who_is_the_dsi(company):
    assert access_desk.is_dsi_role("DSI") and access_desk.is_dsi_role("Directeur des systèmes d’information")
    assert access_desk.is_dsi_role("CIO") and not access_desk.is_dsi_role("Lead DevOps / SRE")
    assert not access_desk.is_dsi_role("Développeur DSI-like")
    assert access_desk.dsi_id() == "00009" and access_desk.desk_owner_id() == "00009"
    del company["00009"]
    assert access_desk.dsi_id() == "" and access_desk.desk_owner_id() == "00003"


@pytest.mark.asyncio
async def test_requests_go_to_the_dsi(company, monkeypatch):
    node = SimpleNamespace(id="n_req", node_type="task", project_id="p1/iter_001", hold_reason="", project_dir="")
    monkeypatch.setattr(access_tools, "_task_context", lambda: ("/x/task_tree.yaml", "p1/iter_001", node))
    dispatched = []

    class FakeDispatch:
        @staticmethod
        def invoke(args):
            dispatched.append(args)
            return {"status": "dispatched", "node_id": "n_desk"}

    monkeypatch.setattr("onemancompany.agents.tree_tools.dispatch_child", FakeDispatch)
    out = await access_tools.request_access.ainvoke({"service": "OVH", "reason": "zone DNS", "employee_id": "00007"})
    assert out["to"] == "00009" and dispatched[0]["target_employee_id"] == "00009"
    assert access_tools._actor("00009") == "DSI"


def test_dsi_has_the_desk_and_vault_tools(company):
    from onemancompany.agents import coo_agent  # noqa: F401  (registers the tools)
    from onemancompany.core.tool_registry import tool_registry

    names = {t.name for t in tool_registry.get_tools_for("00009")}
    assert {"grant_access", "open_access_request", "vault_add_login", "vault_grant"} <= names
    company["00009"]["role"] = "Directrice des systèmes d'information"
    assert "vault_grant" in {t.name for t in tool_registry.get_tools_for("00009")}
    assert "vault_grant" not in {t.name for t in tool_registry.get_tools_for("00007")}


def test_dsi_reports_to_the_executive_assistant(company):
    from onemancompany.agents.common_tools import manager_of
    from onemancompany.core.config import COO_ID, EA_ID

    assert manager_of("00009") == EA_ID and manager_of("00007") == COO_ID


def test_dsi_gets_the_role_guide(company, tmp_path, monkeypatch):
    from onemancompany.core import vessel

    guides = tmp_path / "role_guides"
    guides.mkdir()
    (guides / "DSI.md").write_text("# DSI\nTu gères tous les accès.")
    monkeypatch.setattr(config_mod, "ROLE_GUIDES_DIR", guides)
    monkeypatch.setattr(config_mod, "EMPLOYEES_DIR", tmp_path / "employees")
    monkeypatch.setattr(vessel, "EMPLOYEES_DIR", tmp_path / "employees")
    monkeypatch.setattr(config_mod, "load_employee_profile_yaml", lambda e: company.get(e, {}))
    text = vessel.build_role_identity("00009")
    assert "La Clé, DSI" in text and "Tu gères tous les accès." in text
    assert "Tu gères" not in vessel.build_role_identity("00007")


def test_dsi_keeps_logins_in_the_vault_without_seeing_them(company):
    out = vault_tools.vault_add_login.invoke({"name": "Scaleway — Le Diplomate", "service": "Scaleway",
                                              "username": "lea.martin@photonet.app", "holders": ["00007"],
                                              "employee_id": "00009"})
    assert out["status"] == "added" and out["has_password"]
    listed = vault_tools.vault_list.invoke({"for_employee": "00007"})["items"]
    assert listed[0]["name"] == "Scaleway — Le Diplomate" and "values" not in listed[0]
    item_id = out["item_id"]
    assert vault_tools.vault_grant.invoke({"item_id": item_id, "target_employee_id": "00003", "reason": "relève",
                                          "employee_id": "00009"})["holders"] == ["00007", "00003"]
    vault_tools.vault_revoke.invoke({"item_id": item_id, "target_employee_id": "00003", "employee_id": "00009"})
    asked = vault_tools.vault_ask_ceo.invoke({"item_id": item_id, "what": "Le code de récupération", "field": "note",
                                             "employee_id": "00009"})
    assert asked["status"] == "asked" and vault.asks_for_ceo()[0]["ask"]["asker"] == "00009"
    assert vault.get_item(item_id)["history"][0]["by"] == "DSI"
    assert vault_tools.vault_grant.invoke({"item_id": "nope", "target_employee_id": "00003", "reason": "x",
                                          "employee_id": "00009"})["status"] == "error"
