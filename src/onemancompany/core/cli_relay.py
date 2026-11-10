"""Company command-line tools (scalingo, gh…) used by employees without the key.

An API-key tool can carry a ``cli`` section next to (or instead of) its HTTP
API::

    cli:
      preset: scalingo                 # known CLI: command, login, read commands
      env: {SCALINGO_REGION: osc-fr1}  # non-secret variables

or, for another CLI::

    cli:
      command: mycli
      key_env: MYCLI_TOKEN             # variable that receives the key
      login: [login, --token, "{key}"] # or a login step run first
      read_commands: [list, "show *"]  # what read-only access may run
      value_flags: [--project]         # flags followed by a value

``run`` checks the employee's access (read-only access runs read commands
only; write access runs anything), then starts the command in a throwaway
Docker container from the runner image. Only that container receives the key
(login step or environment variable), only the employee's current folder is
mounted (same path), the output comes back with the key redacted, and every
command is written to the tool's journal. The employee never sees the key.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import signal
import uuid
from pathlib import Path

from loguru import logger

DEFAULT_IMAGE = "onemancompany-runner"
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600
MAX_OUTPUT_CHARS = 20000
MAX_ARGS = 100
MAX_ARG_CHARS = 4000
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
# Paths an employee may not hand to a CLI (where the throwaway container keeps
# the key: its environment and its temporary home).
_FORBIDDEN_PREFIXES = ("/proc", "/sys", "/tmp", "/dev", "/etc", "/root", "/run", "/var/run")
_CONTAINER_HOME = "/tmp/home"

PRESETS: dict[str, dict] = {
    "scalingo": {
        "command": "scalingo",
        "login": ["login", "--api-token", "{key}"],
        "env": {"DISABLE_UPDATE_CHECKER": "true", "DISABLE_INTERACTIVE": "true", "SCALINGO_REGION": "osc-fr1"},
        "value_flags": ["-a", "--app", "--region", "-r", "--remote", "--addon", "--database"],
        "depth": 1,
        "read_commands": [
            "apps", "apps-info", "ps", "logs", "logs-archives", "env", "addons", "addons-info",
            "addons-plans", "addons-list", "domains", "domains-info", "collaborators", "deployments",
            "deployment-logs", "stats", "timeline", "user-timeline", "backups", "backups-download",
            "backup-download", "regions", "notifiers", "notifiers-details", "alerts", "metrics",
            "cron-tasks", "integrations", "integration-link", "region-migrations", "self", "whoami",
            "stacks", "autoscalers", "scm-integrations", "git-show", "database-maintenance-list",
            "database-maintenance-info", "help", "version",
        ],
        "deny_commands": ["login", "logout"],
        "docs_url": "https://doc.scalingo.com/tools/cli/introduction",
    },
    "gh": {
        "command": "gh",
        "key_env": "GH_TOKEN",
        "env": {"GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1",
                "GH_NO_EXTENSION_UPDATE_NOTIFIER": "1"},
        "value_flags": ["-R", "--repo", "-L", "--limit", "-s", "--state", "--json", "-H", "--header",
                        "-b", "--branch", "-a", "--author", "-l", "--label", "-w", "--workflow"],
        "depth": 2,
        "read_commands": [
            "repo view", "repo list", "pr list", "pr view", "pr diff", "pr checks", "pr status",
            "issue list", "issue view", "issue status", "run list", "run view", "workflow list",
            "workflow view", "release list", "release view", "search *", "api", "status",
            "secret list", "variable list", "label list", "cache list", "ruleset list", "ruleset view",
            "help", "version",
        ],
        # Writes in "gh api": a method other than GET, fields or a request body.
        "write_flags": ["-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"],
        # jq filters can read the process environment (where the key is).
        "deny_flags": ["-q", "--jq"],
        "deny_commands": ["auth", "extension", "alias", "config", "codespace", "attestation"],
        "docs_url": "https://cli.github.com/manual/",
    },
}


def _list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v for v in re.split(r"[,\n]", value) if v.strip()]
    return [str(v) for v in value]


def normalize_cli(cli: dict | str | None) -> dict | None:
    """Validate a tool's ``cli`` section; a bare string names a preset or a command."""
    if not cli:
        return None
    if isinstance(cli, str):
        cli = {"preset": cli} if cli in PRESETS else {"command": cli}
    preset = str(cli.get("preset") or "").strip()
    if preset and preset not in PRESETS:
        raise ValueError(f"Unknown CLI preset: {preset} (known: {', '.join(PRESETS)})")
    base = dict(PRESETS.get(preset, {}))
    command = str(cli.get("command") or base.get("command") or "").strip()
    if not _NAME_RE.fullmatch(command):
        raise ValueError("The CLI command must be a plain program name, e.g. scalingo or gh")
    out: dict = {"command": command}
    if preset:
        out["preset"] = preset
    key_env = str(cli.get("key_env") or base.get("key_env") or "").strip()
    login = [str(a) for a in (cli.get("login") or base.get("login") or [])]
    if key_env and not _ENV_RE.fullmatch(key_env):
        raise ValueError(f"Invalid environment variable name: {key_env}")
    if login and not any("{key}" in a for a in login):
        raise ValueError("The login step must contain {key}")
    if not key_env and not login:
        raise ValueError("Say how the CLI receives the key: key_env (variable) or login (step)")
    if key_env:
        out["key_env"] = key_env
    if login:
        out["login"] = login
    env = {**(base.get("env") or {}), **(cli.get("env") or {})}
    for name in env:
        if not _ENV_RE.fullmatch(str(name)) or str(name) in ("HOME", "PATH", "OMC_CLI_KEY"):
            raise ValueError(f"Invalid environment variable name: {name}")
    out["env"] = {str(k): str(v) for k, v in env.items()}
    for field in ("read_commands", "value_flags", "write_flags", "deny_flags", "deny_commands"):
        items = _list(cli.get(field)) or _list(base.get(field))
        out[field] = [" ".join(i.split()) for i in items if i.strip()]
    out["depth"] = int(cli.get("depth") or base.get("depth") or 1)
    if base.get("docs_url") or cli.get("docs_url"):
        out["docs_url"] = str(cli.get("docs_url") or base.get("docs_url"))
    return out


