"""Browser tools of the DSI: real web pages, and not one secret seen.

The browser runs in OneManCompany's server (core/browser.py), with a profile
of its own that keeps sessions. Pages come back as text with refs ([e12] for
what can be clicked or typed in, [t7] for text). Password fields never show a
value, and anything secret-looking reads [secret].

Passwords and 2FA codes are typed from the vault by OneManCompany's code, only
on the vault item's own site. A key or a 2FA secret shown on a page goes
straight into the vault or into a company API tool. What an agent may not do
(captcha, SMS code, payment, accepting terms for the company, the CEO's own
sign-in) is asked of the CEO, who does it in the live view of this browser.
"""

from __future__ import annotations

from langchain_core.tools import tool


def _svc():
    from onemancompany.core.browser import browser_service

    return browser_service


def _err(exc: Exception) -> dict:
    from onemancompany.core.browser import mask

    return {"status": "error", "message": mask(str(exc))[:600]}


async def _page(coro) -> dict:
    try:
        return {"status": "ok", "page": await coro}
    except Exception as exc:  # BrowserError, Playwright timeouts…
        return _err(exc)


def _actor(employee_id: str) -> str:
    from onemancompany.agents.access_tools import _actor as desk_actor

    return desk_actor(employee_id)


def _is_keeper(employee_id: str) -> bool:
    from onemancompany.core import access_desk

    return bool(employee_id) and access_desk.dsi_id() == str(employee_id)


@tool
async def browser_open(url: str, employee_id: str = "") -> dict:
    """Open a web page in your browser and read it (text with refs, secrets masked).

    Your browser keeps its sessions: sites where the CEO signed in for you stay
    signed in. Act on the page with the refs it shows ([e12]).

    Args:
        url: The address, e.g. "https://console.scaleway.com".
        employee_id: Your employee ID (auto-filled).
    """
    return await _page(_svc().open(employee_id, url))


@tool
async def browser_snapshot(employee_id: str = "") -> dict:
    """Read the current page again (after waiting, or when refs went stale).

    Args:
        employee_id: Your employee ID (auto-filled).
    """
    return await _page(_svc().snapshot(employee_id))


@tool
async def browser_click(ref: str, employee_id: str = "") -> dict:
    """Click an element of the page by its ref, then read the page.

    Args:
        ref: The ref from the last page reading, e.g. "e12".
        employee_id: Your employee ID (auto-filled).
    """
    return await _page(_svc().click(employee_id, ref))


@tool
async def browser_type(ref: str, text: str, submit: bool = False, employee_id: str = "") -> dict:
    """Type ordinary text in a field (an email address, a name, a search). Never a password.

    Password fields are refused: use browser_fill_secret, which types the value
    from the vault without anyone seeing it.

    Args:
        ref: The field's ref, e.g. "e4".
        text: What to type (replaces the field's content).
        submit: True to press Enter afterwards.
        employee_id: Your employee ID (auto-filled).
    """
    return await _page(_svc().type_text(employee_id, ref, text, submit))


@tool
async def browser_select(ref: str, option: str, employee_id: str = "") -> dict:
    """Choose an option in a drop-down list.

    Args:
        ref: The list's ref.
        option: The option's label (or value).
        employee_id: Your employee ID (auto-filled).
    """
    return await _page(_svc().select(employee_id, ref, option))


@tool
async def browser_press(key: str, employee_id: str = "") -> dict:
    """Press a key on the page: "Enter", "Tab", "Escape", "PageDown", "ArrowDown"…

    Args:
        key: The key name.
        employee_id: Your employee ID (auto-filled).
    """
    return await _page(_svc().press(employee_id, key))


@tool
async def browser_back(employee_id: str = "") -> dict:
    """Go back to the previous page.

    Args:
        employee_id: Your employee ID (auto-filled).
    """
    return await _page(_svc().back(employee_id))


