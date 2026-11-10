"""The company vault: logins, passwords, 2FA codes and notes that employees use without seeing them.

* Values are encrypted (Fernet) with a key kept in the secret store, and the
  file is denied to employees' sessions (see claude_session).
* No employee tool returns a value. Employees use a login through actions run
  by OneManCompany's own code (fill a browser field, type a 2FA code); only
  the CEO can reveal a value, in their own interface.
* Who may use each item is listed (``holders``: employee ids, or "*" for the
  whole company), and every change and every use is journaled: who, what,
  when, why.

The DSI (or the COO until the company has one) runs it; the CEO sees it in
the "Vault" tab of the access box.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import secrets
import string
import struct
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from loguru import logger

FILE_NAME = "vault.json"
KEY_NAME = "OMC_VAULT_KEY"
EVERYONE = "*"
KINDS = ("login", "note")
FIELDS = ("password", "totp", "note")
MAX_HISTORY = 200

_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Storage and encryption
# ---------------------------------------------------------------------------

def vault_path() -> Path:
    from onemancompany.core.config import COMPANY_DIR

    return COMPANY_DIR / FILE_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fernet():
    from cryptography.fernet import Fernet

    from onemancompany.core.secret_store import get_secret_store

    store = get_secret_store()
    key = store.get(KEY_NAME)
    if not key:
        key = Fernet.generate_key().decode()
        store.set_many({KEY_NAME: key})
    return Fernet(key.encode())


def _enc(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _dec(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def _load() -> list[dict]:
    path = vault_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except ValueError as exc:
        logger.error("[vault] unreadable {}: {}", path, exc)
        return []
    return [i for i in data if isinstance(i, dict) and i.get("id")]


def _save(items: list[dict]) -> None:
    path = vault_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError as exc:  # pragma: no cover - non-POSIX filesystems
        logger.warning("[vault] cannot restrict permissions of {}: {}", path, exc)


def _find(items: list[dict], item_id: str) -> dict:
    item = next((i for i in items if i.get("id") == item_id), None)
    if item is None:
        raise ValueError(f"Unknown vault item {item_id!r}")
    return item


def _history(item: dict, by: str, event: str, detail: str = "") -> None:
    item.setdefault("history", []).append({"at": _now(), "by": str(by or "?"), "event": event,
                                           "detail": str(detail or "")[:300]})
    item["history"] = item["history"][-MAX_HISTORY:]
    item["updated_at"] = _now()


# ---------------------------------------------------------------------------
# Values: passwords, 2FA codes
# ---------------------------------------------------------------------------

_SYMBOLS = "!#$%&*+-=?@_"


def new_password(length: int = 24, symbols: bool = True) -> str:
    """A random password with lower case, upper case, digits (and symbols)."""
    length = max(12, min(int(length or 24), 128))
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits] + ([_SYMBOLS] if symbols else [])
    chars = [secrets.choice(p) for p in pools]
    alphabet = "".join(pools)
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def totp_secret(value: str) -> str:
    """Base32 secret from a raw secret or an otpauth:// address (from a QR code)."""
    value = str(value or "").strip()
    if value.lower().startswith("otpauth://"):
        value = (parse_qs(urlparse(value).query).get("secret") or [""])[0]
    value = value.replace(" ", "").replace("-", "").upper()
    if not value:
        raise ValueError("Empty 2FA secret")
    try:
        base64.b32decode(value + "=" * (-len(value) % 8))
    except Exception as exc:
        raise ValueError("The 2FA secret is not valid base32") from exc
    return value


