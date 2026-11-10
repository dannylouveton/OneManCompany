"""API keys as company tools, used by employees through a relay.

An API-key tool is an asset tool folder whose ``tool.yaml`` has
``type: api_key``::

    id: intercom_api
    name: Intercom API
    type: api_key
    api:
      base_url: https://api.intercom.io
      auth: {in: header, name: Authorization, format: "Bearer {key}"}
      headers: {Intercom-Version: "2.11"}     # extra, non-secret headers
      docs_url: https://developers.intercom.com/docs/references/rest-api
    secret: OMC_API_INTERCOM_API_KEY         # name in the secret store
    allowed_users: ["00006"]                 # nobody by default
    rules:                                   # shared rules
      read_only: true                        # writes need allowed_writes
      allowed_writes: ["POST /conversations/*/reply"]
      approval: true                         # permitted writes wait for the CEO
    employee_rules: {"00006": {...}}         # personal rules (override)
    grants: {"00006": {access, reason, request_id, granted_by, granted_at}}
    grant_history: [...]                     # who got / lost access, by whom, why
    cli: {preset: scalingo}                  # optional command-line tool (cli_relay)

Other ways to send the key: ``auth: {in: path, format: "/bot{key}"}`` (in the
URL, e.g. Telegram) and ``auth.exchange: {url, token_field}`` (the key is
exchanged for a short-lived token, e.g. Scalingo).

Employees never see the key. They call ``api_request`` (an internal tool):
the server checks the rules, adds the key, calls the API (only under
``base_url``) and returns the response. Every call is logged in
``api_log.jsonl``; writes needing approval wait in ``pending/``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from loguru import logger

TOOL_TYPE_API_KEY = "api_key"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
ALL_METHODS = READ_METHODS | {"POST", "PUT", "PATCH", "DELETE"}
DEFAULT_RULES = {"read_only": True, "allowed_writes": [], "approval": True}
MAX_RESPONSE_CHARS = 20000
MAX_LOG_LINES = 500
MAX_GRANT_HISTORY = 200
REQUEST_TIMEOUT = 30.0
AUTH_PLACES = ("header", "query", "path")


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _tools_dir() -> Path:
    from onemancompany.core.config import TOOLS_DIR

    return TOOLS_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_tool(tool_id: str) -> dict | None:
    path = _tools_dir() / tool_id / "tool.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if data.get("type") == TOOL_TYPE_API_KEY else None


def save_tool(tool_id: str, data: dict) -> None:
    from onemancompany.core.store import mark_dirty, DirtyCategory

    path = _tools_dir() / tool_id / "tool.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False), encoding="utf-8")
    mark_dirty(DirtyCategory.TOOLS)


def list_api_tools() -> dict[str, dict]:
    root = _tools_dir()
    tools: dict[str, dict] = {}
    if not root.exists():
        return tools
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (data := load_tool(entry.name)):
            tools[entry.name] = data
    return tools


def _granted(data: dict, employee_id: str) -> bool:
    allowed = data.get("allowed_users")
    return isinstance(allowed, list) and str(employee_id) in {str(u) for u in allowed}


def _normalize_rules(rules: dict | None) -> dict:
    rules = rules or {}
    writes = []
    for pattern in rules.get("allowed_writes") or []:
        pattern = " ".join(str(pattern).split())
        if not pattern:
            continue
        method, _, path = pattern.partition(" ")
        method = method.upper()
        if method not in ALL_METHODS - READ_METHODS and method != "*":
            raise ValueError(f"Invalid write rule: {pattern}")
        writes.append(f"{method} {'/' + path.lstrip('/') if path else '/*'}")
    return {
        "read_only": bool(rules.get("read_only", True)),
        "allowed_writes": sorted(set(writes)),
        "approval": bool(rules.get("approval", True)),
    }


def effective_rules(data: dict, employee_id: str) -> dict:
    personal = (data.get("employee_rules") or {}).get(str(employee_id))
    if isinstance(personal, dict):
        return _normalize_rules({**DEFAULT_RULES, **personal})
    return _normalize_rules({**DEFAULT_RULES, **(data.get("rules") or {})})


# ---------------------------------------------------------------------------
# Creating / updating
# ---------------------------------------------------------------------------

def _unique_id(name: str) -> str:
    from onemancompany.core.mcp_tools import RESERVED_SERVER_NAMES, slugify

    base = slugify(name)
    if base in RESERVED_SERVER_NAMES:
        base = f"{base}_api"
    candidate, n = base, 2
    while (_tools_dir() / candidate).exists():
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def _validate_base_url(base_url: str) -> str:
    base_url = (base_url or "").strip().rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme != "https" and parts.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("The API address must start with https://")
    if not parts.hostname:
        raise ValueError("Invalid API address")
    return base_url


def _validate_exchange(exchange: dict | None) -> dict | None:
    if not exchange:
        return None
    url = str(exchange.get("url") or "").strip()
    if urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
        raise ValueError("The token exchange address must start with https://")
    return {"url": url, "token_field": str(exchange.get("token_field") or "token"),
            "ttl_seconds": int(exchange.get("ttl_seconds") or 3000)}


def create_api_tool(name: str, base_url: str, key: str, *, auth_in: str = "header",
                    auth_name: str = "Authorization", auth_format: str = "Bearer {key}",
                    docs_url: str = "", description: str = "", headers: dict | None = None,
                    exchange: dict | None = None, cli: dict | str | None = None,
                    added_by: str = "CEO") -> str:
    """Store the key and create the tool. ``base_url`` may be empty for a CLI-only tool."""
    from onemancompany.core.cli_relay import normalize_cli
    from onemancompany.core.secret_store import get_secret_store

    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required")
    if not key:
        raise ValueError("API key is required")
    if auth_in not in AUTH_PLACES:
        raise ValueError("auth_in must be header, query or path")
    if "{key}" not in (auth_format or ""):
        auth_format = "/{key}" if auth_in == "path" else "{key}"
    cli_spec = normalize_cli(cli)
    if not (base_url or "").strip() and not cli_spec:
        raise ValueError("Give the API address, or a command-line tool")
    base_url = _validate_base_url(base_url) if (base_url or "").strip() else ""
    auth = {"in": auth_in, "name": auth_name or "Authorization", "format": auth_format}
    if (ex := _validate_exchange(exchange)):
        auth["exchange"] = ex
    tool_id = _unique_id(name)
    secret_name = "OMC_API_" + re.sub(r"[^A-Z0-9]+", "_", tool_id.upper()).strip("_") + "_KEY"
    get_secret_store().set_many({secret_name: key})
    data = {
        "id": tool_id,
        "name": name,
        "description": description or (f"API access: {base_url}" if base_url else f"Command line: {cli_spec['command']}"),
        "added_by": added_by,
        "type": TOOL_TYPE_API_KEY,
        "sprite": "desk_equipment",
        "api": {
            "base_url": base_url,
            "auth": auth,
            "headers": {str(k): str(v) for k, v in (headers or {}).items()},
            "docs_url": docs_url,
        },
        "secret": secret_name,
        "allowed_users": [],
        "rules": dict(DEFAULT_RULES),
    }
    if cli_spec:
        data["cli"] = cli_spec
    save_tool(tool_id, data)
    logger.info("Created API key tool {} ({})", tool_id, base_url or cli_spec["command"])
    return tool_id


def replace_key(tool_id: str, key: str) -> None:
    from onemancompany.core.secret_store import get_secret_store

    data = load_tool(tool_id)
    if not data:
        raise ValueError("Not an API key tool")
    if not key:
        raise ValueError("API key is required")
    get_secret_store().set_many({data["secret"]: key})


def delete_secret(tool_id: str) -> None:
    from onemancompany.core.secret_store import get_secret_store

    data = load_tool(tool_id)
    if data and data.get("secret"):
        get_secret_store().delete(data["secret"])


def _record_history(data: dict, entry: dict) -> None:
    history = list(data.get("grant_history") or [])
    history.append(entry)
    data["grant_history"] = history[-MAX_GRANT_HISTORY:]


def _sync_state(tool_id: str, data: dict) -> None:
    """Keep the in-memory office tool in step with tool.yaml."""
    try:
        from onemancompany.core.state import company_state

        tool = company_state.tools.get(tool_id)
        if tool is not None:
            tool.allowed_users = list(data.get("allowed_users") or [])
    except Exception as exc:  # the file is the source of truth
        logger.debug("Cannot sync tool {} in memory: {}", tool_id, exc)


def rules_for_access(access: str, allowed_writes: list[str] | None = None) -> dict:
    """Personal rules for a grant: reads only, some writes, or all writes (no per-write approval)."""
    if access == "write":
        if allowed_writes:
            return {"read_only": True, "allowed_writes": list(allowed_writes), "approval": False}
        return {"read_only": False, "allowed_writes": [], "approval": False}
    return {"read_only": True, "allowed_writes": [], "approval": False}


def grant_employee(tool_id: str, employee_id: str, *, access: str = "read",
                   allowed_writes: list[str] | None = None, reason: str = "",
                   request_id: str = "", by: str = "COO") -> dict:
    """Give an employee access, with the minimum rules for it, and trace why and by whom."""
    data = load_tool(tool_id)
    if not data:
        raise ValueError("Not an API key tool")
    access = "write" if access == "write" else "read"
    emp = str(employee_id)
    rules = _normalize_rules(rules_for_access(access, allowed_writes))
    data["allowed_users"] = sorted({str(u) for u in data.get("allowed_users") or []} | {emp})
    personal = dict(data.get("employee_rules") or {})
    personal[emp] = rules
    data["employee_rules"] = personal
    info = {"access": access, "allowed_writes": rules["allowed_writes"], "reason": reason,
            "request_id": request_id, "granted_by": by, "granted_at": _now()}
    grants = dict(data.get("grants") or {})
    grants[emp] = info
    data["grants"] = grants
    _record_history(data, {"at": info["granted_at"], "employee": emp, "event": "granted", "by": by,
                           "access": access, "reason": reason, "request_id": request_id})
    save_tool(tool_id, data)
    _sync_state(tool_id, data)
    return info


def revoke_employee(tool_id: str, employee_id: str, *, by: str = "CEO", reason: str = "") -> bool:
    data = load_tool(tool_id)
    if not data:
        raise ValueError("Not an API key tool")
    emp = str(employee_id)
    users = {str(u) for u in data.get("allowed_users") or []}
    if emp not in users:
        return False
    data["allowed_users"] = sorted(users - {emp})
    (data.get("employee_rules") or {}).pop(emp, None)
    (data.get("grants") or {}).pop(emp, None)
    _record_history(data, {"at": _now(), "employee": emp, "event": "revoked", "by": by, "reason": reason})
    save_tool(tool_id, data)
    _sync_state(tool_id, data)
    return True


def update_access(tool_id: str, allowed_users: list[str] | None = None, rules: dict | None = None,
                  employee_rules: dict[str, dict | None] | None = None, *, by: str = "CEO") -> dict:
    data = load_tool(tool_id)
    if not data:
        raise ValueError("Not an API key tool")
    if allowed_users is not None:
        before = {str(u) for u in data.get("allowed_users") or []}
        after = {str(u) for u in allowed_users}
        grants = dict(data.get("grants") or {})
        for emp in sorted(after - before):
            grants[emp] = {"access": "custom", "reason": "", "request_id": "", "granted_by": by, "granted_at": _now()}
            _record_history(data, {"at": _now(), "employee": emp, "event": "granted", "by": by})
        for emp in sorted(before - after):
            grants.pop(emp, None)
            _record_history(data, {"at": _now(), "employee": emp, "event": "revoked", "by": by})
        data["grants"] = grants
        data["allowed_users"] = sorted(after)
    if rules is not None:
        data["rules"] = _normalize_rules(rules)
    if employee_rules is not None:
        personal = dict(data.get("employee_rules") or {})
        for emp_id, emp_rules in employee_rules.items():
            if emp_rules is None:
                personal.pop(str(emp_id), None)
            else:
                personal[str(emp_id)] = _normalize_rules(emp_rules)
        if personal:
            data["employee_rules"] = personal
        else:
            data.pop("employee_rules", None)
    save_tool(tool_id, data)
    return data


# ---------------------------------------------------------------------------
# Rule checks
# ---------------------------------------------------------------------------

def _clean_path(path: str) -> str:
    path = (path or "").strip()
    if not path:
        raise ValueError("Path is required (e.g. /conversations)")
    if "://" in path or path.startswith("//") or "\\" in path:
        raise ValueError("Give a path relative to the API address, not a full URL")
    path = "/" + path.lstrip("/")
    if any(part == ".." for part in path.split("?")[0].split("/")):
        raise ValueError("'..' is not allowed in the path")
    return path


def decide(data: dict, employee_id: str, method: str, path: str) -> tuple[str, str]:
    """Return (decision, reason) with decision in allowed / approval / denied."""
    if not _granted(data, employee_id):
        return "denied", "You do not have access to this API. Ask for it with request_access()."
    method = method.upper()
    if method not in ALL_METHODS:
        return "denied", f"Unsupported HTTP method: {method}"
    if method in READ_METHODS:
        return "allowed", ""
    rules = effective_rules(data, employee_id)
    bare = path.split("?")[0]
    permitted = not rules["read_only"] or any(
        rule.split(" ", 1)[0] in (method, "*") and fnmatch.fnmatchcase(bare, rule.split(" ", 1)[1])
        for rule in rules["allowed_writes"]
    )
    if not permitted:
        return "denied", (f"{method} {bare} is not allowed for you (read-only access). "
                          "If you really need it, ask with request_access(access='write').")
    if rules["approval"]:
        return "approval", "This write needs the CEO's approval."
    return "allowed", ""


# ---------------------------------------------------------------------------
# Calling the API
# ---------------------------------------------------------------------------

def _redact(value: Any, secret: str) -> Any:
    if not secret:
        return value
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    redacted = text.replace(secret, "[REDACTED]")
    if isinstance(value, str):
        return redacted
    try:
        return json.loads(redacted)
    except Exception:
        return redacted


_exchange_cache: dict[str, tuple[str, float]] = {}


def _exchanged_token(data: dict, key: str) -> str:
    """Short-lived token obtained with the key (e.g. Scalingo), cached until it expires."""
    import httpx

    exchange = (data.get("api") or {}).get("auth", {}).get("exchange") or {}
    cache_key = f"{data.get('id', '')}:{hashlib.sha256(key.encode()).hexdigest()[:16]}"
    hit = _exchange_cache.get(cache_key)
    if hit and hit[1] > time.time():
        return hit[0]
    resp = httpx.post(exchange["url"], auth=("", key), headers={"Accept": "application/json"},
                      timeout=REQUEST_TIMEOUT, follow_redirects=False)
    if not resp.is_success:
        raise ValueError(f"the key was refused when asking for a session token (HTTP {resp.status_code})")
    token = str((resp.json() or {}).get(exchange.get("token_field") or "token") or "")
    if not token:
        raise ValueError("no session token in the answer")
    _exchange_cache[cache_key] = (token, time.time() + int(exchange.get("ttl_seconds") or 3000))
    return token


def _execute(data: dict, method: str, path: str, query: dict | None, body: Any) -> dict:
    import httpx

    from onemancompany.core.secret_store import get_secret_store

    api = data["api"]
    key = get_secret_store().get(data["secret"]) or ""
    if not key:
        return {"ok": False, "error": "The API key is missing. Ask the CEO to set it in the Tools panel."}
    base = (api.get("base_url") or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "This tool has no HTTP API: use run_cli."}
    auth = api.get("auth") or {}
    secrets = [key]
    value = key
    if auth.get("exchange"):
        try:
            value = _exchanged_token(data, key)
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "error": _redact(f"Authentication failed: {exc}", key)[:500]}
        secrets.append(value)
    credential = str(auth.get("format") or "{key}").replace("{key}", value)
    url = base + (credential if auth.get("in") == "path" else "") + path
    if urlsplit(url).netloc != urlsplit(base).netloc or not url.startswith(base):
        return {"ok": False, "error": "The request must stay under the API address"}

    headers = {"Accept": "application/json", **(api.get("headers") or {})}
    params = dict(query or {})
    if auth.get("in") == "query":
        params[auth.get("name") or "api_key"] = credential
    elif auth.get("in") != "path":
        headers[auth.get("name") or "Authorization"] = credential

    kwargs: dict[str, Any] = {"params": params, "headers": headers, "timeout": REQUEST_TIMEOUT}
    if body is not None and method not in READ_METHODS:
        if isinstance(body, (dict, list)):
            kwargs["json"] = body
        else:
            kwargs["content"] = str(body)
    try:
        resp = httpx.request(method, url, follow_redirects=False, **kwargs)
    except httpx.HTTPError as exc:
        message = f"Request failed: {type(exc).__name__}: {exc}"
        for secret in secrets:
            message = _redact(message, secret)
        return {"ok": False, "error": message[:500]}

    text = resp.text[:MAX_RESPONSE_CHARS]
    try:
        payload: Any = resp.json()
        if len(text) >= MAX_RESPONSE_CHARS:
            payload = text + "… [truncated]"
    except ValueError:
        payload = text + ("… [truncated]" if len(resp.text) > MAX_RESPONSE_CHARS else "")
    for secret in secrets:
        payload = _redact(payload, secret)
    return {"ok": resp.is_success, "http_status": resp.status_code, "body": payload}


def _log(tool_id: str, entry: dict) -> None:
    path = _tools_dir() / tool_id / "api_log.jsonl"
    line = json.dumps(entry, ensure_ascii=False, default=str)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = (lines + [line])[-MAX_LOG_LINES:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_log(tool_id: str, limit: int = 30) -> list[dict]:
    path = _tools_dir() / tool_id / "api_log.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            logger.debug("Skipping malformed API log line in {}", tool_id)
    return list(reversed(out))


def _short(value: Any, limit: int = 2000) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _pending_dir(tool_id: str) -> Path:
    return _tools_dir() / tool_id / "pending"


def request(tool_id: str, employee_id: str, method: str, path: str,
            query: dict | None = None, body: Any = None) -> dict:
    """Entry point used by the employee tool ``api_request``."""
    data = load_tool(tool_id)
    if not data:
        return {"status": "error", "message": f"Unknown API: {tool_id}. Use list_company_apis()."}
    method = (method or "GET").upper()
    try:
        path = _clean_path(path)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    decision, reason = decide(data, employee_id, method, path)
    entry = {"at": _now(), "employee": employee_id, "method": method, "path": path, "decision": decision}
    if decision == "denied":
        _log(tool_id, {**entry, "reason": reason})
        return {"status": "denied", "message": reason}

    if decision == "approval":
        req_id = uuid.uuid4().hex[:10]
        pending = {"id": req_id, "tool_id": tool_id, "created_at": _now(), "employee": employee_id,
                   "method": method, "path": path, "query": query or {}, "body": body, "status": "pending"}
        _pending_dir(tool_id).mkdir(parents=True, exist_ok=True)
        (_pending_dir(tool_id) / f"{req_id}.json").write_text(json.dumps(pending, ensure_ascii=False, default=str), encoding="utf-8")
        _log(tool_id, {**entry, "request_id": req_id, "body": _short(body)})
        return {"status": "pending_approval", "request_id": req_id,
                "message": "Waiting for the CEO's approval. Check later with api_request_status(request_id)."}

    result = _execute(data, method, path, query, body)
    _log(tool_id, {**entry, "http_status": result.get("http_status"), "ok": result.get("ok"),
                   "error": result.get("error"), "body": _short(body) if body is not None else None})
    return {"status": "done" if result.get("ok") else "failed", **result}


def list_pending(tool_id: str) -> list[dict]:
    root = _pending_dir(tool_id)
    if not root.exists():
        return []
    items = []
    for path in sorted(root.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            logger.warning("Skipping malformed pending API call {}", path)
            continue
        if item.get("status") == "pending":
            items.append(item)
    return items


def get_request(tool_id: str, req_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{10}", req_id or ""):
        return None
    path = _pending_dir(tool_id) / f"{req_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def find_request(req_id: str) -> dict | None:
    for tool_id in list_api_tools():
        if (item := get_request(tool_id, req_id)):
            return item
    return None


def _save_request(item: dict) -> None:
    path = _pending_dir(item["tool_id"]) / f"{item['id']}.json"
    path.write_text(json.dumps(item, ensure_ascii=False, default=str), encoding="utf-8")


def resolve_request(tool_id: str, req_id: str, approve: bool) -> dict:
    """CEO decision on a pending write. Approving runs the call now."""
    item = get_request(tool_id, req_id)
    data = load_tool(tool_id)
    if not item or not data:
        raise ValueError("Request not found")
    if item.get("status") != "pending":
        return item
    item["decided_at"] = _now()
    if approve:
        result = _execute(data, item["method"], item["path"], item.get("query"), item.get("body"))
        item.update(status="done" if result.get("ok") else "failed", result=result)
    else:
        item["status"] = "rejected"
    _save_request(item)
    _log(tool_id, {"at": _now(), "employee": item["employee"], "method": item["method"], "path": item["path"],
                   "decision": "approved" if approve else "rejected", "request_id": req_id,
                   "http_status": (item.get("result") or {}).get("http_status")})
    return item


def granted_apis(employee_id: str) -> list[dict]:
    apis = []
    for tool_id, data in list_api_tools().items():
        if not _granted(data, employee_id):
            continue
        rules = effective_rules(data, employee_id)
        base_url = (data.get("api") or {}).get("base_url", "")
        item = {
            "api": tool_id,
            "name": data.get("name", tool_id),
            "base_url": base_url,
            "docs_url": (data.get("api") or {}).get("docs_url", ""),
            "description": data.get("description", ""),
            "reads": "allowed (GET)" if base_url else "no HTTP API (use run_cli)",
            "writes": ("only " + ", ".join(rules["allowed_writes"]) if rules["read_only"] and rules["allowed_writes"]
                       else "not allowed" if rules["read_only"] else "allowed"),
            "approval_for_writes": rules["approval"],
        }
        cli = data.get("cli") or {}
        if cli.get("command"):
            item["cli"] = {
                "command": cli["command"],
                "use": f'run_cli(api="{tool_id}", command="<{cli["command"]} arguments>")',
                "allowed": "all commands" if not rules["read_only"] else "read commands only",
                **({"docs_url": cli["docs_url"]} if cli.get("docs_url") else {}),
            }
        apis.append(item)
    return apis
