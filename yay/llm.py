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
        self.time = time or datetime.now(timezone.utc)


class Context:
    def __init__(
        self,
        provider,
        compress_threshold: float = 0.8,
        compression_callback=None,
    ):
        self.provider = provider
        self.messages: list[Message] = []
        self.compress_threshold = compress_threshold
        self.compression_callback = compression_callback
        self._system_prompt: str | None = None

    

    def set_system_prompt(self, text: str) -> None:
        """
        Set (or replace) the system prompt.

        The system message is always kept as the very first message.
        Calling this method is idempotent — repeated calls update the text.
        """
        self._system_prompt = text
        system_msg = Message(role="system", content=Content(text=text))

        if self.messages and self.messages[0].role == "system":
            self.messages[0] = system_msg
        else:
            self.messages.insert(0, system_msg)

    

    def append(self, message: Message) -> None:
        """
        Append a message.  System messages coming from outside (e.g. compressed
        context summaries) are handled specially so they do not displace the
        original system prompt.
        """
        
        
        if (
            message.role == "system"
            and getattr(message.content, "text", "").startswith(SYSTEM_SUMMARY_MARKER)
        ):
            self._insert_summary(message)
            return

        self.messages.append(message)

    def _insert_summary(self, summary_msg: Message) -> None:
        """
        Insert a compressed-context summary right after the real system prompt
        (position 1), replacing any previous summary.
        """
        
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
            text = getattr(getattr(msg, "content", None), "text", "")
            total += len(text) // 4
        return total

    @property
    def max_tokens(self) -> int:
        return getattr(self.provider, "context_length", 0)

    def usage_percent(self) -> float:
        max_tokens = self.max_tokens
        if max_tokens <= 0:
            return 0.0
        return (self.estimate_tokens() / max_tokens) * 100.0

    def needs_compression(self) -> bool:
        return self.usage_percent() >= self.compress_threshold * 100

    

    def compress(self) -> bool:
        """
        Summarise the conversation and replace the bulk of messages with the
        summary, keeping the system prompt and the last 10 messages intact.
        """
        
        to_summarise = [
            m for m in self.messages
            if m.role != "system"
        ]

        before_tokens = self.estimate_tokens()

        summary_text = self.provider.summarize(to_summarise)

        
        recent = [m for m in self.messages if m.role != "system"][-10:]

        
        new_messages: list[Message] = []

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
            self.compression_callback(
                {
                    "before_tokens": before_tokens,
                    "after_tokens": after_tokens,
                    "usage_percent": self.usage_percent(),
                }
            )

        return True

    def compress_if_needed(self) -> bool:
        if self.needs_compression():
            return self.compress()
        return False