def totp_now(secret: str, at: float | None = None, digits: int = 6, period: int = 30) -> str:
    """RFC 6238 time-based code (SHA-1, 30 s, 6 digits: what authenticator apps use)."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((time.time() if at is None else at) // period)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


# ---------------------------------------------------------------------------
# Holders
# ---------------------------------------------------------------------------

def _clean_holders(holders) -> list[str]:
    if isinstance(holders, str):
        holders = [h.strip() for h in holders.split(",")]
    out = []
    for h in holders or []:
        h = str(h).strip()
        if h and h not in out:
            out.append(h)
    return [EVERYONE] if EVERYONE in out else out


def can_use(item: dict, employee_id: str) -> bool:
    holders = item.get("holders") or []
    return EVERYONE in holders or str(employee_id) in holders


def _label(employee_id: str) -> str:
    if employee_id == EVERYONE:
        return "*"
    try:
        from onemancompany.core.access_desk import label

        return label(employee_id)
    except Exception:  # pragma: no cover - label is best effort
        return str(employee_id)


def _public(item: dict, history: int = 20) -> dict:
    """What anyone may see: never a value."""
    values = item.get("values") or {}
    out = {k: copy.deepcopy(v) for k, v in item.items() if k not in ("values", "history")}
    out.update({f"has_{f}": bool(values.get(f)) for f in FIELDS})
    out["holder_labels"] = [_label(h) for h in item.get("holders") or []]
    out["history"] = copy.deepcopy((item.get("history") or [])[-history:]) if history else []
    return out


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def create_item(name: str, *, service: str = "", url: str = "", username: str = "", kind: str = "login",
                holders=None, by: str = "", password: str = "", totp: str = "", note: str = "",
                generate_password: bool = False, length: int = 24, symbols: bool = True) -> dict:
    """Add a login (or a note). Values given here are encrypted at once; never returned."""
    name = " ".join(str(name or "").split())[:120]
    if not name:
        raise ValueError("Give the item a name, e.g. \"Scalingo — Le Diplomate\"")
    kind = kind if kind in KINDS else "login"
    values: dict[str, str] = {}
    if generate_password:
        password = new_password(length, symbols)
    if password:
        values["password"] = _enc(str(password))
    if totp:
        values["totp"] = _enc(totp_secret(totp))
    if note:
        values["note"] = _enc(str(note))
    item = {"id": uuid.uuid4().hex[:10], "name": name, "kind": kind, "service": str(service or "")[:80],
            "url": str(url or "")[:300], "username": str(username or "")[:200], "holders": _clean_holders(holders),
            "created_by": str(by or "?"), "created_at": _now(), "updated_at": _now(), "last_used": "",
            "ask": {}, "values": values, "history": []}
    _history(item, by, "created", ("password generated" if generate_password else "") +
             (f"; holders: {', '.join(item['holders'])}" if item["holders"] else ""))
    with _lock:
        items = _load()
        items.append(item)
        _save(items)
    return _public(item)


def update_item(item_id: str, *, by: str, **fields) -> dict:
    with _lock:
        items = _load()
        item = _find(items, item_id)
        changed = []
        for key in ("name", "service", "url", "username"):
            if key in fields and fields[key] is not None and str(fields[key]) != item.get(key, ""):
                item[key] = str(fields[key])[:300]
                changed.append(key)
        if changed:
            _history(item, by, "edited", ", ".join(changed))
            _save(items)
        return _public(item)


def set_secret(item_id: str, field: str, value: str, *, by: str) -> dict:
    """Store a value (the CEO typing a password, a 2FA secret captured by the browser…)."""
    if field not in FIELDS:
        raise ValueError(f"field must be one of {', '.join(FIELDS)}")
    if not str(value or "").strip():
        raise ValueError("Empty value")
    stored = totp_secret(value) if field == "totp" else str(value)
    with _lock:
        items = _load()
        item = _find(items, item_id)
        replaced = bool((item.get("values") or {}).get(field))
        item.setdefault("values", {})[field] = _enc(stored)
        if (item.get("ask") or {}).get("field") == field:
            item["ask"] = {}
        _history(item, by, "replaced" if replaced else "stored", field)
        _save(items)
        return _public(item)


def generate_password(item_id: str, *, by: str, length: int = 24, symbols: bool = True) -> dict:
    """Put a new random password in the item (it replaces the old one). Never returned."""
    return set_secret(item_id, "password", new_password(length, symbols), by=by)


def grant(item_id: str, employee_id: str, *, by: str, reason: str = "") -> dict:
    emp = str(employee_id or "").strip()
    if not emp:
        raise ValueError("Say who may use it (an employee id, or \"*\" for everyone)")
    with _lock:
        items = _load()
        item = _find(items, item_id)
        holders = _clean_holders([*(item.get("holders") or []), emp])
        if holders != item.get("holders"):
            item["holders"] = holders
            _history(item, by, "granted", f"{emp}: {reason}".strip(": "))
            _save(items)
        return _public(item)


def revoke(item_id: str, employee_id: str, *, by: str, reason: str = "") -> dict:
    emp = str(employee_id or "").strip()
    with _lock:
        items = _load()
        item = _find(items, item_id)
        if emp in (item.get("holders") or []):
            item["holders"] = [h for h in item["holders"] if h != emp]
            _history(item, by, "revoked", f"{emp}: {reason}".strip(": "))
            _save(items)
        return _public(item)


def delete_item(item_id: str, *, by: str) -> None:
    with _lock:
        items = _load()
        item = _find(items, item_id)
        items = [i for i in items if i is not item]
        _save(items)
    logger.info("[vault] {} deleted {} ({})", by, item_id, item.get("name"))


def ask_ceo(item_id: str, field: str, what: str, *, by: str, asker: str = "") -> dict:
    """Ask the CEO to type a value only they have (shown in their access box)."""
    if field not in FIELDS:
        raise ValueError(f"field must be one of {', '.join(FIELDS)}")
    what = str(what or "").strip()
    if not what:
        raise ValueError("Say what the CEO should type, e.g. \"Le mot de passe actuel du compte OVH\"")
    with _lock:
        items = _load()
        item = _find(items, item_id)
        item["ask"] = {"field": field, "what": what[:500], "by": str(by or "?"), "asker": str(asker or ""),
                       "at": _now()}
        _history(item, by, "asked the CEO", f"{field}: {what}")
        _save(items)
        return _public(item)


def get_item(item_id: str) -> dict | None:
    with _lock:
        item = next((i for i in _load() if i.get("id") == item_id), None)
    return _public(item) if item else None


def list_items(employee_id: str | None = None, history: int = 0) -> list[dict]:
    """All items (no values), or only those an employee may use."""
    with _lock:
        items = _load()
    if employee_id:
        items = [i for i in items if can_use(i, employee_id)]
    return [_public(i, history=history) for i in sorted(items, key=lambda i: i.get("name", "").lower())]


def asks_for_ceo() -> list[dict]:
    return [i for i in list_items() if i.get("ask")]


def secret_values() -> list[str]:
    """Every value in the vault, decrypted: only for masking pages before a model sees them."""
    with _lock:
        items = _load()
    values = []
    for item in items:
        for field, token in (item.get("values") or {}).items():
            if token:
                values.append(_dec(token))
                if field == "totp":  # the code of the moment too
                    values.append(totp_now(values[-1]))
    return values


# ---------------------------------------------------------------------------
# Using a value: OneManCompany's own code only (never an employee tool)
# ---------------------------------------------------------------------------

def use(item_id: str, field: str, *, employee_id: str, purpose: str = "", keeper: bool = False) -> str:
    """The value, for OneManCompany's code acting for an employee (e.g. filling a browser field).

    ``keeper``: the DSI, who keeps the vault, may use any item (to create and
    look after accounts); the browser still types it only on the item's site.
    """
    if field not in FIELDS:
        raise ValueError(f"field must be one of {', '.join(FIELDS)}")
    with _lock:
        items = _load()
        item = _find(items, item_id)
        if not keeper and not can_use(item, employee_id):
            raise PermissionError(f"{employee_id} may not use {item.get('name')!r}: ask the DSI (request_access)")
        token = (item.get("values") or {}).get(field)
        if not token:
            raise ValueError(f"{item.get('name')!r} has no {field}")
        item["last_used"] = _now()
        _history(item, employee_id, "used", f"{field}: {purpose}".strip(": "))
        _save(items)
    return _dec(token)


def totp_code(item_id: str, *, employee_id: str, purpose: str = "", at: float | None = None,
              keeper: bool = False) -> str:
    return totp_now(use(item_id, "totp", employee_id=employee_id, purpose=purpose, keeper=keeper), at=at)


def reveal(item_id: str, field: str, *, by: str = "CEO") -> str:
    """For the CEO's own interface only. Journaled."""
    if field not in FIELDS:
        raise ValueError(f"field must be one of {', '.join(FIELDS)}")
    with _lock:
        items = _load()
        item = _find(items, item_id)
        token = (item.get("values") or {}).get(field)
        if not token:
            raise ValueError(f"{item.get('name')!r} has no {field}")
        _history(item, by, "revealed", field)
        _save(items)
    value = _dec(token)
    return totp_now(value) if field == "totp" else value
