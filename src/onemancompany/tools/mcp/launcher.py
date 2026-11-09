"""Launch MCP servers for employee sessions without exposing secrets.

Claude CLI starts every MCP server listed in the employee's MCP config. That
file lives in the employee's folder and the CLI process environment is
stripped of secrets, so neither may contain API keys. Instead each server is
started through this launcher, which reads secrets from the secret store
only inside the server process:

    python -m onemancompany.tools.mcp.launcher internal -- <command> [args...]
        OneManCompany's own servers: run with the company secrets in env.

    python -m onemancompany.tools.mcp.launcher connector <tool_id>
        A connector from the Tools panel. stdio connectors are exec'd with
        their resolved env; http/sse connectors are bridged to stdio here, so
        the Authorization header never leaves this process.

The launcher needs OMC_DATA_ROOT (set by the config builder) to find the
company data directory.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys


def _company_secrets() -> dict[str, str]:
    from onemancompany.core.secret_store import get_secret_store

    store = get_secret_store()
    return {name: value for name in store.names() if (value := store.get(name))}


def _exec(command: str, args: list[str], extra_env: dict[str, str], cwd: str | None = None) -> None:
    env = {**os.environ, **extra_env}
    if cwd:
        os.chdir(cwd)
    path = shutil.which(command, path=env.get("PATH")) or command
    os.execvpe(path, [command, *args], env)


async def _bridge(spec: dict) -> None:
    """Expose a remote (http/sse) MCP server over stdio, adding its headers."""
    from mcp import ClientSession
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    from mcp import types

    transport = spec.get("type") or "http"
    headers = spec.get("headers") or None
    if transport == "sse":
        from mcp.client.sse import sse_client

        client_ctx = sse_client(spec["url"], headers=headers)
    else:
        from mcp.client.streamable_http import streamablehttp_client

        client_ctx = streamablehttp_client(spec["url"], headers=headers)

    async with client_ctx as streams:
        async with ClientSession(streams[0], streams[1]) as remote:
            init = await remote.initialize()
            server = Server(getattr(init.serverInfo, "name", "connector") or "connector")

            @server.list_tools()
            async def _list_tools() -> list[types.Tool]:
                return (await remote.list_tools()).tools

            @server.call_tool(validate_input=False)
            async def _call_tool(name: str, arguments: dict) -> types.CallToolResult:
                # Pass the remote result through unchanged (content, structured
                # output and error flag) so output schemas still validate.
                return await remote.call_tool(name, arguments or {})

            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())


def _fetch_connector_spec(tool_id: str) -> dict:
    import httpx

    from onemancompany.core.config import ENV_OMC_EMPLOYEE_ID, ENV_OMC_SERVER_URL
    from onemancompany.core.secret_store import CALLER_HEADER, caller_signature

    employee_id = os.environ.get(ENV_OMC_EMPLOYEE_ID, "")
    url = os.environ.get(ENV_OMC_SERVER_URL, "http://localhost:8000").rstrip("/")
    resp = httpx.post(f"{url}/api/internal/connector-spec", timeout=30,
                      headers={CALLER_HEADER: caller_signature(employee_id)},
                      json={"employee_id": employee_id, "tool_id": tool_id})
    if resp.status_code != 200:
        sys.exit(f"launcher: connector {tool_id} refused ({resp.status_code})")
    return resp.json()["mcp"]


def main(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[0] == "internal" and "--" in argv:
        command = argv[argv.index("--") + 1:]
        if not command:
            sys.exit("launcher: missing command")
        _exec(command[0], command[1:], _company_secrets())
        return

    if len(argv) == 2 and argv[0] == "connector":
        if os.environ.get("OMC_REMOTE_CONNECTORS") == "1":
            # On a runner: the connector's keys stay on the control plane,
            # which hands the resolved spec to this employee's signed request.
            spec = _fetch_connector_spec(argv[1])
        else:
            from onemancompany.core.mcp_tools import load_tool, resolve_placeholders

            data = load_tool(argv[1]) or {}
            spec = data.get("mcp")
            if data.get("type") != "mcp" or not isinstance(spec, dict):
                sys.exit(f"launcher: unknown connector {argv[1]}")
            spec = resolve_placeholders(dict(spec))
        if spec.get("url"):
            asyncio.run(_bridge(spec))
        else:
            command = str(spec["command"])
            if os.environ.get("OMC_REMOTE_CONNECTORS") == "1" and os.path.isabs(command) and not os.path.exists(command):
                # A path from the control plane's machine (e.g. a Mac's node):
                # use the runner's own interpreter of the same name.
                spec["command"] = os.path.basename(command)
            env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
            _exec(str(spec["command"]), [str(a) for a in spec.get("args", [])], env, spec.get("cwd"))
        return

    sys.exit("usage: launcher internal -- <command...> | launcher connector <tool_id>")


if __name__ == "__main__":
    main(sys.argv[1:])