def command_words(spec: dict, args: list[str]) -> list[str]:
    """The subcommand words of a command line (flags and their values skipped)."""
    value_flags = set(spec.get("value_flags") or [])
    words: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg.startswith("-"):
            skip = arg in value_flags
            continue
        words.append(arg)
        if len(words) >= int(spec.get("depth") or 1):
            break
    return words


def _matches(pattern: str, words: list[str]) -> bool:
    parts = pattern.split()
    return len(words) >= len(parts) and all(p == "*" or p == w for p, w in zip(parts, words))


def _flag_in(args: list[str], flags: list[str]) -> str:
    for arg in args:
        for flag in flags:
            if arg == flag or (flag.startswith("--") and arg.startswith(flag + "=")) or (
                    not flag.startswith("--") and len(flag) == 2 and arg.startswith(flag) and len(arg) > 2):
                return flag
    return ""


def is_read(spec: dict, args: list[str]) -> bool:
    """True when the command only reads (allowed with read-only access)."""
    words = command_words(spec, args)
    if not words or _flag_in(args, spec.get("write_flags") or []):
        return False
    return any(_matches(p, words) for p in spec.get("read_commands") or [])


def check_args(spec: dict, args: list[str], workdir: Path) -> str:
    """Return an error message, or "" when the arguments are acceptable."""
    if len(args) > MAX_ARGS:
        return f"Too many arguments (max {MAX_ARGS})"
    for arg in args:
        if "\x00" in arg or len(arg) > MAX_ARG_CHARS:
            return "Invalid argument"
    flag = _flag_in(args, spec.get("deny_flags") or [])
    if flag:
        return f"The {flag} option is not available through the company CLI: process the output yourself"
    words = command_words(spec, args)
    if words and any(_matches(p, words) for p in spec.get("deny_commands") or []):
        return f"'{' '.join(words)}' is not available through the company CLI"
    # Only the work folder is mounted in the container: a file argument inside
    # it must be a regular file (a link could point at the key's location).
    root = workdir.resolve()
    for arg in args:
        candidates = []
        if arg.startswith("@"):
            candidates.append(arg[1:])
        if "=@" in arg:
            candidates.append(arg.split("=@", 1)[1])
        if "=" in arg and arg.startswith("--"):
            candidates.append(arg.split("=", 1)[1])
        if not arg.startswith("-"):
            candidates.append(arg)
        for cand in candidates:
            if not cand:
                continue
            if cand.startswith("~"):
                return "Use files in your work folder (no ~ paths)"
            path = Path(os.path.normpath(cand if os.path.isabs(cand) else root / cand))
            if path != root and root not in path.parents:
                # Outside the mounted folder: only the container's own files
                # are there, including where it keeps the key.
                if any(str(path) == p or str(path).startswith(p + "/") for p in _FORBIDDEN_PREFIXES):
                    return "Arguments may not point to system or temporary folders: use files in your work folder"
                continue
            probe = path
            while probe != root:
                if probe.is_symlink():
                    return "Links are not accepted as CLI files: give a regular file in your work folder"
                probe = probe.parent
    return ""


