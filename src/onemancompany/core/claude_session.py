"""Claude Code daemon session management.

Each self-hosted employee gets a persistent Claude CLI process (daemon) that
stays alive across tasks.  Prompts are sent via stdin using stream-json format,
responses are read from stdout as NDJSON.

Lifecycle:
  1. First prompt  → spawn ``claude -p --input-format stream-json
     --output-format stream-json --session-id <uuid> ...``
  2. Send prompt   → write ``{"type":"user","message":{...}}`` to stdin
  3. Read response → collect NDJSON lines until ``result`` message
  4. Next task     → reuse the same process, send another prompt
  5. Process dies  → auto-restart with ``--resume <uuid>``

Data file: {employee_dir}/sessions.json
Format:    {"project_id": {"session_id": "uuid", "work_dir": "/path",
            "created": "iso", "used": true/false}, ...}
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from onemancompany.core.config import BLOCK_KEY_TEXT, BLOCK_KEY_TYPE, BLOCK_TYPE_TEXT, EMPLOYEES_DIR, ENCODING_UTF8, PROJECTS_DIR, read_text_utf, write_text_utf

LLM_TRACES_FILENAME = "llm_traces.jsonl"


# ---------------------------------------------------------------------------
# Shared LLM trace writer — project-level JSONL log
# ---------------------------------------------------------------------------

def write_llm_trace(project_id: str, entry: dict) -> None:
    """Append a single trace entry to the project's llm_traces.jsonl.

    Only active when OMC_DEBUG=1.
    Called by both ClaudeDaemon (self-hosted) and vessel _on_log (company-hosted).
    """
    from onemancompany.core.config import IS_DEBUG
    if not IS_DEBUG:
        return
    if not project_id or project_id == "default":
        return
    path = PROJECTS_DIR / project_id / LLM_TRACES_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding=ENCODING_UTF8) as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.debug("[llm-trace] write failed for project={}: {}", project_id, e)


def _fmt_tool_call(name: str, args: dict) -> str:
    """Compact one-line summary of a tool call for live on_log signals."""
    try:
        compact = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        compact = str(args)
    if len(compact) > 300:
        compact = compact[:300] + "…"
    return f"{name}({compact})"


# Single-file constants
SESSIONS_FILENAME = "sessions.json"
_KEY_SESSION_ID = "session_id"
_KEY_WORK_DIR = "work_dir"
_KEY_CREATED = "created"
_KEY_USED = "used"
_KEY_RUNNING_PID = "running_pid"

# ---------------------------------------------------------------------------
# Per-employee locks — prevent concurrent sends on the same daemon
# ---------------------------------------------------------------------------
_session_locks: dict[str, asyncio.Lock] = {}


def _get_session_lock(employee_id: str, project_id: str) -> asyncio.Lock:
    key = f"{employee_id}:{project_id}"
    if key not in _session_locks:
        _session_locks[key] = asyncio.Lock()
    return _session_locks[key]


def _remove_session_lock(employee_id: str, project_id: str) -> None:
    key = f"{employee_id}:{project_id}"
    _session_locks.pop(key, None)


# ---------------------------------------------------------------------------
# Session persistence helpers (unchanged)
# ---------------------------------------------------------------------------

def _sessions_file(employee_id: str) -> Path:
    return EMPLOYEES_DIR / employee_id / SESSIONS_FILENAME


def _load_sessions(employee_id: str) -> dict:
    path = _sessions_file(employee_id)
    if not path.exists():
        return {}
    try:
        return json.loads(read_text_utf(path))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sessions(employee_id: str, data: dict) -> None:
    path = _sessions_file(employee_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_utf(path, json.dumps(data, indent=2, ensure_ascii=False))


def get_or_create_session(
    employee_id: str, project_id: str, work_dir: str = "",
) -> tuple[str, bool]:
    """Return (session_id, is_new)."""
    sessions = _load_sessions(employee_id)
    entry = sessions.get(project_id)
    if entry and entry.get(_KEY_SESSION_ID):
        if entry.get(_KEY_USED):
            return entry[_KEY_SESSION_ID], False
        return entry[_KEY_SESSION_ID], True

    session_id = str(uuid.uuid4())
    sessions[project_id] = {
        _KEY_SESSION_ID: session_id,
        _KEY_WORK_DIR: work_dir,
        _KEY_CREATED: datetime.now(timezone.utc).isoformat(),
        _KEY_USED: False,
    }
    _save_sessions(employee_id, sessions)
    return session_id, True


def _mark_session_used(employee_id: str, project_id: str) -> None:
    sessions = _load_sessions(employee_id)
    entry = sessions.get(project_id)
    if entry and not entry.get(_KEY_USED):
        entry[_KEY_USED] = True
        _save_sessions(employee_id, sessions)


def _save_running_pid(employee_id: str, project_id: str, pid: int) -> None:
    sessions = _load_sessions(employee_id)
    entry = sessions.get(project_id)
    if entry:
        entry[_KEY_RUNNING_PID] = pid
        _save_sessions(employee_id, sessions)


def _clear_running_pid(employee_id: str, project_id: str) -> None:
    sessions = _load_sessions(employee_id)
    entry = sessions.get(project_id)
    if entry and _KEY_RUNNING_PID in entry:
        del entry[_KEY_RUNNING_PID]
        _save_sessions(employee_id, sessions)


# ---------------------------------------------------------------------------
# ClaudeDaemon — persistent Claude CLI process per employee
# ---------------------------------------------------------------------------

# Registry of live daemons: key = "employee_id:project_id"
_daemons: dict[str, "ClaudeDaemon"] = {}

_ensured_plugins: set[str] = set()

# Known marketplaces that need to be added before installing plugins from them.
# Format: marketplace_name -> repo path for `claude plugin marketplace add`
_KNOWN_MARKETPLACES: dict[str, str] = {
    "superpowers-marketplace": "obra/superpowers-marketplace",
}


async def _run_claude_cmd(cmd: list[str], label: str, env: dict[str, str]) -> bool:
    """Run a claude CLI command with timeout and error handling. Returns True on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        out = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        if proc.returncode == 0:
            logger.debug("[claude-plugins] {} ok: {}", label, out[:200])
            return True
        logger.warning("[claude-plugins] {} failed (rc={}): {} {}", label, proc.returncode, out[:200], err[:200])
    except asyncio.TimeoutError:
        logger.warning("[claude-plugins] {} timed out", label)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("[claude-plugins] {} error: {}", label, e)
    return False


