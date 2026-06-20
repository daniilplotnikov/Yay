from __future__ import annotations

from .tool import Tool


class ToolsManager:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._enabled: set[str] = set()

        if tools:
            self.register_many(tools)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self._enabled.add(tool.name)

    def register_many(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._enabled.discard(name)

    def unregister_many(self, names: list[str]) -> None:
        for name in names:
            self.unregister(name)

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_tools(self) -> dict[str, Tool]:
        return {
            name: tool
            for name, tool in self._tools.items()
            if name in self._enabled
        }

    def get_all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def enable(self, name: str) -> None:
        if name in self._tools:
            self._enabled.add(name)

    def disable(self, name: str) -> None:
        self._enabled.discard(name)

    def is_enabled(self, name: str) -> bool:
        return name in self._enabled