from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt
from rich.markdown import Markdown
from rich.live import Live
from rich.text import Text
from rich.table import Table
from rich import box

from .events import (
    EventBus,
    ModelProcessingEvent,
    StreamChunkEvent,
    ProviderResponseEvent,
    ToolCallEvent,
    ToolFinishedEvent,
    ToolErrorEvent,
    ApprovalRequestedEvent,
    ApprovalGrantedEvent,
    ApprovalDeniedEvent,
    QuestionRequestedEvent,
    ContextCompressedEvent,
    ContextCompressionErrorEvent,
    TaskFinishedEvent,
    TaskErrorEvent,
    ErrorEvent,
)
from .renderer import Renderer

class ShellUI:
    def __init__(self, agent, bus: EventBus) -> None:
        self.agent   = agent
        self.bus     = bus
        self.console = Console()
        self.R       = Renderer()

        self._stream_lock = threading.Lock()
        self._streaming   = False
        self._stream_buf  = ""
        self._live: Optional[Live] = None

        self._register_handlers()

    def _start_stream(self) -> None:

        if self._streaming:
            return
        self._stream_buf = ""
        self._live = Live(
            Markdown(""),
            console=self.console,
            refresh_per_second=20,
            transient=False,
        )
        self._live.start()
        self._streaming = True

    def _end_stream(self) -> None:
        with self._stream_lock:
            self._end_stream_locked()

    def _end_stream_locked(self) -> None:

        if not self._streaming:
            return
        if self._live:
            try:
                self._live.update(Markdown(self._stream_buf, code_theme="monokai"))
                self._live.stop()
            except Exception:
                pass
            self._live = None
        self.console.print()
        self._streaming  = False
        self._stream_buf = ""

    def _register_handlers(self) -> None:

        @self.bus.subscribe(ModelProcessingEvent)
        def _(e):
            with self._stream_lock:
                if not self._streaming:
                    items = self.R.thinking()
                else:
                    items = []
            for item in items:
                self.console.print(item)

        @self.bus.subscribe(StreamChunkEvent)
        def _(e: StreamChunkEvent):
            if not isinstance(e.data, dict) or e.data.get("type") != "text":
                return
            chunk = e.data.get("content", "")
            if not chunk:
                return
            with self._stream_lock:
                if not self._streaming:
                    self._start_stream()
                self._stream_buf += chunk
                if self._live:
                    try:
                        self._live.update(Markdown(self._stream_buf, code_theme="monokai"))
                    except Exception:
                        pass

        @self.bus.subscribe(ProviderResponseEvent)
        def _(e):
            self._end_stream()

        @self.bus.subscribe(ToolCallEvent)
        def _(e: ToolCallEvent):
            self._end_stream()
            if not e.tool or e.tool in {"FinishTask", "FinishTaskTool", "Question", "QuestionTool"}:
                return
            for item in self.R.tool_call(e.tool, e.args):
                self.console.print(item)

        @self.bus.subscribe(ToolFinishedEvent)
        def _(e: ToolFinishedEvent):
            self._end_stream()
            if e.tool in {"Question", "QuestionTool"}:
                return
            for item in self.R.tool_result(e.tool, e.result):
                self.console.print(item)

        @self.bus.subscribe(ToolErrorEvent)
        def _(e: ToolErrorEvent):
            self._end_stream()
            for item in self.R.tool_error(e.tool, e.error):
                self.console.print(item)

        @self.bus.subscribe(ApprovalRequestedEvent)
        def _(e: ApprovalRequestedEvent):
            self._end_stream()
            for item in self.R.approval_request(e.tool):
                self.console.print(item)
            answer = Prompt.ask(
                "[bold yellow]›[/] Approve? [y/n/a]",
                choices=["y", "n", "a"],
                default="n",
                console=self.console,
            )
            if answer == "a":
                self.agent.approve_mode = "always"
                self.agent.resolve_approval(True)
            elif answer == "y":
                self.agent.resolve_approval(True)
            else:
                self.agent.resolve_approval(False)

        @self.bus.subscribe(ApprovalGrantedEvent)
        def _(e: ApprovalGrantedEvent):
            for item in self.R.approval_result(True, e.tool):
                self.console.print(item)

        @self.bus.subscribe(ApprovalDeniedEvent)
        def _(e: ApprovalDeniedEvent):
            for item in self.R.approval_result(False, e.tool):
                self.console.print(item)

        @self.bus.subscribe(QuestionRequestedEvent)
        def _(e: QuestionRequestedEvent):
            self._end_stream()
            question    = e.payload.get("question", "")
            context     = e.payload.get("context", "")
            suggestions = e.payload.get("suggestions", [])
            for item in self.R.question_request(question, context, suggestions):
                self.console.print(item)
            raw = Prompt.ask("[bold yellow]›[/]", console=self.console)
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(suggestions):
                    raw = suggestions[idx]
            for item in self.R.question_answer(raw):
                self.console.print(item)
            self.agent.resolve_question(raw)

        @self.bus.subscribe(ContextCompressedEvent)
        def _(e: ContextCompressedEvent):
            for item in self.R.context_compressed(
                e.info.get("before_tokens", 0),
                e.info.get("after_tokens", 0),
            ):
                self.console.print(item)

        @self.bus.subscribe(ContextCompressionErrorEvent)
        def _(e: ContextCompressionErrorEvent):
            for item in self.R.context_compression_error(e.error):
                self.console.print(item)

        @self.bus.subscribe(TaskFinishedEvent)
        def _(e):
            self._end_stream()

        @self.bus.subscribe(TaskErrorEvent)
        def _(e: TaskErrorEvent):
            self._end_stream()
            for item in self.R.task_error(e.error):
                self.console.print(item)

        @self.bus.subscribe(ErrorEvent)
        def _(e: ErrorEvent):
            self._end_stream()
            for item in self.R.generic_error(e.source, e.message):
                self.console.print(item)

