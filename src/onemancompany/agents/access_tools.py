"""Access desk tools.

Employees: ``request_access`` — ask for an API, a command-line tool, an
account or another tool. The COO handles it; the requester's task waits and
resumes with the decision.

COO: ``list_access_requests``, ``grant_access`` (the company already has it),
``escalate_access_request`` (only the CEO can create it: a card goes to the
CEO's "Access requests" box and the COO's task waits), ``refuse_access``.
See core/access_desk.py.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool
from loguru import logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task_context():
    """(project tree path or "", project_id, node) of the task being run, if any."""
    from onemancompany.agents.tree_tools import _find_entry_for_task
    from onemancompany.core.config import TASK_TREE_FILENAME
    from onemancompany.core.task_tree import get_tree
    from onemancompany.core.vessel import _current_task_id

    task_id = _current_task_id.get("")
    if not task_id:
        return "", "", None
    _project_dir, tree_path = _find_entry_for_task(task_id)
    if not tree_path or not Path(tree_path).exists():
        return "", "", None
    node = get_tree(tree_path).get_node(task_id)
    if node is None:
        return "", "", None
    in_project = Path(tree_path).name == TASK_TREE_FILENAME
    return (tree_path if in_project else ""), node.project_id or "", node


def _is_task_node(node) -> bool:
    from onemancompany.core.task_lifecycle import NodeType

    return node is not None and node.node_type in (NodeType.TASK, NodeType.TASK.value)


def _node_active(tree_path: str, node_id: str) -> bool:
    from onemancompany.core.task_lifecycle import RESOLVED, TaskPhase
    from onemancompany.core.task_tree import get_tree

    if not tree_path or not node_id:
        return False
    node = get_tree(tree_path).get_node(node_id)
    return node is not None and TaskPhase(node.status) not in RESOLVED


def _fr() -> bool:
    from onemancompany.core.i18n import get_company_language

    return get_company_language() == "fr"


def _service_matches(service: str, *names: str) -> bool:
    from onemancompany.core.access_desk import service_key

    words = [w for w in service_key(service).split("-") if len(w) >= 3]
    hay = " ".join(names).lower()
    return bool(words) and any(w in hay for w in words)


def _already_granted(employee_id: str, service: str, access: str, kind: str) -> list[dict]:
    from onemancompany.core import mcp_tools
    from onemancompany.core.api_tools import granted_apis

    found = []
    for item in granted_apis(employee_id):
        if not _service_matches(service, item["api"], item["name"]):
            continue
        if access == "write" and item["writes"] == "not allowed":
            continue
        if kind == "cli" and "cli" not in item:
            continue
        found.append(item)
    if kind in ("api", "other"):
        for tool_id, data in mcp_tools.list_mcp_tools().items():
            if (data.get("type") == mcp_tools.TOOL_TYPE_MCP and str(employee_id) in (data.get("allowed_users") or [])
                    and _service_matches(service, tool_id, data.get("name", ""))):
                found.append({"connector": tool_id, "name": data.get("name", tool_id),
                              "use": "its actions are already in your tools"})
    return found


def _coo_brief(req: dict, employee_id: str) -> str:
    """The task the COO receives for one requester."""
    from onemancompany.core.access_desk import label, matching_tools

    entry = next(q for q in req["requesters"] if q["employee"] == str(employee_id))
    others = [f"{label(q['employee'])} ({q.get('access')}, {q.get('status')})"
              for q in req["requesters"] if q["employee"] != str(employee_id)]
    tools = matching_tools(req["service"])
    tools_text = "\n".join(
        f"  - {t['tool_id']} ({t['type']}{', CLI ' + t['cli'] if t.get('cli') else ''}) — "
        f"already used by: {', '.join(t.get('allowed_users') or []) or 'nobody'}" for t in tools) or "  none"
    card = req.get("card") or {}
    waiting = (f"\nAlready waiting for the CEO: {card.get('what')} (card sent by {card.get('by')})."
               if req.get("status") == "waiting_ceo" else "")
    rid = req["id"]
    emp = str(employee_id)
    return (
        f"Access request {rid} — {req['service']}\n"
        f"From: {label(emp)} [{emp}] · access asked: {entry.get('access')} · kind: {entry.get('kind')}\n"
        f"Why: {entry.get('reason')}\n"
        f"Blocked until granted: {entry.get('blocked') or '—'}\n"
        f"Other employees on this request: {', '.join(others) or 'none'}{waiting}\n"
        f"Company tools that may already cover it:\n{tools_text}\n\n"
        "You run the access desk (see \"Access desk\" in your role guide). Decide for this employee:\n"
        f"1. The company already has it (a tool above, list_company_apis, list_tools): "
        f"grant_access(request_id=\"{rid}\", target_employee_id=\"{emp}\", tool_id=..., access=\"read\" or \"write\") "
        "with the minimum rights; then finish with the one line it returns. The employee then carries on with "
        "their task by themselves (no review needed).\n"
        f"2. Only the CEO can create it (key, token, account, invitation): escalate_access_request(request_id=\"{rid}\", "
        "what_to_create=..., why=..., minimal_rights=..., preset=... or base_url/auth/cli). Write the card in the "
        "CEO's language; the CEO should only have to paste the key. Then end your turn: this task waits and ends "
        "by itself when the CEO answers, and the employee carries on.\n"
        f"3. Not justified for this work: refuse_access(request_id=\"{rid}\", target_employee_id=\"{emp}\", reason=...).\n"
        "Never ask the CEO in chat for keys and never handle keys yourself."
    )


# ---------------------------------------------------------------------------
# Employee tool
# ---------------------------------------------------------------------------

@tool
async def request_access(service: str, reason: str, access: str = "read", kind: str = "api",
                         blocked: str = "", employee_id: str = "") -> dict:
    """Ask for access to a service, a command-line tool, an account or another tool.

    The COO handles it: if the company already has the access, they grant it;
    otherwise they ask the CEO to create the key or the account. You never
    receive keys: once granted, use api_request() for an API or run_cli() for
    a command-line tool. Check list_company_apis() first.

    Everything stays in the project you are working on (its thread shows the
    request and the decision). Inside a task, end your turn right after this
    call: the same task comes back to you with the decision and you carry on
    from where you stopped. Outside a project, the decision arrives as a new task.

    Args:
        service: What you need, e.g. "Scalingo", "GitHub id_picture", "n8n", "Telegram bot".
        reason: Why, for which work — shown to the COO and the CEO.
        access: "read" (default: look only) or "write" (change things). Ask for the minimum.
        kind: "api" (HTTP API), "cli" (command-line tool such as scalingo or gh),
            "account" (an account or an invitation), or "other".
        blocked: What you cannot do until you have it.
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.agents.common_tools import _validate_employee_id
    from onemancompany.core import access_desk
    from onemancompany.core.config import CEO_ID, COO_ID, EA_ID

    if err := _validate_employee_id(employee_id):
        return err
    access = access_desk._clean_access(access)
    have = _already_granted(employee_id, service, access, kind)
    if have:
        return {"status": "already_granted", "access": have,
                "message": "You already have it: use api_request / run_cli (see list_company_apis())."}

    tree_path, project_id, node = _task_context()
    # Same request already on its way (e.g. a retry in the same task)?
    key = access_desk.service_key(service)
    for req in access_desk.list_requests("active"):
        entry = next((q for q in req["requesters"] if q["employee"] == str(employee_id)), None)
        if (req.get("key") == key and entry and entry.get("status") in ("new", "validated")
                and _node_active(tree_path, entry.get("coo_node", ""))):
            return {"status": "already_requested", "request_id": req["id"],
                    "message": "This request is already with the COO. End your turn: you will be resumed with the decision."}
    try:
        req, _created = access_desk.submit(employee_id, service, reason, access=access, kind=kind, blocked=blocked,
                                           task_id=node.id if node is not None else "", project_id=project_id,
                                           tree_path=tree_path)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    entry = next(q for q in req["requesters"] if q["employee"] == str(employee_id))

    if str(employee_id) in (COO_ID, EA_ID, CEO_ID):
        return {"status": "recorded", "request_id": req["id"],
                "message": "Recorded. You run the access desk: grant it (grant_access) or ask the CEO "
                           "(escalate_access_request) yourself."}

    brief = _coo_brief(req, employee_id)
    title = (f"Accès : {req['service']}" if _fr() else f"Access: {req['service']}")[:60]
    if tree_path and _is_task_node(node):
        from onemancompany.agents.tree_tools import dispatch_child

        result = dispatch_child.invoke({
            "target_employee_id": COO_ID,
            "description": brief,
            "acceptance_criteria": ["Access granted, provided by the CEO, or refused with a reason"],
            "title": title,
        })
        if result.get("status") in ("dispatched", "dispatched_waiting") and result.get("node_id"):
            access_desk.set_coo_node(req["id"], employee_id, result["node_id"])
            await access_desk.post_to_thread(project_id, employee_id, access_desk.thread_text("requested", req, entry))
            return {"status": "requested", "request_id": req["id"], "to": COO_ID,
                    "message": "Sent to the COO, in this project. End your turn now: this same task comes back "
                               "to you with the decision, and you carry on from where you stopped."}
        logger.warning("[access] dispatch to COO failed ({}), sending as a separate task", result.get("message"))

    from onemancompany.api.routes import _push_adhoc_task

    _push_adhoc_task(COO_ID, brief)
    return {"status": "requested", "request_id": req["id"], "to": COO_ID,
            "message": "Sent to the COO. The decision will come to you as a new task; carry on with what you can."}


