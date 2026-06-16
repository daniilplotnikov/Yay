from __future__ import annotations
from .openai_compatible import OpenAICompatibleProvider

class OpenRouter(OpenAICompatibleProvider):
    def __init__(self, api_key, model, tools_manager, bus):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://openrouter.ai/api/v1",
            tools_manager=tools_manager,
            bus=bus,
        )

        self.name = "OpenRouter"