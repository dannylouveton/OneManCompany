"""Logins from another password manager: read in memory, listed without values, the chosen ones in the vault."""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from starlette.datastructures import UploadFile

from onemancompany.core import config as config_mod
from onemancompany.core import vault, vault_import


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
    people = {"00009": {"nickname": "Le Gardien", "role": "DSI"}}
    monkeypatch.setattr("onemancompany.core.store.load_all_employees", lambda: people)
    monkeypatch.setattr("onemancompany.core.store.load_employee", lambda e: people.get(e, {}))
    vault_import._pending.clear()
    return tmp_path


ONEPASSWORD_CSV = (
    "Title,Url,Username,Password,OTPAuth,Favorite,Archived,Tags,Notes\n"
    "Scaleway,https://console.scaleway.com,danny@photonet.app,S3cr3t!pass,"
    "otpauth://totp/Scaleway?secret=JBSWY3DPEHPK3PXP,false,false,Photonet,\n"
    "Ancien,https://old.example.com,x,y,,false,true,,\n"
)
DASHLANE_CSV = ("username,username2,username3,title,password,note,url,category,otpSecret\n"
                "danny@photonet.app,,,OVH,Ovh-p4ss,,https://www.ovh.com/manager,Photonet,\n")
BITWARDEN_CSV = ("folder,favorite,type,name,notes,fields,reprompt,login_uri,login_username,login_password,login_totp\n"
                 "Photonet,,login,Stripe,,,0,https://dashboard.stripe.com,danny@photonet.app,str1pe,\n"
                 ",,card,Visa,,,0,,,,\n"
                 ",,note,Une note,texte,,0,,,,\n")


def test_the_usual_exports_are_read():
    items = vault_import.parse_csv(ONEPASSWORD_CSV.encode())
    assert [i["name"] for i in items] == ["Scaleway"]  # the archived one is left out
    assert items[0]["totp"].startswith("otpauth://") and items[0]["folder"] == "Photonet"
    dashlane = vault_import.parse_csv(DASHLANE_CSV.encode("utf-8-sig"))
    assert (dashlane[0]["name"], dashlane[0]["username"], dashlane[0]["folder"]) == ("OVH", "danny@photonet.app", "Photonet")
    assert [i["name"] for i in vault_import.parse_csv(BITWARDEN_CSV.encode())] == ["Stripe"]  # no card, no note
    chrome_fr = vault_import.parse_csv("name;url;username;password;note\nqonto.com;app.qonto.com;danny; q0nt0;\n"
                                       .encode("cp1252"))
    assert chrome_fr[0]["password"] == " q0nt0" and chrome_fr[0]["url"] == "https://app.qonto.com"
    firefox = vault_import.parse_csv(b"url,username,password,httpRealm\nhttps://github.com,danny,gh-pass,\n")
    assert firefox[0]["name"] == "github.com"
    apple = vault_import.parse_csv("Title,URL,Username,Password,Notes,OTPAuth\nn8n,https://n8n.photonet.app,admin,"
                                   "n8n-p4ss,,\n".encode("utf-16"))
    assert apple[0]["name"] == "n8n"
    with pytest.raises(ValueError):
        vault_import.parse_csv(b"a,b\n1,2\n")


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def test_a_1password_export_and_a_dashlane_archive():
    export = {"accounts": [{"vaults": [{"attrs": {"name": "Photonet"}, "items": [
        {"state": "active", "overview": {"title": "Scalingo", "url": "https://dashboard.scalingo.com", "tags": ["infra"]},
         "details": {"loginFields": [{"designation": "username", "value": "danny@photonet.app"},
                                     {"designation": "password", "value": "sc4l1ng0"}],
                     "sections": [{"fields": [{"title": "one-time password", "value": {"totp": "JBSWY3DPEHPK3PXP"}}]}],
                     "notesPlain": "compte principal"}},
        {"state": "archived", "overview": {"title": "Ancien"},
         "details": {"loginFields": [{"designation": "password", "value": "x"}]}},
    ]}]}]}
    items, kind = vault_import.parse_export("Photonet.1pux", _zip({"export.attributes": "{}",
                                                                   "export.data": json.dumps(export)}))
    assert kind.startswith("1Password") and [i["name"] for i in items] == ["Scalingo"]
    assert items[0]["folder"] == "Photonet · infra" and items[0]["totp"] == "JBSWY3DPEHPK3PXP"
    items, _ = vault_import.parse_export("dashlane.zip", _zip({"credentials.csv": DASHLANE_CSV,
                                                               "securenotes.csv": "title,note\nA,b\n"}))
    assert [i["name"] for i in items] == ["OVH"]
    with pytest.raises(ValueError):
        vault_import.parse_export("x.1pux", b"not a zip")


def test_the_ceo_picks_what_goes_in_the_vault(box):
    vault.create_item("OVH", url="https://www.ovh.com/manager", username="danny@photonet.app", by="CEO", password="old")
    data = (ONEPASSWORD_CSV + "OVH,https://www.ovh.com/auth,danny@photonet.app,new,,false,false,Photonet,\n"
            "n8n,https://n8n.example.com,admin,n8n-pass,pas-du-base32!!,false,false,Perso,\n").encode()
    preview = vault_import.start("1password.csv", data)
    shown = json.dumps(preview)
    assert "S3cr3t!pass" not in shown and "JBSWY3" not in shown and "n8n-pass" not in shown
    found = {i["name"]: i for i in preview["items"]}
    assert found["Scaleway"]["has_totp"] and found["OVH"]["in_vault"] and preview["folders"] == ["Perso", "Photonet"]
    out = vault_import.finish(preview["import_id"], [i["i"] for i in preview["items"]], holders=["00009"])
    assert out == {"imported": 2, "already_in_vault": 1, "totp_dropped": 1}
    scaleway = next(i for i in vault.list_items() if i["name"] == "Scaleway")
    assert scaleway["holders"] == ["00009"] and scaleway["has_totp"] and scaleway["service"] == "scaleway.com"
    assert vault.reveal(scaleway["id"], "password") == "S3cr3t!pass"
    n8n = next(i for i in vault.list_items() if i["name"] == "n8n")
    assert n8n["has_password"] and not n8n["has_totp"]
    with pytest.raises(ValueError, match="expired"):
        vault_import.finish(preview["import_id"], [0])  # the file is forgotten


@pytest.mark.asyncio
async def test_the_import_routes(box):
    from fastapi import HTTPException

    from onemancompany.api import routes

    preview = await routes.vault_import_start(file=UploadFile(file=io.BytesIO(DASHLANE_CSV.encode()), filename="d.csv"))
    assert preview["items"][0]["name"] == "OVH" and "Ovh-p4ss" not in json.dumps(preview)
    out = await routes.vault_import_finish(preview["import_id"], {"indices": [0]})
    assert out["imported"] == 1 and vault.list_items()[0]["holders"] == []
    with pytest.raises(HTTPException) as exc:
        await routes.vault_import_start(file=UploadFile(file=io.BytesIO(b"a,b\n1,2\n"), filename="x.csv"))
    assert exc.value.status_code == 400
    again = await routes.vault_import_start(file=UploadFile(file=io.BytesIO(DASHLANE_CSV.encode()), filename="d.csv"))
    await routes.vault_import_cancel(again["import_id"])
    assert again["import_id"] not in vault_import._pending
