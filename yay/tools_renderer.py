from rich.panel import Panel
from rich.syntax import Syntax
from rich.console import Console
import difflib

console = Console()

def render_tool_result(tool_name: str, result):
    if tool_name == "ThinkTool":
        thinking_text = result if isinstance(result, str) else "● Thinking..."
        console.print(
            Panel(thinking_text, title="[yellow]Think[/yellow]", border_style="yellow")
        )
        return

    if tool_name in {"CreateFileTool", "PatchFileTool", "RemoveFileTool"}:
        if isinstance(result, dict):
            if "diff" in result:
                console.print(Syntax(result["diff"], "diff", word_wrap=True))
            else:
                action_map = {
                    "CreateFileTool": "[green]● Created file[/green]",
                    "PatchFileTool": "[cyan]● Patched file[/cyan]",
                    "RemoveFileTool": "[red]● Deleted file[/red]",
                }
                console.print(action_map.get(tool_name, tool_name))

            if tool_name == "RemoveFileTool" and "results" in result:
                for r in result["results"]:
                    path = r.get("path")
                    if "diff" in r:
                        console.print(Syntax(r["diff"], "diff", word_wrap=True))
                    elif r.get("status") == "deleted":
                        console.print(f"[red]● Deleted[/red] {path}")
                    elif "error" in r:
                        console.print(f"[red]✗ Error deleting[/red] {path}: {r['error']}")
        return

    if tool_name == "CreateDirectoryTool":
        path = result.replace("Directory created: ", "") if isinstance(result, str) else ""
        console.print(f"[blue]● Created directory[/blue] {path}")
        return

    if tool_name == "ReadFileTool" and isinstance(result, dict):
        path = result.get("path", "")
        content = result.get("content", "")
        lines = len(content.splitlines())
        console.print(f"[cyan]● Read[/cyan] {path} ({lines} lines)")
        return

    if tool_name == "ListFilesTool" and isinstance(result, list):
        console.print(f"[cyan]● Listed[/cyan] {len(result)} files")
        return

    if tool_name == "GrepTool" and isinstance(result, dict):
        console.print(f"[cyan]● Search[/cyan] {result['matches']} matches")
        return

    if tool_name == "GlobTool" and isinstance(result, dict):
        console.print(f"[cyan]● Found[/cyan] {result['count']} files")
        return

    if tool_name == "CMDTool" and isinstance(result, dict):
        stdout = result.get("stdout", "").strip()
        stderr = result.get("stderr", "").strip()
        code = result.get("code", 0)
        title = "Command ✓" if code == 0 else "Command ✗"
        body = "\n\n".join(filter(None, [stdout, stderr])) or "(no output)"
        console.print(Panel(body, title=title, border_style="green" if code == 0 else "red"))
        return

    if tool_name == "PDFTool" and isinstance(result, dict):
        console.print(f"[cyan]● PDF[/cyan] {result.get('path')}")
        return

    if tool_name == "TreeTool" and isinstance(result, str):
        console.print(Panel(result, title="[cyan]Directory Tree[/cyan]"))
        return

    console.print(Panel(str(result), title=tool_name))


def render_tool_call(tool_name: str, args):
    if tool_name in {"ThinkTool", "FinishTaskTool"}:
        return

    old_text = args.get("old")
    new_text = args.get("new")

    if old_text is not None and new_text is not None:
        diff = "\n".join(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile="old",
                tofile="new",
                lineterm=""
            )
        )
        console.print(
            Panel(
                Syntax(diff, "diff", line_numbers=False, word_wrap=True),
                title=f"[cyan]Diff[/cyan] ({tool_name})",
                border_style="magenta"
            )
        )
        return

    if tool_name == "CMDTool":
        cmd = args.get("cmd", "")
        console.print(
            Panel(
                Syntax(cmd, "bash", word_wrap=True),
                title="Command",
                border_style="cyan",
            )
        )
        return

    if tool_name == "GrepTool":
        pattern = args.get("pattern", "")
        console.print(f"[cyan]● Search[/cyan] {pattern}")
        return

    if tool_name == "GlobTool":
        pattern = args.get("pattern", "")
        console.print(f"[cyan]● Find[/cyan] {pattern}")
        return

    if tool_name == "PDFTool":
        path = args.get("path", "")
        console.print(f"[cyan]● PDF[/cyan] {path}")
        return

    if tool_name == "TreeTool":
        path = args.get("path", ".")
        console.print(f"[cyan]● Tree[/cyan] {path}")
        return

    console.print(Panel(str(args), title=tool_name))