"""EA chat routing: Claude Code employees answer through their CLI session."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onemancompany.core.conversation import Conversation, Message
from onemancompany.core.conversation_adapters import ClaudeSessionAdapter, LangChainAdapter


def _conv():
    return Conversation(id="c1", type="ea_chat", phase="active", employee_id="00004", tools_enabled=True)


def _msg(text="Introduce yourself in one sentence."):
    return Message(sender="ceo", role="CEO", text=text, timestamp="2026-11-09T00:00:00")


@pytest.mark.asyncio
async def test_claude_session_ea_chat_uses_executor():
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=MagicMock(output="Bonjour, je suis l'EA."))
    adapter = ClaudeSessionAdapter()
    with patch("onemancompany.core.conversation_adapters._get_employee_executor", return_value=executor), \
         patch("onemancompany.core.conversation_adapters._resolve_conversation_work_dir", return_value="/tmp"), \
         patch.object(adapter, "_send_ea_chat", new=AsyncMock()) as direct:
        reply = await adapter.send(_conv(), [], _msg())
    assert reply == "Bonjour, je suis l'EA."
    executor.execute.assert_awaited_once()
    direct.assert_not_awaited()
    prompt = executor.execute.await_args.args[0]
    assert "Executive Assistant" in prompt


@pytest.mark.asyncio
async def test_langchain_ea_chat_keeps_direct_agent():
    adapter = LangChainAdapter()
    with patch.object(adapter, "_send_ea_chat", new=AsyncMock(return_value="ok")) as direct:
        assert await adapter.send(_conv(), [], _msg()) == "ok"
    direct.assert_awaited_once()


def test_conversation_prompt_includes_language_directive(monkeypatch):
    from onemancompany.core import config as config_mod
    from onemancompany.core.conversation_adapters import _build_conversation_prompt

    monkeypatch.setattr(config_mod, "load_app_config", lambda: {"language": "fr"})
    prompt = _build_conversation_prompt(_conv(), [], _msg())
    assert prompt.startswith("## Working Language")
