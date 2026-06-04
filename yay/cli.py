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

tools_manager = ToolsManager(tools_pkg)
providers_manager = ProviderManager(providers_pkg)
tools_manager.load()
providers_manager.load()

def run_tui():
    agent = build_agent(tools_manager=tools_manager, providers_manager=providers_manager)

    agent.start_queue()

    tui = AgentTUI(agent, providers_manager, tools_manager)

    agent.event_callback = tui.event_handler

    tui.run()


def main():
    has_args = len(sys.argv) > 1
    has_pipe = not sys.stdin.isatty()

    if has_args or has_pipe:
        return run_shell()

    return run_tui()