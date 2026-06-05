from abc import ABC, abstractmethod

class Provider(ABC):
    def __init__(self):
        self.name: str = "Generic Provider"
        self.model: str = ""
        self.base_url: str = ""
        self.context_length: int = 0

    @abstractmethod
    def get_models(self) -> list[str]:
        raise NotImplementedError

    def set_model(self, model: str):
        self.model = model
        return model

    def get_model(self) -> str:
        return self.model

    def set_base_url(self, base_url: str):
        self.base_url = base_url
        return base_url

    def get_base_url(self) -> str:
        return self.base_url

    @abstractmethod
    def process(self, context):
        raise NotImplementedError

    @abstractmethod
    def process_stream(
        self,
        context,
        on_chunk=None,
    ):
        raise NotImplementedError

    @abstractmethod
    def summarize(self, messages) -> str:
        raise NotImplementedError

    def supports_tools(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return True

    def supports_summarization(self) -> bool:
        return True

class NonSelectedProvider(Provider):

    def __init__(self):
        super().__init__()
        self.name = "Not configured"

    def get_models(self):
        return []

    def set_model(self, model: str):
        raise RuntimeError(
            "Provider is not configured"
        )

    def set_base_url(self, base_url: str):
        raise RuntimeError(
            "Provider is not configured"
        )

    def process(self, context):
        raise RuntimeError(
            "Provider is not configured. "
            "Use /provider first."
        )

    def process_stream(
        self,
        context,
        on_chunk=None,
    ):
        raise RuntimeError(
            "Provider is not configured. "
            "Use /provider first."
        )

    def summarize(self, messages):
        raise RuntimeError(
            "Provider is not configured. "
            "Use /provider first."
        )