import pytest
from unittest.mock import AsyncMock


class FakeAgent:
    def __init__(self):
        self.bus = AsyncMock()
        self.provider = AsyncMock()
        self.context = AsyncMock()
        self.tool_executor = AsyncMock()

    def _extract_tool_calls(self, response):
        return []

    async def _stream_chunk(self, c):
        return None


@pytest.mark.asyncio
async def test_tool_execution_flow():
    from yay.workflow.default import DefaultAgentStep
    from yay.workflow import WorkflowContext

    agent = FakeAgent()
    step = DefaultAgentStep()
    ctx = WorkflowContext()

    response = AsyncMock()
    response.content = type("obj", (), {"text": "hello"})()

    agent.provider.process_stream = AsyncMock(return_value=response)

    agent._extract_tool_calls = lambda r: []

    result = await step.run(agent, ctx)

    assert result.result == "hello"

    agent.bus.emit.assert_called()