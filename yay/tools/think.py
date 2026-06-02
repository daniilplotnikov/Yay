from ..tool import Tool

class ThinkTool(Tool):
    def __init__(self):
        super().__init__()

        self.description = (
            "Internal reasoning step. "
            "Use to plan before acting."
        )

        self.is_safe = True

        self.arguments = {
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string"
                }
            },
            "required": ["thought"]
        }

    def execute(self, args):
        return args["thought"]