async def _ensure_plugins(plugins: list[str]) -> None:
    """Ensure the given Claude CLI plugins are installed and enabled (idempotent).

    Args:
        plugins: List of plugin identifiers, e.g. ["superpowers@superpowers-marketplace"].
    """
    needed = [p for p in plugins if p not in _ensured_plugins]
    if not needed:
        return

    _exclude_env = {"CLAUDECODE", "ANTHROPIC_API_KEY"}
    env = {k: v for k, v in os.environ.items() if k not in _exclude_env}

    # Collect marketplaces that need to be added
    marketplaces_to_add: set[str] = set()
    for plugin_id in needed:
        if "@" in plugin_id:
            marketplace = plugin_id.split("@", 1)[1]
            if marketplace in _KNOWN_MARKETPLACES:
                marketplaces_to_add.add(marketplace)

    # Add marketplaces first
    for marketplace in marketplaces_to_add:
        repo = _KNOWN_MARKETPLACES[marketplace]
        await _run_claude_cmd(
            ["claude", "plugin", "marketplace", "add", repo],
            f"marketplace-add:{marketplace}", env,
        )

    # Install and enable each plugin
    for plugin_id in needed:
        ok = await _run_claude_cmd(
            ["claude", "plugin", "install", plugin_id],
            f"install:{plugin_id}", env,
        )
        if ok:
            await _run_claude_cmd(
                ["claude", "plugin", "enable", plugin_id],
                f"enable:{plugin_id}", env,
            )
            _ensured_plugins.add(plugin_id)

    logger.info("[claude-plugins] setup complete for: {}", needed)



# Files an employee's shell commands and Read tool must never open: the
# company secret store and the CEO's own credentials.
_SANDBOX_DENY_READ_HOME = (
    "~/.claude.json", "~/.claude/.credentials.json", "~/.ssh", "~/.aws", "~/.gnupg",
    "~/.config/gh", "~/.config/gcloud", "~/.netrc", "~/.docker/config.json",
    "~/.npmrc", "~/.pypirc", "~/.kube", "~/Library/Keychains",
)


# The CEO's personal data: shell commands cannot read it (the company
# folder inside stays readable).
_SANDBOX_PERSONAL_DIRS = (
    "~/Documents", "~/Desktop", "~/Downloads", "~/Pictures", "~/Movies", "~/Music",
    "~/Library/Mobile Documents", "~/Library/CloudStorage", "~/Library/Mail",
    "~/Library/Messages", "~/Library/Safari", "~/Library/Cookies",
    "~/Library/Application Support/Google", "~/Library/Application Support/Firefox",
    "~/Library/Application Support/Claude",
)


def _rule(path: Path | str) -> str:
    """Absolute path in permission-rule syntax ("//abs/path")."""
    return "/" + str(path)


def _outside(keep: list[Path], root: Path) -> list[Path]:
    """Every entry under ``root`` that is neither in ``keep`` nor on the way to it."""
    out: list[Path] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return out
    for entry in entries:
        if any(entry == k for k in keep):
            continue
        if any(k.is_relative_to(entry) for k in keep):
            out += _outside(keep, entry)
        else:
            out.append(entry)
    return out


