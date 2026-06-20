"""Tests for Workflow, WorkflowRunner, Step, Transition, Finish, DefaultAgentStep."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from yay.workflow import Workflow, Step, Transition, Finish, WorkflowRunner
from yay.workflow.default import DefaultAgentStep, create_default_workflow


class DummyStep(Step):
    async def run(self, agent, ctx):
        ctx.data["x"] = ctx.data.get("x", 0) + 1
        if ctx.data["x"] >= 2:
            return Finish("done")
        return Transition("step2")


class DummyStep2(Step):
    async def run(self, agent, ctx):
        ctx.data["x"] += 1
        return Transition("step1")


class NullStep(Step):
    async def run(self, agent, ctx):
        return None


class FinishStep(Step):
    async def run(self, agent, ctx):
        return Finish("finished")


class TestWorkflowContext:
    def test_default(self):
        from yay.workflow import WorkflowContext
        ctx = WorkflowContext()
        assert ctx.data == {}
        assert ctx.result is None


class TestTransition:
    def test_target(self):
        t = Transition("next")
        assert t.target == "next"


class TestFinish:
    def test_result(self):
        f = Finish("result")
        assert f.result == "result"


class TestWorkflow:
    def test_node_sets_start(self):
        wf = Workflow()
        wf.node("first", MagicMock())
        assert wf.start_node == "first"

    def test_node_keeps_first_start(self):
        wf = Workflow()
        wf.node("first", MagicMock())
        wf.node("second", MagicMock())
        assert wf.start_node == "first"

    def test_edge(self):
        wf = Workflow()
        wf.edge("a", "b")
        assert wf.edges["a"] == "b"

    def test_node_returns_self(self):
        wf = Workflow()
        result = wf.node("a", MagicMock())
        assert result is wf

    def test_edge_returns_self(self):
        wf = Workflow()
        result = wf.edge("a", "b")
        assert result is wf


class TestWorkflowRunner:
    @pytest.mark.asyncio
    async def test_runner_loop(self):
        wf = Workflow()
        wf.node("step1", DummyStep())
        wf.node("step2", DummyStep2())
        runner = WorkflowRunner(wf)
        result = await runner.run(object())
        assert result == "done"

    @pytest.mark.asyncio
    async def test_runner_none_workflow(self):
        runner = WorkflowRunner(None)
        with pytest.raises(RuntimeError, match="Workflow is None"):
            await runner.run(object())

    @pytest.mark.asyncio
    async def test_runner_no_start_node(self):
        wf = Workflow()
        wf.nodes = {}
        wf.start_node = None
        runner = WorkflowRunner(wf)
        with pytest.raises(RuntimeError, match="no start_node"):
            await runner.run(object())

    @pytest.mark.asyncio
    async def test_runner_missing_step(self):
        wf = Workflow()
        wf.nodes = {}
        wf.start_node = "missing"
        runner = WorkflowRunner(wf)
        with pytest.raises(RuntimeError, match="not found"):
            await runner.run(object())

    @pytest.mark.asyncio
    async def test_runner_max_steps(self):
        class LoopStep(Step):
            async def run(self, agent, ctx):
                return Transition("loop")

        wf = Workflow()
        wf.node("loop", LoopStep())
        runner = WorkflowRunner(wf)
        with pytest.raises(RuntimeError, match="max step limit"):
            await runner.run(object())

    @pytest.mark.asyncio
    async def test_runner_with_entry(self):
        wf = Workflow()
        wf.node("a", FinishStep())
        wf.node("b", FinishStep())
        runner = WorkflowRunner(wf)
        result = await runner.run(object(), entry="b")
        assert result == "finished"

    @pytest.mark.asyncio
    async def test_runner_null_result(self):
        wf = Workflow()
        wf.node("a", NullStep())
        runner = WorkflowRunner(wf)
        result = await runner.run(object())
        assert result is None

    @pytest.mark.asyncio
    async def test_runner_edge_fallback(self):
        wf = Workflow()
        wf.node("a", NullStep())
        wf.edge("a", "b")
        wf.node("b", FinishStep())
        runner = WorkflowRunner(wf)
        result = await runner.run(object())
        assert result == "finished"


class TestDefaultAgentStep:
    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_finish(self):
        from yay.workflow import WorkflowContext

        class FakeAgent:
            def __init__(self):
                self.bus = AsyncMock()
                self.context = AsyncMock()
            def _extract_tool_calls(self, response):
                return []
            async def _stream_chunk(self, c):
                return None

        agent = FakeAgent()
        agent.provider = AsyncMock()
        response = MagicMock()
        response.content.text = "Hello world"
        agent.provider.process_stream = AsyncMock(return_value=response)

        step = DefaultAgentStep()
        ctx = WorkflowContext()
        result = await step.run(agent, ctx)

        assert isinstance(result, Finish)
        assert result.result == "Hello world"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        from yay.workflow import WorkflowContext

        class FakeAgent:
            def __init__(self):
                self.bus = AsyncMock()
                self.context = AsyncMock()
            def _extract_tool_calls(self, response):
                return []
            async def _stream_chunk(self, c):
                return None

        agent = FakeAgent()
        agent.provider = AsyncMock()
        response = MagicMock()
        response.content.text = "   "
        agent.provider.process_stream = AsyncMock(return_value=response)

        step = DefaultAgentStep()
        ctx = WorkflowContext()
        with pytest.raises(RuntimeError, match="Empty model response"):
            await step.run(agent, ctx)

    @pytest.mark.asyncio
    async def test_emits_model_processing(self):
        from yay.workflow import WorkflowContext
        from yay.events import ModelProcessingEvent

        class FakeAgent:
            def __init__(self):
                self.bus = AsyncMock()
                self.context = AsyncMock()
            def _extract_tool_calls(self, response):
                return []
            async def _stream_chunk(self, c):
                return None

        agent = FakeAgent()
        agent.provider = AsyncMock()
        response = MagicMock()
        response.content.text = "Hi"
        agent.provider.process_stream = AsyncMock(return_value=response)

        step = DefaultAgentStep()
        ctx = WorkflowContext()
        await step.run(agent, ctx)

        processing_calls = [
            c for c in agent.bus.emit.call_args_list
            if isinstance(c[0][0], ModelProcessingEvent)
        ]
        assert len(processing_calls) == 1


class TestCreateDefaultWorkflow:
    def test_creates_workflow(self):
        wf = create_default_workflow()
        assert isinstance(wf, Workflow)
        assert wf.start_node == "agent"
        assert "agent" in wf.nodes