class _McpAction(argparse.Action):
    """
    Collects MCP server specs into namespace.mcp_servers as a list of dicts:
        {"type": "http"|"ws"|"stdio", "target": str|list, "label": str|None, "env": dict}
    """
    def __call__(self, parser, namespace, values, option_string=None):
        servers: list = getattr(namespace, "mcp_servers", None) or []
        kind = {
            "--mcp-http":  "http",
            "--mcp-ws":    "ws",
            "--mcp-stdio": "stdio",
        }[option_string]

        if kind == "stdio":
            target = values if isinstance(values, list) else values.split()
        else:
            target = values

        servers.append({"type": kind, "target": target, "label": None, "env": {}})
        namespace.mcp_servers = servers

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yay",
        description="AI agent shell with full MCP support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  yay "Explain project"
  yay "Fix bug" main.py
  yay "Review" src/ --mcp-stdio npx -y @modelcontextprotocol/server-filesystem /tmp
  yay "Search web" --mcp-http http://localhost:3000
  yay "List files" --mcp-ws ws://localhost:4000 --mcp-label "my ws server"
  cat logs.txt | yay "Analyze errors"
""",
    )

    p.add_argument("prompt_or_files", nargs="*", metavar="PROMPT|FILE|DIR")

    mcp = p.add_argument_group("MCP servers")
    mcp.add_argument(
        "--mcp-http",
        dest="mcp_servers",
        metavar="URL",
        action=_McpAction,
        help="Add an HTTP+SSE MCP server",
    )
    mcp.add_argument(
        "--mcp-ws",
        dest="mcp_servers",
        metavar="URL",
        action=_McpAction,
        help="Add a WebSocket MCP server",
    )
    mcp.add_argument(
        "--mcp-stdio",
        dest="mcp_servers",
        metavar="CMD",
        nargs=argparse.REMAINDER,
        action=_McpAction,
        help="Add a stdio MCP server (rest of args = command)",
    )
    mcp.add_argument(
        "--mcp-env",
        dest="mcp_env",
        metavar="KEY=VAL",
        nargs="+",
        default=[],
        help="Env vars for stdio MCP servers  (KEY=VAL ...)",
    )
    mcp.add_argument(
        "--mcp-label",
        dest="mcp_label",
        metavar="LABEL",
        default=None,
        help="Label for the last --mcp-* server added",
    )
    mcp.add_argument(
        "--no-mcp",
        action="store_true",
        default=False,
        help="Disable all MCP servers",
    )

    agent = p.add_argument_group("Agent")
    agent.add_argument(
        "--approve",
        action="store_true",
        default=False,
        help="Auto-approve all tool calls (no prompts)",
    )
    agent.add_argument(
        "--list-tools",
        action="store_true",
        default=False,
        help="List all registered tools and exit",
    )

    return p

def _parse_mcp_env(raw: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in raw:
        if "=" in item:
            k, _, v = item.partition("=")
            env[k.strip()] = v
        else:
            env[item.strip()] = os.environ.get(item.strip(), "")
    return env

def _wire_mcp(
    mcp_manager,
    servers: list[dict],
    extra_env: dict[str, str],
    console: Console,
) -> None:

    if mcp_manager is None:
        _warn(console, "MCPManager not available – MCP servers will be skipped.")
        return

    for spec in servers:
        kind   = spec["type"]
        target = spec["target"]
        label  = spec.get("label")
        env    = {**extra_env, **spec.get("env", {})}

        try:
            if kind in ("http", "ws"):
                mcp_manager.add(target, label=label)
                t = Text()
                t.append("  ⊕ ", style="bold green")
                t.append(f"MCP {kind.upper()}", style="green")
                t.append(f"  {target}", style="grey50")
                console.print(t)
            elif kind == "stdio":
                cmd_str = " ".join(target) if isinstance(target, list) else target
                key = mcp_manager.add_stdio(
                    target if isinstance(target, list) else target.split(),
                    label=label,
                    env=env or None,
                )
                t = Text()
                t.append("  ⊕ ", style="bold green")
                t.append("MCP stdio", style="green")
                t.append(f"  {cmd_str}", style="grey50")
                console.print(t)
        except Exception as exc:
            _warn(console, f"Failed to register MCP server {target!r}: {exc}")

    if servers:
        console.print()
        results = mcp_manager.connect_all()
        for key, info in results.items():
            if info["ok"]:
                n = info["n_tools"] if "n_tools" in info else len(info.get("tools", []))
                t = Text()
                t.append("  ✓ ", style="bold green")
                t.append(key, style="green")
                t.append(f"  ({n} tools)", style="grey50")
                console.print(t)
            else:
                t = Text()
                t.append("  ✗ ", style="bold red")
                t.append(key, style="red")
                t.append(f"  {info['error']}", style="grey50")
                console.print(t)
        console.print()

def _warn(console: Console, msg: str) -> None:
    console.print(f"  [bold yellow]⚠[/]  [yellow]{msg}[/]")

def build_prompt(positionals: list[str], console: Console) -> str:
    parts:        list[str]  = []
    prompt_parts: list[str]  = []
    files:        list[Path] = []

    for arg in positionals:
        path = Path(arg)
        if path.exists():
            files.append(path)
        else:
            prompt_parts.append(arg)

    if prompt_parts:
        parts.append(" ".join(prompt_parts))

    if not sys.stdin.isatty():
        stdin_text = sys.stdin.read()
        if stdin_text.strip():
            t = Text()
            t.append("  ⊙ ", style="bold cyan")
            t.append("stdin", style="cyan")
            t.append(f"  ({len(stdin_text):,} chars)", style="grey50")
            console.print(t)
            parts.append("=== STDIN ===\n" + stdin_text)

    for path in files:
        if path.is_file():
            try:
                size    = path.stat().st_size
                content = path.read_text(encoding="utf-8", errors="replace")
                lines   = content.count("\n") + 1
                t = Text()
                t.append("  ⊙ ", style="bold cyan")
                t.append(path.name, style="cyan")
                t.append(f"  ({lines:,} lines, {size:,} bytes)", style="grey50")
                console.print(t)
                parts.append(f"=== FILE: {path} ===\n{content}")
            except Exception as exc:
                t = Text()
                t.append("  ✗ ", style="bold red")
                t.append(path.name, style="red")
                t.append(f": {exc}", style="grey50")
                console.print(t)
                parts.append(f"=== FILE ERROR: {path} ===\n{exc}")
        elif path.is_dir():
            try:
                tree = [str(item.relative_to(path)) for item in sorted(path.rglob("*"))]
                t = Text()
                t.append("  ⊟ ", style="bold cyan")
                t.append(path.name, style="cyan")
                t.append(f"  ({len(tree):,} entries)", style="grey50")
                console.print(t)
                parts.append(f"=== DIRECTORY: {path} ===\n" + "\n".join(tree))
            except Exception as exc:
                t = Text()
                t.append("  ✗ ", style="bold red")
                t.append(path.name, style="red")
                t.append(f": {exc}", style="grey50")
                console.print(t)
                parts.append(f"=== DIRECTORY ERROR: {path} ===\n{exc}")

    return "\n\n".join(parts)

def _print_tools(tools_manager, mcp_manager, console: Console) -> None:
    table = Table(
        title="Available tools",
        box=box.SIMPLE_HEAD,
        show_lines=False,
        title_style="bold",
    )
    table.add_column("Tool", style="bold cyan", no_wrap=True)
    table.add_column("Source", style="grey50")
    table.add_column("Description")

    builtin_tools = []
    if tools_manager and hasattr(tools_manager, "all_tools"):
        builtin_tools = tools_manager.all_tools()
    elif tools_manager and hasattr(tools_manager, "tools"):
        builtin_tools = tools_manager.tools

    for tool in builtin_tools:
        name = getattr(tool, "name", str(tool))
        desc = getattr(tool, "description", "")
        table.add_row(name, "built-in", desc)

    if mcp_manager:
        for row in mcp_manager.status_rows():
            server_key = row.get("label") or row.get("key", "?")
            for tool_name in row.get("tools", []) if "tools" in row else []:
                table.add_row(tool_name, f"mcp:{server_key}", "")

    console.print(table)

def run_shell(
    bus: EventBus,
    tools_manager,
    providers_manager,
    mcp_manager=None,
) -> int:
    from .builder import build_agent

    parser  = _build_arg_parser()
    args    = parser.parse_args()

    console = Console()

    if args.mcp_label and getattr(args, "mcp_servers", None):
        args.mcp_servers[-1]["label"] = args.mcp_label

    if not args.no_mcp and getattr(args, "mcp_servers", None):
        extra_env = _parse_mcp_env(args.mcp_env)
        _wire_mcp(mcp_manager, args.mcp_servers, extra_env, console)

    prompt = build_prompt(args.prompt_or_files, console)

    if args.list_tools:
        _print_tools(tools_manager, mcp_manager, console)
        return 0

    if not prompt.strip():
        console.print(
            "\n[bold]Usage:[/]\n"
            "  yay \"Explain project\"\n"
            "  yay \"Explain file\" main.py\n"
            "  yay \"Review changes\" src/\n"
            "  cat logs.txt | yay \"Analyze\"\n"
            "  yay \"Use filesystem\" --mcp-stdio npx -y @modelcontextprotocol/server-filesystem /tmp\n"
        )
        return 1

    agent = build_agent(bus, tools_manager, providers_manager, mcp_manager)

    if args.approve:
        agent.approve_mode = "always"

    ShellUI(agent, bus)

    try:
        agent.work_loop(prompt)
        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/]")
        return 130
    except Exception as exc:
        console.print(f"\n[bold red]Error:[/] {exc}")
        return 1