def agent_sandbox_settings() -> dict | None:
    """Claude Code ``--settings`` that confine an employee session, or None if disabled.

    config.yaml::

        agent_sandbox:
          enabled: true          # default
          allow_dirs: []         # extra folders employees may read and write
          read_dirs: []          # extra folders employees may only read
          deny_read: []          # extra secret files/folders

    * Shell commands run in the OS sandbox (Seatbelt on macOS, bubblewrap on
      Linux): no secrets, none of the CEO's personal folders, writes only in
      the company folder and the temp dir, no unsandboxed fallback, no access
      to OneManCompany's local API.
    * File tools (Read/Write/Edit are not sandboxed): reads limited to the
      working folders, writes denied everywhere in the home folder outside
      them (source code, shell profiles, ~/.claude…), secrets denied.
    """
    from onemancompany.core.config import DATA_ROOT, DOT_ENV_FILENAME, SOURCE_ROOT, load_app_config

    cfg = load_app_config().get("agent_sandbox")
    cfg = cfg if isinstance(cfg, dict) else {"enabled": cfg is not False}
    if cfg.get("enabled", True) is False:
        return None
    home = Path.home()
    # "~" in config.yaml means the CEO's home, also inside the runner container.
    config_home = os.environ.get("OMC_CONFIG_HOME")

    def expand(items) -> list[Path]:
        out = []
        for item in items or []:
            text = str(item)
            if config_home and (text == "~" or text.startswith("~/")):
                text = config_home + text[1:]
            out.append(Path(text).expanduser().resolve())
        return out

    work_dirs = list(dict.fromkeys([Path(DATA_ROOT).resolve(), *expand(cfg.get("allow_dirs")), *expand(cfg.get("allow_write"))]))
    read_dirs = [d for d in expand(cfg.get("read_dirs")) if d not in work_dirs]

    secrets = [str(DATA_ROOT / DOT_ENV_FILENAME), str(SOURCE_ROOT / DOT_ENV_FILENAME)]
    secrets += [str(home / p[2:]) for p in _SANDBOX_DENY_READ_HOME]
    secrets += [str(p) for p in expand(cfg.get("deny_read"))]
    secrets = list(dict.fromkeys(secrets))
    ceo_homes = list(dict.fromkeys([home, *([Path(config_home)] if config_home else [])]))
    personal = [str(h / p[2:]) for h in ceo_homes for p in _SANDBOX_PERSONAL_DIRS]
    personal.append(str(Path(SOURCE_ROOT).resolve()))

    deny: list[str] = []
    for path in secrets:
        targets = [_rule(path), _rule(path) + "/**"] if Path(path).is_dir() else [_rule(path)]
        deny += [f"{tool}({t})" for t in targets for tool in ("Read", "Edit")]
    # Writes with the file tools: nothing in the home folder outside the
    # working folders (covers source code, ~/.zshrc, ~/.claude, LaunchAgents…).
    for path in _outside(work_dirs, home):
        deny += [f"Edit({_rule(path)})", f"Edit({_rule(path)}/**)"] if path.is_dir() else [f"Edit({_rule(path)})"]
    deny += [f"Edit({_rule(home)}/.*)", f"Edit({_rule(home)}/.*/**)"]
    for path in read_dirs:  # read-only folders, wherever they are
        deny += [f"Edit({_rule(path)})", f"Edit({_rule(path)}/**)"]
    for system_dir in ("/Applications", "/Library", "/etc", "/usr/local", "/opt"):
        deny.append(f"Edit({_rule(system_dir)}/**)")
    # Shell commands must not call OneManCompany's own API (approve their
    # own API calls, change access rights…): only the CEO's browser does.
    from urllib.parse import urlparse

    port = str(os.environ.get("PORT") or 8000)
    local_api = [f"{h}:{port}" for h in ("localhost", "127.0.0.1", "[::1]", "0.0.0.0")]
    control = urlparse(control_plane_url())
    if control.hostname:
        local_api.append(f"{control.hostname}:{control.port or (443 if control.scheme == 'https' else 80)}")
    local_api = list(dict.fromkeys(local_api))
    deny += [f"WebFetch(domain:{h})" for h in dict.fromkeys(["localhost", "127.0.0.1", control.hostname or "localhost"])]
    nested = os.environ.get("OMC_RUNNER_CONTAINER") == "1"
    return {
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "failIfUnavailable": True,
            "filesystem": {
                "allowWrite": [str(d) for d in work_dirs],
                "denyWrite": secrets,
                # In the container, /proc is shared with the sandbox: hide
                # other processes' environments (CLI token, signing key).
                "denyRead": secrets + personal + (["/proc/*/environ"] if nested else []),
                "allowRead": [str(d) for d in work_dirs + read_dirs],
            },
            "network": {"deniedDomains": local_api},
            # Shell commands never see these, even if the CLI needs them.
            "credentials": {"envVars": [
                {"name": n, "mode": "deny"} for n in sorted(ALWAYS_EXCLUDED_ENV | {"CLAUDE_CODE_OAUTH_TOKEN"})
            ]},
            # Inside the runner container the container is the outer boundary:
            # bubblewrap cannot mount a fresh /proc there.
            **({"enableWeakerNestedSandbox": True} if nested else {}),
        },
        "permissions": {
            "deny": list(dict.fromkeys(deny)),
            "additionalDirectories": [str(d) for d in work_dirs + read_dirs],
            "blockReadsOutsideWorkingDirectories": True,
        },
    }


# ---------------------------------------------------------------------------
# Session command — built on the machine that runs the agent (here or runner)
# ---------------------------------------------------------------------------

@dataclass
class SessionSpec:
    """What the control plane asks for; the runner turns it into a command."""

    employee_id: str
    project_id: str
    session_id: str
    is_new: bool
    max_turns: int = 50
    model: str = ""
    plugins: list[str] = field(default_factory=list)
    task_id: str = ""
    project_dir: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionSpec":
        known = {f.name for f in fields(cls)}
        spec = cls(**{k: v for k, v in data.items() if k in known})
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", spec.employee_id or ""):
            raise ValueError("invalid employee_id")
        if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", spec.session_id or ""):
            raise ValueError("invalid session_id")
        return spec


