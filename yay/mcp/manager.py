from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Union

from .client import MCPClient, MCPTool, MCPResource, MCPPrompt
from .transport import (
    MCPStdioTransport,
    transport_from_url,
    stdio_transport,
)

class _ServerConfig:
    def __init__(
        self,
        key: str,
        *,
        url: Optional[str] = None,
        command: Optional[List[str]] = None,
        label: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ):
        self.key = key                    
        self.url = url
        self.command = command
        self.label = label or key
        self.headers = headers or {}
        self.env = env or {}
        self.timeout = timeout
        self.enabled: bool = True

    def build_transport(self):
        if self.command:
            return MCPStdioTransport(self.command, env=self.env, timeout=self.timeout)
        if self.url:
            return transport_from_url(self.url, headers=self.headers, timeout=self.timeout)
        raise ValueError("Server config has neither url nor command")

class MCPManager:
    def __init__(self, tools_manager=None, bus=None):
        self.tools_manager = tools_manager
        self.bus = bus

        self._configs: Dict[str, _ServerConfig] = {}    
        self._clients: Dict[str, MCPClient] = {}         

        self._tools:     Dict[str, List[str]] = {}
        self._resources: Dict[str, List[str]] = {}
        self._prompts:   Dict[str, List[str]] = {}

        self._notification_handlers: List[Callable] = []

    def add(
        self,
        url: str,
        *,
        label: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> None:

        key = url.rstrip("/")
        if key in self._configs:
            return
        self._configs[key] = _ServerConfig(
            key, url=key, label=label, headers=headers, timeout=timeout
        )

    def add_stdio(
        self,
        command: List[str],
        *,
        key: Optional[str] = None,
        label: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> str:
        derived_key = key or f"stdio://{' '.join(command)}"
        if derived_key in self._configs:
            return derived_key
        self._configs[derived_key] = _ServerConfig(
            derived_key, command=command, label=label, env=env, timeout=timeout
        )
        return derived_key

    def remove(self, ref: Union[int, str]) -> None:
        key = self._resolve_key(ref)
        self._disconnect(key)
        del self._configs[key]

    def enable(self, ref: Union[int, str]) -> None:
        key = self._resolve_key(ref)
        self._configs[key].enabled = True

    def disable(self, ref: Union[int, str]) -> None:
        key = self._resolve_key(ref)
        self._configs[key].enabled = False
        self._disconnect(key)

    def connect(self, ref: Union[int, str]) -> MCPClient:
        key = self._resolve_key(ref)
        cfg = self._configs[key]

        self._disconnect(key)

        transport = cfg.build_transport()
        client = MCPClient(transport)

        if hasattr(transport, "on_notification"):
            transport.on_notification(
                lambda msg, _key=key: self._on_server_notification(_key, msg)
            )

        client.start()
        self._clients[key] = client
        self._fetch_capabilities(key, client)
        return client

    def connect_all(self) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for key, cfg in self._configs.items():
            if not cfg.enabled:
                continue
            try:
                client = self.connect(key)
                results[key] = {
                    "ok": True,
                    "tools": self._tools.get(key, []),
                    "resources": self._resources.get(key, []),
                    "prompts": self._prompts.get(key, []),
                    "server": client.server_info,
                    "error": None,
                }
            except Exception as exc:
                results[key] = {
                    "ok": False,
                    "tools": [], "resources": [], "prompts": [],
                    "error": str(exc),
                }
                self._emit_error(key, exc)
        return results

    def fetch_server(self, url: str) -> List[MCPTool]:
        if url.rstrip("/") not in self._configs:
            self.add(url)
        self.connect(url)
        return [
            self._clients[url.rstrip("/")].list_tools()
            if url.rstrip("/") in self._clients else []
        ]

    def fetch_all(self) -> Dict[str, Any]:
        return self.connect_all()

    def reload_all(self) -> Dict[str, Any]:
        for key in list(self._clients.keys()):
            self._disconnect(key)
        return self.connect_all()

    def list_tools(self, ref: Union[int, str]) -> List[MCPTool]:
        client = self._get_client(ref)
        return client.list_tools()

    def call_tool(
        self,
        ref: Union[int, str],
        name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        client = self._get_client(ref)
        return client.call_tool(name, arguments)

    def list_resources(self, ref: Union[int, str]) -> List[MCPResource]:
        client = self._get_client(ref)
        return client.list_resources()

    def read_resource(self, ref: Union[int, str], uri: str) -> Dict[str, Any]:
        client = self._get_client(ref)
        return client.read_resource(uri)

    def list_prompts(self, ref: Union[int, str]) -> List[MCPPrompt]:
        client = self._get_client(ref)
        return client.list_prompts()

    def get_prompt(
        self,
        ref: Union[int, str],
        name: str,
        arguments: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        client = self._get_client(ref)
        return client.get_prompt(name, arguments)

    def ping_all(self) -> Dict[str, bool]:
        out: Dict[str, bool] = {}
        for key, cfg in self._configs.items():
            if key in self._clients:
                out[key] = self._clients[key].ping()
            else:

                try:
                    transport = cfg.build_transport()
                    transport.start()
                    transport.request("ping", {})
                    transport.stop()
                    out[key] = True
                except Exception:
                    out[key] = False
        return out

    def on_notification(self, handler: Callable) -> None:
        self._notification_handlers.append(handler)

    def _on_server_notification(self, key: str, msg: Dict[str, Any]) -> None:
        method = msg.get("method", "")
        if method == "notifications/tools/list_changed" and key in self._clients:
            try:
                self._refresh_tools(key, self._clients[key])
            except Exception:
                pass
        elif method == "notifications/resources/list_changed" and key in self._clients:
            try:
                self._refresh_resources(key, self._clients[key])
            except Exception:
                pass
        elif method == "notifications/prompts/list_changed" and key in self._clients:
            try:
                self._refresh_prompts(key, self._clients[key])
            except Exception:
                pass

        for h in self._notification_handlers:
            try:
                h(key, msg)
            except Exception:
                pass

    def status_rows(self) -> List[Dict[str, Any]]:
        rows = []
        for i, (key, cfg) in enumerate(self._configs.items()):
            rows.append({
                "index": i,
                "key": key,
                "label": cfg.label,
                "url": cfg.url,
                "command": cfg.command,
                "enabled": cfg.enabled,
                "connected": key in self._clients,
                "n_tools": len(self._tools.get(key, [])),
                "n_resources": len(self._resources.get(key, [])),
                "n_prompts": len(self._prompts.get(key, [])),
            })
        return rows

    def get_client(self, ref: Union[int, str]) -> Optional[MCPClient]:
        try:
            return self._get_client(ref)
        except Exception:
            return None

    def _resolve_key(self, ref: Union[int, str]) -> str:
        if isinstance(ref, int):
            return list(self._configs.keys())[ref]
        key = ref.rstrip("/")
        if key not in self._configs:
            raise KeyError(f"Server not found: {ref!r}")
        return key

    def _get_client(self, ref: Union[int, str]) -> MCPClient:
        key = self._resolve_key(ref)
        if key not in self._clients:
            raise RuntimeError(f"Server '{key}' is not connected. Call connect() first.")
        return self._clients[key]

    def _disconnect(self, key: str) -> None:
        client = self._clients.pop(key, None)
        if client:
            try:
                client.stop()
            except Exception:
                pass

        if self.tools_manager:
            for name in self._tools.get(key, []):
                try:
                    self.tools_manager.unregister(name)
                except Exception:
                    pass

        self._tools.pop(key, None)
        self._resources.pop(key, None)
        self._prompts.pop(key, None)

    def _fetch_capabilities(self, key: str, client: MCPClient) -> None:
        caps = client.server_capabilities

        if "tools" in caps:
            self._refresh_tools(key, client)

        if "resources" in caps:
            self._refresh_resources(key, client)

        if "prompts" in caps:
            self._refresh_prompts(key, client)

    def _refresh_tools(self, key: str, client: MCPClient) -> None:
        if self.tools_manager:
            for name in self._tools.get(key, []):
                try:
                    self.tools_manager.unregister(name)
                except Exception:
                    pass

        tools = client.list_tools()
        self._tools[key] = [t.name for t in tools]

        if self.tools_manager:
            self.tools_manager.register_many(tools)

    def _refresh_resources(self, key: str, client: MCPClient) -> None:
        resources = client.list_resources()
        self._resources[key] = [r.uri for r in resources]

    def _refresh_prompts(self, key: str, client: MCPClient) -> None:
        prompts = client.list_prompts()
        self._prompts[key] = [p.name for p in prompts]

    def _emit_error(self, key: str, exc: Exception) -> None:
        if self.bus:
            try:
                from ..events import ErrorEvent
                self.bus.emit(ErrorEvent(
                    source="MCPManager",
                    message=f"Failed MCP server {key!r}: {exc}",
                ))
            except Exception:
                pass