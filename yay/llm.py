from __future__ import annotations

import inspect
import asyncio

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .events import EventBus, ContextCompressionNeededEvent

SYSTEM_SUMMARY_MARKER = "[COMPRESSED_CONTEXT]"


class Content:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def __repr__(self) -> str:
        preview = self.text[:60].replace("\n", "\\n")
        return f"Content({preview!r}{'…' if len(self.text) > 60 else ''})"


class Message:
    def __init__(
        self,
        content: Content,
        role: str,
        tool: Any = None,
        tool_call_id: Optional[str] = None,
        tool_calls: Optional[List] = None,
        time: Optional[datetime] = None,
    ) -> None:
        self.content = content
        self.role = role
        self.tool = tool
        self.tool_call_id = tool_call_id
        self.tool_calls = tool_calls or []
        self.time = time or datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return f"Message(role={self.role!r}, tool={bool(self.tool)})"


class Context:
    def __init__(
        self,
        provider: Any,
        compress_threshold: float = 0.8,
        compression_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        system_prompt: Optional[str] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self.provider = provider
        self.messages: List[Message] = []
        self.compress_threshold = compress_threshold
        self.compression_callback = compression_callback
        self._system_prompt: Optional[str] = None
        self.bus = bus
        self._compression_tasks: set[asyncio.Task] = set()

        if system_prompt:
            self.set_system_prompt(system_prompt)

    def set_system_prompt(self, text: str) -> None:
        self._system_prompt = text
        system_msg = Message(role="system", content=Content(text=text))
        if self.messages and self.messages[0].role == "system":
            self.messages[0] = system_msg
        else:
            self.messages.insert(0, system_msg)

    def append(self, message: Message) -> None:
        if (
            message.role == "system"
            and getattr(message.content, "text", "").startswith(SYSTEM_SUMMARY_MARKER)
        ):
            self._insert_summary(message)
        else:
            self.messages.append(message)

        if self.bus and self.needs_compression():
            task = asyncio.create_task(
                self.bus.emit(ContextCompressionNeededEvent())
            )
            # Prevent the task from being garbage-collected before completion
            self._compression_tasks.add(task)
            task.add_done_callback(self._compression_tasks.discard)

    def _insert_summary(self, summary_msg: Message) -> None:
        self.messages = [
            m for m in self.messages
            if not (
                m.role == "system"
                and getattr(m.content, "text", "").startswith(SYSTEM_SUMMARY_MARKER)
            )
        ]
        insert_at = 1 if (self.messages and self.messages[0].role == "system") else 0
        self.messages.insert(insert_at, summary_msg)

    def estimate_tokens(self) -> int:
        total = 0
        for msg in self.messages:
            text = getattr(getattr(msg, "content", None), "text", "") or ""
            total += len(text) // 4
        return total

    @property
    def max_tokens(self) -> int:
        for attr in ("context_length", "max_tokens", "_context_length", "ctx_length"):
            val = getattr(self.provider, attr, None)
            if val:
                try:
                    n = int(val)
                    if n > 0:
                        return n
                except (TypeError, ValueError):
                    pass
        return 0

    def usage_percent(self) -> float:
        max_t = self.max_tokens
        if max_t <= 0:
            return 0.0
        return (self.estimate_tokens() / max_t) * 100.0

    def needs_compression(self) -> bool:
        return self.usage_percent() >= self.compress_threshold * 100

    async def compress(self) -> bool:

        non_system = [m for m in self.messages if m.role != "system"]
        if len(non_system) <= 10:
            return False

        to_summarise = non_system[:-10]
        recent = non_system[-10:]

        before_tokens = self.estimate_tokens()

        if inspect.iscoroutinefunction(self.provider.summarize):
            summary_text = await self.provider.summarize(to_summarise)
        else:
            import asyncio as _asyncio
            summary_text = await _asyncio.to_thread(self.provider.summarize, to_summarise)

        new_messages: List[Message] = []

        if self._system_prompt:
            new_messages.append(
                Message(role="system", content=Content(text=self._system_prompt))
            )

        new_messages.append(
            Message(
                role="system",
                content=Content(text=f"{SYSTEM_SUMMARY_MARKER}\n\n{summary_text}"),
            )
        )

        new_messages.extend(recent)
        self.messages = new_messages

        after_tokens = self.estimate_tokens()

        if self.compression_callback:
            info = {
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "usage_percent": self.usage_percent(),
            }
            if inspect.iscoroutinefunction(self.compression_callback):
                await self.compression_callback(info)
            else:
                self.compression_callback(info)

        return True