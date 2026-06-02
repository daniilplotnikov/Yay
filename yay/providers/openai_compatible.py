import json
from openai import OpenAI
from ..llm import Message, Content
from ..provider import Provider


class OpenAICompatibleProvider(Provider):
    def __init__(self, api_key: str, model: str, base_url: str, tools: list = None):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model
        self.tools = tools or []

        self.max_context_tokens = (
            self._detect_context_size()
        )

    def _messages(self, context):
        messages = []

        for m in context.messages:
            text = getattr(getattr(m, "content", None), "text", "") or ""

            if m.role == "assistant" and getattr(m, "tool", None):
                calls = []
                tool_data = m.tool
                if isinstance(tool_data, dict) and "calls" in tool_data:
                    for call in tool_data["calls"]:
                        calls.append({
                            "id": call.get("id"),
                            "type": "function",
                            "function": {
                                "name": call.get("name"),
                                "arguments": json.dumps(call.get("arguments", {})),
                            }
                        })

                messages.append({
                    "role": "assistant",
                    "content": text,
                    "tool_calls": calls,
                })
                continue

            if m.role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": getattr(
                        m,
                        "tool_call_id",
                        ""
                    ),
                    "content": text,
                })
                continue

            if not text.strip():
                continue

            messages.append({
                "role": m.role,
                "content": text,
            })

        return messages

    def _tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.arguments,
                },
            }
            for tool in self.tools
        ]

    def get_models(self):
        try:
            models = self.client.models.list()
            result = [getattr(model, "id", None) for model in getattr(models, "data", []) if getattr(model, "id", None)]
            return sorted(result)
        except Exception as e:
            return {"error": str(e)}

    def set_model(self, model):
        self.model = model
        self.max_context_tokens = (
            self._detect_context_size()
        )

    def set_base_url(self, base_url: str):
        self.client.base_url = base_url
        return base_url

    def process(self, context):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self._messages(context),
            tools=self._tools() if self.tools else None,
            tool_choice="auto",
        )

        msg = response.choices[0].message
        content_text = getattr(msg, "content", "") or ""

        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            calls = []
            for tc in tool_calls:
                try:
                    args_raw = getattr(getattr(tc, "function", None), "arguments", "{}") or "{}"
                    args = json.loads(args_raw)
                except Exception:
                    args = {}
                calls.append({
                    "id": getattr(tc, "id", None),
                    "name": getattr(getattr(tc, "function", None), "name", None),
                    "arguments": args,
                })
            return Message(
                role="assistant",
                content=Content(text=content_text),
                tool={"calls": calls},
            )

        tool_data = getattr(msg, "tool", None)
        if isinstance(tool_data, dict) and "name" in tool_data:
            try:
                args = json.loads(tool_data.get("arguments", "{}") or "{}")
            except Exception:
                args = {}
            return Message(
                role="assistant",
                content=Content(text=content_text),
                tool={"name": tool_data.get("name"), "arguments": args},
            )

        return Message(
            role="assistant",
            content=Content(text=content_text),
            tool=None,
        )

    def summarize(self, messages):
        history = []

        for m in messages:
            text = getattr(
                getattr(m, "content", None),
                "text",
                "",
            )

            if text.strip():
                history.append(
                    f"[{m.role}] {text}"
                )

        response = self.client.chat.completions.create(
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
                    "content": "\n".join(history),
                },
            ],
        )

        return (
            response.choices[0]
            .message
            .content
            or "Conversation summary unavailable."
        )

    def process_stream(self, context, on_chunk=None):

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=self._messages(context),
            tools=self._tools() if self.tools else None,
            tool_choice="auto",
            stream=True,
        )

        content = []
        tool_calls = {}

        for chunk in stream:
            delta = chunk.choices[0].delta

            if getattr(delta, "content", None):
                text = delta.content
                content.append(text)
                if on_chunk:
                    on_chunk({"type": "text", "content": text})

            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": tc.id, "name": "", "arguments": ""}
                    fn = getattr(tc, "function", None)
                    if fn:
                        if getattr(fn, "name", None):
                            tool_calls[idx]["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            tool_calls[idx]["arguments"] += fn.arguments

        text = "".join(content)
        calls = []
        for tc in tool_calls.values():
            try:
                args = json.loads(tc["arguments"] or "{}")
            except Exception:
                args = {}
            calls.append({
                "id": tc["id"],
                "name": tc["name"],
                "arguments": args,
            })

        return Message(
            role="assistant",
            content=Content(text=text),
            tool={"calls": calls} if calls else None,
        )
    
    def _detect_context_size(self) -> int:
        def find_context(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k.lower() in ("context_length", "max_context_length", "max_tokens", "context_window"):
                        try:
                            return int(v)
                        except Exception:
                            continue
                    result = find_context(v)
                    if result:
                        return result
            elif hasattr(obj, "__dict__"):
                for k, v in vars(obj).items():
                    if k.lower() in ("context_length", "max_context_length", "max_tokens", "context_window"):
                        try:
                            return int(v)
                        except Exception:
                            continue
                    result = find_context(v)
                    if result:
                        return result
            elif isinstance(obj, (list, tuple, set)):
                for item in obj:
                    result = find_context(item)
                    if result:
                        return result
            return None

        if "openrouter.ai" in str(self.client.base_url):
            try:
                import requests
                response = requests.get(
                    f"{str(self.client.base_url)}/api/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                models = data.get("data", data)
                for model in models:
                    if model.get("id") == self.model:
                        result = find_context(model)
                        if result:
                            return result
            except Exception:
                pass

        try:
            models = self.client.models.list()
            for model in getattr(models, "data", []):
                if getattr(model, "id", None) != self.model:
                    continue
                result = find_context(model)
                if result:
                    return result
        except Exception:
            pass

        return 32000