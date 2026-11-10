"""Company CLIs through the relay: the employee never sees the key."""
from __future__ import annotations

import os
import stat

import pytest

from onemancompany.core import api_tools, cli_relay
from onemancompany.core import config as config_mod

KEY = "scalingo_tk-us-SECRET9876"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    data_root = tmp_path / "data"
    workdir = data_root / "projects" / "p1"
    workdir.mkdir(parents=True)
    monkeypatch.setattr(config_mod, "TOOLS_DIR", tools)
    monkeypatch.setattr(config_mod, "DATA_ROOT", data_root)
    monkeypatch.setattr(config_mod, "load_app_config", lambda: {})
    monkeypatch.setattr("onemancompany.core.store.mark_dirty", lambda *a, **k: None)
    tool_id = api_tools.create_api_tool("Scalingo", "", KEY, cli={"preset": "scalingo"})
    return tool_id, workdir, tmp_path


def _fake_docker(tmp_path, body: str) -> str:
    path = tmp_path / "docker"
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_presets_and_validation():
    spec = cli_relay.normalize_cli("scalingo")
    assert spec["command"] == "scalingo" and spec["login"] == ["login", "--api-token", "{key}"]
    assert spec["env"]["SCALINGO_REGION"] == "osc-fr1"
    gh = cli_relay.normalize_cli({"preset": "gh", "env": {"GH_HOST": "github.com"}})
    assert gh["key_env"] == "GH_TOKEN" and gh["env"]["GH_HOST"] == "github.com" and gh["depth"] == 2
    custom = cli_relay.normalize_cli({"command": "mycli", "key_env": "MYCLI_TOKEN", "read_commands": "list, show *"})
    assert custom["read_commands"] == ["list", "show *"]
    for bad in ({"command": "rm -rf /", "key_env": "X"}, {"command": "ok"}, {"command": "ok", "login": ["login"]},
                {"command": "ok", "key_env": "lower"}, {"preset": "nope"}, {"command": "ok", "key_env": "A", "env": {"PATH": "/x"}}):
        with pytest.raises(ValueError):
            cli_relay.normalize_cli(bad)


def test_read_or_write():
    sc = cli_relay.normalize_cli("scalingo")
    assert cli_relay.is_read(sc, ["apps"])
    assert cli_relay.is_read(sc, ["--app", "photonet-backend", "logs", "-n", "100"])
    assert cli_relay.is_read(sc, ["-a", "photonet-backend", "backups"])
    assert not cli_relay.is_read(sc, ["--app", "photonet-backend", "restart"])
    assert not cli_relay.is_read(sc, ["-a", "x", "env-set", "A=1"])
    assert not cli_relay.is_read(sc, [])
    gh = cli_relay.normalize_cli("gh")
    assert cli_relay.is_read(gh, ["pr", "list", "-R", "photonet/id_picture"])
    assert cli_relay.is_read(gh, ["-R", "o/r", "run", "view", "123"])
    assert cli_relay.is_read(gh, ["api", "repos/o/r/actions/runs"])
    assert not cli_relay.is_read(gh, ["api", "-X", "POST", "repos/o/r/issues"])
    assert not cli_relay.is_read(gh, ["api", "repos/o/r/issues", "-f", "title=x"])
    assert not cli_relay.is_read(gh, ["api", "repos/o/r/issues", "--method=PATCH"])
    assert not cli_relay.is_read(gh, ["pr", "merge", "12"])


def test_arguments_that_could_reach_the_key_are_refused(env):
    _tool_id, workdir, _tmp = env
    gh = cli_relay.normalize_cli("gh")
    sc = cli_relay.normalize_cli("scalingo")
    assert cli_relay.check_args(gh, ["api", "user", "--jq", "env.GH_TOKEN"], workdir)
    assert cli_relay.check_args(gh, ["api", "user", "-q", ".login"], workdir)
    assert cli_relay.check_args(gh, ["auth", "token"], workdir)
    assert cli_relay.check_args(gh, ["api", "gists", "-F", "files[a][content]=@/proc/self/environ"], workdir)
    assert cli_relay.check_args(gh, ["api", "x", "--input", "/tmp/home/.config/gh/hosts.yml"], workdir)
    assert cli_relay.check_args(sc, ["deploy", "../" * 12 + "proc/self/environ"], workdir)
    assert cli_relay.check_args(sc, ["login", "--api-token", "mine"], workdir)
    assert cli_relay.check_args(sc, ["deploy", "~/.ssh/id_rsa"], workdir)
    (workdir / "link").symlink_to("/proc/self/environ")
    assert "Links" in cli_relay.check_args(gh, ["api", "x", "--input", "link"], workdir)
    (workdir / "body.json").write_text("{}")
    assert cli_relay.check_args(gh, ["api", "x", "--input", "body.json"], workdir) == ""
    assert cli_relay.check_args(gh, ["api", "/repos/o/r/environments"], workdir) == ""
    assert cli_relay.check_args(sc, ["--app", "photonet-backend", "logs"], workdir) == ""


