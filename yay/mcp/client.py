from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .transport import MCPTransport, MCPError

@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    _client: "MCPClient" = field(repr=False)

    @property
    def arguments(self) -> Dict:
        return self.input_schema
    
    def __call__(self, args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        if args is not None:
            return self._client.call_tool(self.name, args)
        return self._client.call_tool(self.name, kwargs)

    def execute(self, args: Dict[str, Any]) -> Any:
        return self._client.call_tool(self.name, args)


@dataclass
class MCPResource:
    uri: str
    name: str
    description: str
    mime_type: str
    _client: "MCPClient" = field(repr=False)

    def read(self) -> Any:
        return self._client.read_resource(self.uri)


@dataclass
class MCPPrompt:
    name: str
    description: str
    arguments: List[Dict[str, Any]]
    _client: "MCPClient" = field(repr=False)

    def get(self, **args: str) -> Dict[str, Any]:
        return self._client.get_prompt(self.name, args)

CLIENT_INFO = {"name": "mcp-client", "version": "1.0.0"}

PROTOCOL_VERSION = "2025-03-26"

CAPABILITIES = {
    "roots": {"listChanged": True},
    "sampling": {},
}


class MCPClient:
    """
    Full MCP client.

    Usage::

        transport = MCPHttpSseTransport("http://localhost:3000")
        client = MCPClient(transport)
        client.start()                  
        tools = client.list_tools()
        result = client.call_tool("myTool", {"arg": "value"})
        client.stop()

    Or as a context manager::

        with MCPClient(transport) as client:
            tools = client.list_tools()
    """

    def __init__(
        self,
        transport: MCPTransport,
        *,
        client_info: Optional[Dict[str, Any]] = None,
        roots: Optional[List[Dict[str, Any]]] = None,
    ):
        self.transport = transport
        self.client_info = client_info or CLIENT_INFO
        self.roots = roots or []

        
        self.server_info: Dict[str, Any] = {}
        self.server_capabilities: Dict[str, Any] = {}
        self.protocol_version: str = PROTOCOL_VERSION

        
        self._progress_handlers: List[Callable] = []
        self._resource_update_handlers: List[Callable] = []
        self._prompt_list_handlers: List[Callable] = []
        self._tool_list_handlers: List[Callable] = []
        self._log_handlers: List[Callable] = []

        self._sampling_handler: Optional[Callable] = None

        self._roots_list_handler: Optional[Callable] = None

        self._initialized = False
        self._lock = threading.Lock()

        if hasattr(transport, "on_notification"):
            transport.on_notification(self._handle_notification)

    def start(self) -> "MCPClient":
        """Start transport and run the MCP handshake."""
        self.transport.start()
        self.initialize()
        return self

    def stop(self) -> None:
        """Send shutdown notification and stop transport."""
        if self._initialized:
            try:
                self._notify("notifications/cancelled", {})
            except Exception:
                pass
        self.transport.stop()
        self._initialized = False

    def __enter__(self) -> "MCPClient":
        return self.start()

    def __exit__(self, *_: Any) -> None:
        self.stop()

    
    
    

    def initialize(self) -> Dict[str, Any]:
        """
        Perform the MCP initialize handshake.
        Must be called before any other method.
        """
        resp = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "clientInfo": self.client_info,
            "capabilities": CAPABILITIES,
        })
        result = resp.get("result", {})
        self.server_info = result.get("serverInfo", {})
        self.server_capabilities = result.get("capabilities", {})
        self.protocol_version = result.get("protocolVersion", PROTOCOL_VERSION)

        
        self._notify("notifications/initialized", {})
        self._initialized = True
        return result

    
    
    

    def list_tools(self, cursor: Optional[str] = None) -> List[MCPTool]:
        """List all tools exposed by the server (handles pagination)."""
        self._assert_capability("tools")
        tools: List[MCPTool] = []
        params: Dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor

        while True:
            resp = self._request("tools/list", params)
            result = resp.get("result", {})
            for t in result.get("tools", []):
                tools.append(MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    _client=self,
                ))
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            params["cursor"] = next_cursor

        return tools

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        progress_token: Optional[str] = None,
    ) -> Any:
        """
        Invoke a tool by name.
        Returns the raw result content list.
        Raises MCPError on tool-reported errors.
        """
        params: Dict[str, Any] = {"name": name, "arguments": arguments}
        if progress_token:
            params["_meta"] = {"progressToken": progress_token}

        resp = self._request("tools/call", params)
        result = resp.get("result", {})

        if result.get("isError"):
            content = result.get("content", [])
            text = " ".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )
            raise MCPError({"code": -32000, "message": text or "Tool error"})

        return result.get("content", result)

    
    
    

    def list_resources(self, cursor: Optional[str] = None) -> List[MCPResource]:
        """List all resources (paginated)."""
        self._assert_capability("resources")
        resources: List[MCPResource] = []
        params: Dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor

        while True:
            resp = self._request("resources/list", params)
            result = resp.get("result", {})
            for r in result.get("resources", []):
                resources.append(MCPResource(
                    uri=r["uri"],
                    name=r.get("name", r["uri"]),
                    description=r.get("description", ""),
                    mime_type=r.get("mimeType", ""),
                    _client=self,
                ))
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            params["cursor"] = next_cursor

        return resources

    def list_resource_templates(self) -> List[Dict[str, Any]]:
        self._assert_capability("resources")
        resp = self._request("resources/templates/list", {})
        return resp.get("result", {}).get("resourceTemplates", [])

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource by URI. Returns the result dict with contents."""
        self._assert_capability("resources")
        resp = self._request("resources/read", {"uri": uri})
        return resp.get("result", {})

    def subscribe_resource(self, uri: str) -> None:
        """Subscribe to resource change notifications."""
        cap = self.server_capabilities.get("resources", {})
        if not cap.get("subscribe"):
            raise RuntimeError("Server does not support resource subscriptions")
        self._request("resources/subscribe", {"uri": uri})

    def unsubscribe_resource(self, uri: str) -> None:
        self._assert_capability("resources")
        self._request("resources/unsubscribe", {"uri": uri})

    
    
    

    def list_prompts(self, cursor: Optional[str] = None) -> List[MCPPrompt]:
        """List all prompts (paginated)."""
        self._assert_capability("prompts")
        prompts: List[MCPPrompt] = []
        params: Dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor

        while True:
            resp = self._request("prompts/list", params)
            result = resp.get("result", {})
            for p in result.get("prompts", []):
                prompts.append(MCPPrompt(
                    name=p["name"],
                    description=p.get("description", ""),
                    arguments=p.get("arguments", []),
                    _client=self,
                ))
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            params["cursor"] = next_cursor

        return prompts

    def get_prompt(self, name: str, arguments: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Get a prompt with optional argument substitution."""
        self._assert_capability("prompts")
        params: Dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments
        resp = self._request("prompts/get", params)
        return resp.get("result", {})

    
    
    

    def set_log_level(self, level: str) -> None:
        """
        Set server log level.
        level: 'debug' | 'info' | 'notice' | 'warning' | 'error' | 'critical' | 'alert' | 'emergency'
        """
        cap = self.server_capabilities.get("logging", {})
        if not cap and "logging" not in self.server_capabilities:
            return  
        self._request("logging/setLevel", {"level": level})

    
    
    

    def ping(self) -> bool:
        """Send a ping. Returns True if server responds."""
        try:
            self._request("ping", {})
            return True
        except Exception:
            return False

    
    
    

    def cancel(self, request_id: str, reason: Optional[str] = None) -> None:
        """Send a cancellation notification for an in-flight request."""
        params: Dict[str, Any] = {"requestId": request_id}
        if reason:
            params["reason"] = reason
        self._notify("notifications/cancelled", params)

    
    
    

    def set_sampling_handler(self, handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        """
        Register a handler for sampling/createMessage requests from the server.

        The handler receives the full params dict and must return a result dict::

            def my_handler(params):
                
                return {
                    "role": "assistant",
                    "content": {"type": "text", "text": "..."},
                    "model": "claude-3-5-sonnet",
                    "stopReason": "endTurn",
                }
        """
        self._sampling_handler = handler

    
    
    

    def set_roots_handler(self, handler: Callable[[], List[Dict[str, Any]]]) -> None:
        """
        Register a handler for roots/list requests from the server.

        The handler must return a list of root dicts::

            def my_roots():
                return [{"uri": "file:///project", "name": "My Project"}]
        """
        self._roots_list_handler = handler

    def set_roots(self, roots: List[Dict[str, Any]]) -> None:
        """Set static roots and notify the server of the change."""
        self.roots = roots
        if self._initialized:
            self._notify("notifications/roots/listChanged", {})

    
    
    

    def on_progress(self, handler: Callable) -> None:
        self._progress_handlers.append(handler)

    def on_resource_updated(self, handler: Callable) -> None:
        self._resource_update_handlers.append(handler)

    def on_prompt_list_changed(self, handler: Callable) -> None:
        self._prompt_list_handlers.append(handler)

    def on_tool_list_changed(self, handler: Callable) -> None:
        self._tool_list_handlers.append(handler)

    def on_log(self, handler: Callable) -> None:
        self._log_handlers.append(handler)

    
    
    

    def _handle_notification(self, msg: Dict[str, Any]) -> None:
        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "notifications/progress":
            for h in self._progress_handlers:
                _safe(h, params)

        elif method == "notifications/resources/updated":
            for h in self._resource_update_handlers:
                _safe(h, params)

        elif method == "notifications/resources/list_changed":
            for h in self._resource_update_handlers:
                _safe(h, params)

        elif method == "notifications/prompts/list_changed":
            for h in self._prompt_list_handlers:
                _safe(h, params)

        elif method == "notifications/tools/list_changed":
            for h in self._tool_list_handlers:
                _safe(h, params)

        elif method == "notifications/message":
            for h in self._log_handlers:
                _safe(h, params)

        elif method == "sampling/createMessage":
            self._handle_sampling_request(msg)

        elif method == "roots/list":
            self._handle_roots_request(msg)

    def _handle_sampling_request(self, msg: Dict[str, Any]) -> None:
        req_id = msg.get("id")
        params = msg.get("params", {})
        if self._sampling_handler:
            try:
                result = self._sampling_handler(params)
                self._respond(req_id, result)
            except Exception as exc:
                self._respond_error(req_id, -32000, str(exc))
        else:
            self._respond_error(req_id, -32601, "No sampling handler registered")

    def _handle_roots_request(self, msg: Dict[str, Any]) -> None:
        req_id = msg.get("id")
        if self._roots_list_handler:
            try:
                roots = self._roots_list_handler()
                self._respond(req_id, {"roots": roots})
            except Exception as exc:
                self._respond_error(req_id, -32000, str(exc))
        else:
            self._respond(req_id, {"roots": self.roots})

    def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.transport.request(method, params)

    def _notify(self, method: str, params: Dict[str, Any]) -> None:
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            self.transport.send(msg)
        except Exception:
            pass

    def _respond(self, req_id: Any, result: Any) -> None:
        self.transport.send({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        })

    def _respond_error(self, req_id: Any, code: int, message: str) -> None:
        self.transport.send({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        })

    def _assert_capability(self, cap: str) -> None:
        if cap not in self.server_capabilities:
            raise RuntimeError(
                f"Server does not advertise '{cap}' capability. "
                f"Available: {list(self.server_capabilities.keys())}"
            )


def _safe(fn: Callable, *args: Any) -> None:
    try:
        fn(*args)
    except Exception:
        pass