"""Tests for Context, Message, Content: token estimation, compression, system prompt."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from yay.llm import Content, Message, Context


class TestContent:
    def test_default_text(self):
        c = Content()
        assert c.text == ""

    def test_repr_short(self):
        c = Content(text="hello")
        assert "hello" in repr(c)

    def test_repr_long(self):
        c = Content(text="a" * 100)
        assert "…" in repr(c)


class TestMessage:
    def test_default_time(self):
        import datetime
        m = Message(role="user", content=Content(text="hi"))
        assert isinstance(m.time, datetime.datetime)

    def test_tool_calls_default(self):
        m = Message(role="assistant", content=Content(text="hi"))
        assert m.tool_calls == []

    def test_repr(self):
        m = Message(role="user", content=Content(text="hi"))
        assert "user" in repr(m)


class TestContext:
    def test_init_empty(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider)
        assert ctx.messages == []
        assert ctx.compress_threshold == 0.8

    def test_init_with_system_prompt(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider, system_prompt="You are a bot")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "system"
        assert ctx.messages[0].content.text == "You are a bot"

    def test_set_system_prompt_replaces_existing(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider, system_prompt="First")
        ctx.set_system_prompt("Second")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].content.text == "Second"

    def test_set_system_prompt_inserts_if_no_system(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider)
        ctx.set_system_prompt("New system")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "system"

    def test_append_message(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider)
        ctx.append(Message(role="user", content=Content(text="hi")))
        assert len(ctx.messages) == 1

    def test_estimate_tokens(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider)
        ctx.append(Message(role="user", content=Content(text="a" * 16)))
        assert ctx.estimate_tokens() == 4

    def test_estimate_tokens_empty(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider)
        assert ctx.estimate_tokens() == 0

    def test_max_tokens_from_context_length(self):
        provider = MagicMock()
        provider.context_length = 8000
        ctx = Context(provider=provider)
        assert ctx.max_tokens == 8000

    def test_max_tokens_fallback(self):
        provider = MagicMock(spec=[])
        ctx = Context(provider=provider)
        assert ctx.max_tokens == 0

    def test_usage_percent_zero_when_no_max(self):
        provider = MagicMock(spec=[])
        ctx = Context(provider=provider)
        assert ctx.usage_percent() == 0.0

    def test_usage_percent(self):
        provider = MagicMock()
        provider.context_length = 100
        ctx = Context(provider=provider)
        ctx.append(Message(role="user", content=Content(text="a" * 80)))
        assert ctx.usage_percent() == 20.0

    def test_needs_compression_below_threshold(self):
        provider = MagicMock()
        provider.context_length = 100
        ctx = Context(provider=provider, compress_threshold=0.8)
        ctx.append(Message(role="user", content=Content(text="a" * 70)))
        assert ctx.needs_compression() is False

    def test_needs_compression_above_threshold(self):
        provider = MagicMock()
        provider.context_length = 100
        ctx = Context(provider=provider, compress_threshold=0.8)
        ctx.append(Message(role="user", content=Content(text="a" * 330)))
        assert ctx.needs_compression() is True

    def test_insert_summary_removes_old_summaries(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider, system_prompt="System")
        ctx.append(Message(
            role="system",
            content=Content(text="[COMPRESSED_CONTEXT]\n\nOld summary")
        ))
        ctx.append(Message(
            role="system",
            content=Content(text="[COMPRESSED_CONTEXT]\n\nNew summary")
        ))
        summaries = [
            m for m in ctx.messages
            if m.content.text.startswith("[COMPRESSED_CONTEXT]")
        ]
        assert len(summaries) == 1
        assert "New summary" in summaries[0].content.text

    def test_insert_summary_preserves_system_prompt(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider, system_prompt="System")
        ctx.append(Message(
            role="system",
            content=Content(text="[COMPRESSED_CONTEXT]\n\nSummary")
        ))
        assert ctx.messages[0].content.text == "System"
        assert ctx.messages[1].content.text.startswith("[COMPRESSED_CONTEXT]")

    def test_compression_tasks_set_exists(self):
        """Verify _compression_tasks set is initialized on Context."""
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider)
        assert hasattr(ctx, '_compression_tasks')
        assert isinstance(ctx._compression_tasks, set)
        assert len(ctx._compression_tasks) == 0

    def test_context_init_with_no_system_prompt(self):
        provider = MagicMock()
        provider.context_length = 1000
        ctx = Context(provider=provider)
        assert ctx._system_prompt is None
