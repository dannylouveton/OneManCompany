"""The DSI's browser tools: vault values typed on their site only, values captured without being read."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from onemancompany.agents import browser_tools
from onemancompany.core import browser, vault
from onemancompany.core import config as config_mod


class _Store:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set_many(self, values):
        self.values.update(values)


class FakeBrowser:
    def __init__(self):
        self.url = "https://console.scaleway.com/login"
        self.raw = ""
        self.filled = []

    async def fill_secret(self, emp, ref, value, *, site, submit=False):
        if browser.site_of(self.url) != site:
            raise browser.BrowserError(f"This login is for {site}")
        self.filled.append((emp, ref, value, submit))
        return 'URL: https://console.scaleway.com/login\n[e2] password "Mot de passe" = [hidden]'

    async def read_raw(self, emp, ref):
        return self.raw, browser.site_of(self.url)

    async def current_url(self, emp):
        return self.url


@pytest.fixture()
def office(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "TOOLS_DIR", tmp_path / "tools")
    (tmp_path / "tools").mkdir()
    store = _Store()
    monkeypatch.setattr("onemancompany.core.secret_store.get_secret_store", lambda: store)
    people = {"00007": {"nickname": "Le Diplomate", "role": "Lead DevOps / SRE"},
              "00009": {"nickname": "Le Gardien", "role": "DSI", "level": 4}}
    monkeypatch.setattr("onemancompany.core.store.load_all_employees", lambda: people)
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: people.get(e, {}))
    monkeypatch.setattr(config_mod, "DSI_ID", "00009")
    fake = FakeBrowser()
    monkeypatch.setattr(browser_tools, "_svc", lambda: fake)
    monkeypatch.setattr(browser, "_vault_values", lambda: [])
    return fake


@pytest.mark.asyncio
async def test_the_keeper_types_a_login_on_its_site_only(office):
    item = vault.create_item("Scaleway — admin", url="https://console.scaleway.com/login", username="danny@photonet.app",
                             by="CEO", generate_password=True, holders=["00009"])  # the CEO lets the DSI use it
    out = await browser_tools.browser_fill_secret.ainvoke({"ref": "e2", "item_id": item["id"], "employee_id": "00009"})
    assert out["status"] == "filled" and "[hidden]" in out["page"]
    typed = office.filled[-1][2]
    assert typed == vault.reveal(item["id"], "password") and typed not in str(out)
    assert ("00009", "used") in [(h["by"], h["event"]) for h in vault.get_item(item["id"])["history"]]

    office.url = "https://evil.example.com/login"
    out = await browser_tools.browser_fill_secret.ainvoke({"ref": "e2", "item_id": item["id"], "employee_id": "00009"})
    assert out["status"] == "error" and len(office.filled) == 1

    office.url = "https://console.scaleway.com/login"  # not the keeper and not a holder
    out = await browser_tools.browser_fill_secret.ainvoke({"ref": "e2", "item_id": item["id"], "employee_id": "00007"})
    assert out["status"] == "error" and len(office.filled) == 1

    bare = vault.create_item("Sans adresse", by="CEO", password="x" * 12, holders=["00009"])
    out = await browser_tools.browser_fill_secret.ainvoke({"ref": "e2", "item_id": bare["id"], "employee_id": "00009"})
    assert out["status"] == "error" and "sign-in address" in out["message"]


@pytest.mark.asyncio
async def test_the_ceo_decides_which_of_their_logins_the_dsi_types(office):
    from onemancompany.agents import vault_tools

    ceo = vault.create_item("Qonto", url="https://app.qonto.com", by="CEO", password="q0nt0-p4ss")
    own = vault.create_item("Scaleway — Le Diplomate", url="https://console.scaleway.com", by="DSI", password="s" * 20)
    office.url = "https://app.qonto.com/signin"
    out = await browser_tools.browser_fill_secret.ainvoke({"ref": "e2", "item_id": ceo["id"], "employee_id": "00009"})
    assert out["status"] == "error" and not office.filled
    refused = vault_tools.vault_grant.invoke({"item_id": ceo["id"], "target_employee_id": "00009", "reason": "x",
                                             "employee_id": "00009"})
    assert refused["status"] == "error" and "Only the CEO" in refused["message"]
    office.url = "https://console.scaleway.com/login"  # what the DSI created, it may type
    out = await browser_tools.browser_fill_secret.ainvoke({"ref": "e2", "item_id": own["id"], "employee_id": "00009"})
    assert out["status"] == "filled" and office.filled[-1][2] == "s" * 20


@pytest.mark.asyncio
async def test_2fa_set_up_and_typed_by_the_dsi(office):
    item = vault.create_item("Scaleway — admin", url="https://console.scaleway.com", by="DSI")
    office.raw = "Clé de configuration : JBSW Y3DP EHPK 3PXP"
    out = await browser_tools.browser_save_secret.ainvoke({"ref": "t9", "item_id": item["id"], "field": "totp",
                                                           "employee_id": "00009"})
    assert out["status"] == "saved" and "JBSW" not in str(out)
    out = await browser_tools.browser_fill_secret.ainvoke({"ref": "e3", "item_id": item["id"], "field": "totp",
                                                           "employee_id": "00009"})
    assert out["status"] == "filled" and office.filled[-1][2] == vault.totp_now("JBSWY3DPEHPK3PXP")


@pytest.mark.asyncio
async def test_a_key_shown_on_a_page_becomes_the_company_tool(office, monkeypatch):
    office.raw = "Votre nouvelle clé : SCWABCDEF1234567890XY (elle ne sera plus affichée)"
    calls = {}

    def provide(request_id, key, *, setup, what, by):
        calls.update(request_id=request_id, key=key, setup=setup, what=what, by=by)
        return {"service": "Scaleway", "requesters": [{"employee": "00007", "status": "granted"}]}, "scaleway_api"

    from onemancompany.core import access_desk

    monkeypatch.setattr(access_desk, "provide_by_desk", provide)
    monkeypatch.setattr(access_desk, "reconcile", AsyncMock(return_value=0))
    monkeypatch.setattr(access_desk, "outcome_text", lambda req, q: "Accès accordé")
    monkeypatch.setattr("onemancompany.agents.coo_agent._load_assets_from_disk", lambda: None)
    out = await browser_tools.browser_save_key.ainvoke({
        "ref": "t4", "request_id": "r1", "base_url": "https://api.scaleway.com", "auth": "header:X-Auth-Token:{key}",
        "what": "Clé Scaleway, lecture seule", "employee_id": "00009"})
    assert out["status"] == "provided" and out["for_the_employees"] == {"00007": "Accès accordé"}
    assert calls["key"] == "SCWABCDEF1234567890XY" and calls["by"] == "DSI"
    assert calls["setup"]["auth_name"] == "X-Auth-Token" and calls["setup"]["base_url"] == "https://api.scaleway.com"
    assert "SCWABCDEF" not in str(out)


@pytest.mark.asyncio
async def test_the_dsi_asks_the_ceo_for_a_step(office, monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr("onemancompany.core.events.event_bus.publish", publish)
    out = await browser_tools.browser_ask_ceo.ainvoke({"what": "Résoudre le captcha OVH", "employee_id": "00009"})
    assert out["status"] == "asked"
    ask = browser.open_asks()[0]
    assert ask["employee_id"] == "00009" and ask["url"] == office.url
    assert publish.await_args.args[0].payload["browser_ask"] == ask["id"]


def test_only_the_dsi_has_a_browser(office, monkeypatch):
    from onemancompany.agents import coo_agent  # noqa: F401  (registers the tools)
    from onemancompany.core.tool_registry import tool_registry

    monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
    names = {t.name for t in tool_registry.get_tools_for("00009")}
    assert {"browser_open", "browser_fill_secret", "browser_save_key", "browser_ask_ceo"} <= names
    assert not {t.name for t in tool_registry.get_tools_for("00007")} & {"browser_open", "browser_fill_secret"}
