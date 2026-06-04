import sys
import threading

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.markdown import Markdown
from rich.live import Live
from rich.text import Text

from .builder import build_agent
from .renderer import Renderer


class ShellUI:
    def __init__(self, agent):
        self.agent = agent

        self.console = Console()
        self.renderer = Renderer()

        self._stream_lock = threading.Lock()

        self._assistant_streaming = False
        self._thinking_visible = False

        self._stream_buffer = ""
        self._live = None

    def write_many(self, items):
        for item in items:
            self.console.print(item)

    def render_markdown(self, text: str):
        self.console.print(
            Markdown(text)
        )

    def _start_stream(self):
        if not self._assistant_streaming:

            self._stream_buffer = ""

            self._live = Live(
                Markdown(""),
                console=self.console,
                refresh_per_second=20,
                transient=False,
            )

            self._live.start()

            self._assistant_streaming = True

    def _end_stream(self):
        if self._assistant_streaming:

            if self._live:

                self._live.update(
                    Markdown(self._stream_buffer)
                )

                self._live.stop()
                self._live = None

            self.console.print()

            self._assistant_streaming = False

    def event_handler(self, event: str, data: dict):

        if event == "task_started":
            pass

        elif event == "model_processing":

            self._thinking_visible = True

            self.write_many(
                self.renderer.thinking()
            )

        elif event == "stream_chunk":

            if data.get("type") != "text":
                return

            with self._stream_lock:

                if self._thinking_visible:
                    self._thinking_visible = False

                self._start_stream()

                chunk = data.get("content", "")

                self._stream_buffer += chunk

                if self._live:
                    self._live.update(
                        Markdown(self._stream_buffer)
                    )

        elif event == "provider_response":

            self._end_stream()

            content = data.get("content")

            if (
                content
                and isinstance(content, str)
                and content.strip()
            ):
                self.render_markdown(content)

        elif event == "tool_call":

            self._end_stream()

            self.write_many(
                self.renderer.tool_call(
                    data.get("tool", ""),
                    data.get("args", {}),
                )
            )

        elif event == "tool_finished":

            self._end_stream()

            self.write_many(
                self.renderer.tool_result(
                    data.get("tool", ""),
                    data.get("result"),
                )
            )

        elif event == "tool_error":

            self._end_stream()

            self.write_many(
                self.renderer.tool_error(
                    data.get("tool", ""),
                    data.get("error", ""),
                )
            )

        elif event == "approval_requested":

            self._end_stream()

            tool = data.get("tool", "")

            self.write_many(
                self.renderer.approval_request(tool)
            )

            answer = Prompt.ask(
                "[bold yellow]›[/]",
                choices=["y", "n", "a"],
                default="n",
            )

            if answer == "a":

                self.agent.approve_mode = "always"
                self.agent.resolve_approval(True)

            elif answer == "y":

                self.agent.resolve_approval(True)

            else:

                self.agent.resolve_approval(False)

        elif event == "approval_granted":

            self.write_many(
                self.renderer.approval_result(
                    True,
                    data.get("tool", ""),
                )
            )

        elif event == "approval_denied":

            self.write_many(
                self.renderer.approval_result(
                    False,
                    data.get("tool", ""),
                )
            )

        elif event == "question_requested":

            self._end_stream()

            question = data.get("question", "")
            context = data.get("context", "")
            suggestions = data.get("suggestions", [])

            self.write_many(
                self.renderer.question_request(
                    question,
                    context,
                    suggestions,
                )
            )

            answer = Prompt.ask(
                "[bold yellow]›[/]"
            )

            if answer.isdigit():

                idx = int(answer) - 1

                if 0 <= idx < len(suggestions):
                    answer = suggestions[idx]

            self.write_many(
                self.renderer.question_answer(
                    answer
                )
            )

            self.agent.resolve_question(
                answer
            )

        elif event == "context_compressed":

            self.write_many(
                self.renderer.context_compressed(
                    data.get("before_tokens", 0),
                    data.get("after_tokens", 0),
                )
            )

        elif event == "task_error":

            self._end_stream()

            self.write_many(
                self.renderer.task_error(
                    data.get("error", "")
                )
            )


def build_prompt(console: Console) -> str:
    parts: list[str] = []

    prompt_parts: list[str] = []
    files: list[Path] = []

    for arg in sys.argv[1:]:

        path = Path(arg)

        if path.exists():
            files.append(path)
        else:
            prompt_parts.append(arg)

    if prompt_parts:
        parts.append(
            " ".join(prompt_parts)
        )

    if not sys.stdin.isatty():

        stdin_text = sys.stdin.read()

        if stdin_text.strip():

            t = Text()
            t.append("  ⊙ ", style="bold cyan")
            t.append("stdin", style="cyan")
            t.append(
                f"  ({len(stdin_text):,} chars)",
                style="grey50",
            )

            console.print(t)

            parts.append(
                "=== STDIN ===\n"
                + stdin_text
            )

    for path in files:

        if path.is_file():

            try:

                size = path.stat().st_size

                content = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

                lines = content.count("\n") + 1

                t = Text()
                t.append("  ⊙ ", style="bold cyan")
                t.append(path.name, style="cyan")
                t.append(
                    f"  ({lines:,} lines, {size:,} bytes)",
                    style="grey50",
                )

                console.print(t)

                parts.append(
                    f"=== FILE: {path} ===\n"
                    f"{content}"
                )

            except Exception as exc:

                t = Text()
                t.append("  ✗ ", style="bold red")
                t.append(path.name, style="red")
                t.append(": ", style="grey50")
                t.append(str(exc), style="red")

                console.print(t)

                parts.append(
                    f"=== FILE ERROR: {path} ===\n"
                    f"{exc}"
                )

        elif path.is_dir():

            tree: list[str] = []

            try:

                for item in sorted(path.rglob("*")):

                    try:
                        tree.append(
                            str(item.relative_to(path))
                        )
                    except Exception:
                        pass

                t = Text()
                t.append("  ⊟ ", style="bold cyan")
                t.append(path.name, style="cyan")
                t.append(
                    f"  ({len(tree):,} entries)",
                    style="grey50",
                )

                console.print(t)

                parts.append(
                    f"=== DIRECTORY: {path} ===\n"
                    + "\n".join(tree)
                )

            except Exception as exc:

                t = Text()
                t.append("  ✗ ", style="bold red")
                t.append(path.name, style="red")
                t.append(": ", style="grey50")
                t.append(str(exc), style="red")

                console.print(t)

                parts.append(
                    f"=== DIRECTORY ERROR: {path} ===\n"
                    f"{exc}"
                )

    return "\n\n".join(parts)


def run_shell():

    console = Console()

    prompt = build_prompt(console)

    if not prompt.strip():

        console.print(
            "\n[bold]Usage:[/]\n"
            "  yay \"Explain project\"\n"
            "  yay \"Explain file\" main.py\n"
            "  yay \"Review changes\" src/\n"
            "  cat logs.txt | yay \"Analyze\"\n"
        )

        return 1

    agent = build_agent()

    ui = ShellUI(agent)

    agent.event_callback = ui.event_handler

    try:

        result = agent.work_loop(prompt)

        if isinstance(result, str):
            print()

        return 0

    except KeyboardInterrupt:

        print("\nInterrupted")

        return 130