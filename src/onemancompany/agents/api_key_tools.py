"""Employee tools to use the company's API keys through the relay.

The key never reaches the employee: ``api_request`` asks the server to make
the call, which checks the CEO's rules, adds the key and returns the
response. Writes may need the CEO's approval.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.tools import tool


def _parse_json(value: Any) -> Any:
    if isinstance(value, str) and value.strip()[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


@tool
def list_company_apis(employee_id: str = "") -> dict:
    """List the APIs the CEO gave you access to (API keys you can use via api_request).

    Returns each API's id, base address, documentation link and what you are
    allowed to do (reads are always allowed; writes may be restricted or need
    the CEO's approval). You never receive the keys themselves.

    Args:
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.core.api_tools import granted_apis

    apis = granted_apis(employee_id)
    if not apis:
        return {"apis": [], "message": "No API access granted. Ask the CEO to add an API key in the Tools panel."}
    return {"apis": apis}


@tool
async def api_request(api: str, method: str, path: str, query: dict | str | None = None,
                      body: dict | list | str | None = None, employee_id: str = "") -> dict:
    """Call a company API (from list_company_apis) — the server adds the API key for you.

    Never ask for or handle API keys yourself. Only paths under the API's base
    address are allowed. Writes (POST/PUT/PATCH/DELETE) may be refused or put
    on hold until the CEO approves them; in that case you get a request_id —
    check it later with api_request_status.

    Args:
        api: API id from list_company_apis (e.g. "intercom_api").
        method: HTTP method: GET, POST, PUT, PATCH, DELETE.
        path: Path relative to the base address, e.g. "/conversations/123".
        query: Optional query parameters (object).
        body: Optional JSON body (object or array) for writes.
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.agents.common_tools import notify_ceo
    from onemancompany.core.api_tools import load_tool, request

    query = _parse_json(query)
    if query is not None and not isinstance(query, dict):
        return {"status": "error", "message": "query must be an object of query parameters"}
    body = _parse_json(body)
    result = await asyncio.to_thread(request, api, employee_id, method, path, query, body)
    if result.get("status") == "pending_approval":
        name = (load_tool(api) or {}).get("name", api)
        notify_ceo.invoke({
            "message": f"API call waiting for your approval: {method.upper()} {path} ({name}). "
                       f"Open Tools › {name} to approve or reject it.",
            "urgency": "high",
            "employee_id": employee_id,
        })
    return result


@tool
def api_request_status(request_id: str, employee_id: str = "") -> dict:
    """Check an API call that was waiting for the CEO's approval.

    Returns its status (pending, done, failed, rejected) and, once approved,
    the API response.

    Args:
        request_id: The request_id returned by api_request.
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.core.api_tools import find_request

    item = find_request(request_id)
    if not item or str(item.get("employee")) != str(employee_id):
        return {"status": "error", "message": "Unknown request_id"}
    out = {"request_id": request_id, "status": item["status"], "method": item["method"], "path": item["path"]}
    if item.get("result") is not None:
        out["result"] = item["result"]
    return out


API_KEY_TOOLS = [list_company_apis, api_request, api_request_status]
