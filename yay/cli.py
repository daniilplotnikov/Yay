import sys

from .builder import build_agent
from .tui import AgentTUI
from .shell import run_shell


def run_tui():
    agent = build_agent()

    agent.start_queue()

    tui = AgentTUI(agent)

    agent.event_callback = tui.event_handler

    tui.run()


def main():
    has_args = len(sys.argv) > 1
    has_pipe = not sys.stdin.isatty()

    if has_args or has_pipe:
        return run_shell()

    return run_tui()