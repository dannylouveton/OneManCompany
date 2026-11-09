"""Where employee sessions run: on this machine, or on a remote runner.

The control plane (web UI, secrets, API relay, approvals) and the execution of
agents can be split. ``spawn_session`` returns a process-like object with the
same surface as ``asyncio.subprocess.Process`` (stdin.write/drain,
stdout/stderr.readline, returncode, pid, terminate/kill/wait), so
``ClaudeDaemon`` does not care where the agent runs.

config.yaml::

    runner:
      url: ws://127.0.0.1:8100     # omit for local execution (default)

The runner token is stored in the secret store as ``OMC_RUNNER_TOKEN``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

RUNNER_TOKEN_NAME = "OMC_RUNNER_TOKEN"
SESSIONS_PATH = "/v1/sessions"


def runner_url() -> str:
    from onemancompany.core.config import load_app_config

    cfg = load_app_config().get("runner") or {}
    return str(cfg.get("url") or "").rstrip("/") if isinstance(cfg, dict) else ""


async def spawn_session(spec) -> Any:
    url = runner_url()
    if url:
        from onemancompany.core.secret_store import get_secret_store

        token = get_secret_store().get(RUNNER_TOKEN_NAME) or ""
        if not token:
            raise RuntimeError("runner.url is set but OMC_RUNNER_TOKEN is missing from the secret store")
        return await RemoteSessionProcess.connect(url + SESSIONS_PATH, token, spec.to_dict())
    return await spawn_local(spec)


async def spawn_local(spec) -> asyncio.subprocess.Process:
    from onemancompany.core.claude_session import prepare_session

    cmd, env, cwd = await prepare_session(spec)
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        limit=16 * 1024 * 1024,  # stream-json lines can be large
    )


# ---------------------------------------------------------------------------
# Remote process over a WebSocket
# ---------------------------------------------------------------------------
# Protocol (JSON text frames):
#   client → runner: {"spec": {...}} first, then {"stdin": "<line>"} or
#                    {"signal": "terminate" | "kill"}
#   runner → client: {"started": pid}, {"stdout": "<line>"}, {"stderr": "<line>"},
#                    {"exit": code}, {"error": "<message>"}


class _Reader:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._eof = False

    def feed(self, line: str) -> None:
        self._queue.put_nowait(line.encode("utf-8") + b"\n")

    def feed_eof(self) -> None:
        if not self._eof:
            self._eof = True
            self._queue.put_nowait(b"")

    async def readline(self) -> bytes:
        line = await self._queue.get()
        if line == b"":
            self._queue.put_nowait(b"")  # stay at EOF for later readers
        return line


class _Writer:
    def __init__(self, proc: "RemoteSessionProcess") -> None:
        self._proc = proc
        self._buffer = b""

    def write(self, data: bytes) -> None:
        self._buffer += data

    async def drain(self) -> None:
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            await self._proc._send({"stdin": line.decode("utf-8", errors="replace")})


class RemoteSessionProcess:
    remote = True

    def __init__(self, ws) -> None:
        self._ws = ws
        self.stdin = _Writer(self)
        self.stdout = _Reader()
        self.stderr = _Reader()
        self.pid: int | None = None
        self.returncode: int | None = None
        self._exited = asyncio.Event()
        self._pump: asyncio.Task | None = None

    @classmethod
    async def connect(cls, url: str, token: str, spec: dict) -> "RemoteSessionProcess":
        import websockets

        ws = await websockets.connect(
            url, additional_headers={"Authorization": f"Bearer {token}"},
            max_size=32 * 1024 * 1024, open_timeout=15, ping_interval=20,
        )
        proc = cls(ws)
        await ws.send(json.dumps({"spec": spec}))
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
        if "error" in first:
            await ws.close()
            raise RuntimeError(f"Runner refused the session: {first['error']}")
        proc.pid = first.get("started")
        proc._pump = asyncio.create_task(proc._read_loop())
        logger.info("[runner] session started remotely (employee={}, remote pid={})", spec.get("employee_id"), proc.pid)
        return proc

    async def _send(self, payload: dict) -> None:
        if self.returncode is not None:
            raise BrokenPipeError("remote session has exited")
        await self._ws.send(json.dumps(payload))

    async def _read_loop(self) -> None:
        try:
            async for frame in self._ws:
                msg = json.loads(frame)
                if "stdout" in msg:
                    self.stdout.feed(msg["stdout"])
                elif "stderr" in msg:
                    self.stderr.feed(msg["stderr"])
                elif "exit" in msg:
                    self.returncode = int(msg["exit"])
                    break
                elif "error" in msg:
                    self.stderr.feed(f"[runner] {msg['error']}")
        except Exception as exc:  # connection lost
            logger.warning("[runner] connection lost: {}", exc)
        finally:
            if self.returncode is None:
                self.returncode = -1
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self._exited.set()
            await self._ws.close()

    async def _signal(self, name: str) -> None:
        try:
            await self._ws.send(json.dumps({"signal": name}))
        except Exception as exc:
            logger.debug("[runner] could not send {}: {}", name, exc)

    def terminate(self) -> None:
        asyncio.ensure_future(self._signal("terminate"))

    def kill(self) -> None:
        asyncio.ensure_future(self._signal("kill"))

    async def wait(self) -> int:
        await self._exited.wait()
        return self.returncode if self.returncode is not None else -1
