"""MCP connectors as company tools ("equipment").

An MCP connector is an asset tool folder with a ``tool.yaml`` of
``type: mcp``::

    id: stripe
    name: Stripe
    type: mcp
    description: ...
    mcp:                       # Claude --mcp-config server spec
      type: http
      url: https://mcp.stripe.com
      headers: {Authorization: "Bearer ${STRIPE_API_KEY}"}
    env_vars:                  # secrets, edited in the tool UI, stored in .env
      - {name: STRIPE_API_KEY, label: API key, secret: true}
    allowed_users: []          # nobody until the CEO grants access
    disallowed_tools: [create_refund]
    available_tools: [{name: ..., description: ...}]   # filled by "Test"

Claude Code employees listed in ``allowed_users`` get the connector in their
sessions; ``disallowed_tools`` are passed to ``--disallowedTools``.
Secrets never live in tool.yaml: ``${VAR}`` placeholders are resolved from
the environment / ``.onemancompany/.env`` when a session starts.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

TOOL_TYPE_MCP = "mcp"
RESERVED_SERVER_NAMES = {"onemancompany", "gmail", "fastskills"}
PROBE_TIMEOUT_SECONDS = 45

# Actions blocked by default: anything that moves money, contacts someone,
# deletes or changes data irreversibly.
SENSITIVE_TOOL_RE = re.compile(
    r"refund|payment|payout|charge|transfer|invoice|subscription|price|"
    r"delete|remove|destroy|cancel|void|archive|close|"
    r"send|reply|message|email|post|publish|comment|"
    r"create|update|write|edit|merge|push|upload|reupload|plate|apply|reject|"
    r"operator",
    re.IGNORECASE,
)

_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# ---------------------------------------------------------------------------
# Catalog of ready-made connectors (verified against vendor docs, 2026-11)
# ---------------------------------------------------------------------------

CATALOG: list[dict[str, Any]] = [
    {
        "id": "stripe",
        "name": "Stripe",
        "description": "Stripe payments: customers, subscriptions, invoices, refunds.",
        "mcp": {"type": "http", "url": "https://mcp.stripe.com",
                "headers": {"Authorization": "Bearer ${STRIPE_API_KEY}"}},
        "env_vars": [{"name": "STRIPE_API_KEY", "label": "Stripe API key (a restricted key is recommended)",
                      "secret": True, "placeholder": "rk_live_..."}],
        "help_url": "https://dashboard.stripe.com/apikeys",
    },
    {
        "id": "intercom",
        "name": "Intercom",
        "description": "Intercom customer support (US workspace): conversations, contacts, articles, internal notes.",
        "mcp": {"type": "http", "url": "https://mcp.intercom.com/mcp",
                "headers": {"Authorization": "Bearer ${INTERCOM_ACCESS_TOKEN}"}},
        "env_vars": [{"name": "INTERCOM_ACCESS_TOKEN", "label": "Intercom access token",
                      "secret": True, "placeholder": "dG9rOj..."}],
        "help_url": "https://developers.intercom.com/docs/build-an-integration/learn-more/authentication",
    },
    {
        "id": "intercom_eu",
        "name": "Intercom (EU)",
        "description": "Intercom customer support (EU-hosted workspace): conversations, contacts, articles, internal notes.",
        "mcp": {"type": "http", "url": "https://mcp.eu.intercom.com/mcp",
                "headers": {"Authorization": "Bearer ${INTERCOM_ACCESS_TOKEN}"}},
        "env_vars": [{"name": "INTERCOM_ACCESS_TOKEN", "label": "Intercom access token",
                      "secret": True, "placeholder": "dG9rOj..."}],
        "help_url": "https://developers.intercom.com/docs/build-an-integration/learn-more/authentication",
    },
    {
        "id": "github",
        "name": "GitHub",
        "description": "GitHub repositories, issues and pull requests.",
        "mcp": {"type": "http", "url": "https://api.githubcopilot.com/mcp/",
                "headers": {"Authorization": "Bearer ${GITHUB_PAT}"}},
        "env_vars": [{"name": "GITHUB_PAT", "label": "GitHub personal access token",
                      "secret": True, "placeholder": "github_pat_..."}],
        "help_url": "https://github.com/settings/personal-access-tokens",
    },
    {
        "id": "notion",
        "name": "Notion",
        "description": "Notion pages and databases shared with the integration.",
        "mcp": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"],
                "env": {"NOTION_TOKEN": "${NOTION_TOKEN}"}},
        "env_vars": [{"name": "NOTION_TOKEN", "label": "Notion integration secret",
                      "secret": True, "placeholder": "ntn_..."}],
        "help_url": "https://www.notion.so/profile/integrations",
    },
    {
        "id": "hubspot",
        "name": "HubSpot",
        "description": "HubSpot CRM: contacts, companies, deals.",
        "mcp": {"command": "npx", "args": ["-y", "@hubspot/mcp-server"],
                "env": {"PRIVATE_APP_ACCESS_TOKEN": "${HUBSPOT_ACCESS_TOKEN}"}},
        "env_vars": [{"name": "HUBSPOT_ACCESS_TOKEN", "label": "HubSpot private app access token",
                      "secret": True, "placeholder": "pat-eu1-..."}],
        "help_url": "https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tools_dir() -> Path:
    from onemancompany.core.config import TOOLS_DIR

    return TOOLS_DIR


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "connector"


def _env_values() -> dict[str, str]:
    from dotenv import dotenv_values

    from onemancompany.core.config import DATA_ROOT, DOT_ENV_FILENAME

    values = {k: v for k, v in dotenv_values(DATA_ROOT / DOT_ENV_FILENAME).items() if v is not None}
    values.update({k: v for k, v in os.environ.items() if v})
    return values


def resolve_placeholders(value: Any, env: dict[str, str] | None = None) -> Any:
    """Replace ${VAR} in strings (recursively) with values from the environment."""
    env = _env_values() if env is None else env
    if isinstance(value, str):
        return _PLACEHOLDER_RE.sub(lambda m: env.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [resolve_placeholders(v, env) for v in value]
    if isinstance(value, dict):
        return {k: resolve_placeholders(v, env) for k, v in value.items()}
    return value


def missing_secrets(data: dict) -> list[str]:
    env = _env_values()
    names = set(_PLACEHOLDER_RE.findall(json.dumps(data.get("mcp") or {})))
    return sorted(n for n in names if not env.get(n))


def save_env_values(values: dict[str, str]) -> None:
    """Persist secrets to .onemancompany/.env and the current process."""
    from onemancompany.core.config import DATA_ROOT, DOT_ENV_FILENAME, read_text_utf, write_text_utf

    values = {k: v for k, v in values.items() if v}
    if not values:
        return
    for k, v in values.items():
        os.environ[k] = v
    env_path = DATA_ROOT / DOT_ENV_FILENAME
    lines = read_text_utf(env_path).splitlines() if env_path.exists() else []
    done = set()
    for i, line in enumerate(lines):
        for k, v in values.items():
            if line.startswith(f"{k}="):
                lines[i] = f"{k}={v}"
                done.add(k)
    lines += [f"{k}={v}" for k, v in values.items() if k not in done]
    write_text_utf(env_path, "\n".join(lines) + "\n")


def load_tool(tool_id: str) -> dict | None:
    path = _tools_dir() / tool_id / "tool.yaml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def save_tool(tool_id: str, data: dict) -> None:
    from onemancompany.core.store import mark_dirty, DirtyCategory

    path = _tools_dir() / tool_id / "tool.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False), encoding="utf-8")
    mark_dirty(DirtyCategory.TOOLS)


def list_mcp_tools() -> dict[str, dict]:
    tools: dict[str, dict] = {}
    root = _tools_dir()
    if not root.exists():
        return tools
    for entry in sorted(root.iterdir()):
        path = entry / "tool.yaml"
        if not entry.is_dir() or not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("Invalid tool.yaml in {}: {}", entry.name, exc)
            continue
        if data.get("type") == TOOL_TYPE_MCP and isinstance(data.get("mcp"), dict):
            tools[entry.name] = data
    return tools


def _granted(data: dict, employee_id: str) -> bool:
    allowed = data.get("allowed_users")
    # Connectors are opt-in: no list means nobody
    return isinstance(allowed, list) and str(employee_id) in {str(u) for u in allowed}


# ---------------------------------------------------------------------------
# Session integration
# ---------------------------------------------------------------------------

def servers_for(employee_id: str) -> dict[str, dict]:
    """Resolved --mcp-config specs of the connectors granted to *employee_id*."""
    env = _env_values()
    servers: dict[str, dict] = {}
    for tool_id, data in list_mcp_tools().items():
        if tool_id in RESERVED_SERVER_NAMES or not _granted(data, employee_id):
            continue
        servers[tool_id] = resolve_placeholders(dict(data["mcp"]), env)
    return servers


def disallowed_for(employee_id: str) -> list[str]:
    """Fully qualified tool names to pass to ``--disallowedTools``."""
    names: list[str] = []
    for tool_id, data in list_mcp_tools().items():
        if not _granted(data, employee_id):
            continue
        for tool in effective_disallowed(data, employee_id):
            names.append(f"mcp__{tool_id}__{tool}")
    return names


def effective_disallowed(data: dict, employee_id: str) -> list[str]:
    """Blocked actions for one employee: personal list if set, else the tool's."""
    personal = (data.get("employee_actions") or {}).get(str(employee_id))
    if isinstance(personal, dict) and isinstance(personal.get("disallowed_tools"), list):
        return list(personal["disallowed_tools"])
    return list(data.get("disallowed_tools") or [])


