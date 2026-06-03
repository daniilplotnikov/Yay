from .. tool import Tool

class FinishTaskTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "FinishTask"
        self.description = "Finish current task and return final summary"

        self.arguments = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "success": {"type": "boolean"}
            },
            "required": ["summary"]
        }

    def execute(self, args):
        return {
            "status": "finished",
            "success": args.get("success", True),
            "summary": args["summary"]
        }