# ---------------------------------------------------------------------------
# Running the command in a throwaway container
# ---------------------------------------------------------------------------

def _settings() -> dict:
    from onemancompany.core.config import load_app_config

    cfg = load_app_config().get("cli_relay")
    return cfg if isinstance(cfg, dict) else {}


def docker_binary() -> str:
    configured = str(_settings().get("docker") or "").strip()
    if configured:
        return configured if Path(configured).exists() else ""
    found = shutil.which("docker")
    if found:
        return found
    for candidate in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker",
                      "/Applications/Docker.app/Contents/Resources/bin/docker"):
        if Path(candidate).exists():
            return candidate
    return ""


def image() -> str:
    return str(_settings().get("image") or DEFAULT_IMAGE)


def _script(spec: dict) -> str:
    """Shell run inside the container. The key is only referenced as $OMC_CLI_KEY."""
    command = spec["command"]
    lines = ["set -eu", f'mkdir -p "{_CONTAINER_HOME}"']
    if spec.get("login"):
        parts = []
        for arg in spec["login"]:
            if "{key}" in arg:  # e.g. "{key}" or "--token={key}"
                before, after = arg.split("{key}", 1)
                parts.append((shlex.quote(before) if before else "") + '"$OMC_CLI_KEY"'
                             + (shlex.quote(after) if after else ""))
            else:
                parts.append(shlex.quote(arg))
        lines.append(f"{shlex.quote(command)} {' '.join(parts)} >/dev/null 2>&1 || "
                     "{ echo 'The CLI did not accept the key (login failed): ask the COO to check it.' >&2; exit 97; }")
    lines.append(f'exec {shlex.quote(command)} "$@"')
    return "\n".join(lines)


