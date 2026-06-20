from __future__ import annotations

import asyncio
from typing import Any, Optional

from .llm import Content, Context, Message
from .events import *
from .task import Task
from .provider import Provider
from .steering import SteeringState
from .tools import ToolExecutor, ToolsManager

from .workflow import Workflow
from .workflow.runner import WorkflowRunner
from .workflow.default import create_default_workflow


class SuspensionReason:
    APPROVAL = "approval"
    QUESTION = "question"


class Suspension:
    def __init__(self):
        self.reason: Optional[str] = None
        self.input: Any = None
        self.output: Any = None


class Agent:

    def __init__(
        self,
        bus,
        provider: Provider,
        context: Context,
        tools_manager: ToolsManager,
        tool_executor: ToolExecutor,
        workflow: Workflow | None = None,
        approve_mode: str = "never",
    ):
        self.bus = bus
        self.provider = provider
        self.context = context
        self.tools_manager = tools_manager
        self.tool_executor = tool_executor
        self.approve_mode = approve_mode

        self.steering = SteeringState()

        self.context.compression_callback = self._on_context_compressed

        self.task_queue: asyncio.Queue[Task] = asyncio.Queue()

        self.running = False
        self.worker_task: Optional[asyncio.Task] = None
        self.current_task: Optional[Task] = None

        self.suspension: Optional[Suspension] = None
        self._resume_event = asyncio.Event()

        self.workflow = workflow or create_default_workflow()
        self.runner = WorkflowRunner(self.workflow)

    async def _suspend(self, reason: str, payload: Any = None, timeout: float | None = None):
        self.suspension = Suspension()
        self.suspension.reason = reason
        self.suspension.input = payload

        self._resume_event.clear()
        try:
            await asyncio.wait_for(self._resume_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.suspension = None
            raise TimeoutError(f"Suspension timed out waiting for resume (reason={reason})")

        result = self.suspension.output
        self.suspension = None
        return result

    def resume_with_approval(self, value: bool):
        if self.suspension and self.suspension.reason == SuspensionReason.APPROVAL:
            self.suspension.output = value
            self._resume_event.set()

    def resume_with_answer(self, answer: str):
        if self.suspension and self.suspension.reason == SuspensionReason.QUESTION:
            self.suspension.output = answer
            self._resume_event.set()

    async def run(self, prompt: str):
        await self.bus.emit(TaskStartedEvent(prompt=prompt))

        self.context.append(
            Message(role="user", content=Content(text=prompt))
        )

        try:
            result = await self.runner.run(self)
            await self.bus.emit(TaskFinishedEvent(result=result))
            return result

        except Exception as e:
            await self.bus.emit(TaskErrorEvent(
                task_id=getattr(self.current_task, "task_id", None),
                error=e
            ))
            raise

    async def enqueue(self, prompt: str, task_id: str, metadata=None):
        await self.task_queue.put(Task(prompt=prompt, task_id=task_id, metadata=metadata))

    async def _queue_loop(self):
        while self.running:
            task = await self.task_queue.get()
            self.current_task = task

            try:
                await self.run(task.prompt)
            finally:
                self.current_task = None
                self.task_queue.task_done()

    async def start_queue(self):
        if self.running:
            return
        self.running = True
        self.worker_task = asyncio.create_task(self._queue_loop())

    async def stop_queue(self):
        self.running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

    async def _on_context_compressed(self, info):
        await self.bus.emit(ContextCompressedEvent(info=info))

    @property
    def is_paused(self) -> bool:
        return self.suspension is not None