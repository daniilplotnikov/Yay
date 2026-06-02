from .llm import Context, Message, Content
from .provider import Provider
from typing import Literal, Dict, Any, Optional
import threading

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
        self.approve_mode = approve_mode

        self.approval_callback = approval_callback
        self.event_callback = event_callback

        self.tools = {tool.name: tool for tool in tools}

        self._approval_event = threading.Event()
        self._approval_result: Optional[bool] = None

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
            return False

        if self.approve_mode == "never":
            return True

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

    def _extract_tool_call(self, response: Message):
        tool = getattr(response, "tool", None)

        if not tool:
            return None

        if isinstance(tool, dict) and "name" in tool:
            return {
                "name": tool.get("name"),
                "args": tool.get("arguments", {}) or {}
            }

        if isinstance(tool, dict) and "tool" in tool:
            return {
                "name": tool.get("tool"),
                "args": tool.get("args", {}) or {}
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

        while True:

            self.emit("model_processing")

            response: Message = self.provider.process(
                self.context
            )

            self.context.append(response)

            self.emit(
                "provider_response",
                {"message": response},
            )

            tool_call = self._extract_tool_call(
                response
            )

            if tool_call is None:

                result = ""

                if (
                    hasattr(response, "content")
                    and response.content
                ):
                    result = getattr(
                        response.content,
                        "text",
                        "",
                    )

                self.emit(
                    "task_finished",
                    {"result": result},
                )

                return result

            tool_name = tool_call["name"]
            args = tool_call["args"]

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

                    self.context.append(
                        Message(
                            role="tool",
                            tool=tool_name,
                            content=Content(
                                text="Rejected by user"
                            ),
                        )
                    )

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
                    content=Content(
                        text=str(result)
                    ),
                )
            )

            if tool_name == "FinishTaskTool":

                self.emit(
                    "task_finished",
                    {"result": result},
                )

                return result