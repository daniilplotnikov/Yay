from __future__ import annotations

import json
import threading
from queue import Queue
from typing import Any, Callable, Dict, Literal, Optional

from .llm import Content, Context, Message
from .managers import ToolsManager
from .provider import Provider
from .steering import SteeringState
from .task import Task

ApproveMode = Literal["never", "safe", "always"]

class Agent:
    def __init__(
        self,
        provider: Provider,
        context: Context,
        tools_manager: ToolsManager,
        approve_mode: ApproveMode = "never",
        approval_callback: Optional[Callable] = None,
        event_callback: Optional[Callable] = None,
    ) -> None:
        self.provider = provider
        self.context = context
        self.context.compression_callback = self._on_context_compressed

        self.steering = SteeringState()
        self.approve_mode: ApproveMode = approve_mode
        self.approval_callback = approval_callback
        self.event_callback = event_callback
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

    def emit(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        if self.event_callback:
            self.event_callback(event, data or {})

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
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

        self.emit("approval_requested", {"tool": tool_name, "args": args})

        if self.approval_callback:
            result = self.approval_callback(tool_name, args)
            self._approval_result = bool(result)
            return self._approval_result

        self._approval_event.wait()
        return bool(self._approval_result)

    def resolve_approval(self, value: bool) -> None:
        self._approval_result = value
        self._approval_event.set()

    def resolve_question(self, answer: str) -> None:
        self._question_answer = answer
        self._question_event.set()

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
        self.emit("task_started", {"prompt": prompt})

        steering_text = self._build_steering_prompt()
        full_prompt = f"{steering_text}\n\n{prompt}" if steering_text else prompt

        self.context.append(
            Message(role="user", content=Content(text=full_prompt))
        )
        self._compress_context_if_needed()

        while True:
            self.wait_if_paused()
            self.emit("model_processing")

            response = self.provider.process_stream(
                self.context,
                on_chunk=lambda data: self.emit("stream_chunk", data),
            )

            self.context.append(response)
            self._compress_context_if_needed()
            self.emit("provider_response", {"message": response})

            tool_call = self._extract_tool_call(response)

            if tool_call is None:
                text = getattr(getattr(response, "content", None), "text", "") or ""
                text = text.strip()
                if not text:
                    raise RuntimeError(
                        "Model returned an empty response (no tool call, no text). "
                        f"Raw content: {getattr(response.content, 'text', None)!r}"
                    )
                self.emit("task_finished", {"result": text})
                return text

            tool_name    = tool_call.get("name")
            args         = tool_call.get("args", {})
            tool_call_id = tool_call.get("id")

            self.emit("tool_call", {"tool": tool_name, "args": args})

            if self.needs_approval(tool_name):
                approved = self.request_approval(tool_name, args)
                if not approved:
                    self.emit("approval_denied", {"tool": tool_name})
                    self.context.append(
                        Message(
                            role="tool",
                            tool=tool_name,
                            tool_call_id=tool_call_id,
                            content=Content(text="Tool execution denied by user"),
                        )
                    )
                    self._compress_context_if_needed()
                    continue
                self.emit("approval_granted", {"tool": tool_name})

            self.emit("tool_started", {"tool": tool_name})
            self.wait_if_paused()

            try:
                result = self.run_tool(tool_name, args)
            except Exception as e:
                result = {"error": str(e)}
                self.emit("tool_error", {"tool": tool_name, "error": str(e)})
                self.context.append(
                    Message(
                        role="tool",
                        tool=tool_name,
                        tool_call_id=tool_call_id,
                        content=Content(text=json.dumps(result, ensure_ascii=False)),
                    )
                )
                self._compress_context_if_needed()
                continue

            if (
                tool_name in {"Question", "QuestionTool"}
                and isinstance(result, dict)
                and result.get("waiting_for_user")
            ):
                self._question_event.clear()
                self._question_answer = None
                self.emit("question_requested", result)

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
                self._compress_context_if_needed()
                continue

            if tool_name in {"FinishTask", "FinishTaskTool"}:
                self.emit("tool_finished", {"tool": tool_name, "result": result})
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
                self._compress_context_if_needed()
                self.emit("task_finished", {"result": result})
                return result

            self.emit("tool_finished", {"tool": tool_name, "result": result})
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
            self._compress_context_if_needed()

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
                self.emit("task_error", {"task_id": task.task_id, "error": str(e)})
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

    def _compress_context_if_needed(self) -> None:
        try:
            self.context.compress_if_needed()
        except Exception as e:
            self.emit("context_compression_error", {"error": str(e)})

    def _on_context_compressed(self, info: Dict[str, Any]) -> None:
        self.emit("context_compressed", info)