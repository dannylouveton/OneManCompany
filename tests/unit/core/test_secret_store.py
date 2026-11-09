"""Secret store (dotenv backend) and secret stripping for employee sessions."""
from __future__ import annotations

import os
import stat

from onemancompany.core.secret_store import DotEnvSecretStore, masked


def test_set_get_delete_and_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv("ACME_KEY", raising=False)
    store = DotEnvSecretStore(tmp_path / ".env")
    (tmp_path / ".env").write_text("HOST=127.0.0.1\n", encoding="utf-8")
    store.set_many({"ACME_KEY": "abc123456789", "EMPTY": ""})
    assert store.get("ACME_KEY") == "abc123456789"
    assert store.names() == {"HOST", "ACME_KEY"}
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600
    store.set_many({"ACME_KEY": "new-value-9999"})
    assert (tmp_path / ".env").read_text().count("ACME_KEY=") == 1
    store.delete("ACME_KEY")
    assert store.get("ACME_KEY") is None and "ACME_KEY" not in os.environ


def test_masked():
    assert masked("sk_live_1234567890") == "••••7890"
    assert masked("short") == "••••"
    assert masked("") == ""


def test_session_env_strips_secrets(monkeypatch):
    import inspect
    from onemancompany.core import claude_session

    assert "secret_env_names()" in inspect.getsource(claude_session.ClaudeDaemon.start)


def test_caller_signature(tmp_path, monkeypatch):
    from onemancompany.core import secret_store

    store = secret_store.DotEnvSecretStore(tmp_path / ".env")
    monkeypatch.setattr(secret_store, "get_secret_store", lambda: store)
    monkeypatch.delenv(secret_store.INTERNAL_KEY_NAME, raising=False)
    assert secret_store.caller_signature("00006") == ""
    assert not secret_store.verify_caller("00006", "")
    secret_store.ensure_internal_key()
    sig = secret_store.caller_signature("00006")
    assert secret_store.verify_caller("00006", sig)
    assert not secret_store.verify_caller("00004", sig)
    assert not secret_store.verify_caller("00006", None)
    monkeypatch.delenv(secret_store.INTERNAL_KEY_NAME, raising=False)
