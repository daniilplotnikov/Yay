import pytest
from unittest.mock import AsyncMock

from yay.tools import Tool, ToolExecutor, ToolsManager
from yay.events import ToolStartedEvent, ToolFinishedEvent, ToolErrorEvent


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


class DummyTool(Tool):
    def __init__(self, name="DummyTool", safe=True):
        super().__init__()
        self.name = name
        self.is_safe = safe
        self.arguments = {
            "type": "object",
            "properties": {"x": {"type": "number"}},
            "required": ["x"],
        }

    def execute(self, args):
        return args["x"] * 2


class AsyncDummyTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "AsyncDummy"
        self.arguments = {
            "type": "object",
            "properties": {"x": {"type": "number"}},
            "required": ["x"],
        }

    async def execute(self, args):
        return args["x"] + 1


class FailingTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "FailingTool"
        self.arguments = {}

    def execute(self, args):
        raise ValueError("tool failed")


class TestTool:
    def test_schema(self):
        tool = DummyTool()
        schema = tool.schema()
        assert schema["name"] == "DummyTool"
        assert "parameters" in schema

    def test_validate_missing_required(self):
        tool = DummyTool()
        with pytest.raises(ValueError, match="Missing required argument: x"):
            tool.validate({})

    def test_validate_ok(self):
        tool = DummyTool()
        tool.validate({"x": 5})

    def test_run_sync(self):
        import asyncio
        tool = DummyTool()
        result = asyncio.run(tool.run({"x": 3}))
        assert result == 6

    def test_run_async(self):
        import asyncio
        tool = AsyncDummyTool()
        result = asyncio.run(tool.run({"x": 3}))
        assert result == 4


class TestToolsManager:
    def test_register_and_get(self):
        tm = ToolsManager()
        tool = DummyTool()
        tm.register(tool)
        assert tm.get_tool("DummyTool") is tool

    def test_get_nonexistent(self):
        tm = ToolsManager()
        assert tm.get_tool("nonexistent") is None

    def test_register_many(self):
        tm = ToolsManager()
        tm.register_many([DummyTool("A"), DummyTool("B")])
        assert len(tm.get_all_tools()) == 2

    def test_unregister(self):
        tm = ToolsManager()
        tm.register(DummyTool())
        tm.unregister("DummyTool")
        assert tm.get_tool("DummyTool") is None

    def test_enable_disable(self):
        tm = ToolsManager()
        tm.register(DummyTool())
        tm.disable("DummyTool")
        assert tm.get_tools() == {}
        tm.enable("DummyTool")
        assert "DummyTool" in tm.get_tools()

    def test_enable_nonexistent(self):
        tm = ToolsManager()
        tm.enable("nonexistent")

    def test_is_enabled(self):
        tm = ToolsManager()
        tm.register(DummyTool())
        assert tm.is_enabled("DummyTool") is True
        tm.disable("DummyTool")
        assert tm.is_enabled("DummyTool") is False

    def test_get_tools_only_enabled(self):
        tm = ToolsManager()
        tm.register(DummyTool("A"))
        tm.register(DummyTool("B"))
        tm.disable("A")
        tools = tm.get_tools()
        assert "A" not in tools
        assert "B" in tools

    def test_init_with_tools(self):
        tm = ToolsManager(tools=[DummyTool("X"), DummyTool("Y")])
        assert len(tm.get_all_tools()) == 2


class TestToolExecutor:
    @pytest.fixture
    def bus(self):
        bus = AsyncMock()
        bus.emit = AsyncMock()
        return bus

    @pytest.fixture
    def tools_manager(self):
        tm = ToolsManager()
        tm.register(DummyTool())
        return tm

    @pytest.mark.asyncio
    async def test_run_tool_success(self, bus, tools_manager):
        executor = ToolExecutor(tools_manager=tools_manager, bus=bus)
        result = await executor.run_tool("DummyTool", {"x": 5})
        assert result == 10

    @pytest.mark.asyncio
    async def test_run_tool_emits_started(self, bus, tools_manager):
        executor = ToolExecutor(tools_manager=tools_manager, bus=bus)
        await executor.run_tool("DummyTool", {"x": 5})
        started_calls = [
            c for c in bus.emit.call_args_list
            if isinstance(c[0][0], ToolStartedEvent)
        ]
        assert len(started_calls) == 1

    @pytest.mark.asyncio
    async def test_run_tool_emits_finished(self, bus, tools_manager):
        executor = ToolExecutor(tools_manager=tools_manager, bus=bus)
        await executor.run_tool("DummyTool", {"x": 5})
        finished_calls = [
            c for c in bus.emit.call_args_list
            if isinstance(c[0][0], ToolFinishedEvent)
        ]
        assert len(finished_calls) == 1

    @pytest.mark.asyncio
    async def test_run_tool_unknown(self, bus, tools_manager):
        executor = ToolExecutor(tools_manager=tools_manager, bus=bus)
        with pytest.raises(ValueError, match="Unknown tool: nonexistent"):
            await executor.run_tool("nonexistent", {})

    @pytest.mark.asyncio
    async def test_run_tool_error_raises(self, bus):
        tm = ToolsManager()
        tm.register(FailingTool())
        executor = ToolExecutor(tools_manager=tm, bus=bus)
        with pytest.raises(ValueError, match="tool failed"):
            await executor.run_tool("FailingTool", {})

    @pytest.mark.asyncio
    async def test_run_tool_error_emits_event(self, bus):
        tm = ToolsManager()
        tm.register(FailingTool())
        executor = ToolExecutor(tools_manager=tm, bus=bus)
        with pytest.raises(ValueError):
            await executor.run_tool("FailingTool", {})
        error_calls = [
            c for c in bus.emit.call_args_list
            if isinstance(c[0][0], ToolErrorEvent)
        ]
        assert len(error_calls) == 1

    def test_normalize_result_string(self, bus):
        executor = ToolExecutor(tools_manager=ToolsManager(), bus=bus)
        assert executor.normalize_result("hello") == "hello"

    def test_normalize_result_dict(self, bus):
        executor = ToolExecutor(tools_manager=ToolsManager(), bus=bus)
        result = executor.normalize_result({"key": "value"})
        assert '"key"' in result


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