# ---------------------------------------------------------------------------
# Creating connectors
# ---------------------------------------------------------------------------

def _unique_id(base: str) -> str:
    base = slugify(base)
    if base in RESERVED_SERVER_NAMES:
        base = f"{base}_mcp"
    candidate, n = base, 2
    while (_tools_dir() / candidate).exists():
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def create_connector(name: str, mcp: dict, *, description: str = "", env_vars: list[dict] | None = None,
                     secrets: dict[str, str] | None = None, source: str = "custom",
                     help_url: str = "", tool_id: str = "") -> str:
    """Create an MCP connector tool folder. Returns the tool id."""
    if not (mcp.get("command") or mcp.get("url")):
        raise ValueError("A connector needs a command or a URL")
    tool_id = _unique_id(tool_id or name)
    data: dict[str, Any] = {
        "id": tool_id,
        "name": name,
        "description": description or f"MCP connector {name}",
        "added_by": "CEO",
        "type": TOOL_TYPE_MCP,
        "sprite": "desk_equipment",
        "source": source,
        "mcp": mcp,
        "allowed_users": [],
    }
    if env_vars:
        data["env_vars"] = env_vars
        if help_url:
            data["env_vars"][0] = {**data["env_vars"][0], "credentials_help": {"text": "", "url": help_url}}
    save_env_values(secrets or {})
    save_tool(tool_id, data)
    logger.info("Created MCP connector {} ({})", tool_id, source)
    return tool_id