# ---------------------------------------------------------------------------
# COO tools
# ---------------------------------------------------------------------------

def _brief(req: dict) -> dict:
    return {
        "request_id": req["id"], "service": req["service"], "status": req["status"],
        "requesters": [{"employee": q["employee"], "who": q.get("label"), "access": q.get("access"),
                        "kind": q.get("kind"), "status": q.get("status"), "reason": q.get("reason"),
                        "blocked": q.get("blocked")} for q in req.get("requesters") or []],
        "card_for_ceo": (req.get("card") or {}).get("what", ""),
        "updated_at": req.get("updated_at"),
    }


def _actor(employee_id: str) -> str:
    from onemancompany.core.config import COO_ID, EA_ID

    return {COO_ID: "COO", EA_ID: "EA"}.get(str(employee_id), str(employee_id) or "COO")


@tool
def list_access_requests(status: str = "active") -> dict:
    """List access requests from employees (the access desk you run as COO).

    Args:
        status: "active" (default: waiting for you or for the CEO), "open", "waiting_ceo",
            "done", "refused" or "all".
    """
    from onemancompany.core import access_desk

    items = access_desk.list_requests(status)
    for item in items:
        item["matching_tools"] = access_desk.matching_tools(item["service"])
    return {"requests": [{**_brief(r), "matching_tools": r["matching_tools"]} for r in items]}


