from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowContext:
    data: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass
class Transition:
    target: str


@dataclass
class Finish:
    result: Any


class Step(ABC):
    @abstractmethod
    async def run(self, agent, ctx: WorkflowContext):
        pass


class Workflow:
    def __init__(self):
        self.nodes: dict[str, Step] = {}
        self.edges: dict[str, str] = {}
        self.start_node: str | None = None

    def node(self, name: str, step: Step):
        self.nodes[name] = step

        if self.start_node is None:
            self.start_node = name

        return self

    def edge(self, source: str, target: str):
        self.edges[source] = target
        return self


class WorkflowRunner:
    def __init__(self, workflow: Workflow):
        self.workflow = workflow

    async def run(self, agent):
        ctx = WorkflowContext()

        current = self.workflow.start_node

        while current:
            step = self.workflow.nodes[current]

            result = await step.run(agent, ctx)

            if isinstance(result, Finish):
                return result.result

            if isinstance(result, Transition):
                current = result.target
            else:
                current = self.workflow.edges.get(current)

        return ctx.result