def create_from_catalog(catalog_id: str, secrets: dict[str, str] | None = None) -> str:
    entry = next((c for c in CATALOG if c["id"] == catalog_id), None)
    if entry is None:
        raise ValueError(f"Unknown catalog connector: {catalog_id}")
    return create_connector(
        entry["name"], json.loads(json.dumps(entry["mcp"])), description=entry["description"],
        env_vars=[dict(v) for v in entry["env_vars"]], secrets=secrets, source="catalog",
        help_url=entry.get("help_url", ""), tool_id=entry["id"],
    )


def parse_custom(text: str) -> dict:
    """Turn a pasted URL or command line into an MCP server spec."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Paste a URL or a command")
    if re.match(r"^https?://", text):
        url = text.split()[0]
        return {"type": "sse" if url.rstrip("/").endswith("/sse") else "http", "url": url}
    if text.startswith("{"):
        spec = json.loads(text)
        if "mcpServers" in spec and isinstance(spec["mcpServers"], dict) and len(spec["mcpServers"]) == 1:
            spec = next(iter(spec["mcpServers"].values()))
        return spec
    parts = shlex.split(text)
    env: dict[str, str] = {}
    while parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", parts[0]):
        k, v = parts.pop(0).split("=", 1)
        env[k] = v
    if not parts:
        raise ValueError("Empty command")
    spec: dict[str, Any] = {"command": parts[0], "args": parts[1:]}
    if env:
        spec["env"] = env
    return spec


def _extract_secrets(tool_id: str, mcp: dict) -> tuple[dict, dict[str, str], list[dict]]:
    """Move env values and header values out of the spec into .env placeholders."""
    mcp = json.loads(json.dumps(mcp))
    secrets: dict[str, str] = {}
    env_vars: list[dict] = []
    prefix = f"OMC_MCP_{tool_id.upper()}_"
    for key in ("env", "headers"):
        block = mcp.get(key) or {}
        for name, value in list(block.items()):
            value = str(value)
            if not value or _PLACEHOLDER_RE.fullmatch(value):
                continue
            var = prefix + re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
            secrets[var] = value
            block[name] = "${" + var + "}"
            env_vars.append({"name": var, "label": f"{name} ({key})", "secret": True})
        if block:
            mcp[key] = block
    return mcp, secrets, env_vars


def create_custom(name: str, text: str, description: str = "") -> str:
    mcp = parse_custom(text)
    tool_id = _unique_id(name)
    mcp, secrets, env_vars = _extract_secrets(tool_id, mcp)
    return create_connector(name, mcp, description=description, env_vars=env_vars or None,
                            secrets=secrets, source="custom", tool_id=tool_id)


# ---------------------------------------------------------------------------
# Reusing the CEO's Claude Code connectors
# ---------------------------------------------------------------------------

def _claude_json_path() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home()))) / ".claude.json"


def _read_claude_servers() -> dict[str, dict]:
    path = _claude_json_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Cannot read {}: {}", path, exc)
        return {}
    servers = data.get("mcpServers") or {}
    return {k: v for k, v in servers.items() if isinstance(v, dict)}


def claude_code_servers() -> list[dict]:
    """The CEO's user-level Claude Code MCP servers (no secret values exposed)."""
    installed = {d.get("source_name") for d in list_mcp_tools().values() if d.get("source") == "claude_code"}
    result = []
    for name, spec in sorted(_read_claude_servers().items()):
        transport = spec.get("type") or ("http" if spec.get("url") else "stdio")
        if spec.get("url"):
            summary = spec["url"]
        else:
            summary = " ".join([Path(str(spec.get("command", ""))).name, *[Path(str(a)).name for a in spec.get("args", [])[:2]]])
        result.append({
            "name": name,
            "transport": transport,
            "summary": summary.strip(),
            "has_secrets": bool(spec.get("env") or spec.get("headers")),
            "installed": name in installed,
        })
    return result


def import_claude_code_server(name: str) -> str:
    spec = _read_claude_servers().get(name)
    if spec is None:
        raise ValueError(f"Claude Code connector not found: {name}")
    keys = {"type", "command", "args", "env", "url", "headers", "cwd"}
    mcp = {k: v for k, v in spec.items() if k in keys}
    tool_id = _unique_id(name)
    mcp, secrets, env_vars = _extract_secrets(tool_id, mcp)
    tool_id = create_connector(name.replace("_", " ").replace("-", " ").title(), mcp,
                               description=f"MCP connector \"{name}\" imported from Claude Code.",
                               env_vars=env_vars or None, secrets=secrets, source="claude_code", tool_id=tool_id)
    data = load_tool(tool_id) or {}
    data["source_name"] = name
    save_tool(tool_id, data)
    return tool_id


# ---------------------------------------------------------------------------
# Access & testing
# ---------------------------------------------------------------------------

def update_access(tool_id: str, allowed_users: list[str] | None = None,
                  disallowed_tools: list[str] | None = None,
                  employee_actions: dict[str, list[str] | None] | None = None) -> dict:
    """Update who may use a connector and which actions are blocked.

    ``employee_actions`` maps an employee id to their personal blocked list,
    or to None to fall back to the tool's shared list.
    """
    data = load_tool(tool_id)
    if not data or data.get("type") != TOOL_TYPE_MCP:
        raise ValueError("Not an MCP connector")
    if allowed_users is not None:
        data["allowed_users"] = sorted({str(u) for u in allowed_users})
    if disallowed_tools is not None:
        data["disallowed_tools"] = sorted({str(t) for t in disallowed_tools})
    if employee_actions is not None:
        personal = dict(data.get("employee_actions") or {})
        for emp_id, blocked in employee_actions.items():
            if blocked is None:
                personal.pop(str(emp_id), None)
            else:
                personal[str(emp_id)] = {"disallowed_tools": sorted({str(t) for t in blocked})}
        if personal:
            data["employee_actions"] = personal
        else:
            data.pop("employee_actions", None)
    save_tool(tool_id, data)
    return data


async def _list_remote_tools(spec: dict) -> list[dict]:
    from mcp import ClientSession, StdioServerParameters

    transport = spec.get("type") or ("http" if spec.get("url") else "stdio")
    if transport == "stdio":
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=spec["command"], args=[str(a) for a in spec.get("args", [])],
            env={**os.environ, **{k: str(v) for k, v in (spec.get("env") or {}).items()}},
            cwd=spec.get("cwd"),
        )
        ctx = stdio_client(params)
    elif transport == "sse":
        from mcp.client.sse import sse_client

        ctx = sse_client(spec["url"], headers=spec.get("headers") or None)
    else:
        from mcp.client.streamable_http import streamablehttp_client

        ctx = streamablehttp_client(spec["url"], headers=spec.get("headers") or None)

    async with ctx as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            return [{"name": t.name, "description": (t.description or "").strip().split("\n")[0][:200]}
                    for t in listed.tools]


async def probe(tool_id: str) -> dict:
    """Connect to the connector, list its actions and store them.

    On the first successful test, sensitive actions are blocked by default.
    """
    data = load_tool(tool_id)
    if not data or data.get("type") != TOOL_TYPE_MCP:
        raise ValueError("Not an MCP connector")
    missing = missing_secrets(data)
    if missing:
        return {"ok": False, "error": "Missing key: " + ", ".join(missing), "tools": []}
    spec = resolve_placeholders(dict(data["mcp"]))
    try:
        tools = await asyncio.wait_for(_list_remote_tools(spec), timeout=PROBE_TIMEOUT_SECONDS)
    except Exception as exc:  # report any connection failure to the CEO
        message = str(exc) or type(exc).__name__
        if hasattr(exc, "exceptions") and exc.exceptions:  # ExceptionGroup from anyio
            message = str(exc.exceptions[0]) or type(exc.exceptions[0]).__name__
        logger.warning("MCP probe failed for {}: {}", tool_id, message)
        return {"ok": False, "error": message[:300], "tools": []}

    data["available_tools"] = tools
    if "disallowed_tools" not in data:
        data["disallowed_tools"] = sorted(t["name"] for t in tools if SENSITIVE_TOOL_RE.search(t["name"]))
    save_tool(tool_id, data)
    return {"ok": True, "tools": tools, "disallowed_tools": data["disallowed_tools"]}
