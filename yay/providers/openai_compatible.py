from __future__ import annotations

import json
import asyncio
import traceback
from openai import OpenAI

from ..llm import Message, Content
from ..provider import Provider
from ..tools import ToolsManager
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
        bus: EventBus,
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
            self.context_length = 128000

    async def _request(self, **kwargs):
        last_error = None

        for attempt in range(self.RETRY_COUNT):
            try:
                return await asyncio.to_thread(
                    self.client.chat.completions.create,
                    **kwargs,
                )

            except Exception as e:
                last_error = e

                await self.bus.emit(ErrorEvent(
                    source=self.name,
                    message=f"Request attempt {attempt+1} failed: {e}",
                    traceback=traceback.format_exc(),
                ))

                if attempt < self.RETRY_COUNT - 1:
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))

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

                msg = {"role": "assistant", "content": text or None}

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

            if text.strip():
                messages.append({"role": m.role, "content": text})

        return messages

    def _tools(self):
        if not self.tools_manager:
            return None

        tools = self.tools_manager.get_tools()
        if not tools:
            return None

        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.arguments,
                },
            }
            for t in tools.values()
        ]

    async def process(self, context) -> Message:
        tools = self._tools()

        kwargs = {
            "model": self.model,
            "messages": self._messages(context),
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self._request(**kwargs)

        msg = response.choices[0].message
        content_text = getattr(msg, "content", None) or ""

        raw_tool_calls = getattr(msg, "tool_calls", None)

        if raw_tool_calls:
            calls = []

            for tc in raw_tool_calls:
                try:
                    args = json.loads(getattr(tc.function, "arguments", "{}") or "{}")
                except Exception:
                    args = {}

                calls.append({
                    "id": tc.id or "",
                    "name": tc.function.name or "",
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

    async def process_stream(self, context, on_chunk=None) -> Message:
        tools = self._tools()

        stream_kwargs = {
            "model": self.model,
            "messages": self._messages(context),
            "stream": True,
        }

        if tools:
            stream_kwargs["tools"] = tools
            stream_kwargs["tool_choice"] = "auto"

        stream = await asyncio.to_thread(
            self.client.chat.completions.create,
            **stream_kwargs,
        )

        content = []
        tool_calls = {}

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
                        tool_calls[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }

                    if tc.id:
                        tool_calls[idx]["id"] = tc.id

                    fn = getattr(tc, "function", None)

                    if fn:
                        if getattr(fn, "name", None):
                            tool_calls[idx]["name"] += fn.name

                        if getattr(fn, "arguments", None):
                            tool_calls[idx]["arguments"] += fn.arguments

        except Exception as e:
            await self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Stream error: {e}",
                traceback=traceback.format_exc(),
            ))

            return Message(
                role="assistant",
                content=Content(text="".join(content)),
                tool=None,
            )

        calls = []

        for c in tool_calls.values():
            try:
                args = json.loads(c["arguments"] or "{}")
            except Exception:
                args = {}

            calls.append({
                "id": c["id"],
                "name": c["name"],
                "arguments": args,
            })

        return Message(
            role="assistant",
            content=Content(text="".join(content)),
            tool={"calls": calls} if calls else None,
        )

    async def summarize(self, messages) -> str:
        history = []

        for m in messages:
            text = getattr(getattr(m, "content", None), "text", "") or ""
            if text.strip():
                history.append(f"[{m.role}] {text}")

        try:
            response = await self._request(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize conversation: tasks, tools, decisions."
                        ),
                    },
                    {
                        "role": "user",
                        "content": "\n".join(history) or "(empty)",
                    },
                ],
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            await self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Summarize failed: {e}",
                traceback=traceback.format_exc(),
            ))

            return "Summary unavailable"
        
    async def get_models(self) -> list | dict:
        try:
            models = self.client.models.list()
            result = [
                getattr(model, "id", None)
                for model in getattr(models, "data", [])
                if getattr(model, "id", None)
            ]
            return sorted(result)
        except Exception as e:
            await self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Failed to fetch model list: {e}",
                traceback=traceback.format_exc()
            ))
            return {"error": str(e)}

    async def set_model(self, model: str) -> None:
        self.model = model
        try:
            self.context_length = self._detect_context_size()
        except Exception as e:
            await self.bus.emit(ErrorEvent(
                source=self.name,
                message=f"Failed to detect context size after model change: {e}",
                traceback=traceback.format_exc()
            ))

    def set_base_url(self, base_url: str) -> str:
        self._base_url = base_url
        self.client = OpenAI(api_key=self._api_key, base_url=base_url)
        return base_url

    def _detect_context_size(self) -> int:
        return 128000