@tool
async def grant_access(request_id: str, target_employee_id: str, tool_id: str, access: str = "read",
                       allowed_writes: list[str] | None = None, note: str = "", employee_id: str = "") -> dict:
    """Grant an existing company tool to an employee who asked for it (minimum rights).

    Works for API keys (with their command-line tool if any), MCP connectors
    and office tools. Reads are always included; ask yourself whether writes
    are really needed. The grant is traced (who, why, by whom, when).

    Args:
        request_id: The access request id.
        target_employee_id: The employee who asked.
        tool_id: The company tool to grant (from the request's matching tools,
            list_company_apis or list_tools).
        access: "read" (default) or "write".
        allowed_writes: API key tools only, optional: allow only these writes,
            e.g. ["POST /conversations/*/reply"] (with access="write").
        note: Optional note kept with the grant.
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.core import access_desk

    try:
        result = access_desk.grant(request_id, target_employee_id, tool_id, access=access,
                                   allowed_writes=allowed_writes, by=_actor(employee_id), note=note)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    if result["tool_type"] == "mcp":  # connectors load when the session starts
        from onemancompany.core.claude_session import stop_employee_daemons

        await stop_employee_daemons({str(target_employee_id)})
    await access_desk.reconcile()  # decided from another task: resume the one waiting
    req = result["request"]
    entry = next(q for q in req["requesters"] if q["employee"] == str(target_employee_id))
    return {"status": "granted", "request_id": request_id, "employee": target_employee_id, "tool_id": tool_id,
            "for_the_employee": access_desk.outcome_text(req, entry),
            "message": "Granted. Finish your task with the 'for_the_employee' line as your result."}


def _parse_auth(auth: str) -> dict:
    """"header:Authorization:Bearer {key}" | "header:X-API-KEY:{key}" | "query:api_key" | "path:/bot{key}"."""
    auth = (auth or "").strip()
    if not auth:
        return {}
    place, _, rest = auth.partition(":")
    place = place.strip().lower()
    if place == "header":
        name, _, fmt = rest.partition(":")
        return {"auth_in": "header", "auth_name": name.strip() or "Authorization", "auth_format": fmt.strip() or "{key}"}
    if place == "query":
        return {"auth_in": "query", "auth_name": rest.strip() or "api_key", "auth_format": "{key}"}
    if place == "path":
        return {"auth_in": "path", "auth_name": "", "auth_format": rest.strip() or "/{key}"}
    raise ValueError('auth must look like "header:Authorization:Bearer {key}", "query:api_key" or "path:/bot{key}"')


def _parse_cli(cli: str) -> dict | None:
    from onemancompany.core.cli_relay import PRESETS

    cli = (cli or "").strip()
    if not cli:
        return None
    if cli in PRESETS:
        return {"preset": cli}
    command, _, key_env = cli.partition(":")
    if not key_env:
        raise ValueError('For a CLI without preset, give "command:KEY_VARIABLE", e.g. "mycli:MYCLI_TOKEN"')
    return {"command": command.strip(), "key_env": key_env.strip()}


def _hold_current_task(request_id: str) -> bool:
    """Make the COO's current task wait for the CEO (resumed by the access desk)."""
    tree_path, _project_id, node = _task_context()
    if not tree_path or not _is_task_node(node):
        return False
    from onemancompany.core.task_tree import get_tree_lock, save_tree_async

    with get_tree_lock(tree_path):
        node.hold_reason = f"access_request={request_id},no_watchdog=1"
    save_tree_async(tree_path)
    return True


