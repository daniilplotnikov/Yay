from __future__ import annotations

from typing import Optional

from .workflow import Workflow, WorkflowContext, Transition, Finish


class WorkflowRunner:
    def __init__(self, workflow: Optional[Workflow]):
        self.workflow = workflow

    async def run(self, agent, *, entry: str | None = None):

        if self.workflow is None:
            raise RuntimeError(
                "Workflow is None. Provide a DefaultWorkflow or custom workflow."
            )

        ctx = WorkflowContext()

        current = entry or self.workflow.start_node

        if current is None:
            raise RuntimeError(
                "Workflow has no start_node defined."
            )

        visited_steps = 0
        max_steps = 10_000

        while current is not None:

            visited_steps += 1
            if visited_steps > max_steps:
                raise RuntimeError(
                    "Workflow exceeded max step limit (possible infinite loop)."
                )

            step = self.workflow.nodes.get(current)

            if step is None:
                raise RuntimeError(
                    f"Step '{current}' not found in workflow."
                )

            result = await step.run(agent, ctx)

            if isinstance(result, Finish):
                ctx.result = result.result
                return ctx.result

            if isinstance(result, Transition):
                current = result.target
                continue

            current = self.workflow.edges.get(current)

        return ctx.result