# Variables that must never reach an employee's CLI environment, even when
# they are not in the secret store (runner tokens, signing key).
ALWAYS_EXCLUDED_ENV = {"CLAUDECODE", "ANTHROPIC_API_KEY", "OMC_INTERNAL_KEY", "OMC_RUNNER_TOKEN"}


def control_plane_url() -> str:
    """URL the employee's tools use to reach OneManCompany (the control plane)."""
    return os.environ.get("OMC_CONTROL_URL") or "http://localhost:8000"


async def prepare_session(spec: SessionSpec) -> tuple[list[str], dict[str, str], str]:
    """Return (command, environment, cwd) for an employee's Claude CLI session."""
    if spec.plugins:
        await _ensure_plugins(spec.plugins)
    mcp_config_path = None
    try:
        from onemancompany.tools.mcp.config_builder import write_mcp_config
        mcp_config_path = str(write_mcp_config(
            spec.employee_id, task_id=spec.task_id, project_id=spec.project_id,
            project_dir=spec.project_dir, server_url=control_plane_url(),
        ))
    except Exception as e:  # pragma: no cover
        logger.warning(f"Failed to generate MCP config: {e}")  # pragma: no cover

    cmd = [
        "claude", "--print", "--verbose",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
        "--max-turns", str(spec.max_turns),
    ]
    if spec.model:
        cmd += ["--model", spec.model]
    if mcp_config_path:
        cmd += ["--mcp-config", mcp_config_path]
    # Only the MCP servers OneManCompany grants (--mcp-config): never the
    # CEO's own Claude Code servers, which would otherwise be inherited
    # and usable without confirmation (--dangerously-skip-permissions).
    cmd += ["--strict-mcp-config"]
    # Connector actions the CEO blocked (enforced even without permission prompts)
    try:
        from onemancompany.tools.mcp.config_builder import disallowed_mcp_tools_for
        blocked = disallowed_mcp_tools_for(spec.employee_id)
    except Exception as exc:  # never block a session on a config error
        logger.warning("[claude-daemon] cannot compute blocked tools for {}: {}", spec.employee_id, exc)
        blocked = []
    if blocked:
        cmd += ["--disallowedTools", ",".join(blocked)]
    # Skip the CEO's user-level settings (personal skills, plugins, hooks).
    # Talent plugins are installed at user scope, so employees that need
    # them keep user settings.
    if spec.plugins:
        logger.info("[claude-daemon] {} uses plugins {} — keeping user-level Claude settings",
                    spec.employee_id, spec.plugins)
    else:
        cmd += ["--setting-sources", "project,local"]
    settings = agent_sandbox_settings() or {}
    # Each employee's durable memory (Claude Code auto memory) lives in their
    # own folder: writable inside the sandbox, kept with the company data,
    # and not shared with other employees or the CEO's own ~/.claude.
    memory_dir = EMPLOYEES_DIR / spec.employee_id / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    settings["autoMemoryDirectory"] = str(memory_dir)
    cmd += ["--settings", json.dumps(settings)]
    cmd += ["--session-id", spec.session_id] if spec.is_new else ["--resume", spec.session_id]

    # Claude CLI uses its own auth (OAuth login or CLAUDE_CODE_OAUTH_TOKEN),
    # never the company-level key. Every stored secret is stripped too:
    # employees reach services only through MCP connectors and the API relay.
    from onemancompany.core.secret_store import secret_env_names
    exclude = ALWAYS_EXCLUDED_ENV | secret_env_names()
    env = {k: v for k, v in os.environ.items() if k not in exclude}
    cwd = str(EMPLOYEES_DIR / spec.employee_id)  # CLAUDE.md lives there
    return cmd, env, cwd


