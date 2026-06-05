from __future__ import annotations

import json
import threading
from queue import Queue
from typing import Any, Dict, Literal, Optional

from .llm import Content, Context, Message
from .managers import ToolsManager
from .provider import Provider
from .steering import SteeringState
from .task import Task
from .events import EventBus, TaskStartedEvent, ModelProcessingEvent, ApprovalRequestedEvent, \
    StreamChunkEvent, ProviderResponseEvent, TaskFinishedEvent, TaskErrorEvent, ToolCallEvent, \
    ToolFinishedEvent, ContextCompressedEvent, ContextCompressionErrorEvent, ApprovalGrantedEvent,\
    ApprovalDeniedEvent, AgentPausedEvent, AgentResumedEvent, ToolStartedEvent, ToolErrorEvent,\
    QuestionRequestedEvent, ContextCompressionNeededEvent

ApproveMode = Literal["never", "safe", "always"]

class Agent:
    def __init__(
        self,
        bus: EventBus,
        provider: Provider,
        context: Context,
        tools_manager: ToolsManager,
        approve_mode: ApproveMode = "never"
    ) -> None:
        
        self.bus = bus

        self.provider = provider
        self.context = context
        self.context.compression_callback = self._on_context_compressed

        self.steering = SteeringState()
        self.approve_mode: ApproveMode = approve_mode
        self.tools_manager = tools_manager

        self._approval_event = threading.Event()
        self._approval_result: Optional[bool] = None

        self._question_event = threading.Event()
        self._question_answer: Optional[str] = None

        self._pause_event = threading.Event()
        self._pause_event.set()  

        self.task_queue: Queue[Task] = Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.running = False
        self.current_task: Optional[Task] = None

        self.bus.subscribe(ApprovalGrantedEvent)(self._on_approval_granted)
        self.bus.subscribe(ApprovalDeniedEvent)(self._on_approval_denied)
        self.bus.subscribe(QuestionRequestedEvent)(self._on_question_requested)
        self.bus.subscribe(ContextCompressionNeededEvent)(self._on_compression_needed)

    def pause(self) -> None:
        self.bus.emit(AgentPausedEvent())
        self._pause_event.clear()

    def resume(self) -> None:
        self.bus.emit(AgentResumedEvent())
        self._pause_event.set()

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def wait_if_paused(self) -> None:
        self._pause_event.wait()

    @property
    def tools(self) -> Dict[str, Any]:
        return self.tools_manager.get_tools()

    def replace_tools(self, tools) -> None:
        self.tools_manager.unregister_many(list(self.tools_manager.get_tools().keys()))
        self.tools_manager.register_many(tools)

    def run_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        tool = self.tools.get(tool_name)
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name!r}")
        runner = getattr(tool, "run", None)
        if runner is None or not callable(runner):
            runner = tool if callable(tool) else None
        if runner is None:
            raise ValueError(f"Tool {tool_name!r} has no callable 'run' method")
        return runner(args)

    def needs_approval(self, tool_name: str) -> bool:
        if self.approve_mode == "always":
            return False
        if self.approve_mode == "never":
            return True
        tool = self.tools.get(tool_name)
        if tool is None:
            return True 
        return not getattr(tool, "is_safe", False)

    def request_approval(self, tool_name: str, args: Dict[str, Any]) -> bool:
        self._approval_event.clear()
        self._approval_result = None

        self.bus.emit(ApprovalRequestedEvent(tool=tool_name, args=args))

        self._approval_event.wait()
        return bool(self._approval_result)

    def resolve_approval(self, value: bool) -> None:
        self._approval_result = value
        self._approval_event.set()

    def _on_approval_granted(self, e: ApprovalGrantedEvent) -> None:
        self.resolve_approval(True)

    def _on_approval_denied(self, e: ApprovalDeniedEvent) -> None:
        self.resolve_approval(False)

    def resolve_question(self, answer: str) -> None:
        self._question_answer = answer
        self._question_event.set()

    def _on_question_requested(self, e: QuestionRequestedEvent) -> None:
        self._question_event.clear()
        self._question_answer = None

    def add_instruction(self, text: str) -> None:
        self.steering.instructions.append(text)

    def clear_instructions(self) -> None:
        self.steering.instructions.clear()

    def _build_steering_prompt(self) -> Optional[str]:
        if not self.steering.instructions:
            return None
        return "\n".join(self.steering.instructions)

    def _extract_tool_call(self, response: Message) -> Optional[Dict[str, Any]]:
        tool = getattr(response, "tool", None)
        if not tool:
            return None

        if isinstance(tool, dict):
            calls = tool.get("calls")
            if calls:
                call = calls[0]
                return {
                    "id":   call.get("id"),
                    "name": call.get("name"),
                    "args": call.get("arguments", {}),
                }
            if "name" in tool:
                return {
                    "id":   None,
                    "name": tool.get("name"),
                    "args": tool.get("arguments", {}),
                }

        return None

    def work_loop(self, prompt: str) -> Any:
        self.bus.emit(TaskStartedEvent(prompt=prompt))

        steering_text = self._build_steering_prompt()
        full_prompt = f"{steering_text}\n\n{prompt}" if steering_text else prompt

        self.context.append(
            Message(role="user", content=Content(text=full_prompt))
        )

        while True:
            self.wait_if_paused()
            self.bus.emit(ModelProcessingEvent())

            response = self.provider.process_stream(
                self.context,
                on_chunk=lambda data: self.bus.emit(StreamChunkEvent(data=data)),
            )

            self.context.append(response)
            self.bus.emit(ProviderResponseEvent(message=response))

            tool_call = self._extract_tool_call(response)

            if tool_call is None:
                text = getattr(getattr(response, "content", None), "text", "") or ""
                text = text.strip()
                if not text:
                    raise RuntimeError(
                        "Model returned an empty response (no tool call, no text). "
                        f"Raw content: {getattr(response.content, 'text', None)!r}"
                    )
                self.bus.emit(TaskFinishedEvent(result=text))
                return text

            tool_name    = tool_call.get("name")
            args         = tool_call.get("args", {})
            tool_call_id = tool_call.get("id")

            self.bus.emit(ToolCallEvent(tool=tool_name, args=args))

            if self.needs_approval(tool_name):
                approved = self.request_approval(tool_name, args)
                if not approved:
                    self.bus.emit(ApprovalDeniedEvent(tool=tool_name))
                    self.context.append(
                        Message(
                            role="tool",
                            tool=tool_name,
                            tool_call_id=tool_call_id,
                            content=Content(text="Tool execution denied by user"),
                        )
                    )
                    continue
                self.bus.emit(ApprovalGrantedEvent(tool=tool_name))

            self.bus.emit(ToolStartedEvent(tool=tool_name))
            self.wait_if_paused()

            try:
                result = self.run_tool(tool_name, args)
            except Exception as e:
                result = {"error": str(e)}
                self.bus.emit(ToolErrorEvent(tool=tool_name, error=e))
                self.context.append(
                    Message(
                        role="tool",
                        tool=tool_name,
                        tool_call_id=tool_call_id,
                        content=Content(text=json.dumps(result, ensure_ascii=False)),
                    )
                )
                continue

            if (
                tool_name in {"Question", "QuestionTool"}
                and isinstance(result, dict)
                and result.get("waiting_for_user")
            ):
                self._question_event.clear()
                self._question_answer = None
                self.bus.emit(QuestionRequestedEvent(payload=result))

                self._question_event.wait()
                answer = self._question_answer or ""

                self.context.append(
                    Message(
                        role="tool",
                        tool=tool_name,
                        tool_call_id=tool_call_id,
                        content=Content(text=json.dumps(result, ensure_ascii=False)),
                    )
                )
                self.context.append(
                    Message(role="user", content=Content(text=answer))
                )
                continue

            if tool_name in {"FinishTask", "FinishTaskTool"}:
                self.bus.emit(ToolFinishedEvent(tool=tool_name, result=result))
                self.context.append(
                    Message(
                        role="tool",
                        tool=tool_name,
                        tool_call_id=tool_call_id,
                        content=Content(
                            text=result if isinstance(result, str)
                            else json.dumps(result, ensure_ascii=False)
                        ),
                    )
                )
                self.bus.emit(TaskFinishedEvent(result=result))
                return result

            self.bus.emit(ToolFinishedEvent(tool=tool_name, result=result))
            self.context.append(
                Message(
                    role="tool",
                    tool=tool_name,
                    tool_call_id=tool_call_id,
                    content=Content(
                        text=result if isinstance(result, str)
                        else json.dumps(result, ensure_ascii=False)
                    ),
                )
            )

    def _queue_loop(self) -> None:
        while self.running:
            try:
                task = self.task_queue.get(timeout=1.0)
            except Exception:
                continue

            self.current_task = task
            try:
                self.work_loop(task.prompt)
            except Exception as e:
                self.bus.emit(TaskErrorEvent(task_id=task.task_id, error=e))
            finally:
                self.current_task = None
                self.task_queue.task_done()

    def enqueue(self, prompt: str, task_id: str, metadata: Any = None) -> None:
        self.task_queue.put(Task(prompt=prompt, task_id=task_id, metadata=metadata))

    def start_queue(self) -> None:
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(
            target=self._queue_loop, daemon=True, name="agent-worker"
        )
        self.worker_thread.start()

    def stop_queue(self) -> None:
        self.running = False

    def _on_context_compressed(self, info: Dict[str, Any]) -> None:
        self.bus.emit(ContextCompressedEvent(info=info))

    def _on_compression_needed(self, e: ContextCompressionNeededEvent) -> None:
        try:
            self.context.compress()
        except Exception as ex:
            self.bus.emit(ContextCompressionErrorEvent(error=ex))