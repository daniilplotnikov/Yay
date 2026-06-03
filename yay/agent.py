from .llm import Context, Message, Content
from .steering import SteeringState
from .provider import Provider
from .task import Task
from typing import Literal, Dict, Any, Optional
from queue import Queue
import threading
import json

ApproveMode = Literal[
    "safe",
    "always",
    "never",
]

class Agent:
    def __init__(
        self,
        provider: Provider,
        context: Context,
        tools: list,
        approve_mode: ApproveMode = "always",
        approval_callback=None,
        event_callback=None,
    ):
        self.provider = provider
        self.context = context
        self.context.compression_callback = (
            self._on_context_compressed
        )

        self.steering = SteeringState()

        self.approve_mode = approve_mode

        self.approval_callback = approval_callback
        self.event_callback = event_callback

        self.tools = {tool.name: tool for tool in tools}

        self._approval_event = threading.Event()
        self._approval_result: Optional[bool] = None

        self.task_queue = Queue()
        self.worker_thread = None
        self.running = False

    def emit(self, event: str, data=None):
        if self.event_callback:
            self.event_callback(event, data or {})

    def run_tool(self, tool_name: str, args: Dict[str, Any]):
        tool = self.tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        return tool.run(args)

    def needs_approval(self, tool_name: str) -> bool:
        tool = self.tools.get(tool_name)
        if not tool:
            return False
        if self.approve_mode == "always":
            return True 
        if self.approve_mode == "never":
            return False
        if self.approve_mode == "safe":
            return not tool.is_safe
        return False

    def request_approval(self, tool_name, args):
        self._approval_event.clear()
        self._approval_result = None

        self.emit("approval_requested", {
            "tool": tool_name,
            "args": args
        })

        if self.approval_callback:
            result = self.approval_callback(tool_name, args)
            self._approval_result = bool(result)
            return self._approval_result

        self._approval_event.wait()
        return self._approval_result

    def resolve_approval(self, value: bool):
        self._approval_result = value
        self._approval_event.set()

    def add_instruction(self, text: str):
        self.steering.instructions.append(text)

    def clear_instructions(self):
        self.steering.instructions.clear()

    def _extract_tool_call(self, response):
        tool = getattr(response, "tool", None)

        if not tool:
            return None

        if (
            isinstance(tool, dict)
            and "calls" in tool
            and tool["calls"]
        ):
            call = tool["calls"][0]

            return {
                "id": call.get("id"),
                "name": call.get("name"),
                "args": call.get("arguments", {}),
            }

        if (
            isinstance(tool, dict)
            and "name" in tool
        ):
            return {
                "id": None,
                "name": tool.get("name"),
                "args": tool.get("arguments", {}),
            }

        return None

    def work_loop(self, prompt: str):
        self.emit("task_started", {"prompt": prompt})

        self.context.append(
            Message(
                role="user",
                content=Content(text=prompt),
                tool=None,
            )
        )

        self._compress_context_if_needed()

        steering = self._build_steering_message()

        if steering:
            self.context.append(steering)

        while True:

            self.emit("model_processing")

            response = self.provider.process_stream(
                self.context,
                on_chunk=lambda data: self.emit("stream_chunk", data)
            )

            self.context.append(response)
            self._compress_context_if_needed()

            self.emit(
                "provider_response",
                {"message": response},
            )

            tool_call = self._extract_tool_call(
                response
            )

            if tool_call is None:

                text = ""

                if (
                    hasattr(response, "content")
                    and response.content
                ):
                    text = getattr(
                        response.content,
                        "text",
                        "",
                    ).strip()

                if not text:
                    raise RuntimeError(
                        "Model returned empty response"
                    )

                self.emit(
                    "task_finished",
                    {
                        "result": text
                    }
                )

                return text

            tool_name = tool_call.get("name")
            args = tool_call.get("args", {})
            tool_call_id = tool_call.get("id")

            self.emit(
                "tool_call",
                {
                    "tool": tool_name,
                    "args": args,
                },
            )

            if self.needs_approval(tool_name):

                approved = self.request_approval(
                    tool_name,
                    args,
                )

                if not approved:

                    self.emit(
                        "approval_denied",
                        {"tool": tool_name},
                    )

                    result = "Tool execution denied by user"

                    self.context.append(
                        Message(
                            role="tool",
                            tool=tool_name,
                            tool_call_id=tool_call_id,
                            content=Content(
                                text=json.dumps(
                                    result,
                                    ensure_ascii=False,
                                )
                                if not isinstance(result, str)
                                else result
                            ),
                        )
                    )

                    self._compress_context_if_needed()

                    continue

                self.emit(
                    "approval_granted",
                    {"tool": tool_name},
                )

            self.emit(
                "tool_started",
                {"tool": tool_name},
            )

            try:

                result = self.run_tool(
                    tool_name,
                    args,
                )

                self.emit(
                    "tool_finished",
                    {
                        "tool": tool_name,
                        "result": result,
                    },
                )

            except Exception as e:

                result = {"error": str(e)}

                self.emit(
                    "tool_error",
                    {
                        "tool": tool_name,
                        "error": str(e),
                    },
                )

            self.context.append(
                Message(
                    role="tool",
                    tool=tool_name,
                    tool_call_id=tool_call_id,
                    content=Content(
                        text=json.dumps(
                            result,
                            ensure_ascii=False,
                        )
                        if not isinstance(result, str)
                        else result
                    ),
                )
            )
            self._compress_context_if_needed()

            if tool_name == "FinishTaskTool":

                self.emit(
                    "task_finished",
                    {"result": result},
                )

                return result

    def _queue_loop(self):
        while self.running:
            try:
                task = self.task_queue.get(timeout=1.0)
            except Exception:
                continue 
            try:
                self.work_loop(task.prompt)
            except Exception as e:
                self.emit("task_error", {"task_id": task.task_id, "error": str(e)})
            self.task_queue.task_done()
        self.running = False 
            
    def enqueue(self, prompt: str, task_id: str, metadata=None):
        self.task_queue.put(
            Task(
                prompt=prompt,
                task_id=task_id,
                metadata=metadata,
            )
        )

    def start_queue(self):
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(target=self._queue_loop, daemon=True)
        self.worker_thread.start()

    def stop_queue(self):
        self.running = False

    def _compress_context_if_needed(self):
        try:
            self.context.compress_if_needed()
        except Exception as e:
            self.emit(
                "context_compression_error",
                {
                    "error": str(e),
                },
            )
            
    def _on_context_compressed(
        self,
        info: Dict[str, Any],
    ):
        self.emit(
            "context_compressed",
            info,
        )

    def _build_steering_message(self):
        if not self.steering.instructions:
            return None

        return Message(
            role="system",
            content=Content(
                text="\n".join(
                    self.steering.instructions
                )
            ),
        )
    
    def replace_tools(self, tools):
        self.tools = {
            tool.name: tool
            for tool in tools
        }