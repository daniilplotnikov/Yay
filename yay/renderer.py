import difflib
from typing import Any
from rich.text import Text
from rich.syntax import Syntax


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


def _token_color(pct: float) -> str:
    return C.TOKENS_OK if pct < 50 else C.TOKENS_WARN if pct < 80 else C.TOKENS_HOT

_TOOL_ICON: dict[str, str] = {
    "CMDTool":              "⬡",
    "BashTool":             "⬡",
    "Shell":                "⬡",
    "ShellTool":            "⬡",
    "ReadFileTool":         "⊙",
    "ReadFile":             "⊙",
    "ReadFilesTool":        "⊙",
    "ReadFiles":            "⊙",
    "WriteFileTool":        "◎",
    "WriteFile":            "◎",
    "CreateFileTool":       "◎",
    "CreateFile":           "◎",
    "PatchFileTool":        "◈",
    "PatchFile":            "◈",
    "RemoveFileTool":       "⊗",
    "RemoveFile":           "⊗",
    "CreateDirectoryTool":  "⊞",
    "CreateDirectory":      "⊞",
    "GrepTool":             "⊛",
    "Grep":                 "⊛",
    "GlobTool":             "⊡",
    "Glob":                 "⊡",
    "ListFilesTool":        "⊞",
    "ListFiles":            "⊞",
    "TreeTool":             "⊟",
    "Tree":                 "⊟",
    "PDFTool":              "⊙",
    "PDF":                  "⊙",
    "ThinkTool":            "⟳",
    "Think":                "⟳",
    "PlanTool":             "☰",
    "Plan":                 "☰",
    "FinishTaskTool":       "✓",
    "FinishTask":           "✓",
    "QuestionTool":         "?",
    "Question":             "?",
    "WebSearchTool":        "⊕",
    "WebSearch":            "⊕",
    "WebVisitTool":         "⊕",
    "WebVisit":             "⊕",
    "default":              "◆",
}

_TOOL_LABEL: dict[str, str] = {
    "CMDTool":              "Bash",
    "BashTool":             "Bash",
    "Shell":                "Shell",
    "ShellTool":            "Shell",
    "ReadFileTool":         "Read",
    "ReadFile":             "Read",
    "ReadFilesTool":        "Read",
    "ReadFiles":            "Read",
    "WriteFileTool":        "Write",
    "WriteFile":            "Write",
    "CreateFileTool":       "Write",
    "CreateFile":           "Write",
    "PatchFileTool":        "Edit",
    "PatchFile":            "Edit",
    "RemoveFileTool":       "Delete",
    "RemoveFile":           "Delete",
    "CreateDirectoryTool":  "Mkdir",
    "CreateDirectory":      "Mkdir",
    "GrepTool":             "Search",
    "Grep":                 "Search",
    "GlobTool":             "Glob",
    "Glob":                 "Glob",
    "ListFilesTool":        "List",
    "ListFiles":            "List",
    "TreeTool":             "Tree",
    "Tree":                 "Tree",
    "PDFTool":              "PDF",
    "PDF":                  "PDF",
    "ThinkTool":            "Think",
    "Think":                "Think",
    "PlanTool":             "Plan",
    "Plan":                 "Plan",
    "FinishTaskTool":       "Finish",
    "FinishTask":           "Finish",
    "QuestionTool":         "Question",
    "Question":             "Question",
    "WebSearchTool":        "Web",
    "WebSearch":            "Web",
    "WebVisitTool":         "Visit",
    "WebVisit":             "Visit",
}

def _icon(tool: str) -> str:
    return _TOOL_ICON.get(tool, _TOOL_ICON["default"])

def _label(tool: str) -> str:
    return _TOOL_LABEL.get(tool, tool.replace("Tool", ""))

