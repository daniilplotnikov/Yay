"""
Full-screen TUI — Claude Code style rendering.
pip install textual rich
"""
from __future__ import annotations

import os
import time
import threading
import difflib
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer, Input, Label, RichLog, Static,
    Button, Select, TabbedContent, TabPane, ListView, ListItem,
)
from textual.screen import ModalScreen
from textual.suggester import Suggester
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table
from rich.rule import Rule
from rich.console import Group
from rich.padding import Padding

from .agent import Agent
from .llm import Context
from .providers.openai_compatible import OpenAICompatibleProvider
from .provider import NonSelectedProvider
from .config import load_config, save_config
from .workspace import load_workspace, save_workspace
class C:
    USER        = "bold white"
    ASSISTANT   = "white"
    DIM         = "dim white"
    MUTED       = "grey50"
    TOOL_ICON   = "bold cyan"
    TOOL_NAME   = "cyan"
    TOOL_ARG    = "white"
    TOOL_META   = "grey50"
    OK          = "green"
    ERR         = "bold red"
    WARN        = "yellow"
    INFO        = "cyan"
    MODEL       = "bold cyan"
    CWD         = "grey62"
    TOKENS_OK   = "green"
    TOKENS_WARN = "yellow"
    TOKENS_HOT  = "red"


def _token_color(pct: float) -> str:
    return C.TOKENS_OK if pct < 50 else C.TOKENS_WARN if pct < 80 else C.TOKENS_HOT
_TOOL_ICON: dict[str, str] = {
    "CMDTool":            "⬡",
    "BashTool":           "⬡",
    "ReadFileTool":       "⊙",
    "WriteFileTool":      "◎",
    "CreateFileTool":     "◎",
    "PatchFileTool":      "◈",
    "RemoveFileTool":     "⊗",
    "CreateDirectoryTool":"⊞",
    "GrepTool":           "⊛",
    "GlobTool":           "⊡",
    "ListFilesTool":      "⊞",
    "TreeTool":           "⊟",
    "PDFTool":            "⊙",
    "ThinkTool":          "⟳",
    "WebSearchTool":      "⊕",
    "default":            "◆",
}

_TOOL_LABEL: dict[str, str] = {
    "CMDTool":            "Bash",
    "BashTool":           "Bash",
    "ReadFileTool":       "Read",
    "WriteFileTool":      "Write",
    "CreateFileTool":     "Write",
    "PatchFileTool":      "Edit",
    "RemoveFileTool":     "Delete",
    "CreateDirectoryTool":"Mkdir",
    "GrepTool":           "Search",
    "GlobTool":           "Glob",
    "ListFilesTool":      "List",
    "TreeTool":           "Tree",
    "PDFTool":            "PDF",
    "ThinkTool":          "Think",
    "WebSearchTool":      "Web",
}

def _icon(tool: str) -> str:
    return _TOOL_ICON.get(tool, _TOOL_ICON["default"])

def _label(tool: str) -> str:
    return _TOOL_LABEL.get(tool, tool.replace("Tool", ""))
