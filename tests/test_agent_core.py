"""Tests for Agent core functionality: run, events, error handling, is_paused."""
import pytest
from unittest.mock import AsyncMock, ANY

from yay.agent import Agent, SuspensionReason
from yay.llm import Content, Message
from yay.events import (
    TaskStartedEvent,
    TaskFinishedEvent,
    TaskErrorEvent,
    ContextCompressedEvent,
)


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
    return agent


@pytest.mark.asyncio
async def test_agent_run_emits_task_started(agent, bus):
    await agent.run("hello")
    # First emit should be TaskStartedEvent
    first_call = bus.emit.call_args_list[0]
    assert isinstance(first_call[0][0], TaskStartedEvent)


@pytest.mark.asyncio
async def test_agent_run_emits_task_finished_on_success(agent, bus):
    agent.runner.run = AsyncMock(return_value="result")
    result = await agent.run("hello")
    assert result == "result"
    # Should emit TaskFinishedEvent with the result
    finished_calls = [
        c for c in bus.emit.call_args_list
        if isinstance(c[0][0], TaskFinishedEvent)
    ]
    assert len(finished_calls) == 1
    assert finished_calls[0][0][0].result == "result"


@pytest.mark.asyncio
async def test_agent_run_emits_task_error_on_exception(agent, bus):
    agent.runner.run = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await agent.run("hello")
    error_calls = [
        c for c in bus.emit.call_args_list
        if isinstance(c[0][0], TaskErrorEvent)
    ]
    assert len(error_calls) == 1


@pytest.mark.asyncio
async def test_agent_run_appends_user_message(agent, bus, context):
    await agent.run("my prompt")
    assert any(
        m.role == "user" and m.content.text == "my prompt"
        for m in context.messages
    )


@pytest.mark.asyncio
async def test_agent_run_re_raises_after_emitting_error(agent, bus):
    agent.runner.run = AsyncMock(side_effect=ValueError("test error"))
    with pytest.raises(ValueError, match="test error"):
        await agent.run("hello")


def test_is_paused_false_when_no_suspension(agent):
    assert agent.is_paused is False


def test_is_paused_true_when_suspended(agent):
    agent.suspension = agent.__class__.__dict__.get  # just check the property
    from yay.agent import Suspension
    agent.suspension = Suspension()
    assert agent.is_paused is True


def test_is_paused_false_after_resume(agent):
    from yay.agent import Suspension
    agent.suspension = Suspension()
    agent.suspension.reason = SuspensionReason.APPROVAL
    agent.suspension.output = True
    agent._resume_event.set()
    # After suspension is cleared
    agent.suspension = None
    assert agent.is_paused is False
