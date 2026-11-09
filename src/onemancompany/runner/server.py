"""Runner service: executes employee sessions on behalf of the control plane.

It holds no company secrets besides the two it needs (in its own secret
store): ``OMC_RUNNER_TOKEN`` to accept the control plane, and
``OMC_INTERNAL_KEY`` so the employees' tool bridge can sign its calls back
to the control plane. API keys and connector tokens stay on the control
plane (API relay; connector specs fetched per call by the launcher).

Run:  python -m onemancompany.runner --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger

from onemancompany.core.session_process import RUNNER_TOKEN_NAME, SESSIONS_PATH

app = FastAPI(title="OneManCompany runner")
_sessions: dict[int, asyncio.subprocess.Process] = {}


def _expected_token() -> str:
    from onemancompany.core.secret_store import get_secret_store

    return get_secret_store().get(RUNNER_TOKEN_NAME) or ""


def _authorized(header: str | None) -> bool:
    expected = _expected_token()
    given = (header or "").removeprefix("Bearer ").strip()
    return bool(expected and given) and hmac.compare_digest(expected, given)


@app.get("/v1/health")
async def health() -> dict:
    return {"status": "ok", "sessions": len(_sessions)}


async def _pump(stream: asyncio.StreamReader, key: str, ws: WebSocket) -> None:
    while True:
        line = await stream.readline()
        if not line:
            return
        await ws.send_text(json.dumps({key: line.decode("utf-8", errors="replace").rstrip("\n")}))


@app.websocket(SESSIONS_PATH)
async def session(ws: WebSocket) -> None:
    if not _authorized(ws.headers.get("authorization")):
        await ws.close(code=4401)
        return
    await ws.accept()
    from onemancompany.core.claude_session import SessionSpec
    from onemancompany.core.session_process import spawn_local

    try:
        first = json.loads(await ws.receive_text())
        spec = SessionSpec.from_dict(first.get("spec") or {})
        proc = await spawn_local(spec)
    except Exception as exc:
        logger.warning("[runner] cannot start session: {}", exc)
        await ws.send_text(json.dumps({"error": str(exc)[:500]}))
        await ws.close()
        return

    _sessions[proc.pid] = proc
    logger.info("[runner] started employee={} project={} pid={}", spec.employee_id, spec.project_id, proc.pid)
    await ws.send_text(json.dumps({"started": proc.pid}))
    pumps = [asyncio.create_task(_pump(proc.stdout, "stdout", ws)),
             asyncio.create_task(_pump(proc.stderr, "stderr", ws))]

    async def _from_client() -> None:
        while True:
            msg = json.loads(await ws.receive_text())
            if "stdin" in msg and proc.stdin:
                proc.stdin.write(str(msg["stdin"]).encode("utf-8") + b"\n")
                await proc.stdin.drain()
            elif msg.get("signal") == "terminate":
                proc.terminate()
            elif msg.get("signal") == "kill":
                proc.kill()

    client = asyncio.create_task(_from_client())
    try:
        await asyncio.wait([client, asyncio.create_task(proc.wait())], return_when=asyncio.FIRST_COMPLETED)
        if client.done() and not client.cancelled() and client.exception():
            logger.debug("[runner] client stream ended: {}", client.exception())
    except WebSocketDisconnect:
        logger.debug("[runner] control plane disconnected (pid={})", proc.pid)
    finally:
        if proc.returncode is None:  # control plane gone: stop the agent
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, TimeoutError):
                proc.kill()
        await asyncio.gather(*pumps, return_exceptions=True)
        client.cancel()
        _sessions.pop(proc.pid, None)
        try:
            await ws.send_text(json.dumps({"exit": proc.returncode}))
            await ws.close()
        except Exception as exc:  # already closed
            logger.debug("[runner] close after exit: {}", exc)
        logger.info("[runner] session pid={} exited ({})", proc.pid, proc.returncode)


def main(argv: list[str] | None = None) -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="python -m onemancompany.runner")
    parser.add_argument("--host", default=os.environ.get("RUNNER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RUNNER_PORT", "8100")))
    args = parser.parse_args(argv)
    if not _expected_token():
        raise SystemExit(f"{RUNNER_TOKEN_NAME} is not set (secret store or environment)")
    uvicorn.run(app, host=args.host, port=args.port, ws_max_size=32 * 1024 * 1024)
