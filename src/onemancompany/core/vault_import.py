"""Bring logins from another password manager into the vault.

Reads the export file of 1Password (.1pux or CSV), Dashlane (CSV or the .zip of
CSVs), Bitwarden, Proton Pass, KeePassXC, LastPass, Apple Passwords and the
browsers (Chrome, Edge, Firefox, Safari): their column names differ, so each
known name maps to what the vault keeps (name, address, username, password,
2FA secret, note, folder).

The file is read in memory and never written to disk. The CEO first gets a
list without any value, picks what to bring in (e.g. the Photonet logins),
then the chosen ones go straight to the encrypted vault and the rest of the
file is forgotten. Nothing here is reachable by an employee: only the CEO's
interface calls it.
"""

from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
import uuid
import zipfile

from loguru import logger

MAX_BYTES = 15 * 1024 * 1024
PENDING_SECONDS = 15 * 60
MAX_ITEMS = 5000

_pending: dict[str, dict] = {}
_lock = threading.Lock()

# Column names of the known exports, normalised (lower case, letters and digits only)
_COLUMNS = {
    "name": ("title", "name", "itemname", "nom", "titre", "entry"),
    "url": ("url", "website", "loginuri", "uri", "urls", "loginurl", "site", "siteweb", "address", "adresse",
            "web", "hostname"),
    "username": ("username", "loginusername", "login", "user", "username1", "identifiant", "utilisateur",
                 "nomdutilisateur", "account"),
    "email": ("email", "emailaddress", "mail", "courriel"),
    "password": ("password", "loginpassword", "pass", "motdepasse", "pwd", "passwort"),
    "totp": ("otpauth", "totp", "logintotp", "otp", "otpsecret", "otpurl", "onetimepassword", "2fa",
             "twofactor", "authenticatorkey", "otpauthurl"),
    "note": ("notes", "note", "extra", "comment", "comments", "commentaire", "commentaires"),
    "folder": ("folder", "grouping", "vault", "group", "category", "collection", "tags", "dossier", "coffre",
               "groupe"),
    "type": ("type", "itemtype"),
}
_SKIP_TYPES = {"card", "creditcard", "identity", "identite", "carte", "alias", "bankaccount", "passport"}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header or "").lower())


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _site(url: str) -> str:
    from onemancompany.core.browser import site_of

    return site_of(url)


def _clean(item: dict) -> dict | None:
    out = {k: " ".join(str(item.get(k) or "").split()) if k not in ("password", "note", "totp") else
           str(item.get(k) or "") for k in ("name", "url", "username", "password", "totp", "note", "folder")}
    out["totp"], out["note"] = out["totp"].strip(), out["note"].strip()
    if not (out["password"] or out["totp"] or out["username"]):
        return None
    if out["url"] and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", out["url"]) and "." in out["url"]:
        out["url"] = "https://" + out["url"]
    out["name"] = (out["name"] or _site(out["url"]) or out["username"] or "Sans nom")[:120]
    return out


