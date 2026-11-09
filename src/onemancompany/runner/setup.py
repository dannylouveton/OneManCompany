"""`python -m onemancompany.runner setup-docker` — prepare a Docker runner.

Run on the control plane machine. It:
* creates the runner token (control plane secret store) and the signing key,
* writes deploy/runner/secrets.env (the runner's only secrets), .env (paths),
  compose.override.yaml (read-only / extra folders at the same paths) and an
  empty claude.env for the Claude Code token,
* sets ``runner.url`` in config.yaml (only when --enable is given).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import yaml

from onemancompany.core.session_process import RUNNER_TOKEN_NAME


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _host_dirs(cfg: dict, key: str) -> list[str]:
    out = []
    for item in cfg.get(key) or []:
        p = Path(str(item)).expanduser().resolve()
        if p.exists():
            out.append(str(p))
    return out


def setup_docker(control_url: str, port: int, enable: bool) -> Path:
    from onemancompany.core.config import DATA_ROOT, SOURCE_ROOT, load_app_config
    from onemancompany.core.secret_store import INTERNAL_KEY_NAME, ensure_internal_key, get_secret_store

    store = get_secret_store()
    token = store.get(RUNNER_TOKEN_NAME) or secrets.token_hex(32)
    store.set_many({RUNNER_TOKEN_NAME: token})
    key = ensure_internal_key()

    out = Path(SOURCE_ROOT) / "deploy" / "runner"
    out.mkdir(parents=True, exist_ok=True)
    data_root = str(Path(DATA_ROOT).resolve())
    _write_private(out / "secrets.env", f"{RUNNER_TOKEN_NAME}={token}\n{INTERNAL_KEY_NAME}={key}\n")
    (out / ".env").write_text(
        f"OMC_DATA_ROOT={data_root}\nOMC_CONTROL_URL={control_url}\n"
        f"OMC_CONFIG_HOME={Path.home()}\nRUNNER_PORT={port}\n", encoding="utf-8")
    if not (out / "claude.env").exists():
        _write_private(out / "claude.env", "# Paste the token printed by `claude setup-token`:\nCLAUDE_CODE_OAUTH_TOKEN=\n")

    sandbox = load_app_config().get("agent_sandbox") or {}
    sandbox = sandbox if isinstance(sandbox, dict) else {}
    mounts = [f"{d}:{d}:ro" for d in _host_dirs(sandbox, "read_dirs")]
    mounts += [f"{d}:{d}" for d in _host_dirs(sandbox, "allow_dirs")]
    override = {"services": {"runner": {"volumes": mounts}}} if mounts else {"services": {"runner": {}}}
    (out / "compose.override.yaml").write_text(yaml.safe_dump(override, sort_keys=False), encoding="utf-8")

    if enable:
        config_path = Path(DATA_ROOT) / "config.yaml"
        text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        if (yaml.safe_load(text) or {}).get("runner"):
            print("config.yaml already has a runner: section — left unchanged")
        else:  # append, keeping the file's comments
            config_path.write_text(text.rstrip("\n") + f"\n\nrunner:\n  url: ws://127.0.0.1:{port}\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m onemancompany.runner setup-docker")
    parser.add_argument("--control-url", default="http://host.docker.internal:" + os.environ.get("PORT", "8000"))
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--enable", action="store_true", help="also set runner.url in config.yaml")
    args = parser.parse_args(argv)
    out = setup_docker(args.control_url, args.port, args.enable)
    print(f"Runner files written to {out}")
    print("Next: put your `claude setup-token` token in deploy/runner/claude.env, then")
    print("      docker compose -f deploy/runner/compose.yaml -f deploy/runner/compose.override.yaml up -d --build")
