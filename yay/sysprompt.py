from __future__ import annotations

from datetime import datetime
import os
import platform


DEFAULT_SYSTEM_PROMPT = """
You are an autonomous AI agent operating inside a terminal environment.

{context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are an agent, not a chatbot.

Your goal is to complete tasks autonomously.
...
""".strip()


class SystemPromptBuilder:
    def __init__(
        self,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        include_environment: bool = True,
    ):
        self.system_prompt = system_prompt
        self.include_environment = include_environment

    def build(self) -> str:
        context = self._build_context()
        return self.system_prompt.format(context=context)

    def _build_context(self) -> str:
        if not self.include_environment:
            return ""

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENVIRONMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Current date:
  {now}

Operating system:
  {platform.system()} {platform.release()}

OS version:
  {platform.version()}

Current working directory:
  {os.getcwd()}
""".strip()