class ClaudeDaemon:
    """A persistent Claude CLI process that accepts prompts via stream-json stdin."""

    def __init__(
        self,
        employee_id: str,
        project_id: str,
        session_id: str,
        is_new: bool,
        mcp_config_path: str | None = None,
        work_dir: str = "",
        max_turns: int = 50,
        claude_plugins: list[str] | None = None,
        model: str = "",
        task_id: str = "",
    ) -> None:
        self.employee_id = employee_id
        self.task_id = task_id
        self.project_dir = work_dir
        self.project_id = project_id
        self.session_id = session_id
        self.is_new = is_new
        self.claude_plugins = claude_plugins or []
        self.mcp_config_path = mcp_config_path
        # Always launch from employee directory so CLAUDE.md is picked up;
        # task-specific work_dir is communicated via the prompt instead.
        self.work_dir = str(EMPLOYEES_DIR / employee_id)
        self.max_turns = max_turns
        self.model = model
        self.proc: asyncio.subprocess.Process | None = None
        self._started = False

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def _drain_stderr(self) -> None:
        """Read and log stderr to prevent pipe buffer from filling up."""
        try:
            while self.proc and self.proc.returncode is None:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                text = line.decode(ENCODING_UTF8, errors="replace").strip()
                if text:
                    logger.debug(f"[claude-daemon:stderr] {self.employee_id}: {text[:300]}")
        except asyncio.CancelledError:  # pragma: no cover — async cancellation during stderr drain
            raise  # pragma: no cover
        except Exception as e:  # pragma: no cover
            logger.warning(f"[claude-daemon:stderr] drain failed for {self.employee_id}: {e}")  # pragma: no cover

    def spec(self) -> "SessionSpec":
        return SessionSpec(
            employee_id=self.employee_id, project_id=self.project_id, session_id=self.session_id,
            is_new=self.is_new, max_turns=self.max_turns, model=self.model,
            plugins=list(self.claude_plugins), task_id=self.task_id, project_dir=self.project_dir,
        )

    async def start(self) -> None:
        """Spawn the persistent claude process — here, or on the remote runner."""
        from onemancompany.core.session_process import spawn_session

        mode = "NEW" if self.is_new else "RESUME"
        logger.info(
            f"[claude-daemon] [{mode}] employee={self.employee_id} "
            f"project={self.project_id} session={self.session_id[:8]}…"
        )
        self.proc = await spawn_session(self.spec())
        if not getattr(self.proc, "remote", False):
            _save_running_pid(self.employee_id, self.project_id, self.proc.pid)
        self._started = True
        # Drain stderr in background to prevent pipe buffer deadlock
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        # Drain initial stdout to discard any stale result from --resume
        await self._drain_initial_stdout()
        # After first successful start, future restarts should use --resume
        self.is_new = False

    async def _drain_initial_stdout(self) -> None:
        """Drain any initial stdout output after process start.

        When resuming a session (--resume), Claude CLI may emit messages from
        the previous session (including a stale ``result`` message). If we
        don't consume these before sending the first prompt, ``send_prompt``
        will read the stale result and return immediately.

        Strategy: read lines with a short timeout. Once no more data arrives
        within the timeout window, we assume the initial burst is over.
        """
        if not self.proc or not self.proc.stdout:
            return
        drained = 0
        try:
            while True:
                line = await asyncio.wait_for(
                    self.proc.stdout.readline(), timeout=3.0,
                )
                if not line:
                    # EOF — process exited during drain
                    break
                drained += 1
                line_str = line.decode(ENCODING_UTF8, errors="replace").strip()
                if line_str:
                    try:
                        msg = json.loads(line_str)
                        msg_type = msg.get("type", "")
                        logger.debug(
                            f"[claude-daemon] Drained initial {msg_type} "
                            f"message for employee={self.employee_id}"
                        )
                    except json.JSONDecodeError:
                        logger.debug("[claude-daemon] Drained non-JSON line: {}", line_str[:100])
        except (asyncio.TimeoutError, TimeoutError):
            logger.debug("[claude-daemon] Drain timeout reached — initial drain complete")
        if drained:
            logger.info(
                f"[claude-daemon] Drained {drained} initial message(s) "
                f"for employee={self.employee_id} (stale --resume output)"
            )

    # ------------------------------------------------------------------
    # LLM trace logging — delegate to shared write_llm_trace
    # ------------------------------------------------------------------

    def _write_trace(self, entry: dict) -> None:
        write_llm_trace(self.project_id, entry)

    def _trace_assistant_message(self, message: dict) -> None:
        """Parse an assistant message's content blocks into trace entries."""
        ts = datetime.now(timezone.utc).isoformat()
        model = message.get("model", "")
        usage = message.get("usage", {})
        content = message.get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get(BLOCK_KEY_TYPE, "")
            if btype == BLOCK_TYPE_TEXT:
                self._write_trace({
                    "ts": ts, "employee_id": self.employee_id,
                    "source": "daemon",
                    "role": "assistant", "type": "text",
                    "content": block.get(BLOCK_KEY_TEXT, ""),
                    "model": model, "usage": usage,
                })
            elif btype == "tool_use":
                self._write_trace({
                    "ts": ts, "employee_id": self.employee_id,
                    "source": "daemon",
                    "role": "assistant", "type": "tool_use",
                    "tool_name": block.get("name", ""),
                    "tool_id": block.get("id", ""),
                    "input": block.get("input", {}),
                    "model": model,
                })
            elif btype == "tool_result":
                self._write_trace({
                    "ts": ts, "employee_id": self.employee_id,
                    "source": "daemon",
                    "role": "tool", "type": "tool_result",
                    "tool_id": block.get("tool_use_id", ""),
                    "content": block.get("content", ""),
                    "is_error": block.get("is_error", False),
                })
            elif btype == "thinking":
                self._write_trace({
                    "ts": ts, "employee_id": self.employee_id,
                    "source": "daemon",
                    "role": "assistant", "type": "thinking",
                    "content": block.get(BLOCK_KEY_TEXT, ""),
                    "model": model,
                })

    @staticmethod
    def _accumulate_debug_assistant(debug_messages: list[dict], message: dict) -> None:
        """Parse a Claude daemon assistant message into SFT-format dicts."""
        content_blocks = message.get("content", [])
        text_parts = []
        tool_calls = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                })
            elif btype == "tool_result":
                # Tool results come as separate messages in SFT format
                debug_messages.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": block.get("content", "")
                        if isinstance(block.get("content"), str)
                        else json.dumps(block.get("content", ""), ensure_ascii=False),
                })
        # Build assistant entry only if there's actual content or tool_calls
        if text_parts or tool_calls:
            entry: dict = {"role": "assistant"}
            if text_parts:
                entry["content"] = "\n".join(text_parts)
            if tool_calls:
                entry["tool_calls"] = tool_calls
                if "content" not in entry:  # pragma: no cover
                    entry["content"] = ""  # pragma: no cover
            debug_messages.append(entry)

    def _write_debug_trace(
        self, debug_messages: list[dict], model: str,
        input_tokens: int, output_tokens: int,
    ) -> None:
        """Write a complete Debug trace record for one daemon turn."""
        try:
            from onemancompany.core.llm_trace import write_debug_trace_async
            from onemancompany.core.project_archive import get_project_dir
            project_dir = get_project_dir(self.project_id)
            if not project_dir:
                return
            # Resolve node_id from contextvar if available
            _node_id = ""
            try:
                from onemancompany.core.vessel import _current_task_id
                _node_id = _current_task_id.get("")
            except Exception as _e:  # pragma: no cover
                logger.debug("[debug_trace] failed to resolve node_id: {}", _e)  # pragma: no cover
            write_debug_trace_async(
                project_dir,
                employee_id=self.employee_id,
                node_id=_node_id,
                source="daemon",
                messages=debug_messages,
                model=model,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            )
        except Exception as e:
            logger.debug("[debug_trace] daemon write failed for {}: {}", self.employee_id, e)

    async def send_prompt(
        self,
        prompt: str,
        timeout: int = 600,
        on_log: Callable[[str, object], None] | None = None,
    ) -> dict:
        """Send a prompt and collect the full response.

        Reads NDJSON lines from stdout until a ``result`` message appears.
        Returns dict with keys: output, model, input_tokens, output_tokens.

        ``on_log(type, content)`` is called live per LLM step (assistant text,
        tool_call, tool_result) so the CEO can see the self-hosted agent working
        instead of a long silence. Mirrors the LangChain path's on_log schema.
        """
        if not self.alive:
            raise RuntimeError("Daemon process is not running")

        # Log user prompt
        self._write_trace({
            "ts": datetime.now(timezone.utc).isoformat(),
            "employee_id": self.employee_id,
            "source": "daemon",
            "role": "user", "type": "prompt",
            "content": prompt,
        })

        # Send user message via stdin
        msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        })
        self.proc.stdin.write(msg.encode(ENCODING_UTF8) + b"\n")
        await self.proc.stdin.drain()

        # Collect response
        text_parts: list[str] = []
        result_text = ""
        total_input_tokens = 0
        total_output_tokens = 0
        model_used = ""
        # Debug trace: accumulate structured messages for this turn
        debug_messages: list[dict] = [{"role": "user", "content": prompt}]

        try:
            async with asyncio.timeout(timeout):
                while True:
                    line = await self.proc.stdout.readline()
                    if not line:  # pragma: no cover
                        # Process exited
                        break  # pragma: no cover
                    line_str = line.decode(ENCODING_UTF8, errors="replace").strip()
                    if not line_str:
                        continue
                    try:
                        msg_data = json.loads(line_str)
                    except json.JSONDecodeError:
                        logger.debug(f"[claude-daemon] non-JSON line: {line_str[:200]}")
                        continue

                    msg_type = msg_data.get("type", "")

                    if msg_type == "stream_event":
                        # Extract text deltas for streaming
                        event = msg_data.get("event", {})
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text_parts.append(delta.get("text", ""))
                        # Extract usage from message_delta events
                        elif event.get("type") == "message_delta":
                            usage = event.get("usage", {})
                            if usage.get("output_tokens"):
                                total_output_tokens = usage["output_tokens"]

                    elif msg_type == "assistant":
                        # Complete assistant message — extract text and usage
                        message = msg_data.get("message", {})
                        # Trace full assistant message (text, tool_use, thinking)
                        self._trace_assistant_message(message)
                        content = message.get("content", [])
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            _btype = block.get(BLOCK_KEY_TYPE)
                            if _btype == BLOCK_TYPE_TEXT:
                                _text = block.get(BLOCK_KEY_TEXT, "")
                                text_parts.append(_text)
                                if on_log and _text.strip():
                                    on_log("llm_output", _text)
                            elif _btype == "tool_use" and on_log:
                                _tname = block.get("name", "tool")
                                _targs = block.get("input", {})
                                on_log("tool_call", {
                                    "tool_name": _tname,
                                    "tool_args": _targs,
                                    "content": _fmt_tool_call(_tname, _targs),
                                })
                        # Extract usage
                        usage = message.get("usage", {})
                        if usage.get("input_tokens"):
                            total_input_tokens += usage["input_tokens"]
                        if usage.get("output_tokens"):
                            total_output_tokens = max(total_output_tokens, usage["output_tokens"])
                        if message.get("model"):
                            model_used = message["model"]
                        # SFT: capture assistant message with tool_calls
                        self._accumulate_debug_assistant(debug_messages, message)

                    elif msg_type == "user" and on_log:
                        # Tool results come back as user-role messages; surface
                        # them live so the CEO sees tool activity completing.
                        umsg = msg_data.get("message", {})
                        for block in umsg.get("content", []) or []:
                            if not isinstance(block, dict) or block.get(BLOCK_KEY_TYPE) != "tool_result":
                                continue
                            _res = block.get("content", "")
                            if isinstance(_res, list):
                                _res = " ".join(
                                    b.get("text", "") for b in _res
                                    if isinstance(b, dict) and b.get("text")
                                )
                            _res = str(_res)
                            on_log("tool_result", {
                                "tool_result": _res,
                                "content": _res[:500],
                            })

                    elif msg_type == "result":
                        # Final result — response complete
                        result_text = msg_data.get("result", "")
                        # result message may also carry usage/cost info
                        if msg_data.get("input_tokens"):
                            total_input_tokens = max(total_input_tokens, msg_data["input_tokens"])
                        if msg_data.get("output_tokens"):
                            total_output_tokens = max(total_output_tokens, msg_data["output_tokens"])
                        if msg_data.get("model"):
                            model_used = msg_data["model"]
                        # Trace result summary
                        self._write_trace({
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "employee_id": self.employee_id,
                            "source": "daemon",
                            "role": "system", "type": "result",
                            "content": result_text or "",
                            "model": model_used,
                            "usage": {
                                "input_tokens": total_input_tokens,
                                "output_tokens": total_output_tokens,
                            },
                        })
                        # Write Debug trace for this turn
                        self._write_debug_trace(
                            debug_messages, model_used,
                            total_input_tokens, total_output_tokens,
                        )
                        _mark_session_used(self.employee_id, self.project_id)
                        break

        except (asyncio.TimeoutError, TimeoutError):
            logger.warning(
                f"[claude-daemon] Timeout after {timeout}s for "
                f"employee={self.employee_id}"
            )
            return {"output": f"[claude-daemon timeout] {timeout}s exceeded",
                    "model": "", "input_tokens": 0, "output_tokens": 0}

        # Prefer result text, fall back to accumulated text deltas
        output = result_text or "".join(text_parts)
        return {
            "output": output.strip(),
            "model": model_used,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        }

    async def stop(self) -> None:
        """Terminate the daemon process gracefully."""
        if hasattr(self, "_stderr_task") and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                logger.debug("[claude-daemon] stderr task cancelled for employee={}", self.employee_id)
        if self.proc and self.proc.returncode is None:
            logger.info(
                f"[claude-daemon] Stopping employee={self.employee_id} "
                f"pid={self.proc.pid}"
            )
            try:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5)
                except (asyncio.TimeoutError, TimeoutError):
                    self.proc.kill()
            except ProcessLookupError:
                logger.debug("Process already exited for employee={} project={}", self.employee_id, self.project_id)
        _clear_running_pid(self.employee_id, self.project_id)
        _remove_session_lock(self.employee_id, self.project_id)
        self.proc = None