@tool
async def browser_tabs(switch_to: int = 0, employee_id: str = "") -> dict:
    """List the tabs of your browser, or switch to one (a new tab opened by a site becomes the current one).

    Args:
        switch_to: Tab number to switch to (1 = first); 0 to only list them.
        employee_id: Your employee ID (auto-filled).
    """
    try:
        out = await _svc().tabs(employee_id, switch_to)
    except Exception as exc:
        return _err(exc)
    return {"status": "ok", **out}


@tool
async def browser_fill_secret(ref: str, item_id: str, field: str = "password", submit: bool = False,
                              employee_id: str = "") -> dict:
    """Type a value from the vault in a field: password, or the current 2FA code. Nobody sees it.

    Only on the vault item's own site (its sign-in address): on any other site
    it is refused. You may type the logins you created and those the CEO lets
    you use. For a new account, first add the login with vault_add_login (it
    generates the password), then fill it here (and in the confirmation field).

    Args:
        ref: The field's ref, e.g. "e7".
        item_id: The vault item (vault_list).
        field: "password" (default), or "totp" to type the current 2FA code.
        submit: True to press Enter afterwards.
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.core import browser, vault

    if field not in ("password", "totp"):
        return {"status": "error", "message": "field must be password or totp"}
    item = vault.get_item(item_id)
    if not item:
        return {"status": "error", "message": f"No vault item {item_id} (vault_list)"}
    site = browser.site_of(item.get("url", ""))
    if not site:
        return {"status": "error", "message": f"{item['name']!r} has no sign-in address: without it, the vault "
                                              f"cannot know where this login may be typed. Add the login again "
                                              f"with its url, or ask the CEO to fill it in (🔑 › Coffre)."}
    keeper = _is_keeper(employee_id)
    try:
        if field == "totp":
            value = vault.totp_code(item_id, employee_id=employee_id, purpose=f"browser: {site}", keeper=keeper)
        else:
            value = vault.use(item_id, "password", employee_id=employee_id, purpose=f"browser: {site}",
                              keeper=keeper)
        page = await _svc().fill_secret(employee_id, ref, value, site=site, submit=submit)
    except Exception as exc:
        return _err(exc)
    return {"status": "filled", "item": item["name"], "field": field, "page": page}


@tool
async def browser_save_secret(ref: str, item_id: str, field: str = "password", employee_id: str = "") -> dict:
    """Put a value shown on the page in the vault, without reading it: a password, a 2FA secret, a recovery code.

    For 2FA, when a site offers an authenticator app, pick "enter the key
    manually" and save that key with field="totp": from then on
    browser_fill_secret(field="totp") types the codes. The element can be a
    field or a text ([t12]) that contains the value.

    Args:
        ref: The element that shows the value.
        item_id: The vault item to store it in (vault_add_login first if needed).
        field: "password", "totp" (2FA secret) or "note" (recovery codes…).
        employee_id: Your employee ID (auto-filled).
    """
    import re

    from onemancompany.core import browser, vault

    if field not in vault.FIELDS:
        return {"status": "error", "message": f"field must be one of {', '.join(vault.FIELDS)}"}
    if not vault.get_item(item_id):
        return {"status": "error", "message": f"No vault item {item_id} (vault_list)"}
    try:
        raw, _site = await _svc().read_raw(employee_id, ref)
        if field == "totp":  # an otpauth:// link, or the key in groups ("JBSW Y3DP EHPK 3PXP")
            found = (re.search(r"otpauth://\S+", raw) or re.search(r"(?:[A-Z2-7]{4,}[ -]?){4,}", raw)
                     or re.search(r"(?:[a-z2-7]{4,}[ -]?){4,}", raw))
            value = found.group().strip() if found else raw.strip()
        elif field == "note":
            value = raw.strip()
        else:
            value = browser.pick_secret(raw)
        if not value:
            return {"status": "error", "message": f"{ref} shows nothing to save"}
        vault.set_secret(item_id, field, value, by=_actor(employee_id))
    except Exception as exc:
        return _err(exc)
    return {"status": "saved", "item_id": item_id, "field": field, "length": len(value),
            "message": "Stored in the vault; nobody saw it."}


@tool
async def browser_save_key(ref: str, request_id: str, preset: str = "", base_url: str = "", auth: str = "",
                           docs_url: str = "", cli: str = "", what: str = "", employee_id: str = "") -> dict:
    """Turn an API key shown on the page into the company tool an access request is waiting for.

    Use it after creating the key yourself in the service's console. The key
    goes to the company's secret store (nobody sees it), becomes a tool used
    through the relay, and the employees on the request get access: the same
    outcome as the CEO pasting it in their 🔑 box, without bothering them.
    The setup says how the relay uses the key (a request the CEO already has a
    card for keeps the card's setup).

    Args:
        ref: The element that shows the new key.
        request_id: The access request (list_access_requests).
        preset: "scalingo", "github", "n8n", "telegram" or "intercom" (fills the setup).
        base_url: API address when there is no preset, e.g. "https://api.scaleway.com".
        auth: How the key is sent: "header:Authorization:Bearer {key}" (default),
            "header:X-Auth-Token:{key}", "query:api_key" or "path:/bot{key}".
        docs_url: API documentation link.
        cli: Command-line tool to unlock: "scalingo" or "gh", or "command:KEY_VARIABLE".
        what: What the key is, e.g. "Clé d'API Scaleway, projet Photonet, lecture seule".
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.agents.access_tools import _parse_auth, _parse_cli
    from onemancompany.agents.coo_agent import _load_assets_from_disk
    from onemancompany.core import access_desk, browser

    try:
        raw, _site = await _svc().read_raw(employee_id, ref)
        key = browser.pick_secret(raw)
        if not key:
            return {"status": "error", "message": f"{ref} shows no key"}
        setup = {"preset": preset.strip().lower(), "base_url": base_url, "docs_url": docs_url, **_parse_auth(auth)}
        parsed_cli = _parse_cli(cli)
        if parsed_cli:
            setup["cli"] = parsed_cli
        req, tool_id = access_desk.provide_by_desk(request_id, key, setup=setup, what=what, by=_actor(employee_id))
    except Exception as exc:
        return _err(exc)
    _load_assets_from_disk()
    await access_desk.reconcile()  # tasks waiting on this request (a card the CEO had) resume
    lines = {q["employee"]: access_desk.outcome_text(req, q) for q in req.get("requesters") or []
             if q.get("status") == "granted"}
    return {"status": "provided", "tool_id": tool_id, "for_the_employees": lines,
            "message": "The key is a company tool now; nobody saw it. If this task is the request's desk task, "
                       "finish it with the line for the employee."}


@tool
async def browser_ask_ceo(what: str, employee_id: str = "") -> dict:
    """Ask the CEO to do a step in your browser that an agent may not do.

    Captcha, code received by SMS or e-mail on the CEO's phone or mailbox,
    payment, accepting terms of service for the company, identity check, the
    CEO's own sign-in to an admin account. The CEO gets a card in the 🔑 box,
    opens your browser where you left it and does the step. You are told when
    it is done: carry on with other work, or finish your turn.

    Args:
        what: The step, in the CEO's language, e.g. "Te connecter à ton compte OVH (connexion à deux facteurs)".
        employee_id: Your employee ID (auto-filled).
    """
    from onemancompany.core import browser

    try:
        url = await _svc().current_url(employee_id)
        ask = browser.add_ask(employee_id, what, url)
    except Exception as exc:
        return _err(exc)
    from onemancompany.core.events import CompanyEvent, event_bus
    from onemancompany.core.models import EventType

    await event_bus.publish(CompanyEvent(type=EventType.ACCESS_REQUEST_UPDATE, agent="DSI",
                                         payload={"browser_ask": ask["id"], "new_card": True, "service": ask["what"][:80]}))
    return {"status": "asked", "ask_id": ask["id"],
            "message": "The CEO sees it in the 🔑 box and does it in your browser. You will be told when it is "
                       "done; do not wait in a loop."}


BROWSER_TOOLS = [browser_open, browser_snapshot, browser_click, browser_type, browser_select, browser_press,
                 browser_back, browser_tabs, browser_fill_secret, browser_save_secret, browser_save_key,
                 browser_ask_ceo]
