import pytest
from unittest.mock import AsyncMock, ANY

from yay.agent import Agent


@pytest.mark.asyncio
async def test_agent_run_uses_workflow(bus, provider, context, tool_executor):
    from yay.workflow import Workflow

    wf = Workflow()
    wf.node("a", AsyncMock(run=AsyncMock(return_value=None)))

    agent = Agent(
        bus=bus,
        provider=provider,
        context=context,
        tools_manager=AsyncMock(),
        tool_executor=tool_executor,
        workflow=wf,
    )

    agent.runner.run = AsyncMock(return_value="OK")

    result = await agent.run("hello")

    assert result == "OK"
    bus.emit.assert_any_call(ANY)