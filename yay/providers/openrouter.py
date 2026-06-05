import traceback
from openai import OpenAI
from ..managers import ToolsManager
from ..events import EventBus, ErrorEvent
from .openai_compatible import OpenAICompatibleProvider

class OpenRouter(OpenAICompatibleProvider):

    RETRY_COUNT = 3
    RETRY_DELAY = 2

    def __init__(
        self,
        api_key: str,
        model: str,
        tools_manager: ToolsManager,
        bus: EventBus
    ):
        self._api_key = api_key
        self._base_url = "https://openrouter.ai/api/v1"

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )

        self.name = "OpenRouter"
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