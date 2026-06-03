from rich.console import Console
from rich.panel import Panel

from .builder import build_agent
from .tui import AgentTUI

console = Console()

def main():
    agent = build_agent()

    agent.start_queue()

    tui = AgentTUI(agent)

    agent.event_callback = tui.event_handler

    console.print(
        Panel.fit(
            """
██     ██        ██        ██     ██
██     ██       ████       ██     ██
 ██   ██       ██  ██       ██   ██
  ██ ██       ████████       ██ ██
   ███       ██      ██       ███
   ███       ██      ██       ███
   ███      ██        ██      ███

        Yet Another Yielder
            """.strip(),
            border_style="blue",
        )
    )

    tui.run()