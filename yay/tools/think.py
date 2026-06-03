from ..tool import Tool

class ThinkTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "Think"
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
    
class PlanTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "Plan"
        self.description = (
            "Create and manage task plans."
        )

        self.is_safe = True

        self.plan = []

        self.arguments = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create",
                        "complete",
                        "get"
                    ]
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    }
                },
                "index": {
                    "type": "integer"
                }
            },
            "required": ["action"]
        }

    def execute(self, args):
        action = args["action"]

        if action == "create":
            self.plan = [
                {
                    "task": step,
                    "completed": False
                }
                for step in args.get("steps", [])
            ]

            return {
                "status": "created",
                "plan": self.plan
            }

        if action == "complete":
            index = args["index"]

            if index < 0 or index >= len(self.plan):
                return {
                    "error": "Invalid step index"
                }

            self.plan[index]["completed"] = True

            return {
                "status": "completed",
                "step": self.plan[index]
            }

        if action == "get":
            return {
                "plan": self.plan
            }

        return {
            "error": f"Unknown action: {action}"
        }