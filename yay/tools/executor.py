from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Dict

from ..managers import ToolsManager
from ..events import EventBus, ToolStartedEvent, ToolFinishedEvent, ToolErrorEvent


class ToolExecutor:
    def __init__(
        self,
        tools_manager: ToolsManager,
        bus: EventBus,
    ):
        self.tools_manager = tools_manager
        self.bus = bus

    @property
    def tools(self) -> Dict[str, Any]:
        return self.tools_manager.get_tools()

    async def run_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        tool = self.tools.get(tool_name)

        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        runner = getattr(tool, "run", tool)

        if not callable(runner):
            raise ValueError(f"Tool {tool_name} is not callable")

        await self.bus.emit(
            ToolStartedEvent(tool=tool_name)
        )

        try:
            if inspect.iscoroutinefunction(runner):
                result = await runner(args)
            else:
                result = await asyncio.to_thread(runner, args)

            await self.bus.emit(
                ToolFinishedEvent(
                    tool=tool_name,
                    result=result,
                )
            )

            return result

        except Exception as e:
            await self.bus.emit(
                ToolErrorEvent(
                    tool=tool_name,
                    error=e,
                )
            )
            return {"error": str(e)}

    def normalize_result(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)