class Renderer:
    """
    Every method returns a list of rich renderables.
    The TUI writes them via RichLog.write() one by one.
    Claude Code conventions:
      • No Panel boxes for tool calls — just indented lines
      • Bash output uses a subtle Syntax block
      • Diffs use Syntax("diff")
      • Assistant text is plain, no border
      • User prompt has a "> " prefix in bold white
    """

    @staticmethod
    def user_prompt(prompt: str) -> list:
        t = Text()
        t.append("\n❯ ", style="bold green")
        t.append(prompt, style=C.USER)
        return [t]

    @staticmethod
    def assistant_start() -> list:
        return [Text("")]          # blank line before response

    @staticmethod
    def assistant_end() -> list:
        return [Text("")]          # blank line after response

    @staticmethod
    def thinking() -> list:
        t = Text()
        t.append("  ⟳ ", style=C.MUTED)
        t.append("Thinking…", style=C.DIM)
        return [t]

    @staticmethod
    def tool_call(tool: str, args: dict) -> list:
        if tool in {"ThinkTool", "FinishTaskTool"}:
            return []

        icon  = _icon(tool)
        label = _label(tool)
        if tool in {"CMDTool", "BashTool"}:
            cmd = args.get("cmd", args.get("command", ""))
            header = Text()
            header.append(f"\n  {icon} ", style=C.TOOL_ICON)
            header.append(label, style=C.TOOL_NAME)
            header.append("  ", style="")
            header.append(cmd[:120], style=C.TOOL_ARG)
            return [header]
        if args.get("old") is not None and args.get("new") is not None:
            diff_lines = "\n".join(difflib.unified_diff(
                args["old"].splitlines(), args["new"].splitlines(),
                fromfile="old", tofile="new", lineterm="",
            ))
            header = Text()
            header.append(f"\n  {icon} ", style=C.TOOL_ICON)
            header.append(label, style=C.TOOL_NAME)
            path = args.get("path", "")
            if path:
                header.append(f"  {path}", style=C.TOOL_META)
            return [header, Syntax(diff_lines, "diff", word_wrap=True,
                                   indent_guides=False, padding=(0, 4))]
        path = (
            args.get("path") or args.get("pattern") or
            args.get("glob") or args.get("query") or ""
        )
        extra = ""
        if tool == "GrepTool":
            pat = args.get("pattern", "")
            in_path = args.get("path", "")
            path = f"{pat}"
            extra = f"  in {in_path}" if in_path else ""
        elif tool == "ReadFileTool":
            sl = args.get("start_line")
            el = args.get("end_line")
            if sl:
                extra = f"  :{sl}-{el or '…'}"

        t = Text()
        t.append(f"\n  {icon} ", style=C.TOOL_ICON)
        t.append(label, style=C.TOOL_NAME)
        t.append(f"  {path}", style=C.TOOL_ARG)
        if extra:
            t.append(extra, style=C.TOOL_META)
        return [t]

    @staticmethod
    def tool_result(tool: str, result: Any) -> list:  # noqa: C901
        icon  = _icon(tool)
        label = _label(tool)

        def _status(msg: str, style: str = C.MUTED) -> Text:
            t = Text()
            t.append(f"    ↳ ", style=C.MUTED)
            t.append(msg, style=style)
            return t
        if tool == "ThinkTool":
            if not isinstance(result, str) or not result.strip():
                return []
            out = [Text("")]
            for line in result.strip().splitlines():
                t = Text()
                t.append("    ", style="")
                t.append(line, style=C.DIM)
                out.append(t)
            return out
        if tool in {"CMDTool", "BashTool"} and isinstance(result, dict):
            stdout = (result.get("stdout") or "").strip()
            stderr = (result.get("stderr") or "").strip()
            code   = result.get("code", 0)
            ok     = code == 0

            items: list = []
            body = "\n".join(filter(None, [stdout, stderr]))
            if body:
                lines = body.splitlines()
                shown = lines[:60]
                hidden = len(lines) - 60
                body_text = "\n".join(shown)
                if hidden > 0:
                    body_text += f"\n  … {hidden} more lines"
                items.append(Syntax(
                    body_text, "bash",
                    word_wrap=True,
                    background_color="default",
                    padding=(0, 4),
                ))
            status_msg = "Done" if ok else f"Exit {code}"
            items.append(_status(status_msg, C.OK if ok else C.ERR))
            return items
        if tool in {"CreateFileTool", "WriteFileTool", "PatchFileTool"}:
            if isinstance(result, dict) and "diff" in result:
                diff_text = result["diff"]
                return [
                    Syntax(diff_text, "diff", word_wrap=True,
                           background_color="default", padding=(0, 4)),
                    _status("Written", C.OK),
                ]
            path = ""
            if isinstance(result, dict):
                path = result.get("path", "")
            elif isinstance(result, str):
                path = result
            return [_status(f"Written  {path}", C.OK)]
        if tool == "RemoveFileTool":
            if isinstance(result, dict) and "results" in result:
                items = []
                for r in result["results"]:
                    p = r.get("path", "")
                    if r.get("status") == "deleted":
                        items.append(_status(f"Deleted  {p}", C.ERR))
                    elif "error" in r:
                        items.append(_status(f"Error  {p}  {r['error']}", C.ERR))
                return items
            return [_status("Deleted", C.ERR)]
        if tool == "CreateDirectoryTool":
            path = (result or "").replace("Directory created: ", "") if isinstance(result, str) else ""
            return [_status(f"Created  {path}", C.OK)]
        if tool == "ReadFileTool" and isinstance(result, dict):
            lines = len((result.get("content") or "").splitlines())
            return [_status(f"{lines:,} lines  {result.get('path', '')}", C.MUTED)]
        if tool == "ListFilesTool" and isinstance(result, list):
            return [_status(f"{len(result)} files", C.MUTED)]
        if tool == "GrepTool" and isinstance(result, dict):
            m = result.get("matches", 0)
            matches_text = f"{m} match{'es' if m != 1 else ''}"
            items: list = [_status(matches_text, C.OK if m else C.MUTED)]
            hits = result.get("lines") or result.get("results") or []
            for hit in hits[:8]:
                t = Text()
                t.append("      ", style="")
                if isinstance(hit, dict):
                    ln  = hit.get("line_number", "")
                    txt = hit.get("line", str(hit))
                    t.append(f"{ln}  ", style=C.MUTED)
                    t.append(txt.rstrip(), style=C.TOOL_ARG)
                else:
                    t.append(str(hit).rstrip(), style=C.TOOL_ARG)
                items.append(t)
            if len(hits) > 8:
                items.append(_status(f"… {len(hits) - 8} more", C.MUTED))
            return items
        if tool == "GlobTool" and isinstance(result, dict):
            c = result.get("count", 0)
            files = result.get("files") or result.get("results") or []
            items: list = [_status(f"{c} file{'s' if c != 1 else ''}", C.MUTED)]
            for f in files[:6]:
                t = Text()
                t.append("      ", style="")
                t.append(str(f), style=C.TOOL_ARG)
                items.append(t)
            if len(files) > 6:
                items.append(_status(f"… {len(files) - 6} more", C.MUTED))
            return items
        if tool == "TreeTool" and isinstance(result, str):
            items: list = []
            for line in result.splitlines()[:40]:
                t = Text()
                t.append("    ", style="")
                t.append(line, style=C.DIM)
                items.append(t)
            return items
        if tool == "PDFTool" and isinstance(result, dict):
            pages = result.get("pages", "?")
            return [_status(f"{pages} pages  {result.get('path', '')}", C.MUTED)]
        if result is not None:
            s = str(result)[:800]
            items: list = []
            for line in s.splitlines():
                t = Text()
                t.append("    ", style="")
                t.append(line, style=C.DIM)
                items.append(t)
            return items

        return []

    @staticmethod
    def approval_request(tool: str) -> list:
        t = Text()
        t.append("\n  ◈ ", style=C.WARN)
        t.append("Allow ", style=C.WARN)
        t.append(tool, style="bold " + C.WARN)
        t.append("?  ", style=C.WARN)
        t.append("y", style="bold green")
        t.append(" / ", style=C.MUTED)
        t.append("n", style="bold red")
        t.append(" / ", style=C.MUTED)
        t.append("a", style="bold cyan")
        t.append(" (always)", style=C.MUTED)
        return [t]

    @staticmethod
    def approval_result(granted: bool, tool: str) -> list:
        if granted:
            t = Text()
            t.append("    ✓ ", style=C.OK)
            t.append("Allowed  ", style=C.MUTED)
            t.append(tool, style=C.MUTED)
        else:
            t = Text()
            t.append("    ✗ ", style=C.ERR)
            t.append("Denied  ", style=C.MUTED)
            t.append(tool, style=C.MUTED)
        return [t]

    @staticmethod
    def tool_error(tool: str, error: str) -> list:
        header = Text()
        header.append(f"\n  {_icon(tool)} ", style=C.ERR)
        header.append(f"{_label(tool)} failed", style=C.ERR)
        detail = Text()
        detail.append("    ", style="")
        detail.append(error[:300], style=C.ERR)
        return [header, detail]

    @staticmethod
    def task_error(error: str) -> list:
        header = Text()
        header.append("\n  ✗ ", style=C.ERR)
        header.append("Error", style=C.ERR)
        items: list = [header]
        for line in error.strip().splitlines():
            t = Text()
            t.append("    ", style="")
            t.append(line, style=C.ERR)
            items.append(t)
        return items

    @staticmethod
    def context_compressed(before: int, after: int) -> list:
        t = Text()
        t.append("  ⟳ ", style=C.WARN)
        t.append("Context compressed  ", style=C.DIM)
        t.append(f"{before:,}", style=C.WARN)
        t.append(" → ", style=C.MUTED)
        t.append(f"{after:,}", style=C.OK)
        t.append(" tokens", style=C.MUTED)
        return [t]

    @staticmethod
    def task_started(prompt: str) -> list:
        t = Text()
        t.append("\n❯ ", style="bold green")
        t.append(prompt, style=C.USER)
        return [t]