def parse_csv(data: bytes) -> list[dict]:
    text = _decode(data)
    if not text.strip():
        raise ValueError("The file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    header = [_norm(h) for h in rows[0]]
    where: dict[str, list[int]] = {}
    for field, names in _COLUMNS.items():
        where[field] = [i for i, h in enumerate(header) if h in names]
    if not where["password"] and not where["username"] and not where["email"]:
        raise ValueError("Unrecognized file: no password or username column (export it as CSV from your password "
                         "manager)")

    archived = [i for i, h in enumerate(header) if h in ("archived", "archive", "trashed", "deleted")]

    def cell(row: list[str], field: str) -> str:
        for i in where[field]:
            if i < len(row) and row[i].strip():
                return row[i] if field == "password" else row[i].strip()
        return ""

    items = []
    for row in rows[1:MAX_ITEMS + 1]:
        if not any(c.strip() for c in row):
            continue
        if _norm(cell(row, "type")) in _SKIP_TYPES:
            continue
        if any(i < len(row) and row[i].strip().lower() in ("true", "1", "yes", "oui") for i in archived):
            continue
        folder = " · ".join(dict.fromkeys(row[i].strip() for i in where["folder"] if i < len(row) and row[i].strip()))
        item = _clean({"name": cell(row, "name"), "url": cell(row, "url").split(",")[0].strip(),
                       "username": cell(row, "username") or cell(row, "email"), "password": cell(row, "password"),
                       "totp": cell(row, "totp"), "note": cell(row, "note"), "folder": folder})
        if item:
            items.append(item)
    return items


def parse_1pux(export: dict) -> list[dict]:
    """1Password's own export (export.data inside the .1pux): logins with their vault, tags and 2FA."""
    items = []
    for account in export.get("accounts") or []:
        for vault_data in account.get("vaults") or []:
            vault_name = (vault_data.get("attrs") or {}).get("name", "")
            for it in vault_data.get("items") or []:
                if it.get("state") == "archived" or it.get("trashed"):
                    continue
                overview, details = it.get("overview") or {}, it.get("details") or {}
                username = password = totp = ""
                for f in details.get("loginFields") or []:
                    value = str(f.get("value") or "")
                    if f.get("designation") == "username" and not username:
                        username = value
                    elif f.get("designation") == "password" and not password:
                        password = value
                password = password or str(details.get("password") or "")
                for section in details.get("sections") or []:
                    for f in section.get("fields") or []:
                        value = f.get("value") or {}
                        if isinstance(value, dict) and value.get("totp") and not totp:
                            totp = str(value["totp"])
                        elif (isinstance(value, dict) and not username and "username" in _norm(f.get("title", ""))
                              and value.get("string")):
                            username = str(value["string"])
                urls = overview.get("urls") or []
                url = overview.get("url") or (urls[0].get("url", "") if urls and isinstance(urls[0], dict) else "")
                tags = ", ".join(overview.get("tags") or [])
                item = _clean({"name": overview.get("title", ""), "url": url, "username": username,
                               "password": password, "totp": totp, "note": details.get("notesPlain", ""),
                               "folder": " · ".join(x for x in (vault_name, tags) if x)})
                if item:
                    items.append(item)
    return items[:MAX_ITEMS]


def parse_export(filename: str, data: bytes) -> tuple[list[dict], str]:
    """(logins, format name) from an export file."""
    if len(data) > MAX_BYTES:
        raise ValueError("The file is too big (15 MB at most)")
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if "export.data" in names:
                return parse_1pux(json.loads(zf.read("export.data"))), "1Password (1PUX)"
            csvs = [n for n in names if n.lower().endswith(".csv")]
            preferred = [n for n in csvs if re.search(r"credential|password|login|identifiant", n, re.I)] or csvs
            if not preferred:
                raise ValueError("No CSV file in this archive")
            items = []
            for name in preferred:
                try:
                    items += parse_csv(zf.read(name))
                except ValueError as exc:
                    logger.debug("[vault-import] {} skipped: {}", name, exc)
            return items, "CSV (archive)"
    if str(filename or "").lower().endswith(".1pux"):
        raise ValueError("This .1pux file cannot be read")
    return parse_csv(data), "CSV"


def _duplicate_keys() -> set[tuple[str, str]]:
    from onemancompany.core import vault

    keys = set()
    for item in vault.list_items():
        user = (item.get("username") or "").lower()
        keys.add((_site(item.get("url", "")) or (item.get("name") or "").lower(), user))
    return keys


def _key(item: dict) -> tuple[str, str]:
    return (_site(item["url"]) or item["name"].lower(), item["username"].lower())


def _purge() -> None:
    now = time.monotonic()
    for import_id in [k for k, v in _pending.items() if now - v["at"] > PENDING_SECONDS]:
        _pending.pop(import_id, None)


def start(filename: str, data: bytes) -> dict:
    """Read an export and keep it in memory; return what it contains, without any value."""
    items, kind = parse_export(filename, data)
    if not items:
        raise ValueError("No login found in this file")
    existing = _duplicate_keys()
    import_id = uuid.uuid4().hex
    with _lock:
        _purge()
        _pending[import_id] = {"at": time.monotonic(), "items": items}
    listing = [{"i": i, "name": it["name"], "url": it["url"], "site": _site(it["url"]), "username": it["username"],
                "folder": it["folder"], "has_password": bool(it["password"]), "has_totp": bool(it["totp"]),
                "has_note": bool(it["note"]), "in_vault": _key(it) in existing} for i, it in enumerate(items)]
    folders = sorted({f.strip() for it in items for f in it["folder"].split(" · ") if f.strip()}, key=str.lower)
    return {"import_id": import_id, "format": kind, "items": listing, "folders": folders}


def finish(import_id: str, indices: list[int], holders: list[str] | None = None, by: str = "CEO") -> dict:
    """Put the chosen logins in the vault and forget the file."""
    from onemancompany.core import vault

    with _lock:
        _purge()
        pending = _pending.pop(import_id, None)
    if pending is None:
        raise ValueError("This import has expired: choose the file again")
    items = pending["items"]
    existing = _duplicate_keys()
    imported, already, totp_dropped = 0, 0, 0
    for i in dict.fromkeys(int(x) for x in indices or []):
        if not 0 <= i < len(items):
            continue
        it = items[i]
        if _key(it) in existing:
            already += 1
            continue
        fields = dict(service=_site(it["url"]), url=it["url"], username=it["username"], holders=holders or [], by=by,
                      password=it["password"], note=it["note"])
        try:
            vault.create_item(it["name"], totp=it["totp"], **fields)
        except ValueError:  # a 2FA secret the vault cannot read: keep the login without it
            vault.create_item(it["name"], **fields)
            totp_dropped += 1 if it["totp"] else 0
        existing.add(_key(it))
        imported += 1
    logger.info("[vault-import] {} logins imported by {} ({} already there)", imported, by, already)
    return {"imported": imported, "already_in_vault": already, "totp_dropped": totp_dropped}


def cancel(import_id: str) -> None:
    with _lock:
        _pending.pop(import_id, None)
