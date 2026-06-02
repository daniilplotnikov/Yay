from ..tool import Tool
import subprocess

class CMDTool(Tool):
    def __init__(self):
        super().__init__()
        self.description = "Run shell command (blocking or background) with process management via execute()"

        self.arguments = {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "background": {"type": "boolean", "default": False},
                "action": {"type": "string", "enum": ["list", "check", "terminate", "terminate_all"]},
                "pid": {"type": "integer"}  
            },
        }

        self.processes = {}
        self.is_safe = False

    def execute(self, args):
        action = args.get("action")

        if action == "list":
            active = [pid for pid, proc in self.processes.items() if proc.poll() is None]
            return {"active_pids": active}

        if action == "check":
            pid = args.get("pid")
            proc = self.processes.get(pid)
            if not proc:
                return {"error": "Process not found"}
            retcode = proc.poll()
            if retcode is None:
                return {"pid": pid, "status": "running"}
            else:
                stdout, stderr = proc.communicate()
                del self.processes[pid]
                return {"pid": pid, "status": "finished", "stdout": stdout, "stderr": stderr, "code": retcode}

        if action == "terminate":
            pid = args.get("pid")
            proc = self.processes.get(pid)
            if not proc:
                return {"error": "Process not found"}
            proc.terminate()
            retcode = proc.wait()
            stdout, stderr = proc.communicate()
            del self.processes[pid]
            return {"pid": pid, "status": "terminated", "stdout": stdout, "stderr": stderr, "code": retcode}

        if action == "terminate_all":
            terminated = []
            for pid in list(self.processes.keys()):
                terminated.append(self.execute({"action": "terminate", "pid": pid}))
            return terminated

        cmd = args.get("cmd")
        if not cmd:
            return {"error": "No command specified"}

        background = args.get("background", False)

        if background:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            self.processes[proc.pid] = proc
            return {"pid": proc.pid, "status": "running"}
        else:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            return {"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode}