from __future__ import annotations

import difflib
import threading
import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

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
    QUESTION    = "bold yellow"
    SUGGEST     = "grey62"
    BORDER      = "grey23"
    HEADER_BG   = "grey7"

def _token_color(pct: float) -> str:
    return C.TOKENS_OK if pct < 50 else C.TOKENS_WARN if pct < 80 else C.TOKENS_HOT

_TOOL_ICON: dict[str, str] = {
    "CMDTool": "⬡", "BashTool": "⬡", "Shell": "⬡", "ShellTool": "⬡",
    "Terminal": "⬡", "TerminalTool": "⬡",
    "ReadFileTool": "⊙", "ReadFile": "⊙", "ReadFilesTool": "⊙", "ReadFiles": "⊙",
    "WriteFileTool": "◎", "WriteFile": "◎", "CreateFileTool": "◎", "CreateFile": "◎",
    "PatchFileTool": "◈", "PatchFile": "◈",
    "RemoveFileTool": "⊗", "RemoveFile": "⊗",
    "CreateDirectoryTool": "⊞", "CreateDirectory": "⊞",
    "GrepTool": "⊛", "Grep": "⊛",
    "GlobTool": "⊡", "Glob": "⊡",
    "ListFilesTool": "⊞", "ListFiles": "⊞",
    "TreeTool": "⊟", "Tree": "⊟",
    "PDFTool": "⊙", "PDF": "⊙",
    "ThinkTool": "⟳", "Think": "⟳",
    "PlanTool": "☰", "Plan": "☰",
    "FinishTaskTool": "✓", "FinishTask": "✓",
    "QuestionTool": "?", "Question": "?",
    "WebSearchTool": "⊕", "WebSearch": "⊕",
    "WebVisitTool": "⊕", "WebVisit": "⊕",
    "default": "◆",
}

_TOOL_LABEL: dict[str, str] = {
    "CMDTool": "Bash", "BashTool": "Bash", "Shell": "Shell", "ShellTool": "Shell",
    "Terminal": "Terminal", "TerminalTool": "Terminal",
    "ReadFileTool": "Read", "ReadFile": "Read", "ReadFilesTool": "Read", "ReadFiles": "Read",
    "WriteFileTool": "Write", "WriteFile": "Write", "CreateFileTool": "Write", "CreateFile": "Write",
    "PatchFileTool": "Edit", "PatchFile": "Edit",
    "RemoveFileTool": "Delete", "RemoveFile": "Delete",
    "CreateDirectoryTool": "Mkdir", "CreateDirectory": "Mkdir",
    "GrepTool": "Search", "Grep": "Search",
    "GlobTool": "Glob", "Glob": "Glob",
    "ListFilesTool": "List", "ListFiles": "List",
    "TreeTool": "Tree", "Tree": "Tree",
    "PDFTool": "PDF", "PDF": "PDF",
    "ThinkTool": "Think", "Think": "Think",
    "PlanTool": "Plan", "Plan": "Plan",
    "FinishTaskTool": "Finish", "FinishTask": "Finish",
    "QuestionTool": "Question", "Question": "Question",
    "WebSearchTool": "Web", "WebSearch": "Web",
    "WebVisitTool": "Visit", "WebVisit": "Visit",
}

_TOOL_SPINNER: dict[str, str] = {
    "Shell": "dots2",    "ShellTool": "dots2",
    "Terminal": "dots2", "TerminalTool": "dots2",
    "CMDTool": "dots2",  "BashTool": "dots2",
    "Think": "dots",     "ThinkTool": "dots",
    "Plan": "dots",      "PlanTool": "dots",
    "WebSearch": "earth","WebSearchTool": "earth",
    "WebVisit": "earth", "WebVisitTool": "earth",
}
_DEFAULT_SPINNER = "dots"

def _icon(tool: str) -> str:
    return _TOOL_ICON.get(tool, _TOOL_ICON["default"])

def _label(tool: str) -> str:
    return _TOOL_LABEL.get(tool, tool.replace("Tool", ""))

def _spinner_style(tool: str) -> str:
    return _TOOL_SPINNER.get(tool, _DEFAULT_SPINNER)

class AnimatedContext:
    def __init__(
        self,
        console: Console,
        tool_name: str,
        label: str = "",
        transient: bool = True,
    ) -> None:
        self.console   = console
        self.tool_name = tool_name
        self.label     = label
        self.transient = transient
        self.elapsed   = 0.0

        self._live: Live | None = None
        self._start: float = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _build_row(self, elapsed: float) -> Table:

        icon    = _icon(self.tool_name)
        lbl     = _label(self.tool_name)
        spin    = _spinner_style(self.tool_name)

        label_cell = Text()
        label_cell.append(f"  {icon} ", style=C.TOOL_ICON)
        label_cell.append(lbl,          style=C.TOOL_NAME)

        arg_cell     = Text(self.label[:120],    style=C.TOOL_ARG) if self.label else Text()
        elapsed_cell = Text(f"{elapsed:.1f}s",   style=C.MUTED)

        grid = Table.grid(padding=(0, 1))
        grid.add_column(no_wrap=True)  
        grid.add_column(no_wrap=True) 
        grid.add_column(no_wrap=True)   
        grid.add_column(no_wrap=True)  

        grid.add_row(
            Spinner(spin, style=C.TOOL_ICON),
            label_cell,
            arg_cell,
            elapsed_cell,
        )
        return grid

    def _tick(self) -> None:

        while not self._stop_event.is_set():
            elapsed = time.perf_counter() - self._start
            if self._live is not None:
                self._live.update(self._build_row(elapsed))
            time.sleep(1 / 12)

    def __enter__(self) -> "AnimatedContext":
        self._start      = time.perf_counter()
        self._stop_event = threading.Event()

        self._live = Live(
            self._build_row(0.0),
            console=self.console,
            refresh_per_second=12,
            transient=self.transient,
        )
        self._live.__enter__()

        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)

        self.elapsed = time.perf_counter() - self._start

        if self._live is not None:
            self._live.__exit__(exc_type, exc_val, exc_tb)