class CommandSuggester(Suggester):
    COMMANDS = [
        "/help", "/tools", "/models", "/model", "/model next",
        "/settings", "/model-picker",
        "/context", "/history", "/reset", "/clear", "/quit",
        "/approve", "/approve ask_all","/approve ask_unsafe","/approve auto_approve",
        "/provider", "/provider openai", "/provider openrouter",
        "/provider openai_compatible", "/provider reset",
        "/baseurl", "/set_context_length", "/compress_context",
        "/pause", "/resume",
        "/steer", "/steer clear",
        "/queue",
    ]

    def __init__(self, app_ref: "AgentTUI") -> None:
        super().__init__(use_cache=False)
        self._app = app_ref

    async def get_suggestion(self, value: str) -> str | None:
        v = value.lstrip()
        if not v:
            return None
        parts = v.split()
        if len(parts) == 1 and v.startswith("/"):
            for cmd in self.COMMANDS:
                if cmd.startswith(v) and cmd != v:
                    return cmd
            return None
        if len(parts) == 2 and parts[0] == "/model":
            try:
                models = self._app.agent.provider.get_models()
                if isinstance(models, list):
                    for m in models:
                        if m.startswith(parts[1]):
                            return f"/model {m}"
            except Exception:
                pass
        if len(parts) == 2 and parts[0] == "/approve":
            for mode in ("safe", "always", "never"):
                if mode.startswith(parts[1]):
                    return f"/approve {mode}"
        if len(parts) == 2 and parts[0] == "/provider":
            for p in ("openai", "openrouter", "openai_compatible", "reset"):
                if p.startswith(parts[1]):
                    return f"/provider {p}"
        if len(parts) == 2 and parts[0] == "/steer":
            if "clear".startswith(parts[1]):
                return "/steer clear"
        return None
