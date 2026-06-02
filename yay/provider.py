
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