from .llm import Model

class Provider:
    def __init__(self, backend: Model):
        self.backend = backend

    def set_backend(self, backend: Model):
        self.backend = backend

    def process(self, context):
        return self.backend.process(context)