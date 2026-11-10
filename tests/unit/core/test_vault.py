"""The company vault: values encrypted, never listed, used only by OneManCompany's code."""
from __future__ import annotations

import json

import pytest

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
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "COMPANY_DIR", tmp_path)
    s = _Store()
    monkeypatch.setattr("onemancompany.core.secret_store.get_secret_store", lambda: s)
    monkeypatch.setattr("onemancompany.core.store.load_employee",
                        lambda e: {"00007": {"nickname": "Le Diplomate", "role": "Lead DevOps / SRE"}}.get(e, {}))
    return s


def test_values_are_encrypted_and_never_listed(store, tmp_path):
    item = vault.create_item("OVH — admin", service="OVH", url="https://www.ovh.com/manager", username="ceo@photonet.app",
                             password="Sup3r-secret!", holders=["00007"], by="CEO")
    raw = (tmp_path / vault.FILE_NAME).read_text()
    assert "Sup3r-secret!" not in raw and vault.KEY_NAME in store.values
    assert item["has_password"] and not item["has_totp"] and "values" not in item
    listed = vault.list_items()
    assert "Sup3r-secret!" not in json.dumps(listed) and listed[0]["holder_labels"] == ["Le Diplomate (Lead DevOps / SRE)"]
    assert vault.list_items("00042") == [] and vault.list_items("00007")[0]["id"] == item["id"]


def test_use_checks_holders_and_journals(store):
    item = vault.create_item("Scaleway", username="lea.martin@photonet.app", generate_password=True, by="DSI")
    with pytest.raises(PermissionError):
        vault.use(item["id"], "password", employee_id="00007", purpose="login")
    vault.grant(item["id"], "00007", by="DSI", reason="inventaire")
    value = vault.use(item["id"], "password", employee_id="00007", purpose="login")
    assert len(value) == 24 and any(c.isdigit() for c in value) and any(c.isupper() for c in value)
    events = [h["event"] for h in vault.get_item(item["id"])["history"]]
    assert events == ["created", "granted", "used"]
    vault.revoke(item["id"], "00007", by="DSI")
    with pytest.raises(PermissionError):
        vault.use(item["id"], "password", employee_id="00007")
    everyone = vault.create_item("Wi-Fi", kind="note", note="code", holders="*", by="DSI")
    assert vault.use(everyone["id"], "note", employee_id="00042") == "code"


def test_totp_from_a_qr_code_and_rfc_vectors(store):
    # RFC 6238 test vector (SHA-1): secret "12345678901234567890", T=59 → 94287082 (8 digits)
    secret = vault.totp_secret("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    assert vault.totp_now(secret, at=59, digits=8) == "94287082"
    item = vault.create_item("GitHub", by="DSI", holders=["00007"],
                             totp="otpauth://totp/GitHub:lea?secret=GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ&issuer=GitHub")
    assert vault.totp_code(item["id"], employee_id="00007", at=59) == "287082"
    with pytest.raises(ValueError):
        vault.totp_secret("not base32 !!")


def test_ceo_asks_reveals_and_replaces(store):
    item = vault.create_item("OVH — admin", by="DSI")
    vault.ask_ceo(item["id"], "password", "Le mot de passe actuel du compte OVH", by="DSI")
    assert vault.asks_for_ceo()[0]["ask"]["what"].startswith("Le mot de passe")
    vault.set_secret(item["id"], "password", "typed-by-ceo", by="CEO")
    assert vault.asks_for_ceo() == []
    assert vault.reveal(item["id"], "password") == "typed-by-ceo"
    assert [h["event"] for h in vault.get_item(item["id"])["history"]][-2:] == ["stored", "revealed"]
    vault.generate_password(item["id"], by="DSI")
    assert vault.reveal(item["id"], "password") != "typed-by-ceo"
    vault.delete_item(item["id"], by="CEO")
    assert vault.list_items() == []


def test_validation(store):
    with pytest.raises(ValueError):
        vault.create_item("", by="DSI")
    item = vault.create_item("x", by="DSI", holders="*")
    with pytest.raises(ValueError):
        vault.set_secret(item["id"], "pin", "1", by="DSI")
    with pytest.raises(ValueError):  # no password stored yet
        vault.use(item["id"], "password", employee_id="00007")
    with pytest.raises(ValueError):
        vault.grant("nope", "00007", by="DSI")
    assert vault.new_password(4).__len__() == 12 and not set(vault.new_password(30, symbols=False)) & set("!#$%&*+-=?@_")
