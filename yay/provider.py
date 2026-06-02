from .llm import Model

class LLMProvider:
    def __init__(self, backend: Model):
        self.backend = backend

    def set_backend(self, backend: Model):
        self.backend = backend

    def process(self, context):
        return self.backend.process(context)