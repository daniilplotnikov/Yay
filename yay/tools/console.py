from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import threading
import time

from ..tool import Tool

_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)

class TerminalSession:
    def __init__(self, shell: str = "/bin/bash", cols: int = 220, rows: int = 50):
        self.shell = shell
        self.cols  = cols
        self.rows  = rows

        self._master_fd: int | None = None
        self._pid: int | None = None
        self._lock = threading.Lock()
        self._output_buf: list[str] = []
        self._reader_thread: threading.Thread | None = None
        self._alive = False

        self._start()

    def _start(self) -> None:
        pid, master_fd = pty.fork()

        if pid == 0:
            _set_winsize(pty.STDOUT_FILENO, self.rows, self.cols)
            os.execvp(self.shell, [self.shell, "--login"])
            os._exit(1)

        self._pid       = pid
        self._master_fd = master_fd
        self._alive     = True

        _set_winsize(master_fd, self.rows, self.cols)

        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        time.sleep(0.3)
        self._drain()

    def _reader_loop(self) -> None:
        while self._alive and self._master_fd is not None:
            try:
                rlist, _, _ = select.select([self._master_fd], [], [], 0.05)
                if rlist:
                    data = os.read(self._master_fd, 4096)
                    if data:
                        text = data.decode("utf-8", errors="replace")
                        with self._lock:
                            self._output_buf.append(text)
            except OSError as e:
                if e.errno in (errno.EIO, errno.EBADF):
                    break  
            except Exception:
                break

    def _drain(self) -> str:
        with self._lock:
            out = "".join(self._output_buf)
            self._output_buf.clear()
        return _strip_ansi(out)

    @property
    def pid(self) -> int | None:
        return self._pid

    def is_alive(self) -> bool:
        if not self._alive or self._pid is None:
            return False
        try:
            os.kill(self._pid, 0)
            return True
        except ProcessLookupError:
            self._alive = False
            return False

    def resize(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        if self._master_fd is not None:
            _set_winsize(self._master_fd, rows, cols)

    def run(
        self,
        cmd: str,
        timeout: float = 30.0,
        sentinel: str | None = None,
        wait_ms: int = 100,
    ) -> dict:
        if not self.is_alive():
            return {"error": "Session is dead", "output": ""}

        marker = f"__TERM_DONE_{int(time.time()*1000)}__"
        full_cmd = f"{cmd}\necho \"{marker}:$?\"\n"

        self._drain()

        os.write(self._master_fd, full_cmd.encode())

        deadline = time.time() + timeout
        collected: list[str] = []

        while time.time() < deadline:
            time.sleep(wait_ms / 1000)
            chunk = self._drain()
            if chunk:
                collected.append(chunk)
            combined = "".join(collected)
            if marker in combined:
                break

        raw = "".join(collected)

        exit_code: int | None = None
        match = re.search(rf"{re.escape(marker)}:(\d+)", raw)
        if match:
            exit_code = int(match.group(1))

        output = re.sub(
            rf"echo \"{re.escape(marker)}:\$\?\".*?\n?", "", raw, flags=re.DOTALL
        )
        output = re.sub(rf".*?{re.escape(marker)}:\d+\r?\n?", "", output, flags=re.DOTALL)
        output = output.strip()

        timed_out = marker not in raw
        result: dict = {"output": output, "timed_out": timed_out}
        if exit_code is not None:
            result["code"] = exit_code
        if timed_out:
            result["error"] = f"Command exceeded timeout ({timeout}s)"
        return result

    def write_raw(self, data: str) -> None:
        if self._master_fd is not None:
            os.write(self._master_fd, data.encode())

    def read_pending(self) -> str:
        time.sleep(0.1)
        return self._drain()

    def close(self) -> None:
        self._alive = False
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGKILL)
                os.waitpid(self._pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
            self._pid = None

def _set_winsize(fd: int, rows: int, cols: int) -> None:
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
    except Exception:
        pass

class TerminalTool(Tool):
    def __init__(self, default_timeout: float = 30.0):
        super().__init__()
        self.name = "Terminal"
        self.description = (
            "Full persistent PTY terminal session(s). "
            "Supports interactive programs, multi-command state, raw input, resize."
        )

        self.arguments = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["open", "run", "write_raw", "read", "resize", "list", "close", "close_all"],
                },
                "session_id": {"type": "integer", "description": "ID returned by 'open'"},
                "cmd":        {"type": "string",  "description": "Shell command to run"},
                "raw":        {"type": "string",  "description": "Raw bytes to write (e.g. '\\x03' for Ctrl-C)"},
                "timeout":    {"type": "number",  "description": "Per-command timeout in seconds"},
                "shell":      {"type": "string",  "description": "Shell binary (default: /bin/bash)"},
                "cols":       {"type": "integer", "description": "Terminal width  (default: 220)"},
                "rows":       {"type": "integer", "description": "Terminal height (default: 50)"},
            },
            "required": ["action"],
        }

        self.default_timeout = default_timeout
        self._sessions: dict[int, TerminalSession] = {}
        self._next_id = 1
        self.is_safe = False

    def execute(self, args: dict) -> dict:
        action = args.get("action")

        if action == "open":
            return self._open(args)
        if action == "run":
            return self._run(args)
        if action == "write_raw":
            return self._write_raw(args)
        if action == "read":
            return self._read(args)
        if action == "resize":
            return self._resize(args)
        if action == "list":
            return self._list()
        if action == "close":
            return self._close(args)
        if action == "close_all":
            return self._close_all()

        return {"error": f"Unknown action: {action!r}"}

    def _open(self, args: dict) -> dict:
        shell = args.get("shell", "/bin/bash")
        cols  = int(args.get("cols", 220))
        rows  = int(args.get("rows", 50))
        try:
            sess = TerminalSession(shell=shell, cols=cols, rows=rows)
        except Exception as e:
            return {"error": f"Failed to open session: {e}"}
        sid = self._next_id
        self._next_id += 1
        self._sessions[sid] = sess
        return {"session_id": sid, "pid": sess.pid, "status": "open"}

    def _get_session(self, args: dict):
        sid = args.get("session_id")
        if sid is None:
            return None, {"error": "session_id is required"}
        sess = self._sessions.get(sid)
        if not sess:
            return None, {"error": f"Session {sid} not found"}
        return sess, None

    def _run(self, args: dict) -> dict:
        sess, err = self._get_session(args)
        if err:
            return err
        cmd = args.get("cmd")
        if not cmd:
            return {"error": "cmd is required"}
        timeout = float(args.get("timeout") or self.default_timeout)
        result = sess.run(cmd, timeout=timeout)
        result["session_id"] = args["session_id"]
        return result

    def _write_raw(self, args: dict) -> dict:
        sess, err = self._get_session(args)
        if err:
            return err
        raw = args.get("raw", "")
        sess.write_raw(raw)
        return {"session_id": args["session_id"], "status": "written", "bytes": len(raw)}

    def _read(self, args: dict) -> dict:
        sess, err = self._get_session(args)
        if err:
            return err
        output = sess.read_pending()
        return {"session_id": args["session_id"], "output": output}

    def _resize(self, args: dict) -> dict:
        sess, err = self._get_session(args)
        if err:
            return err
        cols = int(args.get("cols", sess.cols))
        rows = int(args.get("rows", sess.rows))
        sess.resize(cols, rows)
        return {"session_id": args["session_id"], "cols": cols, "rows": rows}

    def _list(self) -> dict:
        return {
            "sessions": [
                {"session_id": sid, "pid": s.pid, "alive": s.is_alive()}
                for sid, s in self._sessions.items()
            ]
        }

    def _close(self, args: dict) -> dict:
        sess, err = self._get_session(args)
        if err:
            return err
        sid = args["session_id"]
        sess.close()
        del self._sessions[sid]
        return {"session_id": sid, "status": "closed"}

    def _close_all(self) -> dict:
        closed = []
        for sid, sess in list(self._sessions.items()):
            sess.close()
            closed.append(sid)
        self._sessions.clear()
        return {"closed_session_ids": closed}

class ShellTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "Shell"
        self.description = (
            "Run shell commands (blocking or background) with process management via execute(). "
            "Can switch background processes to blocking mode dynamically."
        )

        self.arguments = {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "background": {"type": "boolean", "default": False},
                "action": {"type": "string", "enum": ["list", "check", "terminate", "terminate_all", "block"]},
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

        if action == "block":
            pid = args.get("pid")
            proc = self.processes.get(pid)
            if not proc:
                return {"error": "Process not found"}
            retcode = proc.wait()
            stdout, stderr = proc.communicate()
            del self.processes[pid]
            return {"pid": pid, "status": "finished", "stdout": stdout, "stderr": stderr, "code": retcode}

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
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
            except subprocess.TimeoutExpired:
                return {
                    "error": "Command timed out",
                    "suggestion": "Run with background=True"
                }
            return {"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode}