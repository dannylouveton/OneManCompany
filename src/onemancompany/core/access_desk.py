"""Access desk: employees ask, the COO decides, the CEO only creates keys and accounts.

1. An employee calls ``request_access`` (service, why, read or write, what is
   blocked). One request per service stays open while several employees can
   wait on it; a task goes to the COO.
2. The COO handles every request:
   * the company already has the access (API key, CLI, connector): the COO
     grants it with the minimum rights (``grant``);
   * it does not: the COO prepares a card for the CEO (``escalate``): what to
     create, where, the minimum rights, why — plus the technical setup so the
     CEO only pastes the key. The COO's task waits;
   * not justified: refused with a reason.
3. In the "Access requests" box the CEO pastes the key, marks the action done,
   or refuses (``provide`` / ``done_without_key`` / ``refuse_by_ceo``). The key
   becomes a company tool, the employees validated by the COO get access, the
   waiting tasks resume and the employees continue their work.

Everything is traced: who asked, why and for which task; who granted, when.
Each use then goes through the relay journal. Stored in
``company/access_requests.yaml``.
"""

from __future__ import annotations

import asyncio
import copy
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from loguru import logger

FILE_NAME = "access_requests.yaml"
ACTIVE = ("open", "waiting_ceo")
KINDS = ("api", "cli", "account", "other")
MAX_FINISHED = 300
_lock = threading.RLock()
_STOP_WORDS = {"api", "cli", "key", "keys", "token", "tokens", "access", "acces", "accès", "account", "compte",
               "the", "le", "la", "les", "de", "du", "des", "pour", "for", "to", "read", "only", "lecture",
               "seule", "write", "ecriture", "écriture", "en", "un", "une", "a", "an"}

