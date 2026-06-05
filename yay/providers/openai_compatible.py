import json
import time
import traceback
from openai import OpenAI
from ..llm import Message, Content
from ..provider import Provider
from ..managers import ToolsManager
from ..events import EventBus, ErrorEvent


class OpenAICompatibleProvider(Provider):

    RETRY_COUNT = 3
    RETRY_DELAY = 2

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        tools_manager: ToolsManager,
        bus: EventBus
    ):
        self._api_key = api_key
        self._base_url = base_url

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        self.name = "OpenAICompatibleProvider"
        self.model = model
        self.tools_manager = tools_manager
        self.bus = bus

        try:
            self.context_length = self._detect_context_size()
        except Exception as e:
            self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Failed to detect context size, defaulting to 128000: {e}",
                traceback=traceback.format_exc()
            ))
            self.context_length = 128000

    def _request(self, **kwargs):
        last_error = None
        for attempt in range(self.RETRY_COUNT):
            try:
                return self.client.chat.completions.create(**kwargs)
            except Exception as e:
                last_error = e
                self.bus.emit(ErrorEvent(
                    source=self.name,
                    message=f"Request attempt {attempt + 1}/{self.RETRY_COUNT} failed: {e}",
                    traceback=traceback.format_exc()
                ))
                if attempt < self.RETRY_COUNT - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
        raise last_error

    def _messages(self, context) -> list:
        messages = []
        for m in context.messages:
            text = getattr(getattr(m, "content", None), "text", "") or ""

            if m.role == "assistant" and getattr(m, "tool", None):
                calls = []
                tool_data = m.tool
                if isinstance(tool_data, dict) and "calls" in tool_data:
                    for call in tool_data["calls"]:
                        calls.append({
                            "id": call.get("id") or "",
                            "type": "function",
                            "function": {
                                "name": call.get("name", ""),
                                "arguments": json.dumps(call.get("arguments", {})),
                            },
                        })
                msg: dict = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                messages.append(msg)
                continue

            if m.role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": getattr(m, "tool_call_id", "") or "",
                    "content": text,
                })
                continue

            if m.role == "assistant":
                messages.append({"role": "assistant", "content": text or ""})
                continue

            if not text.strip():
                continue

            messages.append({"role": m.role, "content": text})

        return messages

    def _tools(self) -> list | None:
        if not self.tools_manager:
            return None
        tools = self.tools_manager.get_tools()
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.arguments,
                },
            }
            for tool in tools.values()
        ]

    @staticmethod
    def _parse_tool_calls(raw_calls: list) -> list:
        calls = []
        for tc in raw_calls:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except Exception:
                args = {}
            calls.append({
                "id":        tc.get("id", ""),
                "name":      tc.get("name", ""),
                "arguments": args,
            })
        return calls

    def get_models(self) -> list | dict:
        try:
            models = self.client.models.list()
            result = [
                getattr(model, "id", None)
                for model in getattr(models, "data", [])
                if getattr(model, "id", None)
            ]
            return sorted(result)
        except Exception as e:
            self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Failed to fetch model list: {e}",
                traceback=traceback.format_exc()
            ))
            return {"error": str(e)}

    def set_model(self, model: str) -> None:
        self.model = model
        try:
            self.context_length = self._detect_context_size()
        except Exception as e:
            self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Failed to detect context size after model change: {e}",
                traceback=traceback.format_exc()
            ))

    def set_base_url(self, base_url: str) -> str:
        self._base_url = base_url
        self.client = OpenAI(api_key=self._api_key, base_url=base_url)
        return base_url

    def process(self, context) -> Message:
        tools = self._tools()
        kwargs: dict = dict(
            model=self.model,
            messages=self._messages(context),
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self._request(**kwargs)
        msg = response.choices[0].message
        content_text = getattr(msg, "content", None) or ""

        raw_tool_calls = getattr(msg, "tool_calls", None)
        if raw_tool_calls:
            calls = []
            for tc in raw_tool_calls:
                try:
                    args = json.loads(
                        getattr(tc.function, "arguments", "{}") or "{}"
                    )
                except Exception as e:
                    self.bus.emit(ErrorEvent(
                        source=self.name,
                        message=f"Failed to parse tool call arguments for '{tc.function.name}': {e}",
                        traceback=traceback.format_exc()
                    ))
                    args = {}
                calls.append({
                    "id":        tc.id or "",
                    "name":      tc.function.name or "",
                    "arguments": args,
                })
            return Message(
                role="assistant",
                content=Content(text=content_text),
                tool={"calls": calls},
            )

        return Message(
            role="assistant",
            content=Content(text=content_text),
            tool=None,
        )

    def process_stream(self, context, on_chunk=None) -> Message:
        tools = self._tools()
        stream_kwargs: dict = dict(
            model=self.model,
            messages=self._messages(context),
            stream=True,
        )
        if tools:
            stream_kwargs["tools"] = tools
            stream_kwargs["tool_choice"] = "auto"

        stream = None
        last_error = None
        for attempt in range(self.RETRY_COUNT):
            try:
                stream = self.client.chat.completions.create(**stream_kwargs)
                break
            except Exception as e:
                last_error = e
                self.bus.emit(ErrorEvent(
                    source=self.name,
                    message=f"Stream attempt {attempt + 1}/{self.RETRY_COUNT} failed: {e}",
                    traceback=traceback.format_exc()
                ))
                if attempt < self.RETRY_COUNT - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))

        if stream is None:
            raise last_error

        content: list[str] = []
        tool_calls: dict[int, dict] = {}

        try:
            for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                if getattr(delta, "content", None):
                    text = delta.content
                    content.append(text)
                    if on_chunk:
                        on_chunk({"type": "text", "content": text})

                for tc in getattr(delta, "tool_calls", None) or []:
                    idx = tc.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": "", "name": "", "arguments": ""}

                    if tc.id:
                        tool_calls[idx]["id"] = tc.id

                    fn = getattr(tc, "function", None)
                    if fn:
                        if getattr(fn, "name", None):
                            tool_calls[idx]["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            tool_calls[idx]["arguments"] += fn.arguments

        except Exception as e:
            self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Error while reading stream: {e}",
                traceback=traceback.format_exc()
            ))
            if content:
                return Message(
                    role="assistant",
                    content=Content(text="".join(content)),
                    tool=None,
                )
            raise

        calls = self._parse_tool_calls(list(tool_calls.values()))

        return Message(
            role="assistant",
            content=Content(text="".join(content)),
            tool={"calls": calls} if calls else None,
        )

    def summarize(self, messages) -> str:
        history = []
        for m in messages:
            text = getattr(getattr(m, "content", None), "text", "") or ""
            if text.strip():
                history.append(f"[{m.role}] {text}")

        try:
            response = self._request(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Create a concise summary of the conversation. "
                            "Keep important facts, user requirements, decisions, "
                            "tool results, generated files and current task state."
                        ),
                    },
                    {
                        "role": "user",
                        "content": "\n".join(history) or "(empty conversation)",
                    },
                ],
            )
            return response.choices[0].message.content or "Conversation summary unavailable."
        except Exception as e:
            self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Failed to summarize conversation: {e}",
                traceback=traceback.format_exc()
            ))
            return "Conversation summary unavailable."

    def _detect_context_size(self) -> int:
        def find_context(obj, depth: int = 0) -> int | None:
            if depth > 6:
                return None

            if isinstance(obj, dict):
                for key in ("context_length", "max_context_length",
                            "context_window", "max_tokens"):
                    val = obj.get(key)
                    if val is not None:
                        try:
                            n = int(val)
                            if n > 0:
                                return n
                        except (ValueError, TypeError):
                            pass
                for v in obj.values():
                    if isinstance(v, (dict, list)) or hasattr(v, "__dict__"):
                        result = find_context(v, depth + 1)
                        if result:
                            return result

            elif hasattr(obj, "__dict__"):
                return find_context(vars(obj), depth)

            elif isinstance(obj, (list, tuple)):
                for item in obj:
                    if isinstance(item, (dict, list)) or hasattr(item, "__dict__"):
                        result = find_context(item, depth + 1)
                        if result:
                            return result

            return None

        base_url_str = str(self.client.base_url).rstrip("/")

        if "openrouter.ai" in base_url_str:
            try:
                import requests
                api_root = base_url_str.split("/api/v1")[0]
                response = requests.get(
                    f"{api_root}/api/v1/models",
                    timeout=10,
                )
                response.raise_for_status()
                for model in response.json().get("data", []):
                    if model.get("id") == self.model:
                        result = find_context(model)
                        if result:
                            return result
            except Exception as e:
                self.bus.emit(ErrorEvent(
                    source=self.name,
                    message=f"Failed to fetch context size from OpenRouter: {e}",
                    traceback=traceback.format_exc()
                ))

        try:
            models = self.client.models.list()
            model_list = getattr(models, "data", None)
            if model_list is None and isinstance(models, list):
                model_list = models
            for model in (model_list or []):
                model_id = (
                    getattr(model, "id", None)
                    or (model.get("id") if isinstance(model, dict) else None)
                )
                if model_id != self.model:
                    continue
                result = find_context(model)
                if result:
                    return result
        except Exception as e:
            self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Failed to fetch context size from model list: {e}",
                traceback=traceback.format_exc()
            ))

        return 128000