class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    """

    def refresh_status(
        self, model: str, cwd: str, tokens: int,
        max_tokens: int, usage: float, paused: bool,
    ) -> None:
        col = _token_color(usage)
        pause = " [yellow][paused][/yellow]" if paused else ""
        cwd_display = cwd if len(cwd) <= 45 else "…" + cwd[-44:]
        self.update(
            f"[{C.MODEL}]{model}[/{C.MODEL}]{pause}"
            f"  [{C.CWD}]{cwd_display}[/{C.CWD}]"
            f"  [{col}]{tokens:,} / {max_tokens:,}  {usage:.0f}%[/{col}]"
        )
class SettingsModal(ModalScreen):
    CSS = """
    SettingsModal > Vertical {
        width: 72;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    .modal-title { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    .field-row   { height: 3; layout: horizontal; align: left middle; margin-bottom: 1; }
    .field-label { width: 22; color: $text-muted; }
    .field-input { width: 1fr; border: solid $accent; }
    .btn-row     { layout: horizontal; height: 3; align: right middle; margin-top: 1; }
    """

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self.agent = agent
        self._cfg = load_config()

    def compose(self) -> ComposeResult:
        p = self.agent.provider
        with Vertical():
            yield Label("⚙  Settings", classes="modal-title")
            with TabbedContent():
                with TabPane("General"):
                    with Horizontal(classes="field-row"):
                        yield Label("Approval mode:", classes="field-label")
                        yield Select(
                            [("safe", "safe"), ("always", "always"), ("never", "never")],
                            value=self.agent.approve_mode, id="sel-approve",
                        )
                    with Horizontal(classes="field-row"):
                        yield Label("Context length:", classes="field-label")
                        yield Input(value=str(self.agent.context.max_tokens),
                                    id="inp-ctx-len", classes="field-input")
                with TabPane("Provider"):
                    with Horizontal(classes="field-row"):
                        yield Label("Provider:", classes="field-label")
                        yield Select(
                            [("openai","openai"),("openrouter","openrouter"),
                             ("openai_compatible","openai_compatible")],
                            value=self._cfg.get("provider","openai_compatible"),
                            id="sel-provider",
                        )
                    with Horizontal(classes="field-row"):
                        yield Label("Base URL:", classes="field-label")
                        yield Input(value=getattr(p,"base_url",""),
                                    id="inp-base-url", classes="field-input")
                    with Horizontal(classes="field-row"):
                        yield Label("API Key:", classes="field-label")
                        yield Input(value=self._cfg.get("api_key",""),
                                    password=True, id="inp-api-key", classes="field-input")
                with TabPane("About"):
                    yield Static(
                        f"[bold cyan]Model:[/bold cyan]     {p.model}\n"
                        f"[bold cyan]Provider:[/bold cyan]  {p.__class__.__name__}\n"
                        f"[bold cyan]Tools:[/bold cyan]     {len(self.agent.tools)}\n"
                        f"[bold cyan]Messages:[/bold cyan]  {len(self.agent.context.messages)}\n"
                        f"[bold cyan]CWD:[/bold cyan]       {os.getcwd()}",
                        markup=True,
                    )
            with Horizontal(classes="btn-row"):
                yield Button("Save", variant="success", id="btn-save")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None); return
        cfg = load_config()
        try:
            v = self.query_one("#sel-approve", Select).value
            if v and v != Select.BLANK:
                self.agent.approve_mode = v; cfg["approve_mode"] = v
        except Exception: pass
        try:
            n = int(self.query_one("#inp-ctx-len", Input).value)
            self.agent.context.max_tokens = n
            self.agent.provider.context_length = n
            cfg["context_length"] = n
        except Exception: pass
        try:
            url = self.query_one("#inp-base-url", Input).value.strip()
            if url:
                p = self.agent.provider
                if hasattr(p,"set_base_url"): p.set_base_url(url)
                elif hasattr(p,"base_url"):   p.base_url = url
                cfg["base_url"] = url
        except Exception: pass
        try:
            key = self.query_one("#inp-api-key", Input).value.strip()
            if key: cfg["api_key"] = key
        except Exception: pass
        save_config(cfg); save_workspace(self.agent)
        self.dismiss("saved")
class ModelPickerModal(ModalScreen):
    CSS = """
    ModelPickerModal > Vertical {
        width: 62; height: 80%;
        background: $surface; border: round $accent; padding: 1 2;
    }
    .modal-title { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    """

    def __init__(self, models: list[str], current: str) -> None:
        super().__init__()
        self._all = models
        self._cur = current

    def _make_items(self, q: str = "") -> list[ListItem]:
        filtered = [m for m in self._all if q.lower() in m.lower()]
        items = []
        for m in filtered:
            marker = "[bold green]●[/bold green]" if m == self._cur else "[dim]○[/dim]"
            items.append(ListItem(Label(f"{marker}  {m}", markup=True), name=m))
        return items

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("⬡  Select Model", classes="modal-title")
            yield Input(placeholder="Filter…", id="model-search")
            yield ListView(*self._make_items(), id="model-list")
            yield Button("Cancel", variant="default", id="btn-cancel")

    def on_input_changed(self, event: Input.Changed) -> None:
        lv = self.query_one("#model-list", ListView)
        lv.clear()
        for item in self._make_items(event.value):
            lv.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.name)

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss(None)
class StreamView(Static):
    """
    Live streaming widget с рамкой только при стриминге.
    """
    DEFAULT_CSS = """
    StreamView {
        height: auto;
        max-height: 60%;
        padding: 0 2;
        background: $background;
        overflow-y: auto;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__("", *args, **kwargs)
        self._lines: list[str] = []
        self._partial: str = ""
        self._lock = threading.Lock()
        self._streaming = False

    def push_chunk(self, text: str) -> None:
        """Добавление текста во время стриминга."""
        with self._lock:
            self._partial += text
            while "\n" in self._partial:
                line, self._partial = self._partial.split("\n", 1)
                self._lines.append(line)
            self._streaming = True
        self.app.call_from_thread(self._update_display)

    def _update_display(self):
        with self._lock:
            t = Text()
            if self._streaming:
                t.append("streaming…\n", style="dim cyan")
                self.styles.border = ("solid", "blue")  # рамка активна
            else:
                self.styles.border = None  # скрываем рамку
            for line in self._lines:
                t.append(line + "\n", style=C.ASSISTANT)
            if self._partial:
                t.append(self._partial, style=C.ASSISTANT)
        super().update(t)

    def commit(self) -> str:
        """Завершение стрима: скрываем рамку и оставляем полный текст."""
        with self._lock:
            if self._partial:
                self._lines.append(self._partial)
                self._partial = ""
            full = "\n".join(self._lines)
            self._lines = []
            self._streaming = False
        self.app.call_from_thread(self._update_display)
        return full

    def cancel(self) -> str:
        return self.commit()

class AgentTUI(App):
    CSS = """
    Screen { layers: base; }
        height: 1fr;
        border: none;
        padding: 0 2;
        scrollbar-gutter: stable;
    }

    StreamView {
        height: auto;
        max-height: 60%;
        padding: 0 2;
        background: $background;
    }
        height: 3;
        border-top: solid $accent;
        background: $surface;
        padding: 0 1;
        layout: horizontal;
        align: left middle;
    }
        width: auto;
        color: $accent;
        padding: 0 1 0 0;
        content-align: left middle;
    }
        height: 1;
        width: 1fr;
        border: none;
        background: transparent;
    }
    Footer { height: 1; }
    """

    BINDINGS = [
        Binding("ctrl+p", "toggle_pause",     "Pause/Resume"),
        Binding("ctrl+c", "do_interrupt",      "Interrupt"),
        Binding("ctrl+s", "open_settings",     "Settings"),
        Binding("ctrl+m", "open_model_picker", "Models"),
    ]

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self.agent = agent
        self._R    = Renderer()

        self._approval_needed = threading.Event()
        self._approval_done   = threading.Event()
        self._approval_tool   = ""

        self._streaming = False

    def compose(self) -> ComposeResult:
        yield StatusBar(id="statusbar")
        yield RichLog(id="log", highlight=False, markup=False, wrap=True)
        yield StreamView(id="stream-view")          # live streaming area
        with Horizontal(id="input-bar"):
            yield Label("❯", id="prompt-label")
            yield Input(
                placeholder="Type a task or /help…",
                id="cmd-input",
                suggester=CommandSuggester(self),
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#cmd-input", Input).focus()
        self._tick_status()
        self.set_interval(2, self._tick_status)
        hint = Text()
        hint.append("  /help", style="bold cyan")
        hint.append(" for commands  ·  ", style=C.MUTED)
        hint.append("Ctrl+S", style="bold cyan")
        hint.append(" settings  ·  ", style=C.MUTED)
        hint.append("Ctrl+M", style="bold cyan")
        hint.append(" models\n", style=C.MUTED)
        self._write(hint)

    def _tick_status(self) -> None:
        try:
            p = self.agent.provider
            self.query_one(StatusBar).refresh_status(
                model      = p.model.split("/")[-1],
                cwd        = os.getcwd(),
                tokens     = self.agent.context.estimate_tokens(),
                max_tokens = self.agent.context.max_tokens,
                usage      = self.agent.context.usage_percent(),
                paused     = self.agent.is_paused,
            )
        except Exception:
            pass

    def _write(self, renderable: Any) -> None:
        def _do():
            self.query_one("#log", RichLog).write(renderable)
        try:
            self.call_from_thread(_do)
        except Exception:
            _do()

    def _write_many(self, items: list) -> None:
        for r in items:
            self._write(r)

    def _sv(self) -> StreamView:
        return self.query_one("#stream-view", StreamView)

    def _stream_chunk(self, text: str) -> None:
        """Receive a text chunk from the agent thread."""
        if not self._streaming:
            self._streaming = True
        self._sv().push_chunk(text)

    def _stream_close(self) -> None:
        """Finalise stream: move accumulated text into RichLog."""
        if not self._streaming:
            return
        self._streaming = False
        sv = self._sv()
        full_text = sv.commit()          # clears StreamView, returns full text
        if full_text.strip():
            def _commit():
                log = self.query_one("#log", RichLog)
                log.write(Text(""))      # blank line before
                for line in full_text.splitlines():
                    log.write(Text(line, style=C.ASSISTANT))
                log.write(Text(""))      # blank line after
            try:
                self.call_from_thread(_commit)
            except Exception:
                _commit()

    def _stream_cancel(self) -> None:
        if not self._streaming:
            return
        self._streaming = False
        sv = self._sv()
        partial = sv.cancel()
        if partial.strip():
            def _commit():
                log = self.query_one("#log", RichLog)
                log.write(Text(""))
                for line in partial.splitlines():
                    log.write(Text(line, style=C.ASSISTANT))
                t = Text()
                t.append("  … interrupted", style=C.WARN)
                log.write(t)
            try:
                self.call_from_thread(_commit)
            except Exception:
                _commit()

    def event_handler(self, event: str, data: dict) -> None:  # noqa: C901

        if event == "task_started":
            self._write_many(self._R.task_started(data["prompt"]))

        elif event == "model_processing":
            self._write_many(self._R.thinking())

        elif event == "stream_chunk":
            if data.get("type") == "text":
                self._stream_chunk(data["content"])

        elif event == "provider_response":
            self._stream_close()

        elif event == "tool_call":
            tool = data.get("tool", "")
            if not tool or tool == "FinishTaskTool":
                return
            self._stream_close()
            self._write_many(self._R.tool_call(tool, data.get("args", {})))

        elif event == "tool_finished":
            self._stream_close()
            items = self._R.tool_result(data["tool"], data.get("result"))
            self._write_many(items)

        elif event == "tool_error":
            self._stream_close()
            self._write_many(self._R.tool_error(
                data.get("tool", "?"), data.get("error", "unknown error")
            ))

        elif event == "approval_requested":
            self._stream_close()
            self._approval_tool = data["tool"]
            self._approval_done.clear()
            self._approval_needed.set()
            self._write_many(self._R.approval_request(data["tool"]))
            self._approval_done.wait()

        elif event == "approval_denied":
            self._write_many(self._R.approval_result(False, data.get("tool", "")))

        elif event == "approval_granted":
            self._write_many(self._R.approval_result(True, data.get("tool", "")))

        elif event == "context_compressed":
            self._write_many(self._R.context_compressed(
                data.get("before_tokens", 0), data.get("after_tokens", 0)
            ))

        elif event == "context_compression_error":
            self._write_many(self._R.task_error(data.get("error", "")))

        elif event == "task_error":
            self._stream_close()
            self._write_many(self._R.task_error(data.get("error", "")))

        elif event == "task_finished":
            self._stream_close()
            save_workspace(self.agent)
            try:
                self.call_from_thread(self._tick_status)
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        if self._approval_needed.is_set():
            self._approval_needed.clear()
            ans = text.lower()
            if ans == "a":
                self.agent.approve_mode = "auto_approve"
                self.agent.resolve_approval(True)
            elif ans in {"y", "yes"}:
                self.agent.resolve_approval(True)
            else:
                self.agent.resolve_approval(False)
            self._approval_done.set()
            return

        self._dispatch(text)

    def _dispatch(self, text: str) -> None:  # noqa: C901
        t = text.strip()

        def info(msg: str) -> None:
            r = Text(); r.append("  "); r.append(msg, style=C.DIM); self._write(r)

        def ok(msg: str) -> None:
            r = Text(); r.append("  ✓ ", style=C.OK); r.append(msg, style=C.DIM); self._write(r)

        def err(msg: str) -> None:
            r = Text(); r.append("  ✗ ", style=C.ERR); r.append(msg); self._write(r)
        if t in {"/quit", "/exit"}:
            self.exit()
        elif t in {"/help", "?"}:
            tbl = Table(border_style="grey30", show_header=False, padding=(0, 2),
                        box=None, pad_edge=False)
            tbl.add_column("cmd",  style="bold cyan",  no_wrap=True, min_width=32)
            tbl.add_column("desc", style="grey62")
            rows = [
                ("/help",                     "This help"),
                ("/tools",                    "List tools"),
                ("/models",                   "List models"),
                ("/model <name> | next",       "Switch model"),
                ("/model-picker  (Ctrl+M)",    "Interactive model picker"),
                ("/settings  (Ctrl+S)",        "Settings modal"),
                ("/context",                  "Token usage"),
                ("/history",                  "Message history"),
                ("/reset",                    "Clear context"),
                ("/approve [ask_all|ask_unsafe|auto_approve]", "Approval mode"),
                ("/provider [name|reset]",    "Switch provider"),
                ("/baseurl [url]",            "Show / set base URL"),
                ("/set_context_length <n>",   "Max tokens"),
                ("/compress_context",         "Compress now"),
                ("/pause  /resume  Ctrl+P",   "Pause / resume"),
                ("/steer [text|clear]",       "Steering instructions"),
                ("/queue",                    "Task queue"),
                ("/clear",                    "Clear log"),
                ("/quit",                     "Exit"),
            ]
            for cmd, desc in rows:
                tbl.add_row(cmd, desc)
            self._write(Text(""))
            self._write(tbl)
            self._write(Text(""))
        elif t == "/tools":
            names = sorted(
                self.agent.tools.keys()
                if isinstance(self.agent.tools, dict)
                else self.agent.tools
            )
            self._write(Text(""))
            for n in names:
                r = Text()
                r.append(f"  {_icon(n)} ", style=C.TOOL_ICON)
                r.append(n, style=C.TOOL_NAME)
                self._write(r)
            self._write(Text(""))
        elif t == "/models":
            models = self.agent.provider.get_models()
            if isinstance(models, dict):
                err(models.get("error", "unknown")); return
            cur = self.agent.provider.model
            self._write(Text(""))
            for m in models:
                r = Text()
                if m == cur:
                    r.append("  ● ", style="bold green")
                    r.append(m, style="bold white")
                else:
                    r.append("  ○ ", style=C.MUTED)
                    r.append(m, style=C.DIM)
                self._write(r)
            self._write(Text(""))
        elif t == "/model":
            info(f"Model: {self.agent.provider.model}")

        elif t == "/model next":
            models = self.agent.provider.get_models()
            if not isinstance(models, list) or not models:
                err("No models"); return
            cur = self.agent.provider.model
            try:   idx = models.index(cur)
            except ValueError: idx = -1
            self._set_model(models[(idx + 1) % len(models)])

        elif t.startswith("/model "):
            self._set_model(t.split(maxsplit=1)[1].strip())

        elif t == "/model-picker":
            self.action_open_model_picker()

        elif t == "/settings":
            self.action_open_settings()
        elif t == "/context":
            tok   = self.agent.context.estimate_tokens()
            max_t = self.agent.context.max_tokens
            use   = self.agent.context.usage_percent()
            col   = _token_color(use)
            r = Text()
            r.append(f"  Messages: ", style=C.MUTED)
            r.append(f"{len(self.agent.context.messages)}", style="white")
            r.append(f"   Tokens: ", style=C.MUTED)
            r.append(f"{tok:,} / {max_t:,}", style=col)
            r.append(f"  ({use:.0f}%)", style=col)
            self._write(r)
        elif t == "/history":
            msgs = self.agent.context.messages
            if not msgs:
                info("History is empty"); return
            for i, msg in enumerate(msgs, 1):
                content = msg.content
                if hasattr(content, "text"): content = content.text
                preview = str(content)[:300].replace("\n", " ")
                r = Text()
                r.append(f"  {i:3}  ", style=C.MUTED)
                r.append(f"{msg.role:<12}", style="bold cyan" if msg.role == "assistant" else "bold white")
                r.append(preview, style=C.DIM)
                self._write(r)
        elif t == "/reset":
            self.agent.context = Context(provider=self.agent.provider)
            self.agent.context.compression_callback = self.agent._on_context_compressed
            save_workspace(self.agent)
            ok("Context cleared")
            self._tick_status()
        elif t == "/clear":
            self.query_one("#log", RichLog).clear()
        elif t == "/approve":
            info(f"Approval mode: {self.agent.approve_mode}")

        elif t.startswith("/approve "):
            mode = t.split(maxsplit=1)[1].strip()
            if mode not in {"safe", "always", "never"}:
                err("Valid: safe | always | never"); return
            self.agent.approve_mode = mode
            cfg = load_config(); cfg["approve_mode"] = mode
            save_config(cfg); save_workspace(self.agent)
            ok(f"Approval → {mode}")
        elif t == "/provider":
            info(f"Provider: {self.agent.provider.__class__.__name__}")

        elif t.startswith("/provider "):
            name = t.split(maxsplit=1)[1].strip()
            if name == "reset":
                cfg = load_config()
                cfg.pop("provider", None); cfg.pop("model", None)
                self.agent.provider = NonSelectedProvider()
                save_config(cfg); save_workspace(self.agent)
                ok("Provider reset")
            else:
                self._switch_provider(name)
        elif t == "/baseurl":
            info(f"Base URL: {getattr(self.agent.provider, 'base_url', 'N/A')}")

        elif t.startswith("/baseurl "):
            url = t.split(maxsplit=1)[1].strip()
            p = self.agent.provider
            if hasattr(p,"set_base_url"): p.set_base_url(url)
            elif hasattr(p,"base_url"):   p.base_url = url
            cfg = load_config(); cfg["base_url"] = url
            save_config(cfg); save_workspace(self.agent)
            ok(f"Base URL → {url}")
        elif t.startswith("/set_context_length "):
            val = t.split(maxsplit=1)[1].strip()
            if not val.isdigit():
                err("Usage: /set_context_length <n>"); return
            n = int(val)
            self.agent.provider.context_length = n
            self.agent.context.max_tokens = n
            cfg = load_config(); cfg["context_length"] = n
            save_config(cfg); save_workspace(self.agent)
            ok(f"Context length → {n:,}")
            self._tick_status()
        elif t == "/compress_context":
            info("Compressing context…")
            self.agent.context.compress()
        elif t == "/pause":
            self.agent.pause()
            r = Text(); r.append("  ⏸ Paused", style=C.WARN)
            self._write(r); self._tick_status()

        elif t == "/resume":
            self.agent.resume()
            r = Text(); r.append("  ▶ Resumed", style=C.OK)
            self._write(r); self._tick_status()
        elif t == "/steer":
            instrs = getattr(self.agent.steering, "instructions", [])
            if not instrs:
                info("No steering instructions")
            else:
                for i, s in enumerate(instrs, 1):
                    r = Text()
                    r.append(f"  {i}. ", style=C.MUTED)
                    r.append(s, style="white")
                    self._write(r)

        elif t == "/steer clear":
            self.agent.clear_instructions(); ok("Steering cleared")

        elif t.startswith("/steer "):
            instr = t[len("/steer "):]
            self.agent.add_instruction(instr); ok(f"Steering: {instr}")
        elif t == "/queue":
            items = list(self.agent.task_queue.queue)
            cur   = self.agent.current_task
            if not cur and not items:
                info("Queue empty"); return
            if cur:
                r = Text()
                r.append("  ▶ ", style="bold cyan")
                r.append(cur.prompt[:80], style="white")
                self._write(r)
            for task in items:
                r = Text()
                r.append("  ○ ", style=C.MUTED)
                r.append(task.prompt[:80], style=C.DIM)
                self._write(r)

        elif t.startswith("/"):
            err(f"Unknown: {t}  (/help)")

        else:
            self.agent.enqueue(prompt=t, task_id=str(time.time()))

    def _set_model(self, model: str) -> None:
        models = self.agent.provider.get_models()
        if isinstance(models, list) and model not in models:
            r = Text(); r.append("  ✗ ", style=C.ERR); r.append(f"Unknown model: {model}")
            self._write(r); return
        self.agent.provider.set_model(model)
        cfg = load_config(); cfg["model"] = model
        save_config(cfg); save_workspace(self.agent)
        r = Text(); r.append("  ✓ ", style=C.OK); r.append(f"Model → {model}", style=C.DIM)
        self._write(r); self._tick_status()

    def _switch_provider(self, name: str) -> None:
        tools = (
            list(self.agent.tools.values())
            if isinstance(self.agent.tools, dict)
            else self.agent.tools
        )
        cur_model = self.agent.provider.model
        cfg = load_config()
        if name == "openai":
            key = cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY","")
            p = OpenAICompatibleProvider(api_key=key, model=cur_model,
                base_url="https://api.openai.com/v1", tools=tools)
        elif name == "openrouter":
            key = cfg.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY","")
            p = OpenAICompatibleProvider(api_key=key, model=cur_model,
                base_url="https://openrouter.ai/api/v1", tools=tools)
        else:
            key = cfg.get("api_key") or os.getenv("API_KEY","dummy")
            p = OpenAICompatibleProvider(api_key=key, model=cur_model,
                base_url=cfg.get("base_url","http://localhost:1234/v1/"), tools=tools)
        self.agent.provider = p
        cfg["provider"] = name; save_config(cfg); save_workspace(self.agent)
        r = Text(); r.append("  ✓ ", style=C.OK); r.append(f"Provider → {name}", style=C.DIM)
        self._write(r); self._tick_status()

    def action_toggle_pause(self) -> None:
        if self.agent.is_paused:
            self.agent.resume()
            r = Text(); r.append("  ▶ Resumed", style=C.OK); self._write(r)
        else:
            self.agent.pause()
            r = Text(); r.append("  ⏸ Paused", style=C.WARN); self._write(r)
        self._tick_status()

    def action_do_interrupt(self) -> None:
        self._stream_cancel()

    def action_open_settings(self) -> None:
        def _cb(result):
            if result == "saved":
                r = Text(); r.append("  ✓ ", style=C.OK)
                r.append("Settings saved", style=C.DIM); self._write(r)
                self._tick_status()
        self.push_screen(SettingsModal(self.agent), _cb)

    def action_open_model_picker(self) -> None:
        try:
            models = self.agent.provider.get_models()
        except Exception:
            r = Text(); r.append("  ✗ ", style=C.ERR)
            r.append("Could not fetch models"); self._write(r); return
        if not isinstance(models, list) or not models:
            r = Text(); r.append("  ", style=""); r.append("No models available", style=C.MUTED)
            self._write(r); return
        self.push_screen(ModelPickerModal(models, self.agent.provider.model),
                         lambda m: m and self._set_model(m))

    def run_tui(self) -> None:
        self.run()