import pytest
from unittest.mock import AsyncMock


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

        def append(self, msg):
            self.messages.append(msg)

    return Ctx()


@pytest.fixture
def tool_executor():
    exec = AsyncMock()
    exec.run_tool = AsyncMock(return_value={"ok": True})
    exec.normalize_result = lambda x: str(x)
    return exec