# Ready-made setups the COO can name when asking the CEO for a key: how the
# relay will use it, where the CEO creates it.
SERVICE_PRESETS: dict[str, dict] = {
    "scalingo": {
        "name": "Scalingo", "base_url": "https://api.osc-fr1.scalingo.com",
        "auth_in": "header", "auth_name": "Authorization", "auth_format": "Bearer {key}",
        "exchange": {"url": "https://auth.scalingo.com/v1/tokens/exchange", "token_field": "token"},
        "docs_url": "https://developers.scalingo.com", "cli": {"preset": "scalingo"},
        "where_url": "https://dashboard.scalingo.com/account/tokens",
    },
    "github": {
        "name": "GitHub", "base_url": "https://api.github.com",
        "auth_in": "header", "auth_name": "Authorization", "auth_format": "Bearer {key}",
        "headers": {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        "docs_url": "https://docs.github.com/rest", "cli": {"preset": "gh"},
        "where_url": "https://github.com/settings/personal-access-tokens/new",
    },
    "n8n": {
        "name": "n8n", "base_url": "",  # the instance's address + /api/v1
        "auth_in": "header", "auth_name": "X-N8N-API-KEY", "auth_format": "{key}",
        "docs_url": "https://docs.n8n.io/api/",
    },
    "telegram": {
        "name": "Telegram bot", "base_url": "https://api.telegram.org",
        "auth_in": "path", "auth_name": "", "auth_format": "/bot{key}",
        "docs_url": "https://core.telegram.org/bots/api", "where_url": "https://t.me/BotFather",
    },
    "intercom": {
        "name": "Intercom", "base_url": "https://api.intercom.io",
        "auth_in": "header", "auth_name": "Authorization", "auth_format": "Bearer {key}",
        "headers": {"Intercom-Version": "2.11"},
        "docs_url": "https://developers.intercom.com/docs/references/rest-api",
    },
}
_SETUP_FIELDS = ("name", "base_url", "auth_in", "auth_name", "auth_format", "exchange", "headers", "docs_url", "cli")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _path() -> Path:
    from onemancompany.core.config import COMPANY_DIR

    return COMPANY_DIR / FILE_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as exc:
        logger.error("[access-desk] unreadable {}: {}", path, exc)
        return []
    return [r for r in data if isinstance(r, dict) and r.get("id")]


def _save(items: list[dict]) -> None:
    active = [r for r in items if r.get("status") in ACTIVE]
    finished = [r for r in items if r.get("status") not in ACTIVE][-MAX_FINISHED:]
    keep = {id(r) for r in active + finished}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump([r for r in items if id(r) in keep], allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _find(items: list[dict], request_id: str) -> dict:
    req = next((r for r in items if r.get("id") == request_id), None)
    if req is None:
        raise ValueError(f"Unknown access request: {request_id}")
    return req


def _requester(req: dict, employee_id: str) -> dict:
    entry = next((q for q in req.get("requesters") or [] if q.get("employee") == str(employee_id)), None)
    if entry is None:
        raise ValueError(f"{employee_id} has not asked for this access (request {req['id']})")
    return entry


def _history(req: dict, by: str, event: str, detail: str = "") -> None:
    req.setdefault("history", []).append({"at": _now(), "by": by, "event": event, "detail": detail[:500]})
    req["updated_at"] = _now()


def _refresh_status(req: dict) -> None:
    """A request is finished once every requester has been answered."""
    requesters = req.get("requesters") or []
    if req.get("status") in ACTIVE and requesters and all(q.get("status") in ("granted", "refused") for q in requesters):
        req["status"] = "done" if any(q.get("status") == "granted" for q in requesters) else "refused"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def service_key(service: str) -> str:
    words = [w for w in re.split(r"[^0-9a-zà-ÿ]+", (service or "").lower()) if w and w not in _STOP_WORDS]
    return "-".join(words) or re.sub(r"\W+", "-", (service or "").lower()).strip("-") or "service"


def label(employee_id: str) -> str:
    from onemancompany.core.store import load_employee

    emp = load_employee(str(employee_id)) or {}
    name = emp.get("nickname") or emp.get("name") or str(employee_id)
    role = emp.get("role") or ""
    return f"{name} ({role})" if role else str(name)


def _public(req: dict) -> dict:
    out = copy.deepcopy(req)
    for q in out.get("requesters") or []:
        q["label"] = label(q.get("employee", ""))
    return out


def get_request(request_id: str) -> dict | None:
    with _lock:
        req = next((r for r in _load() if r.get("id") == request_id), None)
    return _public(req) if req else None


def list_requests(status: str = "active") -> list[dict]:
    """status: active (open + waiting_ceo), open, waiting_ceo, done, refused or all."""
    with _lock:
        items = _load()
    if status == "active":
        items = [r for r in items if r.get("status") in ACTIVE]
    elif status != "all":
        items = [r for r in items if r.get("status") == status]
    return [_public(r) for r in sorted(items, key=lambda r: r.get("updated_at", ""), reverse=True)]


def waiting_for_ceo() -> list[dict]:
    return list_requests("waiting_ceo")


def requests_for_tool(tool_id: str, limit: int = 20) -> list[dict]:
    with _lock:
        items = _load()
    found = [r for r in items
             if (r.get("resolution") or {}).get("tool_id") == tool_id
             or (r.get("card") or {}).get("tool_id") == tool_id
             or any(q.get("tool_id") == tool_id for q in r.get("requesters") or [])]
    return [_public(r) for r in sorted(found, key=lambda r: r.get("updated_at", ""), reverse=True)[:limit]]


def matching_tools(service: str) -> list[dict]:
    """Company tools that may already cover a service (API keys, CLIs, connectors)."""
    from onemancompany.core import api_tools, mcp_tools

    words = [w for w in service_key(service).split("-") if len(w) >= 3]
    if not words:
        return []
    found = []
    for tool_id, data in api_tools.list_api_tools().items():
        hay = f"{tool_id} {data.get('name', '')}".lower()
        if any(w in hay for w in words):
            found.append({"tool_id": tool_id, "name": data.get("name", tool_id), "type": "api_key",
                          "api": bool((data.get("api") or {}).get("base_url")),
                          "cli": (data.get("cli") or {}).get("command", ""),
                          "allowed_users": data.get("allowed_users") or []})
    for tool_id, data in mcp_tools.list_mcp_tools().items():
        hay = f"{tool_id} {data.get('name', '')}".lower()
        if data.get("type") == mcp_tools.TOOL_TYPE_MCP and any(w in hay for w in words):
            found.append({"tool_id": tool_id, "name": data.get("name", tool_id), "type": "mcp",
                          "allowed_users": data.get("allowed_users") or []})
    return found


# ---------------------------------------------------------------------------
# Employee side
# ---------------------------------------------------------------------------

def _clean_access(access: str) -> str:
    return "write" if str(access or "").strip().lower() in ("write", "w", "rw", "écriture", "ecriture", "read-write") else "read"


def submit(employee_id: str, service: str, reason: str, *, access: str = "read", kind: str = "api",
           blocked: str = "", task_id: str = "", project_id: str = "") -> tuple[dict, bool]:
    """Record a request (or join the open one for this service). Returns (request, created)."""
    service = " ".join(str(service or "").split())[:80]
    reason = str(reason or "").strip()[:2000]
    if not service:
        raise ValueError("Say which service you need (e.g. Scalingo, GitHub, n8n)")
    if not reason:
        raise ValueError("Say why you need it and for what work")
    access = _clean_access(access)
    kind = kind if kind in KINDS else "other"
    emp = str(employee_id)
    fields = {"reason": reason, "access": access, "kind": kind, "blocked": str(blocked or "").strip()[:1000],
              "task_id": task_id, "project_id": project_id, "requested_at": _now()}
    with _lock:
        items = _load()
        key = service_key(service)
        req = next((r for r in items if r.get("key") == key and r.get("status") in ACTIVE), None)
        created = req is None
        if created:
            req = {"id": uuid.uuid4().hex[:8], "service": service, "key": key, "kinds": [kind], "status": "open",
                   "created_at": _now(), "updated_at": _now(), "requesters": [], "card": {}, "history": []}
            items.append(req)
        elif kind not in req.setdefault("kinds", []):
            req["kinds"].append(kind)
        entry = next((q for q in req["requesters"] if q.get("employee") == emp), None)
        if entry is None:
            req["requesters"].append({"employee": emp, **fields, "status": "new", "coo_node": ""})
        else:
            if entry.get("access") == "write":
                fields["access"] = "write"  # never downgrade an earlier write request
            entry.update(fields, status="new", coo_node="", decided_at="", decided_by="", note="")
        _history(req, emp, "requested", f"{access}: {reason}")
        _save(items)
        out = copy.deepcopy(req)
    _publish(out)
    return out, created


def set_coo_node(request_id: str, employee_id: str, node_id: str) -> None:
    with _lock:
        items = _load()
        req = _find(items, request_id)
        _requester(req, employee_id)["coo_node"] = node_id
        _save(items)


# ---------------------------------------------------------------------------
# COO side
# ---------------------------------------------------------------------------

def _grant_on_tool(tool_id: str, employee_id: str, access: str, allowed_writes: list[str] | None,
                   reason: str, request_id: str, by: str) -> str:
    """Apply a grant on whatever kind of company tool it is. Returns the tool type."""
    from onemancompany.core import api_tools, mcp_tools

    if api_tools.load_tool(tool_id):
        api_tools.grant_employee(tool_id, employee_id, access=access, allowed_writes=allowed_writes,
                                 reason=reason, request_id=request_id, by=by)
        return "api_key"
    data = mcp_tools.load_tool(tool_id)
    if data and data.get("type") == mcp_tools.TOOL_TYPE_MCP:
        users = sorted({str(u) for u in data.get("allowed_users") or []} | {str(employee_id)})
        mcp_tools.update_access(tool_id, allowed_users=users)
        data = mcp_tools.load_tool(tool_id) or {}
        grants = dict(data.get("grants") or {})
        grants[str(employee_id)] = {"access": access, "reason": reason, "request_id": request_id,
                                    "granted_by": by, "granted_at": _now()}
        data["grants"] = grants
        history = list(data.get("grant_history") or [])
        history.append({"at": _now(), "employee": str(employee_id), "event": "granted", "by": by,
                        "access": access, "reason": reason, "request_id": request_id})
        data["grant_history"] = history[-200:]
        mcp_tools.save_tool(tool_id, data)
        api_tools._sync_state(tool_id, data)
        return "mcp"
    from onemancompany.agents.coo_agent import grant_tool_access

    result = grant_tool_access.invoke({"tool_id": tool_id, "target_employee_id": str(employee_id)})
    if result.get("status") != "success":
        raise ValueError(f"Unknown tool: {tool_id}")
    return "office"


def grant(request_id: str, employee_id: str, tool_id: str, *, access: str = "read",
          allowed_writes: list[str] | None = None, by: str = "COO", note: str = "") -> dict:
    """Grant an existing company tool to one requester (minimum rights)."""
    with _lock:
        req = _find(_load(), request_id)
        entry = _requester(req, employee_id)
        reason = entry.get("reason", "")
    access = _clean_access(access or entry.get("access"))
    tool_type = _grant_on_tool(tool_id, employee_id, access, allowed_writes, reason, request_id, by)
    with _lock:
        items = _load()
        req = _find(items, request_id)
        entry = _requester(req, employee_id)
        entry.update(status="granted", tool_id=tool_id, granted_access=access, decided_by=by,
                     decided_at=_now(), note=note[:1000])
        _history(req, by, "granted", f"{employee_id} · {tool_id} ({access}){' — ' + note if note else ''}")
        _refresh_status(req)
        _save(items)
        out = copy.deepcopy(req)
    _publish(out)
    return {"request": out, "tool_type": tool_type}


def refuse(request_id: str, employee_id: str, reason: str, *, by: str = "COO") -> dict:
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("Give the reason for the refusal: the employee needs it")
    with _lock:
        items = _load()
        req = _find(items, request_id)
        entry = _requester(req, employee_id)
        entry.update(status="refused", decided_by=by, decided_at=_now(), note=reason[:1000])
        _history(req, by, "refused", f"{employee_id}: {reason}")
        _refresh_status(req)
        _save(items)
        out = copy.deepcopy(req)
    _publish(out)
    return out


def normalize_setup(setup: dict | None) -> dict:
    """How the relay will use the key: preset values completed by explicit ones."""
    from onemancompany.core import api_tools
    from onemancompany.core.cli_relay import normalize_cli

    setup = dict(setup or {})
    preset = str(setup.pop("preset", "") or "").strip().lower()
    if preset and preset not in SERVICE_PRESETS:
        raise ValueError(f"Unknown preset: {preset} (known: {', '.join(SERVICE_PRESETS)})")
    base = {k: v for k, v in SERVICE_PRESETS.get(preset, {}).items() if k in _SETUP_FIELDS}
    out = {**base, **{k: v for k, v in setup.items() if k in _SETUP_FIELDS and v not in (None, "", [], {})}}
    if preset:
        out["preset"] = preset
    if out.get("base_url"):
        out["base_url"] = api_tools._validate_base_url(out["base_url"])
    out.setdefault("auth_in", "header")
    if out["auth_in"] not in api_tools.AUTH_PLACES:
        raise ValueError("auth_in must be header, query or path")
    if out.get("exchange"):
        out["exchange"] = api_tools._validate_exchange(out["exchange"])
    if out.get("cli"):
        out["cli"] = normalize_cli(out["cli"])
    if out.get("headers") and not isinstance(out["headers"], dict):
        raise ValueError("headers must be an object of header names and values")
    return out


def escalate(request_id: str, *, what: str, why: str, where_url: str = "", rights: str = "",
             deliverable: str = "key", setup: dict | None = None, tool_id: str = "",
             by: str = "COO") -> dict:
    """Ask the CEO to create what only they can create. Validates the waiting requesters."""
    from onemancompany.core import api_tools

    what = str(what or "").strip()
    why = str(why or "").strip()
    if not what or not why:
        raise ValueError("Say what the CEO must create (what) and why it is needed (why)")
    deliverable = "action" if deliverable == "action" else "key"
    clean = normalize_setup(setup) if deliverable == "key" else {}
    if tool_id and not api_tools.load_tool(tool_id):
        raise ValueError(f"{tool_id} is not a company API key tool")
    if deliverable == "key" and not tool_id and not (clean.get("base_url") or clean.get("cli")):
        raise ValueError("Give the API address (base_url) and/or the command-line tool (cli or a preset) so the "
                         "key can be used through the relay; or deliverable='action' if no key is needed")
    where_url = str(where_url or "").strip() or SERVICE_PRESETS.get(clean.get("preset", ""), {}).get("where_url", "")
    with _lock:
        items = _load()
        req = _find(items, request_id)
        if req.get("status") not in ACTIVE:
            raise ValueError(f"Request {request_id} is already {req.get('status')}")
        req["card"] = {"what": what[:1000], "why": why[:2000], "where_url": where_url[:500], "rights": str(rights or "")[:1000],
                       "deliverable": deliverable, "setup": clean, "tool_id": tool_id, "by": by, "at": _now()}
        for q in req["requesters"]:
            if q.get("status") == "new":
                q["status"] = "validated"
        req["status"] = "waiting_ceo"
        _history(req, by, "escalated", what)
        _save(items)
        out = copy.deepcopy(req)
    _publish(out, new_card=True)
    return out


# ---------------------------------------------------------------------------
# CEO side
# ---------------------------------------------------------------------------

def _waiting(req: dict) -> dict:
    if req.get("status") != "waiting_ceo":
        raise ValueError(f"This request is no longer waiting for you ({req.get('status')})")
    return req


def provide(request_id: str, key: str, *, overrides: dict | None = None, note: str = "",
            by: str = "CEO") -> tuple[dict, str]:
    """The CEO pastes the key: it becomes a company tool and the validated requesters get access."""
    from onemancompany.core import api_tools

    key = str(key or "").strip()
    if not key:
        raise ValueError("Paste the key")
    with _lock:
        req = copy.deepcopy(_waiting(_find(_load(), request_id)))
    card = req.get("card") or {}
    tool_id = card.get("tool_id") or ""
    if tool_id and api_tools.load_tool(tool_id):
        api_tools.replace_key(tool_id, key)
    else:
        setup = normalize_setup({**(card.get("setup") or {}), **(overrides or {})})
        tool_id = api_tools.create_api_tool(
            setup.get("name") or req["service"], setup.get("base_url", ""), key,
            auth_in=setup.get("auth_in", "header"), auth_name=setup.get("auth_name") or "Authorization",
            auth_format=setup.get("auth_format") or "Bearer {key}", docs_url=setup.get("docs_url", ""),
            description=f"{req['service']} — {card.get('what', '')}"[:200], headers=setup.get("headers"),
            exchange=setup.get("exchange"), cli=setup.get("cli"), added_by=by,
        )
    granted = []
    for q in req["requesters"]:
        if q.get("status") == "validated":
            api_tools.grant_employee(tool_id, q["employee"], access=q.get("access", "read"),
                                     reason=q.get("reason", ""), request_id=request_id, by=by)
            granted.append(q["employee"])
    with _lock:
        items = _load()
        stored = _find(items, request_id)
        for q in stored["requesters"]:
            if q["employee"] in granted:
                q.update(status="granted", tool_id=tool_id, granted_access=q.get("access", "read"),
                         decided_by=by, decided_at=_now())
        stored["status"] = "done"
        stored["resolution"] = {"by": by, "at": _now(), "tool_id": tool_id, "note": str(note or "")[:1000],
                                "outcome": "key"}
        _history(stored, by, "key provided", f"{tool_id} → {', '.join(granted) or 'nobody yet'}")
        _save(items)
        out = copy.deepcopy(stored)
    _publish(out)
    logger.info("[access-desk] {} provided the key for {} ({}); granted to {}", by, req["service"], tool_id, granted)
    return out, tool_id


def done_without_key(request_id: str, note: str = "", *, by: str = "CEO") -> dict:
    """The CEO did what was asked (account, invitation…) without a key to store."""
    with _lock:
        items = _load()
        req = _waiting(_find(items, request_id))
        for q in req["requesters"]:
            if q.get("status") == "validated":
                q.update(status="granted", tool_id="", decided_by=by, decided_at=_now(), note=str(note or "")[:1000])
        req["status"] = "done"
        req["resolution"] = {"by": by, "at": _now(), "tool_id": "", "note": str(note or "")[:1000], "outcome": "done"}
        _history(req, by, "done", note or "")
        _save(items)
        out = copy.deepcopy(req)
    _publish(out)
    return out


def refuse_by_ceo(request_id: str, reason: str = "", *, by: str = "CEO") -> dict:
    with _lock:
        items = _load()
        req = _waiting(_find(items, request_id))
        for q in req["requesters"]:
            if q.get("status") in ("new", "validated"):
                q.update(status="refused", decided_by=by, decided_at=_now(), note=str(reason or "")[:1000])
        req["status"] = "refused"
        req["resolution"] = {"by": by, "at": _now(), "tool_id": "", "note": str(reason or "")[:1000],
                             "outcome": "refused"}
        _history(req, by, "refused", reason or "")
        _save(items)
        out = copy.deepcopy(req)
    _publish(out)
    return out


# ---------------------------------------------------------------------------
# Telling the employees
# ---------------------------------------------------------------------------

def _lang() -> str:
    from onemancompany.core.i18n import get_company_language

    return "fr" if get_company_language() == "fr" else "en"


def outcome_text(req: dict, entry: dict) -> str:
    """What the employee reads when their access is decided."""
    from onemancompany.core import api_tools

    fr = _lang() == "fr"
    service = req.get("service", "")
    status = entry.get("status")
    resolution = req.get("resolution") or {}
    if status == "refused":
        who = entry.get("decided_by") or "COO"
        note = entry.get("note") or resolution.get("note") or ""
        return (f"Accès refusé ({service}) par {who} : {note}" if fr
                else f"Access refused ({service}) by {who}: {note}")
    tool_id = entry.get("tool_id") or ""
    blocked = entry.get("blocked") or ""
    if not tool_id:
        note = entry.get("note") or resolution.get("note") or ""
        text = (f"C'est fait pour {service}" if fr else f"Done for {service}") + (f" : {note}" if note else ".")
    else:
        from onemancompany.core import mcp_tools

        data = api_tools.load_tool(tool_id) or {}
        access = entry.get("granted_access") or entry.get("access") or "read"
        how = []
        if (data.get("api") or {}).get("base_url"):
            how.append(f'api_request(api="{tool_id}", method=..., path=...)')
        if (data.get("cli") or {}).get("command"):
            how.append(f'run_cli(api="{tool_id}", command="<{data["cli"]["command"]} …>")')
        if not how and (mcp_tools.load_tool(tool_id) or {}).get("type") == mcp_tools.TOOL_TYPE_MCP:
            how.append(f"ses actions mcp__{tool_id}__… (dans tes outils)" if fr
                       else f"its actions mcp__{tool_id}__… (in your tools)")
        if not how:
            how.append(f'use_tool("{tool_id}")')
        rights = ("lecture seule" if access == "read" else "lecture et écriture") if fr else (
            "read-only" if access == "read" else "read and write")
        text = (f"Accès accordé : {service} ({rights}). Utilise " + " ou ".join(how) + "." if fr
                else f"Access granted: {service} ({rights}). Use " + " or ".join(how) + ".")
    if blocked:
        text += (f" Reprends maintenant ce qui était bloqué : {blocked}" if fr
                 else f" Now carry on with what was blocked: {blocked}")
    return text


async def _resume_later(coo_id: str, node_id: str, text: str, employee_id: str, attempts: int = 40) -> None:
    """The COO's task may still be running when the CEO answers: retry until it waits."""
    from onemancompany.core.vessel import employee_manager

    for _ in range(attempts):
        await asyncio.sleep(15)
        try:
            if await employee_manager.resume_held_task(coo_id, node_id, text):
                return
        except Exception as exc:
            logger.debug("[access-desk] resume retry failed for {}: {}", node_id, exc)
    logger.warning("[access-desk] COO task {} never waited; telling {} directly", node_id, employee_id)
    from onemancompany.api.routes import _push_adhoc_task

    _push_adhoc_task(employee_id, text)


async def notify_requesters(req: dict, employees: list[str] | None = None) -> list[str]:
    """Resume the COO's waiting tasks (so the requesters continue) or tell them directly."""
    from onemancompany.core.config import COO_ID
    from onemancompany.core.vessel import employee_manager

    told = []
    for entry in req.get("requesters") or []:
        emp = entry.get("employee")
        if employees is not None and emp not in employees:
            continue
        if entry.get("status") not in ("granted", "refused"):
            continue
        text = outcome_text(req, entry)
        node = entry.get("coo_node") or ""
        resumed = False
        if node:
            try:
                resumed = await employee_manager.resume_held_task(COO_ID, node, text)
            except Exception as exc:
                logger.warning("[access-desk] cannot resume COO task {}: {}", node, exc)
            if not resumed and _node_running(node):
                asyncio.get_running_loop().create_task(_resume_later(COO_ID, node, text, emp))
                told.append(emp)
                continue
        if not resumed:
            from onemancompany.api.routes import _push_adhoc_task

            _push_adhoc_task(emp, text)
        told.append(emp)
    return told


def _node_running(node_id: str) -> bool:
    """True if the COO is still working on that node (it may wait once its turn ends)."""
    from onemancompany.core.config import COO_ID
    from onemancompany.core.vessel import employee_manager

    current = employee_manager._current_entries.get(COO_ID)
    if current is not None and current.node_id == node_id:
        return True
    return any(e.node_id == node_id for e in employee_manager._schedule.get(COO_ID, []))


def _publish(req: dict, new_card: bool = False) -> None:
    """Tell the CEO's interface (badge, box) that a request changed."""
    try:
        from onemancompany.core.events import CompanyEvent, event_bus
        from onemancompany.core.models import EventType

        count = sum(1 for r in _load() if r.get("status") == "waiting_ceo")
        event = CompanyEvent(type=EventType.ACCESS_REQUEST_UPDATE, agent="COO", payload={
            "id": req.get("id"), "service": req.get("service"), "status": req.get("status"),
            "waiting_ceo": count, "new_card": new_card,
        })
        asyncio.get_running_loop().create_task(event_bus.publish(event))
    except RuntimeError:
        logger.debug("[access-desk] no event loop: update for {} not pushed", req.get("id"))
    except Exception as exc:
        logger.warning("[access-desk] cannot publish update: {}", exc)