async def _get_or_start_daemon(
    employee_id: str,
    project_id: str,
    work_dir: str = "",
    max_turns: int = 50,
    task_id: str = "",
) -> ClaudeDaemon:
    """Get an existing daemon or start a new one for this employee+project."""
    key = f"{employee_id}:{project_id}"

    daemon = _daemons.get(key)
    if daemon and daemon.alive:
        return daemon

    # Clean up dead daemon
    if daemon:
        await daemon.stop()

    # Load claude_plugins and model from employee profile
    from onemancompany.core.config import load_employee_profile_yaml, employee_configs
    _profile = load_employee_profile_yaml(employee_id)
    claude_plugins = _profile.get("claude_plugins", [])
    _cfg = employee_configs.get(employee_id)
    llm_model = _cfg.llm_model if _cfg and _cfg.llm_model else ""

    # Try to start daemon (may resume existing session)
    session_id, is_new = get_or_create_session(employee_id, project_id, work_dir=work_dir)

    daemon = ClaudeDaemon(
        employee_id=employee_id,
        project_id=project_id,
        session_id=session_id,
        is_new=is_new,
        work_dir=work_dir,
        max_turns=max_turns,
        claude_plugins=claude_plugins,
        model=llm_model,
        task_id=task_id,
    )
    await daemon.start()

    # If process died during startup/drain (common with --resume: CLI outputs
    # the old result then exits), restart with a fresh session.
    if not daemon.alive:
        logger.warning(
            f"[claude-daemon] Process died after start (--resume output "
            f"consumed). Restarting with new session for employee={employee_id}"
        )
        await daemon.stop()
        new_session_id = str(uuid.uuid4())
        sessions = _load_sessions(employee_id)
        sessions[project_id] = {
            _KEY_SESSION_ID: new_session_id,
            _KEY_WORK_DIR: work_dir,
            _KEY_CREATED: datetime.now(timezone.utc).isoformat(),
            _KEY_USED: False,
        }
        _save_sessions(employee_id, sessions)

        daemon = ClaudeDaemon(
            employee_id=employee_id,
            project_id=project_id,
            session_id=new_session_id,
            is_new=True,
            work_dir=work_dir,
            max_turns=max_turns,
            claude_plugins=claude_plugins,
            model=llm_model,
            task_id=task_id,
        )
        await daemon.start()

    _daemons[key] = daemon
    return daemon


