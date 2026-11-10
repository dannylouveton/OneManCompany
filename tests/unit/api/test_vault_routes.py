"""The CEO's vault tab: list, add, answer the DSI, reveal, holders, delete."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from onemancompany.api import routes
from onemancompany.core import config as config_mod
from onemancompany.core import vault


class _Store:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set_many(self, values):
        self.values.update(values)


@pytest.fixture()
def box(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    store = _Store()
    monkeypatch.setattr("onemancompany.core.secret_store.get_secret_store", lambda: store)
    people = {"00001": {"role": "CEO"}, "00007": {"nickname": "Le Diplomate", "role": "Lead DevOps / SRE"},
              "00009": {"nickname": "La Clé", "role": "DSI"}}
    monkeypatch.setattr("onemancompany.core.store.load_all_employees", lambda: people)
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: people.get(e, {}))
    monkeypatch.setattr("onemancompany.core.i18n.get_company_language", lambda: "fr")
    pushed = []
    monkeypatch.setattr(routes, "_push_adhoc_task", lambda emp, text, **k: pushed.append((emp, text)))
    return pushed


@pytest.mark.asyncio
async def test_ceo_adds_reveals_and_shares(box):
    out = await routes.vault_add({"name": "OVH — admin", "username": "danny@photonet.app", "password": "p4ss-w0rd",
                                  "holders": ["00009"]})
    item_id = out["item"]["id"]
    data = await routes.vault_items()
    assert data["keeper"] == "La Clé (DSI)" and [p["id"] for p in data["employees"]] == ["00007", "00009"]
    assert data["items"][0]["holder_labels"] == ["La Clé (DSI)"] and "p4ss-w0rd" not in str(data)
    assert (await routes.vault_reveal(item_id, {"field": "password"}))["value"] == "p4ss-w0rd"
    shared = await routes.vault_holders(item_id, {"grant": ["00007"], "revoke": ["00009"]})
    assert shared["item"]["holders"] == ["00007"]
    await routes.vault_delete(item_id)
    assert (await routes.vault_items())["items"] == []
    with pytest.raises(HTTPException) as exc:
        await routes.vault_reveal(item_id, {"field": "password"})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_ceo_answers_the_dsi_and_the_dsi_is_told(box):
    item = vault.create_item("OVH — admin", by="DSI")
    vault.ask_ceo(item["id"], "password", "Le mot de passe actuel du compte OVH", by="DSI", asker="00009")
    listing = await routes.access_requests_list()
    assert listing["vault_asks"] == 1
    await routes.vault_set_secret(item["id"], {"field": "password", "value": "typed"})
    assert box and box[0][0] == "00009" and "OVH — admin" in box[0][1]
    assert (await routes.access_requests_list())["vault_asks"] == 0
    with pytest.raises(HTTPException):
        await routes.vault_add({"name": ""})
