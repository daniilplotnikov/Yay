import pytest
import asyncio
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_queue_runner(bus, provider, context, tool_executor):
    from yay.agent import Agent

    agent = Agent(
        bus=bus,
        provider=provider,
        context=context,
        tools_manager=AsyncMock(),
        tool_executor=tool_executor,
    )

    agent.run = AsyncMock(return_value="done")

    await agent.start_queue()

    await agent.enqueue("hello", task_id="1")

    await asyncio.sleep(0.05)

    await agent.stop_queue()

    agent.run.assert_called_with("hello")