# ---------------------------------------------------------------------------
# Public API — drop-in replacement for the old run_claude_session
# ---------------------------------------------------------------------------

async def run_claude_session(
    employee_id: str,
    project_id: str,
    prompt: str,
    work_dir: str = "",
    max_turns: int = 50,
    timeout: int = 600,
    task_id: str = "",
    on_log: Callable[[str, object], None] | None = None,
) -> dict:
    """Send a prompt to the employee's persistent Claude daemon.

    If no daemon is running, one is started automatically.
    If the daemon died, it is restarted with --resume.

    Returns dict: {output, model, input_tokens, output_tokens}
    """
    _empty = {"output": "", "model": "", "input_tokens": 0, "output_tokens": 0}
    lock = _get_session_lock(employee_id, project_id)

    async with lock:
        try:
            daemon = await _get_or_start_daemon(
                employee_id, project_id, work_dir, max_turns, task_id,
            )
            result = await daemon.send_prompt(prompt, timeout=timeout, on_log=on_log)

            # If daemon died during execution, try once more with restart
            if not daemon.alive and not result.get("output"):
                logger.warning(
                    f"[claude-daemon] Process died during execution, "
                    f"restarting for employee={employee_id}"
                )
                daemon = await _get_or_start_daemon(
                    employee_id, project_id, work_dir, max_turns, task_id,
                )
                result = await daemon.send_prompt(prompt, timeout=timeout, on_log=on_log)

            return result
        except FileNotFoundError:
            return {**_empty, "output": "[claude-daemon error] `claude` CLI not found on PATH"}
        except Exception as e:
            logger.error(f"[claude-daemon] Error for employee={employee_id}: {e}")
            return {**_empty, "output": f"[claude-daemon error] {e}"}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def stop_all_daemons() -> int:
    """Stop all running daemon processes. Called on server shutdown."""
    count = 0
    for key, daemon in list(_daemons.items()):
        await daemon.stop()
        count += 1
    _daemons.clear()
    return count


