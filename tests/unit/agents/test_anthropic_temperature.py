"""Claude 5+ models reject the temperature parameter."""
from __future__ import annotations

import pytest


class TestAnthropicTemperature:
    @pytest.mark.parametrize(
        "model,expected",
        [("claude-opus-5-5", False), ("claude-sonnet-5-5", False), ("claude-haiku-5-5", False),
         ("claude-sonnet-4-20250514", True), ("claude-3-5-haiku-latest", True), ("", True)],
    )
    def test_accepts_temperature(self, model, expected):
        from onemancompany.agents.base import _anthropic_accepts_temperature

        assert _anthropic_accepts_temperature(model) is expected
