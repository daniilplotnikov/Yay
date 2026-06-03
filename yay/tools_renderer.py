import difflib


def render_tool_result(tool_name: str, result):

    if tool_name == "ThinkTool":
        return (
            result
            if isinstance(result, str)
            else "Thinking..."
        )

    if tool_name in {
        "CreateFileTool",
        "PatchFileTool",
        "RemoveFileTool",
    }:

        if isinstance(result, dict):

            if "diff" in result:
                return (
                    f"[DIFF]\n"
                    f"{result['diff']}"
                )

            action_map = {
                "CreateFileTool": "Created file",
                "PatchFileTool": "Patched file",
                "RemoveFileTool": "Deleted file",
            }

            text = [
                action_map.get(
                    tool_name,
                    tool_name,
                )
            ]

            if (
                tool_name == "RemoveFileTool"
                and "results" in result
            ):
                for r in result["results"]:

                    path = r.get("path", "")

                    if "diff" in r:
                        text.append(
                            f"\n[DIFF]\n{r['diff']}"
                        )

                    elif r.get("status") == "deleted":
                        text.append(
                            f"Deleted {path}"
                        )

                    elif "error" in r:
                        text.append(
                            f"Error deleting "
                            f"{path}: {r['error']}"
                        )

            return "\n".join(text)

        return str(result)

    if tool_name == "CreateDirectoryTool":

        if isinstance(result, str):

            path = result.replace(
                "Directory created: ",
                "",
            )

            return f"Created directory {path}"

        return str(result)

    if (
        tool_name == "ReadFileTool"
        and isinstance(result, dict)
    ):
        path = result.get("path", "")
        content = result.get("content", "")

        return (
            f"Read {path} "
            f"({len(content.splitlines())} lines)"
        )

    if (
        tool_name == "ListFilesTool"
        and isinstance(result, list)
    ):
        return (
            f"Listed {len(result)} files"
        )

    if (
        tool_name == "GrepTool"
        and isinstance(result, dict)
    ):
        return (
            f"Search: "
            f"{result.get('matches', 0)} matches"
        )

    if (
        tool_name == "GlobTool"
        and isinstance(result, dict)
    ):
        return (
            f"Found "
            f"{result.get('count', 0)} files"
        )

    if (
        tool_name == "CMDTool"
        and isinstance(result, dict)
    ):

        stdout = result.get(
            "stdout",
            "",
        ).strip()

        stderr = result.get(
            "stderr",
            "",
        ).strip()

        code = result.get(
            "code",
            0,
        )

        output = (
            "\n\n".join(
                filter(
                    None,
                    [stdout, stderr],
                )
            )
            or "(no output)"
        )

        return (
            f"[COMMAND "
            f"{'OK' if code == 0 else 'FAILED'}]\n"
            f"{output}"
        )

    if (
        tool_name == "PDFTool"
        and isinstance(result, dict)
    ):
        return (
            f"PDF: "
            f"{result.get('path', '')}"
        )

    if (
        tool_name == "TreeTool"
        and isinstance(result, str)
    ):
        return (
            f"[DIRECTORY TREE]\n"
            f"{result}"
        )

    return (
        f"[{tool_name}]\n"
        f"{result}"
    )


def render_tool_call(
    tool_name: str,
    args,
):

    if tool_name in {
        "ThinkTool",
        "FinishTaskTool",
    }:
        return None

    old_text = args.get("old")
    new_text = args.get("new")

    if (
        old_text is not None
        and new_text is not None
    ):
        diff = "\n".join(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile="old",
                tofile="new",
                lineterm="",
            )
        )

        return (
            f"[DIFF] {tool_name}\n"
            f"{diff}"
        )

    if tool_name == "CMDTool":

        return (
            "[COMMAND]\n"
            f"{args.get('cmd', '')}"
        )

    if tool_name == "GrepTool":

        return (
            "Search pattern: "
            f"{args.get('pattern', '')}"
        )

    if tool_name == "GlobTool":

        return (
            "Find pattern: "
            f"{args.get('pattern', '')}"
        )

    if tool_name == "PDFTool":

        return (
            "PDF: "
            f"{args.get('path', '')}"
        )

    if tool_name == "TreeTool":

        return (
            "Tree: "
            f"{args.get('path', '.')}"
        )

    return (
        f"[{tool_name}]\n"
        f"{args}"
    )