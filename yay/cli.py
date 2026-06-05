import sys
import yay.tools as tools_pkg
import yay.providers as providers_pkg

from .builder import build_agent
from .tui import AgentTUI
from .shell import run_shell
from .managers import (
    ProviderManager,
    ToolsManager,
)
from .events import EventBus
from .mcp import MCPManager

bus = EventBus()
tools_manager = ToolsManager(tools_pkg, bus)
providers_manager = ProviderManager(providers_pkg, bus)
mcp_manager = MCPManager(tools_manager, bus)

tools_manager.load()
providers_manager.load()

def run_tui():
    agent = build_agent(bus=bus, tools_manager=tools_manager, providers_manager=providers_manager)

    agent.start_queue()

    tui = AgentTUI(bus=bus, agent=agent, providers_manager=providers_manager, tools_manager=tools_manager, mcp_manager=mcp_manager)

    tui.run()

def main():
    has_args = len(sys.argv) > 1
    has_pipe = not sys.stdin.isatty()

    if has_args or has_pipe:
        return run_shell(bus=bus, tools_manager=tools_manager, providers_manager=providers_manager, mcp_manager=mcp_manager)

    return run_tui()