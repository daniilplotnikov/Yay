from .builder import build_agent
from .tui import AgentTUI

def main():
    agent = build_agent()

    tui = AgentTUI(agent)

    agent.event_callback = tui.event_handler

    tui.run()