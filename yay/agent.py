from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from .llm import Content, Context, Message
from .events import *
from .task import Task
from .provider import Provider
from .managers import ToolsManager
from .steering import SteeringState
from .tools import ToolExecutor

ApproveMode = str

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
        approve_mode: ApproveMode = "never",
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

    def _extract_tool_calls(self, response: Message) -> list[dict]:
        tool = getattr(response, "tool", None)
        if not tool:
            return []

        result = []

        if isinstance(tool, dict):
            calls = tool.get("calls")

            if calls:
                for c in calls:
                    result.append({
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "args": c.get("arguments", {}) or {},
                    })

            elif "name" in tool:
                result.append({
                    "id": tool.get("id"),
                    "name": tool.get("name"),
                    "args": tool.get("arguments", {}) or {},
                })

        return result
    
    async def _suspend(self, reason: str, payload: Any = None):
        self.suspension = Suspension()
        self.suspension.reason = reason
        self.suspension.input = payload

        self._resume_event.clear()
        await self._resume_event.wait()

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

    async def work_loop(self, prompt: str):
        await self.bus.emit(TaskStartedEvent(prompt=prompt))

        self.context.append(
            Message(role="user", content=Content(text=prompt))
        )

        while True:
            await self.bus.emit(ModelProcessingEvent())

            response = await self.provider.process_stream(
                self.context,
                on_chunk=lambda c: asyncio.create_task(
                    self.bus.emit(StreamChunkEvent(data=c))
                ),
            )

            self.context.append(response)

            await self.bus.emit(
                ProviderResponseEvent(message=response)
            )

            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                text = (
                    getattr(getattr(response, "content", None), "text", "")
                    or ""
                ).strip()

                if not text:
                    raise RuntimeError("Empty model response")

                await self.bus.emit(TaskFinishedEvent(result=text))
                return text

            for call in tool_calls:
                tool_name = call["name"]
                args = call["args"]
                tool_id = call.get("id")

                await self.bus.emit(
                    ToolCallEvent(tool=tool_name, args=args)
                )

                if self.approve_mode != "always":
                    approved = await self._suspend(
                        SuspensionReason.APPROVAL,
                        (tool_name, args),
                    )

                    if not approved:
                        await self.bus.emit(
                            ApprovalDeniedEvent(tool=tool_name)
                        )
                        continue

                result = await self.tool_executor.run_tool(
                    tool_name,
                    args,
                )

                if tool_name in {"Question", "QuestionTool"} and isinstance(result, dict) and result.get("waiting_for_user"):
                    await self.bus.emit(QuestionRequestedEvent(payload=result))

                    answer = await self._suspend(
                        SuspensionReason.QUESTION,
                        result,
                    )

                    self.context.append(
                        Message(role="user", content=Content(text=answer))
                    )
                    continue

                self.context.append(
                    Message(
                        role="tool",
                        tool=tool_name,
                        tool_call_id=tool_id,
                        content=Content(
                            text=self.tool_executor.normalize_result(result)
                        ),
                    )
                )

    async def enqueue(self, prompt: str, task_id: str, metadata=None):
        await self.task_queue.put(Task(prompt=prompt, task_id=task_id, metadata=metadata))

    async def _queue_loop(self):
        while self.running:
            task = await self.task_queue.get()
            self.current_task = task

            try:
                await self.work_loop(task.prompt)
            except Exception as e:
                await self.bus.emit(TaskErrorEvent(task_id=task.task_id, error=e))
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

    async def _on_context_compressed(self, info):
        await self.bus.emit(ContextCompressedEvent(info=info))

    @property
    def is_paused(self) -> bool:
        return self.suspension is not None