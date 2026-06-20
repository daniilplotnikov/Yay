import pytest
import asyncio

from yay.workflow import Workflow, Step, Transition, Finish, WorkflowRunner


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


@pytest.mark.asyncio
async def test_workflow_runner_loop():
    wf = Workflow()

    wf.node("step1", DummyStep())
    wf.node("step2", DummyStep2())

    runner = WorkflowRunner(wf)

    agent = object()

    result = await runner.run(agent)

    assert result == "done"