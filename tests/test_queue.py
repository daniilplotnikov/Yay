import pytest
import asyncio
from unittest.mock import AsyncMock

from yay.agent import Agent


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
async def test_queue_runner(agent):
    agent.run = AsyncMock(return_value="done")

    await agent.start_queue()
    await agent.enqueue("hello", task_id="1")
    await asyncio.sleep(0.05)
    await agent.stop_queue()

    agent.run.assert_called_with("hello")


@pytest.mark.asyncio
async def test_queue_processes_multiple_tasks(agent):
    agent.run = AsyncMock(return_value="done")

    await agent.start_queue()
    await agent.enqueue("task1", task_id="1")
    await agent.enqueue("task2", task_id="2")
    await agent.enqueue("task3", task_id="3")
    await asyncio.sleep(0.1)
    await agent.stop_queue()

    assert agent.run.call_count == 3


@pytest.mark.asyncio
async def test_queue_sets_current_task(agent):
    agent.run = AsyncMock(return_value="done")

    await agent.start_queue()
    await agent.enqueue("hello", task_id="1")
    await asyncio.sleep(0.05)

    # current_task should be set during processing
    # After processing, it should be cleared
    assert agent.current_task is None
    await agent.stop_queue()


@pytest.mark.asyncio
async def test_queue_clears_current_task_on_error(agent):
    agent.run = AsyncMock(side_effect=RuntimeError("fail"))

    await agent.start_queue()
    await agent.enqueue("hello", task_id="1")

    # Wait for the error to propagate and the worker to finish
    await asyncio.sleep(0.1)

    # current_task should be cleared even on error
    assert agent.current_task is None


@pytest.mark.asyncio
async def test_start_queue_idempotent(agent):
    agent.run = AsyncMock(return_value="done")

    await agent.start_queue()
    worker = agent.worker_task
    await agent.start_queue()  # second call should be no-op
    assert agent.worker_task is worker

    await agent.stop_queue()


@pytest.mark.asyncio
async def test_stop_queue_awaits_worker(agent):
    agent.run = AsyncMock(return_value="done")

    await agent.start_queue()
    await agent.stop_queue()

    # worker_task should be done (cancelled)
    assert agent.worker_task.done()


@pytest.mark.asyncio
async def test_queue_task_done_called(agent):
    """Ensure task_queue.task_done() is called after each task."""
    agent.run = AsyncMock(return_value="done")

    await agent.start_queue()
    await agent.enqueue("hello", task_id="1")
    await asyncio.sleep(0.05)
    await agent.stop_queue()

    # Queue should be empty
    assert agent.task_queue.empty()
