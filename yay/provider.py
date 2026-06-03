
class Provider:
    def __init__(self):
        pass

    def get_models(self):
        pass
        
    def set_model(self, model: str):

        self.model = model

        return model
    
    def set_base_url(self, base_url: str):
        pass

    def process(self, context):
        return self.backend.process(context)

class NonSelectedProvider(Provider):
    def __init__(self):
        self.model = ""
        self.base_url = ""

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