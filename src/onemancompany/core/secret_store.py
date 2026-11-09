"""Secret store — where API keys and tokens live.

Every secret OneManCompany keeps (provider keys, connector tokens, API keys
given to employees) goes through this module, so the backend can be swapped
without touching callers:

* ``dotenv`` (default, local install): ``.onemancompany/.env``, file mode 0600.
  Employees never read it directly: their CLI sessions get an environment
  without these variables and a sandbox that denies reading the file.
* A hosted deployment would plug in a KMS / Vault backend implementing the
  same four methods (envelope encryption, per-tenant keys).

Secrets are write-only from the UI: callers display ``masked()`` values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set_many(self, values: dict[str, str]) -> None: ...
    def delete(self, name: str) -> None: ...
    def names(self) -> set[str]: ...


def masked(value: str | None) -> str:
    """Display form of a secret: last 4 characters only."""
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"


class DotEnvSecretStore:
    """Secrets in the company .env file (0600), mirrored into the server process env."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        if self._path is not None:
            return self._path
        from onemancompany.core.config import DATA_ROOT, DOT_ENV_FILENAME

        return DATA_ROOT / DOT_ENV_FILENAME

    def _read(self) -> dict[str, str]:
        from dotenv import dotenv_values

        if not self.path.exists():
            return {}
        return {k: v for k, v in dotenv_values(self.path).items() if v is not None}

    def get(self, name: str) -> str | None:
        return self._read().get(name) or os.environ.get(name) or None

    def names(self) -> set[str]:
        return set(self._read())

    def _write_lines(self, lines: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError as exc:  # pragma: no cover - non-POSIX filesystems
            from loguru import logger

            logger.warning("Cannot restrict permissions of {}: {}", self.path, exc)

    def set_many(self, values: dict[str, str]) -> None:
        values = {k: v for k, v in values.items() if v}
        if not values:
            return
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
        done: set[str] = set()
        for i, line in enumerate(lines):
            key = line.split("=", 1)[0].strip()
            if key in values:
                lines[i] = f"{key}={values[key]}"
                done.add(key)
        lines += [f"{k}={v}" for k, v in values.items() if k not in done]
        self._write_lines(lines)
        os.environ.update(values)

    def delete(self, name: str) -> None:
        if self.path.exists():
            lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines()
                     if ln.split("=", 1)[0].strip() != name]
            self._write_lines(lines)
        os.environ.pop(name, None)


_BACKENDS = {"dotenv": DotEnvSecretStore}


def get_secret_store() -> SecretStore:
    """Backend chosen by config.yaml ``secret_store`` (default: dotenv)."""
    from onemancompany.core.config import load_app_config

    backend = str(load_app_config().get("secret_store") or "dotenv")
    factory = _BACKENDS.get(backend)
    if factory is None:
        raise RuntimeError(f"Unknown secret_store backend: {backend}")
    return factory()


def secret_env_names() -> set[str]:
    """Environment variable names that hold secrets and must not reach employees."""
    try:
        return get_secret_store().names()
    except Exception:  # never break session start on a store error
        return set()


# ---------------------------------------------------------------------------
# Caller identity for internal tool calls
# ---------------------------------------------------------------------------
# Tool calls reach the server through /api/internal/tool-call. The caller
# (OneManCompany's MCP server or the ACP subprocess) signs the employee id
# with a company key that employees cannot read (stripped from their
# environment, .env denied by the sandbox), so an employee cannot act as
# another one by changing employee_id.

INTERNAL_KEY_NAME = "OMC_INTERNAL_KEY"
CALLER_HEADER = "X-OMC-Caller"


def ensure_internal_key() -> str:
    store = get_secret_store()
    key = store.get(INTERNAL_KEY_NAME)
    if not key:
        import secrets as _secrets

        key = _secrets.token_hex(32)
        store.set_many({INTERNAL_KEY_NAME: key})
    return key


def caller_signature(employee_id: str) -> str:
    import hashlib
    import hmac

    key = get_secret_store().get(INTERNAL_KEY_NAME) or ""
    if not key:
        return ""
    return hmac.new(key.encode(), f"caller:{employee_id}".encode(), hashlib.sha256).hexdigest()


def verify_caller(employee_id: str, signature: str | None) -> bool:
    import hmac

    expected = caller_signature(employee_id)
    return bool(expected and signature) and hmac.compare_digest(expected, str(signature))
