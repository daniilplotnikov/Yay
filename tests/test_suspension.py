import pytest
import asyncio
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_agent_suspension(bus, provider, context, tool_executor):
    from yay.agent import Agent, SuspensionReason

    agent = Agent(
        bus=bus,
        provider=provider,
        context=context,
        tools_manager=AsyncMock(),
        tool_executor=tool_executor,
    )

    async def resume_later():
        await asyncio.sleep(0.01)
        agent.resume_with_approval(True)

    asyncio.create_task(resume_later())

    result = await agent._suspend(SuspensionReason.APPROVAL, {"tool": "x"})

    assert result is True