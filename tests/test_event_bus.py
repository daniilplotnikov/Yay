"""Tests for EventBus: emit, subscribe, error handling, type validation."""
import pytest
from unittest.mock import AsyncMock

from yay.events import EventBus, Event
from yay.events.types import ErrorEvent, TaskStartedEvent


@pytest.fixture
def bus():
    return EventBus()


def test_subscribe_decorator(bus):
    @bus.subscribe(TaskStartedEvent)
    async def handler(event):
        pass

    assert handler in bus._handlers[TaskStartedEvent]


def test_subscribe_multiple_handlers(bus):
    @bus.subscribe(TaskStartedEvent)
    async def handler1(event):
        pass

    @bus.subscribe(TaskStartedEvent)
    async def handler2(event):
        pass

    assert len(bus._handlers[TaskStartedEvent]) == 2


@pytest.mark.asyncio
async def test_emit_no_handlers(bus):
    """Emit with no handlers should not raise."""
    await bus.emit(TaskStartedEvent(prompt="test"))


@pytest.mark.asyncio
async def test_emit_calls_async_handler(bus):
    received = []

    @bus.subscribe(TaskStartedEvent)
    async def handler(event):
        received.append(event)

    await bus.emit(TaskStartedEvent(prompt="hello"))
    assert len(received) == 1
    assert received[0].prompt == "hello"


@pytest.mark.asyncio
async def test_emit_calls_sync_handler(bus):
    received = []

    @bus.subscribe(TaskStartedEvent)
    def handler(event):
        received.append(event)

    await bus.emit(TaskStartedEvent(prompt="hello"))
    assert len(received) == 1


@pytest.mark.asyncio
async def test_emit_calls_multiple_handlers(bus):
    count = 0

    @bus.subscribe(TaskStartedEvent)
    async def handler1(event):
        nonlocal count
        count += 1

    @bus.subscribe(TaskStartedEvent)
    async def handler2(event):
        nonlocal count
        count += 1

    await bus.emit(TaskStartedEvent(prompt="hello"))
    assert count == 2


@pytest.mark.asyncio
async def test_emit_type_validation(bus):
    with pytest.raises(TypeError, match="EventBus can only emit Event instances"):
        await bus.emit("not an event")


@pytest.mark.asyncio
async def test_handler_error_emits_error_event(bus):
    """When a handler raises, an ErrorEvent should be emitted."""
    errors = []

    @bus.subscribe(ErrorEvent)
    async def error_handler(event):
        errors.append(event)

    @bus.subscribe(TaskStartedEvent)
    async def bad_handler(event):
        raise RuntimeError("handler failed")

    await bus.emit(TaskStartedEvent(prompt="test"))

    assert len(errors) == 1
    assert "handler failed" in errors[0].message


@pytest.mark.asyncio
async def test_error_event_handler_error_no_infinite_loop(bus):
    """If an ErrorEvent handler raises, it should not cause infinite recursion."""
    @bus.subscribe(ErrorEvent)
    async def bad_error_handler(event):
        raise RuntimeError("error in error handler")

    @bus.subscribe(TaskStartedEvent)
    async def bad_handler(event):
        raise RuntimeError("original error")

    # Should not raise
    await bus.emit(TaskStartedEvent(prompt="test"))


@pytest.mark.asyncio
async def test_safe_emit_catches_exceptions(bus):
    """_safe_emit should not raise even if emit fails."""
    original_emit = bus.emit

    async def failing_emit(event):
        if not isinstance(event, ErrorEvent):
            raise RuntimeError("emit failed")
        await original_emit(event)

    bus.emit = failing_emit

    # Should not raise
    await bus._safe_emit(TaskStartedEvent(prompt="test"))
