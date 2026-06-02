from datetime import datetime, timezone

SYSTEM_SUMMARY_MARKER = "[COMPRESSED_CONTEXT]"

class Content:
    def __init__(self, text=""):
        self.text = text


class Message:
    def __init__(
        self,
        content: Content,
        role: str,
        tool=None,
        tool_call_id=None,
        tool_calls=None,
        time=None,
    ):
        self.content = content
        self.role = role

        self.tool = tool

        self.tool_call_id = tool_call_id

        self.tool_calls = tool_calls or []

        self.time = (
            time
            or datetime.now(timezone.utc)
        )

class Context:
    def __init__(
        self,
        provider,
        compress_threshold: float = 0.8,
        compression_callback=None,
    ):
        self.provider = provider
        self.messages = []
        self.compress_threshold = compress_threshold
        self.compression_callback = compression_callback

    def append(self, message):
        self.messages.append(message)

    def estimate_tokens(self):
        total = 0
        for msg in self.messages:
            text = getattr(getattr(msg, "content", None), "text", "")
            total += len(text) // 4  
        return total

    @property
    def max_tokens(self):
        return getattr(self.provider, "max_context_tokens", 0)

    def usage_percent(self):
        max_tokens = self.max_tokens
        if max_tokens <= 0:
            return 0
        return (self.estimate_tokens() / max_tokens) * 100

    def needs_compression(self):
        return self.usage_percent() >= self.compress_threshold * 100

    def compress(self):
        if not self.needs_compression():
            return False

        old_messages = [
            m for m in self.messages
            if not (m.role == "system" and getattr(getattr(m, "content", None), "text", "").startswith(SYSTEM_SUMMARY_MARKER))
        ]

        summary_text = self.provider.summarize(old_messages)

        recent_messages = self.messages[-10:] if len(self.messages) > 10 else []

        self.messages = [
            Message(
                role="system",
                content=Content(
                    text=f"{SYSTEM_SUMMARY_MARKER}\n\n{summary_text}"
                )
            )
        ] + recent_messages

        if self.compression_callback:
            self.compression_callback({
                "old_tokens": sum(len(getattr(getattr(m, "content", None), "text", "")) // 4 for m in old_messages),
                "new_tokens": self.estimate_tokens(),
                "usage_percent": self.usage_percent(),
            })

        return True

    def compress_if_needed(self):
        if self.needs_compression():
            return self.compress()
        return False