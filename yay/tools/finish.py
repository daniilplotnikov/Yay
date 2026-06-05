from .. tool import Tool

class FinishTaskTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "FinishTask"
        self.description = "Finish current task"

        self.arguments = {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"}
            }
        }

    def execute(self, args):
        return {
            "status": "finished",
            "success": args.get("success", True),
        }