from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from abc import ABC, abstractmethod
from queue import Empty, Queue
from typing import Any, Callable, Dict, Generator, List, Optional

class MCPTransport(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def send(self, message: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        pass

    def _make_id(self) -> str:
        return str(uuid.uuid4())

    def _build_request(self, method: str, params: Dict[str, Any], req_id: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

    def _build_notification(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

class MCPHttpSseTransport(MCPTransport):
    def __init__(
        self,
        base_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        legacy_sse_path: str = "/sse",
        post_path: str = "/",
    ):
        try:
            import requests
        except ImportError:
            raise ImportError("pip install requests")

        self.base_url = base_url.rstrip("/")
        self.extra_headers = headers or {}
        self.timeout = timeout
        self.post_path = post_path
        self.legacy_sse_path = legacy_sse_path

        import requests
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.extra_headers,
        })

        self._pending: Dict[str, Queue] = {}  
        self._notification_handlers: List[Callable] = []
        self._sse_thread: Optional[threading.Thread] = None
        self._running = False
        self._session_id: Optional[str] = None  

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=2)

    def _post_url(self) -> str:
        return self.base_url + self.post_path

    def _sse_url(self) -> str:
        return self.base_url + self.legacy_sse_path

    def send(self, message: Dict[str, Any]) -> None:

        headers = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        self._session.post(self._post_url(), json=message, headers=headers, timeout=self.timeout)

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        req_id = self._make_id()
        payload = self._build_request(method, params, req_id)

        headers = {"Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        resp = self._session.post(
            self._post_url(),
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()

        if "Mcp-Session-Id" in resp.headers:
            self._session_id = resp.headers["Mcp-Session-Id"]

        content_type = resp.headers.get("Content-Type", "")

        if "text/event-stream" in content_type:
            return self._parse_sse_response(resp)

        data = resp.json()
        if "error" in data:
            raise MCPError(data["error"])
        return data

    def _parse_sse_response(self, resp) -> Dict[str, Any]:

        result = None
        for line in resp.iter_lines(decode_unicode=True):
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                raw = line[5:].strip()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "result" in msg or "error" in msg:
                    result = msg
                    break

                self._dispatch_notification(msg)

        if result is None:
            raise MCPError({"code": -32000, "message": "No response in SSE stream"})
        if "error" in result:
            raise MCPError(result["error"])
        return result

    def _dispatch_notification(self, msg: Dict[str, Any]) -> None:
        for handler in self._notification_handlers:
            try:
                handler(msg)
            except Exception:
                pass

    def on_notification(self, handler: Callable) -> None:
        self._notification_handlers.append(handler)

    def start_sse_listener(self) -> None:

        self._sse_thread = threading.Thread(
            target=self._sse_listener_loop, daemon=True
        )
        self._sse_thread.start()

    def _sse_listener_loop(self) -> None:
        import requests
        headers = {"Accept": "text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            with self._session.get(
                self._sse_url(),
                headers=headers,
                stream=True,
                timeout=None,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not self._running:
                        break
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        self._route_message(msg)
        except Exception:
            pass

    def _route_message(self, msg: Dict[str, Any]) -> None:
        req_id = msg.get("id")
        if req_id and req_id in self._pending:
            self._pending[req_id].put(msg)
        elif "method" in msg:
            self._dispatch_notification(msg)

class MCPStdioTransport(MCPTransport):

    def __init__(
        self,
        command: List[str],
        *,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ):
        self.command = command
        self.env = env
        self.timeout = timeout

        self._process: Optional[subprocess.Popen] = None
        self._pending: Dict[str, Queue] = {}
        self._notification_handlers: List[Callable] = []
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        import os
        env = {**os.environ, **(self.env or {})}
        self._process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )
        self._running = True
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._reader_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._process:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass

    def send(self, message: Dict[str, Any]) -> None:
        if not self._process:
            raise RuntimeError("Transport not started")
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        req_id = self._make_id()
        payload = self._build_request(method, params, req_id)
        q: Queue = Queue()
        self._pending[req_id] = q
        self.send(payload)
        try:
            result = q.get(timeout=self.timeout)
        except Empty:
            raise TimeoutError(f"No response for {method} within {self.timeout}s")
        finally:
            self._pending.pop(req_id, None)

        if "error" in result:
            raise MCPError(result["error"])
        return result

    def _reader_loop(self) -> None:
        while self._running and self._process:
            try:
                line = self._process.stdout.readline()
            except Exception:
                break
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._route_message(msg)

    def _route_message(self, msg: Dict[str, Any]) -> None:
        req_id = msg.get("id")
        if req_id and req_id in self._pending:
            self._pending[req_id].put(msg)
        elif "method" in msg:
            for handler in self._notification_handlers:
                try:
                    handler(msg)
                except Exception:
                    pass

    def on_notification(self, handler: Callable) -> None:
        self._notification_handlers.append(handler)

class MCPWebSocketTransport(MCPTransport):
    def __init__(self, url: str, *, timeout: int = 30, headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.timeout = timeout
        self.extra_headers = headers or {}

        self._ws = None
        self._pending: Dict[str, Queue] = {}
        self._notification_handlers: List[Callable] = []
        self._thread: Optional[threading.Thread] = None
        self._connected = threading.Event()
        self._running = False

    def start(self) -> None:
        try:
            import websocket
        except ImportError:
            raise ImportError("pip install websocket-client")

        import websocket

        self._ws = websocket.WebSocketApp(
            self.url,
            header=self.extra_headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._running = True
        self._thread = threading.Thread(
            target=self._ws.run_forever, daemon=True
        )
        self._thread.start()
        if not self._connected.wait(timeout=self.timeout):
            raise TimeoutError("WebSocket connection timed out")

    def stop(self) -> None:
        self._running = False
        if self._ws:
            self._ws.close()

    def send(self, message: Dict[str, Any]) -> None:
        self._ws.send(json.dumps(message, ensure_ascii=False))

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        req_id = self._make_id()
        payload = self._build_request(method, params, req_id)
        q: Queue = Queue()
        self._pending[req_id] = q
        self.send(payload)
        try:
            result = q.get(timeout=self.timeout)
        except Empty:
            raise TimeoutError(f"No response for {method} within {self.timeout}s")
        finally:
            self._pending.pop(req_id, None)

        if "error" in result:
            raise MCPError(result["error"])
        return result

    def _on_open(self, ws) -> None:
        self._connected.set()

    def _on_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        req_id = msg.get("id")
        if req_id and req_id in self._pending:
            self._pending[req_id].put(msg)
        elif "method" in msg:
            for handler in self._notification_handlers:
                try:
                    handler(msg)
                except Exception:
                    pass

    def _on_error(self, ws, error) -> None:
        pass

    def _on_close(self, ws, code, msg) -> None:
        self._connected.clear()

    def on_notification(self, handler: Callable) -> None:
        self._notification_handlers.append(handler)

class MCPError(Exception):
    def __init__(self, error: Dict[str, Any]):
        self.code = error.get("code", -1)
        self.message = error.get("message", "Unknown MCP error")
        self.data = error.get("data")
        super().__init__(f"[{self.code}] {self.message}")

def transport_from_url(url: str, **kwargs) -> MCPTransport:
    if url.startswith("ws://") or url.startswith("wss://"):
        return MCPWebSocketTransport(url, **kwargs)
    return MCPHttpSseTransport(url, **kwargs)

def stdio_transport(command: List[str], **kwargs) -> MCPStdioTransport:

    return MCPStdioTransport(command, **kwargs)