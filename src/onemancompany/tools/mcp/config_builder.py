"""Build MCP config for Claude CLI sessions.

Generates a JSON config dict that tells Claude CLI to spawn the
OneManCompany MCP server as a stdio subprocess with the right
environment variables for tool context.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from onemancompany.core.config import (
    DATA_ROOT, ENV_OMC_DATA_ROOT, EMPLOYEES_DIR, ENV_OMC_EMPLOYEE_ID, ENV_OMC_PROJECT_DIR,
    ENV_OMC_PROJECT_ID, ENV_OMC_SERVER_URL, ENV_OMC_TASK_ID,
    MCP_CONFIG_FILENAME, TOOLS_DIR, WORKSPACE_DIR_NAME,
    write_text_utf,
)


def build_mcp_config(
    employee_id: str,
    task_id: str = "",
    project_id: str = "",
    project_dir: str = "",
    server_url: str = "http://localhost:8000",
) -> dict:
    """Build MCP config dict for Claude CLI.

    Returns a dict matching Claude's ``--mcp-config`` JSON format.
    Tool permissions are resolved dynamically by the MCP server via ToolRegistry.
    """
    python_path = sys.executable

    servers: dict = {
        "onemancompany": {
            "command": python_path,
            "args": ["-m", "onemancompany.tools.mcp.server"],
            "env": {
                ENV_OMC_EMPLOYEE_ID: employee_id,
                ENV_OMC_TASK_ID: task_id,
                ENV_OMC_PROJECT_ID: project_id,
                ENV_OMC_PROJECT_DIR: project_dir,
                ENV_OMC_SERVER_URL: server_url,
                ENV_OMC_DATA_ROOT: str(DATA_ROOT.resolve()),
            },
        },
    }

    # Add Gmail MCP server if employee has access and server script exists
    gmail_mcp = TOOLS_DIR / "gmail" / "mcp_server.py"
    if gmail_mcp.exists():
        servers["gmail"] = {
            "command": python_path,
            "args": [str(gmail_mcp)],
        }

    # FastSkills MCP — available to all employees with API key configured
    from onemancompany.core.config import settings
    if settings.skillsmp_api_key:
        emp_dir = EMPLOYEES_DIR / employee_id
        skills_dir = emp_dir / "skills"
        workdir = emp_dir / WORKSPACE_DIR_NAME
        servers["fastskills"] = {
            "command": "uvx",
            "args": [
                "fastskills",
                "--skills-dir", str(skills_dir),
                "--workdir", str(workdir),
            ],
            "env": {
                "SKILLSMP_API_KEY": settings.skillsmp_api_key,
            },
        }

    # MCP connectors installed as company tools (Tools panel), granted per employee
    from onemancompany.core.mcp_tools import servers_for
    for name, spec in servers_for(employee_id).items():
        servers.setdefault(name, spec)

    # Extra MCP servers the CEO granted in config.yaml (`mcp_servers`)
    servers.update(company_mcp_servers_for(employee_id, reserved=set(servers)))

    return {"mcpServers": servers}


_MCP_SPEC_KEYS = {"command", "args", "env", "type", "url", "headers", "cwd"}


def disallowed_mcp_tools_for(employee_id: str) -> list[str]:
    """Connector actions *employee_id* must not use (for ``--disallowedTools``)."""
    from onemancompany.core.config import load_app_config
    from onemancompany.core.mcp_tools import disallowed_for

    names = disallowed_for(employee_id)
    raw = load_app_config().get("mcp_servers") or {}
    if isinstance(raw, dict):
        for name, spec in raw.items():
            if not isinstance(spec, dict):
                continue
            employees = spec.get("employees")
            if employees is not None and str(employee_id) not in {str(e) for e in employees}:
                continue
            names += [f"mcp__{name}__{tool}" for tool in spec.get("disallowed_tools") or []]
    return names


def company_mcp_servers_for(employee_id: str, reserved: set[str] | None = None) -> dict:
    """MCP servers from config.yaml ``mcp_servers`` that *employee_id* may use.

    Each entry is a Claude ``--mcp-config`` server spec (command/args/env or
    type/url/headers) plus an optional ``employees`` list restricting it to
    specific employee IDs. Without ``employees`` the server is granted to
    every Claude Code employee.
    """
    from loguru import logger
    from onemancompany.core.config import load_app_config

    reserved = reserved or set()
    raw = load_app_config().get("mcp_servers") or {}
    if not isinstance(raw, dict):
        logger.warning("config.yaml mcp_servers must be a mapping; ignored")
        return {}

    granted: dict = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict) or name in reserved:
            if name in reserved:
                logger.warning("config.yaml mcp_servers: '{}' is reserved; ignored", name)
            continue
        employees = spec.get("employees")
        if employees is not None and str(employee_id) not in {str(e) for e in employees}:
            continue
        entry = {k: v for k, v in spec.items() if k in _MCP_SPEC_KEYS}
        if "command" not in entry and "url" not in entry:
            logger.warning("config.yaml mcp_servers: '{}' has no command or url; ignored", name)
            continue
        if "env" in entry:
            entry["env"] = {str(k): str(v) for k, v in (entry["env"] or {}).items()}
        granted[str(name)] = entry
    return granted


def write_mcp_config(
    employee_id: str,
    task_id: str = "",
    project_id: str = "",
    project_dir: str = "",
    server_url: str = "http://localhost:8000",
) -> Path:
    """Build and write MCP config to the employee's directory.

    Returns the path to the written config file.
    """
    config = build_mcp_config(employee_id, task_id, project_id, project_dir, server_url)
    config_path = EMPLOYEES_DIR / employee_id / MCP_CONFIG_FILENAME
    config_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_utf(config_path, json.dumps(config, indent=2))
    return config_path