class ProgressContext:
    def __init__(self, console: Console, total: int, label: str = "") -> None:
        self.console = console
        self.total   = total
        self.label   = label
        self._prog: Progress | None = None
        self._task_id = None

    def __enter__(self) -> "ProgressContext":
        self._prog = Progress(
            SpinnerColumn(_DEFAULT_SPINNER),
            TextColumn(f"  [cyan]{self.label}[/]  " if self.label else "  "),
            BarColumn(
                bar_width=30,
                style=C.MUTED,
                complete_style=C.OK,
                finished_style=C.OK,
            ),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("[grey50]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        )
        self._prog.__enter__()
        self._task_id = self._prog.add_task("", total=self.total)
        return self

    def advance(self, description: str = "", step: int = 1) -> None:
        if self._prog is not None and self._task_id is not None:
            self._prog.update(
                self._task_id,
                advance=step,
                description=description[:60],
            )

    def __exit__(self, *args) -> None:
        if self._prog is not None:
            self._prog.__exit__(*args)

class Renderer:
    @staticmethod
    def _status(msg: str, style: str = C.MUTED, elapsed: float | None = None) -> Text:
        t = Text()
        t.append("    ↳ ", style=C.MUTED)
        t.append(msg,      style=style)
        if elapsed is not None:
            t.append(f"  {elapsed:.2f}s", style=C.MUTED)
        return t

    @staticmethod
    def _separator() -> Rule:
        return Rule(style=C.BORDER)

    @staticmethod
    def user_prompt(prompt: str) -> list:
        t = Text()
        t.append("\n❯ ", style="bold green")
        t.append(prompt,   style=C.USER)
        return [t]

    @staticmethod
    def assistant_start() -> list:
        return [Text("")]

    @staticmethod
    def assistant_end() -> list:
        return [Text("")]

    @staticmethod
    def thinking() -> list:
        t = Text()
        t.append("  ⟳ ", style=C.MUTED)
        t.append("Thinking…", style=C.DIM)
        return [t]

    @staticmethod
    def tool_call(tool: str, args: dict) -> list:
        if tool in {"Think", "ThinkTool", "FinishTask", "FinishTaskTool"}:
            return []

        icon  = _icon(tool)
        label = _label(tool)

        if tool in {"Shell", "ShellTool", "CMDTool", "BashTool",
                    "Terminal", "TerminalTool"}:
            cmd    = args.get("cmd", args.get("command", ""))
            bg     = args.get("background", False)
            action = args.get("action")

            header = Text()
            header.append(f"\n  {icon} ", style=C.TOOL_ICON)
            header.append(label,          style=C.TOOL_NAME)

            if action:
                header.append(f"  [{action}]",   style=C.TOOL_META)
                for key in ("pid", "session_id"):
                    if args.get(key):
                        header.append(f"  {key}={args[key]}", style=C.TOOL_META)
            elif cmd:
                header.append("  ",        style="")
                header.append(cmd[:120],   style=C.TOOL_ARG)
                if bg:
                    header.append("  &",   style=C.MUTED)
            return [header]

        if args.get("old") is not None and args.get("new") is not None:
            diff_lines = "\n".join(difflib.unified_diff(
                args["old"].splitlines(),
                args["new"].splitlines(),
                fromfile="old", tofile="new", lineterm="",
            ))
            header = Text()
            header.append(f"\n  {icon} ", style=C.TOOL_ICON)
            header.append(label,          style=C.TOOL_NAME)
            if path := args.get("path", ""):
                header.append(f"  {path}", style=C.TOOL_META)
            return [
                header,
                Syntax(diff_lines, "diff", word_wrap=True,
                       indent_guides=False, padding=(0, 4)),
            ]

        if tool in {"Plan", "PlanTool"}:
            action = args.get("action", "")
            header = Text()
            header.append(f"\n  {icon} ", style=C.TOOL_ICON)
            header.append(label,          style=C.TOOL_NAME)
            header.append(f"  {action}",  style=C.TOOL_META)
            items: list = [header]
            if action == "create":
                for i, step in enumerate(args.get("steps", []), 1):
                    t = Text()
                    t.append(f"    {i}. ", style=C.MUTED)
                    t.append(step,         style=C.TOOL_ARG)
                    items.append(t)
            elif action == "complete":
                t = Text()
                t.append(f"    step {args.get('index', '?')}", style=C.TOOL_META)
                items.append(t)
            return items

        if tool in {"Question", "QuestionTool"}:
            question    = args.get("question", "")
            context     = args.get("context", "")
            suggestions = args.get("suggestions", [])

            items = []
            header = Text()
            header.append(f"\n  {icon} ", style=C.QUESTION)
            header.append(label,          style=C.QUESTION)
            items.append(header)

            q_text = Text()
            q_text.append("    ")
            q_text.append(question, style="bold white")
            items.append(q_text)

            if context:
                ctx = Text()
                ctx.append("    ")
                ctx.append(context, style=C.DIM)
                items.append(ctx)

            if suggestions:
                hint = Text()
                hint.append("    Suggestions: ", style=C.MUTED)
                hint.append(
                    "  |  ".join(f"[{i+1}] {s}" for i, s in enumerate(suggestions)),
                    style=C.SUGGEST,
                )
                items.append(hint)

            prompt = Text()
            prompt.append("    › ",                             style=C.QUESTION)
            prompt.append("type your answer or number", style=C.MUTED)
            items.append(prompt)
            return items

        if tool in {"ReadFiles", "ReadFilesTool"}:
            paths = args.get("paths", [])
            t = Text()
            t.append(f"\n  {icon} ", style=C.TOOL_ICON)
            t.append(label,          style=C.TOOL_NAME)
            if paths:
                t.append(f"  {paths[0]}", style=C.TOOL_ARG)
                if len(paths) > 1:
                    t.append(f"  +{len(paths) - 1} more", style=C.TOOL_META)
            return [t]

        path = (
            args.get("path") or args.get("pattern") or
            args.get("glob") or args.get("query") or args.get("url") or ""
        )
        extra = ""
        if tool in {"Grep", "GrepTool"}:
            path  = args.get("pattern", "")
            extra = f"  in {args.get('path', '')}" if args.get("path") else ""
        elif tool in {"ReadFile", "ReadFileTool"}:
            sl = args.get("start_line")
            el = args.get("end_line")
            if sl:
                extra = f"  :{sl}-{el or '…'}"

        t = Text()
        t.append(f"\n  {icon} ", style=C.TOOL_ICON)
        t.append(label,          style=C.TOOL_NAME)
        t.append(f"  {path}",    style=C.TOOL_ARG)
        if extra:
            t.append(extra, style=C.TOOL_META)
        return [t]

    @staticmethod
    def tool_result(tool: str, result: Any, elapsed: float | None = None) -> list: 
        s = Renderer._status

        if tool in {"Think", "ThinkTool"}:
            if not isinstance(result, str) or not result.strip():
                return []
            out = [Text("")]
            for line in result.strip().splitlines():
                t = Text()
                t.append("    ")
                t.append(line, style=C.DIM)
                out.append(t)
            return out

        if tool in {"Shell", "ShellTool", "CMDTool", "BashTool",
                    "Terminal", "TerminalTool"}:
            if not isinstance(result, dict):
                return [s(str(result), C.MUTED, elapsed)]

            if result.get("status") == "running" and "pid" in result:
                return [s(f"Started  pid={result['pid']}", C.OK, elapsed)]

            if result.get("status") == "open" and "session_id" in result:
                return [s(
                    f"Session {result['session_id']} opened  pid={result.get('pid', '?')}",
                    C.OK, elapsed,
                )]

            if result.get("status") == "terminated":
                return [s(f"Terminated  pid={result.get('pid', '?')}", C.WARN, elapsed)]

            if result.get("active_pids") is not None:
                pids = ", ".join(str(p) for p in result["active_pids"])
                return [s(f"Running: {pids or 'none'}", C.MUTED, elapsed)]

            stdout = (result.get("stdout") or result.get("output") or "").strip()
            stderr = (result.get("stderr") or "").strip()
            code   = result.get("code", 0)
            ok     = (code == 0) and not result.get("timed_out")

            items: list = []
            if result.get("timed_out"):
                items.append(s(result.get("error", "Timed out"), C.WARN))

            body = "\n".join(filter(None, [stdout, stderr]))
            if body:
                lines     = body.splitlines()
                shown     = lines[:60]
                hidden    = len(lines) - 60
                body_text = "\n".join(shown)
                if hidden > 0:
                    body_text += f"\n  … {hidden} more lines"
                items.append(
                    Syntax(body_text, "bash", word_wrap=True,
                           background_color="default", padding=(0, 4))
                )
            items.append(s("Done" if ok else f"Exit {code}",
                           C.OK if ok else C.ERR, elapsed))
            return items

        if tool in {"Plan", "PlanTool"}:
            if not isinstance(result, dict):
                return [s(str(result), C.MUTED, elapsed)]
            status = result.get("status", "")
            plan   = result.get("plan", [])
            items = []
            if status == "created":
                items.append(s(f"Plan created  ({len(plan)} steps)", C.OK, elapsed))
            elif status == "completed":
                step = result.get("step", {})
                items.append(s(f"✓ {step.get('task', '')}", C.OK, elapsed))
            elif "error" in result:
                items.append(s(result["error"], C.ERR, elapsed))
            else:
                for step in plan:
                    done = step.get("completed", False)
                    t = Text()
                    t.append("      ")
                    t.append("✓ " if done else "○ ",
                             style=C.OK if done else C.MUTED)
                    t.append(step.get("task", ""),
                             style=C.DIM if done else C.TOOL_ARG)
                    items.append(t)
            return items

        if tool in {"Question", "QuestionTool"}:
            return []

        if tool in {"CreateFile", "CreateFileTool", "WriteFile", "WriteFileTool",
                    "PatchFile", "PatchFileTool"}:
            if isinstance(result, dict) and "diff" in result:
                items = []
                if result["diff"].strip():
                    items.append(
                        Syntax(result["diff"], "diff", word_wrap=True,
                               background_color="default", padding=(0, 4))
                    )
                items.append(s(
                    f"{result.get('action', 'written').capitalize()}  {result.get('path','')}",
                    C.OK, elapsed,
                ))
                return items
            path = result.get("path", "") if isinstance(result, dict) else str(result)
            return [s(f"Written  {path}", C.OK, elapsed)]

        if tool in {"RemoveFile", "RemoveFileTool"}:
            if isinstance(result, dict) and "results" in result:
                items = []
                for r in result["results"]:
                    p = r.get("path", "")
                    if r.get("status") == "deleted":
                        items.append(s(f"Deleted  {p}", C.ERR, elapsed))
                    elif "error" in r:
                        items.append(s(f"Error  {p}  {r['error']}", C.ERR))
                return items
            return [s("Deleted", C.ERR, elapsed)]

        if tool in {"CreateDirectory", "CreateDirectoryTool"}:
            path = (
                result.get("path", "") if isinstance(result, dict)
                else str(result).replace("Directory created: ", "")
            )
            return [s(f"Created  {path}", C.OK, elapsed)]

        if tool in {"ReadFile", "ReadFileTool"} and isinstance(result, dict):
            if "error" in result:
                return [s(f"Error  {result['error']}", C.ERR, elapsed)]
            lines = len((result.get("content") or "").splitlines())
            return [s(f"{lines:,} lines  {result.get('path', '')}", C.MUTED, elapsed)]

        if tool in {"ReadFiles", "ReadFilesTool"} and isinstance(result, dict):
            files     = result.get("files", [])
            ok_files  = [f for f in files if "content" in f and "error" not in f]
            err_files = [f for f in files if "error" in f]
            items = [s(
                "  ".join(filter(None, [
                    f"{len(ok_files)} read",
                    (f"{len(err_files)} error{'s' if len(err_files) > 1 else ''}"
                     if err_files else ""),
                ])),
                C.OK if not err_files else C.WARN,
                elapsed,
            )]
            for f in files:
                t = Text()
                t.append("      ")
                if "error" in f:
                    t.append(f.get("path", ""),     style=C.MUTED)
                    t.append(f"  ✗ {f['error']}",  style=C.ERR)
                else:
                    lines = len((f.get("content") or "").splitlines())
                    t.append(f.get("path", ""),      style=C.TOOL_ARG)
                    t.append(f"  {lines:,} lines",  style=C.MUTED)
                items.append(t)
            return items

        if tool in {"ListFiles", "ListFilesTool"} and isinstance(result, list):
            return [s(f"{len(result)} files", C.MUTED, elapsed)]

        if tool in {"Grep", "GrepTool"} and isinstance(result, dict):
            m = result.get("matches", 0)
            items = [s(
                f"{m} match{'es' if m != 1 else ''}",
                C.OK if m else C.MUTED,
                elapsed,
            )]
            for hit in (result.get("lines") or result.get("results") or [])[:8]:
                t = Text()
                t.append("      ")
                if isinstance(hit, dict):
                    t.append(f"{hit.get('line_number', '')}  ", style=C.MUTED)
                    t.append(
                        str(hit.get("text", hit.get("line", hit))).rstrip(),
                        style=C.TOOL_ARG,
                    )
                else:
                    t.append(str(hit).rstrip(), style=C.TOOL_ARG)
                items.append(t)
            return items

        if tool in {"Glob", "GlobTool"} and isinstance(result, dict):
            files = result.get("files") or result.get("results") or []
            count = result.get("count", 0)
            items = [s(f"{count} file{'s' if count != 1 else ''}", C.MUTED, elapsed)]
            for f in files[:6]:
                t = Text()
                t.append("      ")
                t.append(str(f), style=C.TOOL_ARG)
                items.append(t)
            if len(files) > 6:
                items.append(s(f"… {len(files) - 6} more", C.MUTED))
            return items

        if tool in {"Tree", "TreeTool"} and isinstance(result, str):
            items = []
            for line in result.splitlines()[:40]:
                t = Text()
                t.append("    ")
                t.append(line, style=C.DIM)
                items.append(t)
            return items

        if tool in {"PDF", "PDFTool"} and isinstance(result, dict):
            return [s(
                f"{result.get('pages', '?')} pages  {result.get('path', '')}",
                C.MUTED, elapsed,
            )]

        if tool in {"WebSearch", "WebSearchTool"} and isinstance(result, dict):
            count = result.get("count", 0)
            items = [s(
                f"{count} result{'s' if count != 1 else ''}",
                C.OK if count else C.MUTED,
                elapsed,
            )]
            for r in (result.get("results") or [])[:4]:
                t = Text()
                t.append("      ")
                t.append(r.get("title", "")[:60], style=C.TOOL_ARG)
                if r.get("url"):
                    t.append(f"  {r['url'][:50]}", style=C.MUTED)
                items.append(t)
            return items

        if tool in {"WebVisit", "WebVisitTool"} and isinstance(result, dict):
            lines = len((result.get("content") or "").splitlines())
            return [s(f"{lines:,} lines  {result.get('url', '')}", C.MUTED, elapsed)]

        if tool in {"FinishTask", "FinishTaskTool"}:
            if isinstance(result, dict):
                success = result.get("success", True)
                t = Text()
                t.append("    ↳ ", style=C.MUTED)
                t.append("✓ " if success else "✗ ",
                         style=C.OK if success else C.ERR)
                t.append(result.get("summary", "")[:200], style=C.DIM)
                return [t]
            return []

        if result is not None:
            items = []
            for line in str(result)[:800].splitlines():
                t = Text()
                t.append("    ")
                t.append(line, style=C.DIM)
                items.append(t)
            return items

        return []

    @staticmethod
    def approval_request(tool: str) -> list:
        t = Text()
        t.append("\n  ◈ ",       style=C.WARN)
        t.append("Allow ",       style=C.WARN)
        t.append(tool,           style="bold " + C.WARN)
        t.append("?  ",          style=C.WARN)
        t.append("y",            style="bold green")
        t.append(" / ",          style=C.MUTED)
        t.append("n",            style="bold red")
        t.append(" / ",          style=C.MUTED)
        t.append("a",            style="bold cyan")
        t.append(" (always)",    style=C.MUTED)
        return [t]

    @staticmethod
    def approval_result(granted: bool, tool: str) -> list:
        t = Text()
        if granted:
            t.append("    ✓ ",    style=C.OK)
            t.append("Allowed  ", style=C.MUTED)
        else:
            t.append("    ✗ ",   style=C.ERR)
            t.append("Denied  ", style=C.MUTED)
        t.append(tool, style=C.MUTED)
        return [t]

    @staticmethod
    def error(title: str, error: Any, prefix: str = "✗") -> list:
        header = Text()
        header.append(f"\n  {prefix} ", style=C.ERR)
        header.append(title,            style=C.ERR)
        detail = Text()
        detail.append("    ")
        detail.append(str(error)[:800], style=C.ERR)
        return [header, detail]

    @staticmethod
    def tool_error(tool: str, error: str) -> list:
        return Renderer.error(f"{_label(tool)} failed", error)

    @staticmethod
    def context_compression_error(e: Any) -> list:
        return Renderer.error("Context compression failed", e)

    @staticmethod
    def task_error(error: str) -> list:
        return Renderer.error("Task failed", error)

    @staticmethod
    def generic_error(
        source: str,
        error: Any,
        traceback_text: str | None = None,
    ) -> list:
        items = Renderer.error(source, error)
        if traceback_text:
            items.append(
                Panel(
                    Syntax(
                        traceback_text,
                        "python",
                        word_wrap=True,
                        line_numbers=True,
                        background_color="default",
                    ),
                    title="Traceback",
                    border_style="red",
                )
            )
        return items

    @staticmethod
    def context_compressed(before: int, after: int) -> list:
        t = Text()
        t.append("  ⟳ ",                  style=C.WARN)
        t.append("Context compressed  ",  style=C.DIM)
        t.append(f"{before:,}",           style=C.WARN)
        t.append(" → ",                   style=C.MUTED)
        t.append(f"{after:,}",            style=C.OK)
        t.append(" tokens",               style=C.MUTED)
        return [t]

    @staticmethod
    def task_started(prompt: str) -> list:
        t = Text()
        t.append("\n❯ ", style="bold green")
        t.append(prompt,  style=C.USER)
        return [t]

    @staticmethod
    def question_request(
        question: str,
        context: str,
        suggestions: list[str],
    ) -> list:
        items = []

        header = Text()
        header.append("\n  ? ",   style=C.QUESTION)
        header.append("Question", style=C.QUESTION)
        items.append(header)

        q = Text()
        q.append("    ")
        q.append(question, style="bold white")
        items.append(q)

        if context:
            ctx = Text()
            ctx.append("    ")
            ctx.append(context, style=C.DIM)
            items.append(ctx)

        for i, suggestion in enumerate(suggestions, 1):
            st = Text()
            st.append(f"    [{i}] ", style=C.QUESTION)
            st.append(suggestion,    style=C.SUGGEST)
            items.append(st)

        hint = Text()
        hint.append("    › ",             style=C.QUESTION)
        hint.append("type answer or number", style=C.MUTED)
        items.append(hint)
        return items

    @staticmethod
    def question_answer(answer: str) -> list:
        t = Text()
        t.append("    ↳ ", style=C.MUTED)
        t.append(answer,   style="white")
        return [t]