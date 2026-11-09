"""Remote runner: a session started over the WebSocket behaves like a local process."""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time

import pytest
import uvicorn

from onemancompany.core import session_process
from onemancompany.core.claude_session import SessionSpec
from onemancompany.runner import server

ECHO = "import sys,json\nfor l in sys.stdin:\n    print(json.dumps({'echo': l.strip()}), flush=True)\n"


@pytest.fixture()
def runner(monkeypatch):
    async def fake_spawn(spec):
        return await asyncio.create_subprocess_exec(
            sys.executable, "-c", ECHO,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    monkeypatch.setattr(session_process, "spawn_local", fake_spawn)
    monkeypatch.setattr(server, "_expected_token", lambda: "tok-123")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cfg = uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"ws://127.0.0.1:{port}{session_process.SESSIONS_PATH}"
    srv.should_exit = True
    thread.join(timeout=5)


SPEC = SessionSpec("00006", "p1", "12345678-aaaa", True).to_dict()


@pytest.mark.asyncio
async def test_remote_session_round_trip(runner):
    proc = await session_process.RemoteSessionProcess.connect(runner, "tok-123", SPEC)
    assert proc.pid and proc.returncode is None
    proc.stdin.write(b'{"type": "user"}\n')
    await proc.stdin.drain()
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
    assert json.loads(line) == {"echo": '{"type": "user"}'}
    proc.terminate()
    assert await asyncio.wait_for(proc.wait(), timeout=10) is not None
    assert await proc.stdout.readline() == b""


@pytest.mark.asyncio
async def test_wrong_token_is_rejected(runner):
    with pytest.raises(Exception):
        await session_process.RemoteSessionProcess.connect(runner, "bad", SPEC)


def test_spec_validation():
    with pytest.raises(ValueError):
        SessionSpec.from_dict({**SPEC, "employee_id": "../../etc"})
    assert SessionSpec.from_dict({**SPEC, "extra": 1}).employee_id == "00006"


def test_setup_docker(tmp_path, monkeypatch):
    from onemancompany.core import config as config_mod
    from onemancompany.core import secret_store
    from onemancompany.runner import setup

    store = secret_store.DotEnvSecretStore(tmp_path / "data" / ".env")
    monkeypatch.setattr(secret_store, "get_secret_store", lambda: store)
    monkeypatch.setattr(config_mod, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(config_mod, "SOURCE_ROOT", tmp_path / "src")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    monkeypatch.setattr(config_mod, "load_app_config", lambda: {"agent_sandbox": {"read_dirs": [str(wiki)]}})
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "config.yaml").write_text("# keep me\nfoo: 1\n")
    out = setup.setup_docker("http://host.docker.internal:8000", 8100, enable=True)
    secrets_env = (out / "secrets.env").read_text()
    assert "OMC_RUNNER_TOKEN=" in secrets_env and "OMC_INTERNAL_KEY=" in secrets_env
    assert store.get("OMC_RUNNER_TOKEN") in secrets_env
    assert f"{wiki}:{wiki}:ro" in (out / "compose.override.yaml").read_text()
    cfg = (tmp_path / "data" / "config.yaml").read_text()
    assert "# keep me" in cfg and "url: ws://127.0.0.1:8100" in cfg
    for name in ("OMC_RUNNER_TOKEN", "OMC_INTERNAL_KEY"):
        monkeypatch.delenv(name, raising=False)
