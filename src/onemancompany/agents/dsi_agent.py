"""DSI Agent — the founding head of IT, when the company runs it in LangChain.

The DSI runs the access desk and the company vault (access_tools, vault_tools).
Its number is not fixed (core/founding.py): the class reads it from config.
Everything it must know is in its role_guide.md, loaded by build_role_identity().
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from onemancompany.agents.base import BaseAgentRunner, extract_final_content, make_llm
from onemancompany.core.config import MAX_SUMMARY_LEN, STATUS_IDLE, STATUS_WORKING


class DSIAgent(BaseAgentRunner):
    role = "DSI"

    def __init__(self) -> None:
        from onemancompany.core import config
        from onemancompany.core.tool_registry import tool_registry

        self.employee_id = config.DSI_ID
        self._agent_tools = tool_registry.get_proxied_tools_for(self.employee_id)
        self._agent = create_react_agent(
            model=make_llm(self.employee_id),
            tools=self._agent_tools,
        )

    def _customize_prompt(self, pb) -> None:
        pass  # All DSI prompt content is in role_guide.md

    async def run(self, task: str) -> str:
        self._set_status(STATUS_WORKING)
        await self._publish("agent_thinking", {"message": f"DSI analyzing: {task}"})

        result = await self._agent.ainvoke(
            {"messages": [
                SystemMessage(content=self._build_full_prompt()),
                HumanMessage(content=task),
            ]}
        )

        self._extract_and_record_usage(result)
        final = extract_final_content(result)
        self._set_status(STATUS_IDLE)
        await self._publish("agent_done", {"role": "DSI", "summary": final[:MAX_SUMMARY_LEN]})
        return final