def test_the_key_never_appears_in_the_command_line(env):
    _tool_id, workdir, _tmp = env
    spec = cli_relay.normalize_cli("scalingo")
    cmd, from_env = cli_relay.build_command(spec, ["apps"], workdir, "omc-cli-test")
    joined = " ".join(cmd)
    assert KEY not in joined and "OMC_CLI_KEY" in from_env
    assert ["-e", "OMC_CLI_KEY"] == cmd[cmd.index("OMC_CLI_KEY") - 1:cmd.index("OMC_CLI_KEY") + 1]
    assert f"{workdir}:{workdir}" in cmd and "--read-only" in cmd and "--cap-drop" in cmd
    script = cmd[cmd.index("-c") + 1]
    assert '"$OMC_CLI_KEY"' in script and "exec scalingo" in script
    gh = cli_relay.normalize_cli("gh")
    _cmd, from_env = cli_relay.build_command(gh, ["pr", "list"], workdir, "omc-cli-test")
    assert from_env == ["OMC_CLI_KEY", "GH_TOKEN"]


@pytest.mark.asyncio
async def test_run_checks_access_and_redacts(env, monkeypatch):
    tool_id, workdir, tmp = env
    docker = _fake_docker(tmp, 'echo "key=$OMC_CLI_KEY args=$*"; echo "warn $OMC_CLI_KEY" >&2; exit 0')
    monkeypatch.setattr(cli_relay, "docker_binary", lambda: docker)

    denied = await cli_relay.run(tool_id, "00007", "apps", workdir)
    assert denied["status"] == "denied"

    api_tools.grant_employee(tool_id, "00007", access="read", reason="sauvegardes")
    write = await cli_relay.run(tool_id, "00007", "--app photonet restart", workdir)
    assert write["status"] == "denied" and "read-only" in write["message"]

    ok = await cli_relay.run(tool_id, "00007", "scalingo --app photonet-backend logs -n 50", workdir)
    assert ok["status"] == "done" and ok["exit_code"] == 0
    assert KEY not in ok["stdout"] + ok["stderr"] and "[REDACTED]" in ok["stdout"]
    assert ok["command"] == "scalingo --app photonet-backend logs -n 50"
    log = api_tools.read_log(tool_id)
    assert log[0]["method"] == "CLI" and log[0]["decision"] == "allowed"
    assert any(e["decision"] == "denied" for e in log)

    outside = await cli_relay.run(tool_id, "00007", "apps", tmp)
    assert outside["status"] == "error"  # work folder must be inside the company folder

    api_tools.grant_employee(tool_id, "00007", access="write", reason="déploiement")
    assert (await cli_relay.run(tool_id, "00007", "--app photonet restart", workdir))["status"] == "done"


@pytest.mark.asyncio
async def test_timeout_and_missing_docker(env, monkeypatch):
    tool_id, workdir, tmp = env
    api_tools.grant_employee(tool_id, "00007", access="read")
    monkeypatch.setattr(cli_relay, "docker_binary", lambda: "")
    assert "Docker" in (await cli_relay.run(tool_id, "00007", "apps", workdir))["error"]
    docker = _fake_docker(tmp, 'if [ "$1" = "kill" ]; then exit 0; fi; sleep 30')
    monkeypatch.setattr(cli_relay, "docker_binary", lambda: docker)
    result = await cli_relay.execute(cli_relay.normalize_cli("scalingo"), KEY, ["logs", "-f"], workdir, timeout=1)
    assert result["ok"] is False and "Stopped" in result["error"]


def test_cli_only_tool_has_no_http_api(env):
    tool_id, _workdir, _tmp = env
    api_tools.grant_employee(tool_id, "00007")
    assert "run_cli" in api_tools.request(tool_id, "00007", "GET", "/apps")["error"]
    item = api_tools.granted_apis("00007")[0]
    assert item["cli"]["command"] == "scalingo" and item["cli"]["allowed"] == "read commands only"
    assert os.environ.get("OMC_CLI_KEY") is None  # never leaked into the server's own environment