@tool
async def escalate_access_request(request_id: str, what_to_create: str, why: str, minimal_rights: str = "",
                            where_url: str = "", preset: str = "", base_url: str = "", auth: str = "",
                            docs_url: str = "", cli: str = "", existing_tool_id: str = "",
                            allowed_writes: list[str] | None = None, deliverable: str = "key",
                            employee_id: str = "") -> dict:
    """Ask the CEO to create what only they can create (key, token, account, invitation).

    The CEO gets a card in their "Access requests" box and only has to paste
    the key (or confirm the action). The key then becomes a company tool, the
    employees you validated on this request get access, and your task resumes.
    Write the texts in the CEO's language, short and concrete.

    Args:
        request_id: The access request id.
        what_to_create: What the CEO must create, e.g. "Un jeton d'API Scalingo".
        why: Who needs it and for what, in one or two sentences.
        minimal_rights: The smallest rights to pick when creating it
            (e.g. "lecture seule sur le dépôt id_picture : Contents, Actions").
        where_url: The page where the CEO creates it (a preset fills it).
        preset: "scalingo", "github", "n8n", "telegram" or "intercom" — fills the
            technical setup (API address, how the key is sent, CLI).
        base_url: API address when there is no preset (https://…), e.g. for n8n
            "https://n8n.example.com/api/v1".
        auth: How the key is sent when there is no preset: "header:Authorization:Bearer {key}"
            (default), "header:X-API-KEY:{key}", "query:api_key" or "path:/bot{key}".
        docs_url: API documentation link.
        cli: Command-line tool to unlock: "scalingo" or "gh", or "command:KEY_VARIABLE".
        existing_tool_id: The company tool exists but needs a new key (expired, revoked).
        allowed_writes: For employees asking for write access through the API: allow
            only these calls once the key is there, e.g. ["POST /sendMessage"]
            ("METHOD /path", * = any segment). Without it, write access means all writes.
        deliverable: "key" (default: the CEO pastes a key) or "action" (the CEO does
            something, e.g. sends an invitation, with nothing to paste).
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.core import access_desk

    try:
        setup = {"preset": preset.strip().lower(), "base_url": base_url, "docs_url": docs_url, **_parse_auth(auth)}
        parsed_cli = _parse_cli(cli)
        if parsed_cli:
            setup["cli"] = parsed_cli
        access_desk.escalate(request_id, what=what_to_create, why=why, where_url=where_url, rights=minimal_rights,
                             deliverable=deliverable, setup=setup, tool_id=existing_tool_id,
                             allowed_writes=allowed_writes, by=_actor(employee_id))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    req = access_desk.get_request(request_id) or {}
    for project_id, emp in {(q.get("project_id", ""), q["employee"]) for q in req.get("requesters") or []
                            if q.get("status") == "validated"}:
        await access_desk.post_to_thread(project_id, emp, access_desk.thread_text("escalated", req))
    if _hold_current_task(request_id):
        return {"status": "sent_to_ceo", "request_id": request_id,
                "message": "Card sent to the CEO. End your turn now: this task waits and ends by itself when the "
                           "CEO answers; the employee then carries on with their task."}
    return {"status": "sent_to_ceo", "request_id": request_id,
            "message": "Card sent to the CEO. The employees will be told when the CEO answers; you can finish."}


@tool
async def refuse_access(request_id: str, target_employee_id: str, reason: str, employee_id: str = "") -> dict:
    """Refuse an access request for one employee, with the reason they will read.

    Args:
        request_id: The access request id.
        target_employee_id: The employee who asked.
        reason: Why (and what they can do instead).
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.core import access_desk

    try:
        req = access_desk.refuse(request_id, target_employee_id, reason, by=_actor(employee_id))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    await access_desk.reconcile()  # decided from another task: resume the one waiting
    entry = next(q for q in req["requesters"] if q["employee"] == str(target_employee_id))
    return {"status": "refused", "for_the_employee": access_desk.outcome_text(req, entry),
            "message": "Refused. Finish your task with the 'for_the_employee' line as your result."}


EMPLOYEE_ACCESS_TOOLS = [request_access]
COO_ACCESS_TOOLS = [list_access_requests, grant_access, escalate_access_request, refuse_access]