def build_command(spec: dict, args: list[str], workdir: Path, name: str) -> tuple[list[str], list[str]]:
    """(docker command, names of the variables taken from the client environment)."""
    from_env = ["OMC_CLI_KEY"] + ([spec["key_env"]] if spec.get("key_env") else [])
    cmd = [
        docker_binary() or "docker", "run", "--rm", "--name", name,
        "--network", "bridge", "--user", "1000:1000",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "256", "--memory", "1g",
        "--read-only", "--tmpfs", "/tmp:rw,size=256m",
        "-e", f"HOME={_CONTAINER_HOME}", "-e", "PATH=/usr/local/bin:/usr/bin:/bin", "-e", "LANG=C.UTF-8",
    ]
    for var in from_env:
        cmd += ["-e", var]  # value taken from the docker client's environment
    for key, value in (spec.get("env") or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += ["-v", f"{workdir}:{workdir}", "-w", str(workdir),
            "--entrypoint", "/bin/sh", image(), "-c", _script(spec), "omc-cli", *args]
    return cmd, from_env


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    return text


def _cap(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "… [truncated]"


async def execute(spec: dict, key: str, args: list[str], workdir: Path, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run the CLI in a throwaway container. Returns ok, exit_code, stdout, stderr."""
    docker = docker_binary()
    if not docker:
        return {"ok": False, "error": "Docker is not available on the company server: the CLI relay needs it."}
    name = f"omc-cli-{uuid.uuid4().hex[:12]}"
    cmd, from_env = build_command(spec, args, workdir, name)
    env = dict(os.environ)
    for var in from_env:
        env[var] = key
    timeout = max(5, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True,
        )
    except OSError as exc:
        return {"ok": False, "error": f"Cannot start Docker: {exc}"}
    timed_out = False
    communicate = asyncio.ensure_future(proc.communicate())
    try:
        out, err = await asyncio.wait_for(asyncio.shield(communicate), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        timed_out = True
        killer = await asyncio.create_subprocess_exec(docker, "kill", name, stdout=asyncio.subprocess.DEVNULL,
                                                      stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
        try:  # the container is gone: the docker client returns
            out, err = await asyncio.wait_for(asyncio.shield(communicate), timeout=5)
        except (asyncio.TimeoutError, TimeoutError):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            out, err = await communicate
    stdout = _cap(_redact(out.decode("utf-8", errors="replace"), [key]))
    stderr = _cap(_redact(err.decode("utf-8", errors="replace"), [key]))
    code = proc.returncode
    if "Unable to find image" in stderr or "No such image" in stderr:
        return {"ok": False, "error": f"The runner image ({image()}) is missing: build it (deploy/runner)."}
    result = {"ok": code == 0 and not timed_out, "exit_code": code, "stdout": stdout, "stderr": stderr}
    if timed_out:
        result["error"] = f"Stopped after {timeout}s (long-running commands such as log streaming are cut)."
    return result


async def run(tool_id: str, employee_id: str, args: list[str] | str, workdir: str | Path,
              timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Entry point used by the employee tool ``run_cli``."""
    from onemancompany.core import api_tools
    from onemancompany.core.config import DATA_ROOT
    from onemancompany.core.secret_store import get_secret_store

    data = api_tools.load_tool(tool_id)
    if not data:
        return {"status": "error", "message": f"Unknown tool: {tool_id}. Use list_company_apis()."}
    spec = data.get("cli")
    if not spec:
        return {"status": "error", "message": f"{data.get('name', tool_id)} has no command-line tool: use api_request."}
    try:
        spec = normalize_cli(spec)
    except ValueError as exc:
        return {"status": "error", "message": f"CLI misconfigured: {exc}"}
    if isinstance(args, str):
        try:
            args = shlex.split(args)
        except ValueError as exc:
            return {"status": "error", "message": f"Cannot parse the command: {exc}"}
    args = [str(a) for a in args]
    if args and args[0] == spec["command"]:
        args = args[1:]
    if not args:
        return {"status": "error", "message": f"Give the {spec['command']} command to run, e.g. \"apps\""}
    shown = " ".join([spec["command"], *args])[:300]
    entry = {"at": api_tools._now(), "employee": employee_id, "method": "CLI", "path": shown}

    if not api_tools._granted(data, employee_id):
        api_tools._log(tool_id, {**entry, "decision": "denied", "reason": "no access"})
        return {"status": "denied", "message": "You do not have access to this tool. Ask with request_access()."}
    root = Path(workdir).resolve()
    data_root = Path(DATA_ROOT).resolve()
    if not root.is_dir() or not (root == data_root or data_root in root.parents):
        return {"status": "error", "message": "The work folder must be inside the company folder"}
    problem = check_args(spec, args, root)
    if problem:
        api_tools._log(tool_id, {**entry, "decision": "denied", "reason": problem})
        return {"status": "denied", "message": problem}
    rules = api_tools.effective_rules(data, employee_id)
    if rules["read_only"] and not is_read(spec, args):
        reason = (f"'{' '.join(command_words(spec, args)) or spec['command']}' may change things and your access "
                  "is read-only. If you really need it, ask with request_access(access='write').")
        api_tools._log(tool_id, {**entry, "decision": "denied", "reason": reason})
        return {"status": "denied", "message": reason}
    key = get_secret_store().get(data.get("secret", "")) or ""
    if not key:
        return {"status": "error", "message": "The key is missing. Ask the COO (request_access)."}

    result = await execute(spec, key, args, root, timeout)
    api_tools._log(tool_id, {**entry, "decision": "allowed", "exit": result.get("exit_code"),
                             "ok": result.get("ok"), "error": result.get("error")})
    logger.info("[cli-relay] {} ran `{}` ({}) → exit {}", employee_id, shown, tool_id, result.get("exit_code"))
    return {"status": "done" if result.get("ok") else "failed", "command": shown, "workdir": str(root), **result}
