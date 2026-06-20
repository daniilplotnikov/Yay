import pytest
import asyncio
from unittest.mock import AsyncMock

from yay.agent import Agent, SuspensionReason


@pytest.fixture
def bus():
    bus = AsyncMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def provider():
    return AsyncMock()


@pytest.fixture
def context():
    class Ctx:
        def __init__(self):
            self.messages = []
            self.compression_callback = None
            self._compression_tasks = set()

        def append(self, msg):
            self.messages.append(msg)

        def estimate_tokens(self):
            return 0

        @property
        def max_tokens(self):
            return 128000

        def needs_compression(self):
            return False

    return Ctx()


@pytest.fixture
def tool_executor():
    exec = AsyncMock()
    exec.run_tool = AsyncMock(return_value={"ok": True})
    exec.normalize_result = lambda x: str(x)
    return exec


@pytest.fixture
def agent(bus, provider, context, tool_executor):
    return Agent(
        bus=bus,
        provider=provider,
        context=context,
        tools_manager=AsyncMock(),
        tool_executor=tool_executor,
    )


@pytest.mark.asyncio
async def test_agent_suspension_approval(agent):
    async def resume_later():
        await asyncio.sleep(0.01)
        agent.resume_with_approval(True)

    asyncio.create_task(resume_later())
    result = await agent._suspend(SuspensionReason.APPROVAL, {"tool": "x"})
    assert result is True


@pytest.mark.asyncio
async def test_agent_suspension_question(agent):
    async def resume_later():
        await asyncio.sleep(0.01)
        agent.resume_with_answer("42")

    asyncio.create_task(resume_later())
    result = await agent._suspend(SuspensionReason.QUESTION, {"q": "what?"})
    assert result == "42"


@pytest.mark.asyncio
async def test_suspension_timeout(agent):
    with pytest.raises(TimeoutError, match="timed out"):
        await agent._suspend(SuspensionReason.APPROVAL, timeout=0.05)


@pytest.mark.asyncio
async def test_suspension_timeout_clears_suspension(agent):
    with pytest.raises(TimeoutError):
        await agent._suspend(SuspensionReason.APPROVAL, timeout=0.01)
    assert agent.suspension is None


@pytest.mark.asyncio
async def test_resume_with_approval_when_not_suspended(agent):
    # Should not raise, just silently do nothing
    agent.resume_with_approval(True)
    assert agent.suspension is None


@pytest.mark.asyncio
async def test_resume_with_answer_when_not_suspended(agent):
    # Should not raise, just silently do nothing
    agent.resume_with_answer("hello")
    assert agent.suspension is None


@pytest.mark.asyncio
async def test_resume_with_approval_wrong_reason(agent):
    from yay.agent import Suspension
    agent.suspension = Suspension()
    agent.suspension.reason = SuspensionReason.QUESTION
    agent.resume_with_approval(True)
    # Should not set output since reason doesn't match
    assert agent.suspension.output is None


@pytest.mark.asyncio
async def test_resume_with_answer_wrong_reason(agent):
    from yay.agent import Suspension
    agent.suspension = Suspension()
    agent.suspension.reason = SuspensionReason.APPROVAL
    agent.resume_with_answer("hello")
    # Should not set output since reason doesn't match
    assert agent.suspension.output is None


@pytest.mark.asyncio
async def test_suspension_stores_input_payload(agent):
    from yay.agent import Suspension
    agent.suspension = Suspension()
    agent.suspension.reason = SuspensionReason.APPROVAL
    agent.suspension.input = {"tool": "test"}
    assert agent.suspension.input == {"tool": "test"}


@pytest.mark.asyncio
async def test_suspension_clears_after_resume(agent):
    async def resume_later():
        await asyncio.sleep(0.01)
        agent.resume_with_approval(True)

    asyncio.create_task(resume_later())
    await agent._suspend(SuspensionReason.APPROVAL)
    assert agent.suspension is None