async def stop_employee_daemons(employee_ids: set[str] | list[str]) -> int:
    """Stop the running CLI processes of these employees.

    The next message starts a new process (resuming the same session) with
    a freshly built MCP config — used when the CEO changes connector access.
    """
    wanted = {str(e) for e in employee_ids}
    count = 0
    for key, daemon in list(_daemons.items()):
        if key.split(":", 1)[0] in wanted:
            await daemon.stop()
            _daemons.pop(key, None)
            count += 1
    return count


def cleanup_orphan_sessions() -> int:
    """Kill orphaned claude session processes from a previous server run."""
    import signal

    killed = 0
    if not EMPLOYEES_DIR.exists():
        return killed

    for emp_dir in sorted(EMPLOYEES_DIR.iterdir()):
        if not emp_dir.is_dir():
            continue
        employee_id = emp_dir.name
        sessions = _load_sessions(employee_id)
        dirty = False
        for project_id, entry in sessions.items():
            pid = entry.get(_KEY_RUNNING_PID)
            if pid is None:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                killed += 1
                logger.info(
                    f"[session-cleanup] Killed orphan PID {pid} "
                    f"(employee={employee_id} project={project_id}) "
                    f"— session preserved for --resume"
                )
            except ProcessLookupError:
                logger.debug(
                    f"[session-cleanup] PID {pid} already gone "
                    f"(employee={employee_id})"
                )
            except PermissionError:
                logger.warning(
                    f"[session-cleanup] No permission to kill PID {pid} "
                    f"(employee={employee_id})"
                )
            del entry[_KEY_RUNNING_PID]
            dirty = True
        if dirty:
            _save_sessions(employee_id, sessions)

    return killed


# ---------------------------------------------------------------------------
# Query helpers (unchanged)
# ---------------------------------------------------------------------------

def list_sessions(employee_id: str) -> list[dict]:
    """Return all sessions for an employee."""
    sessions = _load_sessions(employee_id)
    result = []
    for pid, entry in sessions.items():
        result.append({
            "project_id": pid,
            _KEY_SESSION_ID: entry.get(_KEY_SESSION_ID, ""),
            _KEY_WORK_DIR: entry.get(_KEY_WORK_DIR, ""),
            _KEY_CREATED: entry.get(_KEY_CREATED, ""),
            _KEY_USED: entry.get(_KEY_USED, False),
        })
    return result


def cleanup_session(employee_id: str, project_id: str) -> None:
    """Remove a session record (does not delete Claude's session files)."""
    sessions = _load_sessions(employee_id)
    if project_id in sessions:
        del sessions[project_id]
        _save_sessions(employee_id, sessions)


def get_daemon_status() -> list[dict]:
    """Return status of all active daemons (for monitoring)."""
    result = []
    for daemon_key, daemon in _daemons.items():
        result.append({
            "key": daemon_key,
            "employee_id": daemon.employee_id,
            "project_id": daemon.project_id,
            "session_id": daemon.session_id[:8] + "…",
            "alive": daemon.alive,
            "pid": daemon.proc.pid if daemon.proc else None,
        })
    return result
