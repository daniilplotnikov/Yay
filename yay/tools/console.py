from ..tool import Tool
import subprocess

class CommandTool(Tool):
    def __init__(self):
        super().__init__()
        self.description = "Run shell command (blocking)"

        self.arguments = {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"}
            },
            "required": ["cmd"]
        }

        is_safe = False

    def execute(self, args):
        cmd = args["cmd"]

        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "code": result.returncode
        }

class CommandBackgroundTool(Tool):
    def __init__(self):
        super().__init__()
        self.description = "Run command in background"

        self.arguments = {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"}
            },
            "required": ["cmd"]
        }

        self.processes = {}

        self.is_safe = False

    def execute(self, args):
        cmd = args["cmd"]

        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        self.processes[proc.pid] = proc

        return {
            "pid": proc.pid,
            "status": "running"
        }