class Renderer:
    @staticmethod
    def user_prompt(prompt: str) -> list:
        t = Text()
        t.append("\n❯ ", style="bold green")
        t.append(prompt, style=C.USER)
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

        if tool in {"Shell", "ShellTool", "CMDTool", "BashTool"}:
            cmd    = args.get("cmd", args.get("command", ""))
            bg     = args.get("background", False)
            action = args.get("action")

            header = Text()
            header.append(f"\n  {icon} ", style=C.TOOL_ICON)
            header.append(label, style=C.TOOL_NAME)

            if action:
                header.append(f"  [{action}]", style=C.TOOL_META)
                if args.get("pid"):
                    header.append(f"  pid={args['pid']}", style=C.TOOL_META)
            elif cmd:
                header.append("  ", style="")
                header.append(cmd[:120], style=C.TOOL_ARG)
                if bg:
                    header.append("  &", style=C.MUTED)
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

        if tool in {"Plan", "PlanTool"}:
            action = args.get("action", "")
            header = Text()
            header.append(f"\n  {icon} ", style=C.TOOL_ICON)
            header.append(label, style=C.TOOL_NAME)
            header.append(f"  {action}", style=C.TOOL_META)
            items: list = [header]
            if action == "create":
                for i, step in enumerate(args.get("steps", []), 1):
                    t = Text()
                    t.append(f"    {i}. ", style=C.MUTED)
                    t.append(step, style=C.TOOL_ARG)
                    items.append(t)
            elif action == "complete":
                idx = args.get("index", "?")
                t = Text()
                t.append(f"    step {idx}", style=C.TOOL_META)
                items.append(t)
            return items

        if tool in {"Question", "QuestionTool"}:
            question    = args.get("question", "")
            context     = args.get("context", "")
            suggestions = args.get("suggestions", [])

            items: list = []
            header = Text()
            header.append(f"\n  {icon} ", style=C.QUESTION)
            header.append(label, style=C.QUESTION)
            items.append(header)

            q_text = Text()
            q_text.append("    ", style="")
            q_text.append(question, style="bold white")
            items.append(q_text)

            if context:
                ctx_text = Text()
                ctx_text.append("    ", style="")
                ctx_text.append(context, style=C.DIM)
                items.append(ctx_text)

            if suggestions:
                hint = Text()
                hint.append("    Suggestions: ", style=C.MUTED)
                hint.append(
                    "  |  ".join(f"[{i+1}] {s}" for i, s in enumerate(suggestions)),
                    style=C.SUGGEST,
                )
                items.append(hint)

            prompt = Text()
            prompt.append("    › ", style=C.QUESTION)
            prompt.append("type your answer or suggestion number", style=C.MUTED)
            items.append(prompt)
            return items

        if tool in {"ReadFiles", "ReadFilesTool"}:
            paths = args.get("paths", [])
            t = Text()
            t.append(f"\n  {icon} ", style=C.TOOL_ICON)
            t.append(label, style=C.TOOL_NAME)
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
            pat     = args.get("pattern", "")
            in_path = args.get("path", "")
            path    = f"{pat}"
            extra   = f"  in {in_path}" if in_path else ""
        elif tool in {"ReadFile", "ReadFileTool"}:
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
    def tool_result(tool: str, result: Any) -> list:  

        def _status(msg: str, style: str = C.MUTED) -> Text:
            t = Text()
            t.append("    ↳ ", style=C.MUTED)
            t.append(msg, style=style)
            return t

        if tool in {"Think", "ThinkTool"}:
            if not isinstance(result, str) or not result.strip():
                return []
            out = [Text("")]
            for line in result.strip().splitlines():
                t = Text()
                t.append("    ", style="")
                t.append(line, style=C.DIM)
                out.append(t)
            return out

        if tool in {"Shell", "ShellTool", "CMDTool", "BashTool"}:
            if not isinstance(result, dict):
                return [_status(str(result), C.MUTED)]

            if result.get("status") == "running" and "pid" in result:
                return [_status(f"Started  pid={result['pid']}", C.OK)]
            if result.get("status") == "terminated":
                return [_status(f"Terminated  pid={result.get('pid', '?')}", C.WARN)]
            if result.get("active_pids") is not None:
                pids = ", ".join(str(p) for p in result["active_pids"])
                return [_status(f"Running: {pids or 'none'}", C.MUTED)]

            stdout = (result.get("stdout") or "").strip()
            stderr = (result.get("stderr") or "").strip()
            code   = result.get("code", 0)
            ok     = code == 0

            items: list = []
            body = "\n".join(filter(None, [stdout, stderr]))
            if body:
                lines  = body.splitlines()
                shown  = lines[:60]
                hidden = len(lines) - 60
                body_text = "\n".join(shown)
                if hidden > 0:
                    body_text += f"\n  … {hidden} more lines"
                items.append(Syntax(body_text, "bash", word_wrap=True,
                                    background_color="default", padding=(0, 4)))
            items.append(_status("Done" if ok else f"Exit {code}", C.OK if ok else C.ERR))
            return items

        if tool in {"Plan", "PlanTool"}:
            if not isinstance(result, dict):
                return [_status(str(result), C.MUTED)]
            status = result.get("status", "")
            plan   = result.get("plan", [])
            items: list = []
            if status == "created":
                items.append(_status(f"Plan created  ({len(plan)} steps)", C.OK))
            elif status == "completed":
                step = result.get("step", {})
                items.append(_status(f"✓ {step.get('task', '')}", C.OK))
            elif "error" in result:
                items.append(_status(result["error"], C.ERR))
            else:
                for step in plan:
                    done = step.get("completed", False)
                    t = Text()
                    t.append("      ", style="")
                    t.append("✓ " if done else "○ ", style=C.OK if done else C.MUTED)
                    t.append(step.get("task", ""), style=C.DIM if done else C.TOOL_ARG)
                    items.append(t)
            return items

        if tool in {"Question", "QuestionTool"}:
            return []

        if tool in {"CreateFile", "CreateFileTool", "WriteFile", "WriteFileTool",
                    "PatchFile", "PatchFileTool"}:
            if isinstance(result, dict) and "diff" in result:
                diff_text = result["diff"]
                items: list = []
                if diff_text.strip():
                    items.append(Syntax(diff_text, "diff", word_wrap=True,
                                        background_color="default", padding=(0, 4)))
                action = result.get("action", "written")
                items.append(_status(f"{action.capitalize()}  {result.get('path','')}", C.OK))
                return items
            path = result.get("path", "") if isinstance(result, dict) else str(result)
            return [_status(f"Written  {path}", C.OK)]

        if tool in {"RemoveFile", "RemoveFileTool"}:
            if isinstance(result, dict) and "results" in result:
                items: list = []
                for r in result["results"]:
                    p = r.get("path", "")
                    if r.get("status") == "deleted":
                        items.append(_status(f"Deleted  {p}", C.ERR))
                    elif "error" in r:
                        items.append(_status(f"Error  {p}  {r['error']}", C.ERR))
                return items
            return [_status("Deleted", C.ERR)]

        if tool in {"CreateDirectory", "CreateDirectoryTool"}:
            path = (result.get("path", "") if isinstance(result, dict)
                    else str(result).replace("Directory created: ", ""))
            return [_status(f"Created  {path}", C.OK)]

        if tool in {"ReadFile", "ReadFileTool"} and isinstance(result, dict):
            if "error" in result:
                return [_status(f"Error  {result['error']}", C.ERR)]
            lines = len((result.get("content") or "").splitlines())
            return [_status(f"{lines:,} lines  {result.get('path', '')}", C.MUTED)]

        if tool in {"ReadFiles", "ReadFilesTool"} and isinstance(result, dict):
            files     = result.get("files", [])
            ok_files  = [f for f in files if "content" in f and "error" not in f]
            err_files = [f for f in files if "error" in f]
            summary_style = C.OK if not err_files else C.WARN
            summary_parts = [f"{len(ok_files)} read"]
            if err_files:
                summary_parts.append(f"{len(err_files)} error{'s' if len(err_files) > 1 else ''}")
            items: list = [_status("  ".join(summary_parts), summary_style)]
            for f in files:
                t = Text()
                t.append("      ")
                path = f.get("path", "")
                if "error" in f:
                    t.append(path, style=C.MUTED)
                    t.append(f"  ✗ {f['error']}", style=C.ERR)
                else:
                    lines = len((f.get("content") or "").splitlines())
                    t.append(path, style=C.TOOL_ARG)
                    t.append(f"  {lines:,} lines", style=C.MUTED)
                items.append(t)
            return items

        if tool in {"ListFiles", "ListFilesTool"} and isinstance(result, list):
            return [_status(f"{len(result)} files", C.MUTED)]

        if tool in {"Grep", "GrepTool"} and isinstance(result, dict):
            m = result.get("matches", 0)
            items: list = [_status(f"{m} match{'es' if m != 1 else ''}", C.OK if m else C.MUTED)]
            hits = result.get("lines") or result.get("results") or []
            for hit in hits[:8]:
                t = Text()
                t.append("      ")
                if isinstance(hit, dict):
                    ln  = hit.get("line_number", hit.get("line", ""))
                    txt = hit.get("text", hit.get("line", str(hit)))
                    t.append(f"{ln}  ", style=C.MUTED)
                    t.append(str(txt).rstrip(), style=C.TOOL_ARG)
                else:
                    t.append(str(hit).rstrip(), style=C.TOOL_ARG)
                items.append(t)
            if len(hits) > 8:
                items.append(_status(f"… {len(hits) - 8} more", C.MUTED))
            return items

        if tool in {"Glob", "GlobTool"} and isinstance(result, dict):
            c     = result.get("count", 0)
            files = result.get("files") or result.get("results") or []
            items: list = [_status(f"{c} file{'s' if c != 1 else ''}", C.MUTED)]
            for f in files[:6]:
                t = Text()
                t.append("      ")
                t.append(str(f), style=C.TOOL_ARG)
                items.append(t)
            if len(files) > 6:
                items.append(_status(f"… {len(files) - 6} more", C.MUTED))
            return items

        if tool in {"Tree", "TreeTool"} and isinstance(result, str):
            items: list = []
            for line in result.splitlines()[:40]:
                t = Text()
                t.append("    ")
                t.append(line, style=C.DIM)
                items.append(t)
            return items

        if tool in {"PDF", "PDFTool"} and isinstance(result, dict):
            pages = result.get("pages", "?")
            return [_status(f"{pages} pages  {result.get('path', '')}", C.MUTED)]

        if tool in {"WebSearch", "WebSearchTool"} and isinstance(result, dict):
            count = result.get("count", 0)
            items: list = [_status(f"{count} result{'s' if count != 1 else ''}", C.OK if count else C.MUTED)]
            for r in (result.get("results") or [])[:4]:
                t = Text()
                t.append("      ")
                t.append(r.get("title", "")[:60], style=C.TOOL_ARG)
                url = r.get("url", "")
                if url:
                    t.append(f"  {url[:50]}", style=C.MUTED)
                items.append(t)
            return items

        if tool in {"WebVisit", "WebVisitTool"} and isinstance(result, dict):
            content = result.get("content", "")
            lines   = len(content.splitlines()) if content else 0
            return [_status(f"{lines:,} lines  {result.get('url', '')}", C.MUTED)]

        if tool in {"FinishTask", "FinishTaskTool"}:
            if isinstance(result, dict):
                summary = result.get("summary", "")
                success = result.get("success", True)
                t = Text()
                t.append("    ↳ ", style=C.MUTED)
                t.append("✓ " if success else "✗ ", style=C.OK if success else C.ERR)
                t.append(summary[:200], style=C.DIM)
                return [t]
            return []

        if result is not None:
            items: list = []
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
        detail.append("    ")
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
            t.append("    ")
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

    @staticmethod
    def question_request(question: str, context: str, suggestions: list[str]) -> list:
        items: list = []
        header = Text()
        header.append("\n  ? ", style=C.QUESTION)
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

        if suggestions:
            for i, s in enumerate(suggestions, 1):
                st = Text()
                st.append(f"    [{i}] ", style=C.QUESTION)
                st.append(s, style=C.SUGGEST)
                items.append(st)

        hint = Text()
        hint.append("    › ", style=C.QUESTION)
        hint.append("type answer or number", style=C.MUTED)
        items.append(hint)
        return items

    @staticmethod
    def question_answer(answer: str) -> list:
        t = Text()
        t.append("    ↳ ", style=C.MUTED)
        t.append(answer, style="white")
        return [t]
