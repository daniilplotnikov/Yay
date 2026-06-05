from ..tool import Tool
import os
import time
from pathlib import Path
from pypdf import PdfReader
import difflib

class CreateFileTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "CreateFile"
        self.description = "Create a new file with content"

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }

        self.is_safe = False

    def execute(self, args):
        path = args["path"]
        content = args["content"]

        os.makedirs(
            os.path.dirname(path) or ".",
            exist_ok=True,
        )

        existed = os.path.exists(path)

        old_content = ""

        if existed:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old_content = f.read()
            except Exception:
                pass

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        diff = "\n".join(
            difflib.unified_diff(
                old_content.splitlines(),
                content.splitlines(),
                fromfile=f"{path} (old)",
                tofile=f"{path} (new)",
                lineterm="",
            )
        )

        return {
            "action": (
                "updated"
                if existed
                else "created"
            ),
            "path": path,
            "diff": diff,
        }

class CreateDirectoryTool(Tool):

    def __init__(self):
        super().__init__()

        self.name = "CreateDirectory"
        self.description = "Create directory"

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                }
            },
            "required": ["path"]
        }

    def execute(self, args):

        path = args["path"]

        os.makedirs(path, exist_ok=True)

        return {
            "action": "created_directory",
            "path": path,
        }

class RemoveFileTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "RemoveFile"
        self.description = "Delete one or more files"

        self.arguments = {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    }
                }
            },
            "required": ["paths"]
        }

        self.is_safe = False

    def execute(self, args):
        results = []

        for path in args["paths"]:

            if not os.path.exists(path):
                results.append({
                    "path": path,
                    "error": "File not found",
                })
                continue

            content = ""

            try:
                with open(
                    path,
                    "r",
                    encoding="utf-8",
                ) as f:
                    content = f.read()
            except Exception:
                pass

            try:
                os.remove(path)

                diff = "\n".join(
                    difflib.unified_diff(
                        content.splitlines(),
                        [],
                        fromfile=path,
                        tofile="/dev/null",
                        lineterm="",
                    )
                )

                results.append({
                    "path": path,
                    "status": "deleted",
                    "diff": diff,
                })

            except Exception as e:
                results.append({
                    "path": path,
                    "error": str(e),
                })

        return {
            "deleted": sum(
                1
                for r in results
                if r.get("status") == "deleted"
            ),
            "results": results,
        }

class TreeTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "Tree"
        self.description = (
            "Show directory tree"
        )

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "default": "."
                },
                "max_depth": {
                    "type": "integer",
                    "default": 4
                }
            }
        }

    def execute(self, args):

        root = Path(
            args.get("path", ".")
        )

        max_depth = args.get(
            "max_depth",
            4,
        )

        lines = []

        def walk(
            current: Path,
            prefix: str = "",
            depth: int = 0,
        ):
            if depth > max_depth:
                return

            try:
                entries = sorted(
                    current.iterdir(),
                    key=lambda p: (
                        not p.is_dir(),
                        p.name.lower(),
                    ),
                )
            except Exception:
                return

            for i, entry in enumerate(entries):

                last = (
                    i == len(entries) - 1
                )

                connector = (
                    "└── "
                    if last
                    else "├── "
                )

                lines.append(
                    prefix
                    + connector
                    + entry.name
                )

                if entry.is_dir():

                    walk(
                        entry,
                        prefix
                        + (
                            "    "
                            if last
                            else "│   "
                        ),
                        depth + 1,
                    )

        lines.append(root.name)

        walk(root)

        return "\n".join(lines)

class ListFilesTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "ListFiles"
        self.description = "List files in directory"

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."}
            },
            "required": []
        }

    def execute(self, args):
        path = args.get("path", ".")

        return os.listdir(path)

class SearchTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "Search"
        self.description = "Search text inside files (simple grep)"

        self.arguments = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."}
            },
            "required": ["query"]
        }

    def execute(self, args):
        query = args["query"]
        base_path = args.get("path", ".")

        results = []

        for root, _, files in os.walk(base_path):
            for file in files:
                full_path = os.path.join(root, file)

                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f):
                            if query in line:
                                results.append({
                                    "file": full_path,
                                    "line": i,
                                    "text": line.strip()
                                })
                except:
                    continue

        return results

class PatchFileTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "PatchFile"
        self.description = "Apply search/replace patches to file"

        self.is_safe = False

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                },
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "find": {
                                "type": "string"
                            },
                            "replace": {
                                "type": "string"
                            }
                        },
                        "required": [
                            "find",
                            "replace"
                        ]
                    }
                }
            },
            "required": [
                "path",
                "changes"
            ]
        }

    def execute(self, args):

        path = Path(args["path"])

        if not path.exists():
            return {
                "error": f"File not found: {path}"
            }

        content = path.read_text(
            encoding="utf-8"
        )

        original = content

        results = []

        for idx, change in enumerate(
            args["changes"],
            start=1,
        ):

            find = change["find"]
            replace = change["replace"]

            count = content.count(find)

            if count == 0:

                results.append({
                    "change": idx,
                    "status": "not_found"
                })

                continue

            content = content.replace(
                find,
                replace,
            )

            results.append({
                "change": idx,
                "status": "ok",
                "replacements": count,
            })

        if content == original:
            return {
                "status": "no_changes",
                "results": results,
            }

        path.write_text(
            content,
            encoding="utf-8"
        )

        diff = "\n".join(
            difflib.unified_diff(
                original.splitlines(),
                content.splitlines(),
                fromfile=str(path),
                tofile=str(path),
                lineterm="",
            )
        )

        return {
            "status": "patched",
            "path": str(path),
            "results": results,
            "diff": diff,
        }

class ReadFileTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "ReadFile"
        self.description = "Read a file from disk"

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }

    def execute(self, args):
        path = args["path"]

        if not os.path.exists(path):
            return {
                "error": "File not found",
                "path": path
            }

        if not os.path.isfile(path):
            return {
                "error": "Path is not a file",
                "path": path
            }

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            return {
                "path": path,
                "content": content
            }

        except Exception as e:
            return {
                "error": str(e),
                "path": path
            } 

class ReadFilesTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "ReadFiles"
        self.description = "Read multiple files from disk"

        self.arguments = {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    }
                }
            },
            "required": ["paths"]
        }

    def execute(self, args):
        results = []

        for path in args["paths"]:

            if not os.path.exists(path):
                results.append({
                    "path": path,
                    "error": "File not found"
                })
                continue

            if not os.path.isfile(path):
                results.append({
                    "path": path,
                    "error": "Path is not a file"
                })
                continue

            try:
                with open(
                    path,
                    "r",
                    encoding="utf-8"
                ) as f:
                    content = f.read()

                results.append({
                    "path": path,
                    "content": content
                })

            except Exception as e:
                results.append({
                    "path": path,
                    "error": str(e)
                })

        return {
            "count": len(results),
            "files": results
        }

class GetFileInfoTool(Tool):
    def __init__(self):
        super().__init__()
        self.name = "GetFileInfo"
        self.description = "Get metadata about a file (size, timestamps, type)"

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }

    def execute(self, args):
        path = args["path"]

        if not os.path.exists(path):
            return {
                "error": "File not found",
                "path": path
            }

        try:
            stat = os.stat(path)

            return {
                "path": path,
                "size_bytes": stat.st_size,
                "is_file": os.path.isfile(path),
                "is_dir": os.path.isdir(path),
                "created_at": time.ctime(stat.st_ctime),
                "modified_at": time.ctime(stat.st_mtime),
                "accessed_at": time.ctime(stat.st_atime)
            }

        except Exception as e:
            return {
                "error": str(e),
                "path": path
            }

class GrepTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "Grep"
        self.description = "Search text inside files"

        self.arguments = {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string"
                },
                "path": {
                    "type": "string",
                    "default": "."
                }
            },
            "required": ["pattern"]
        }

    def execute(self, args):

        pattern = args["pattern"]
        root = Path(
            args.get("path", ".")
        )

        results = []

        for file in root.rglob("*"):

            if not file.is_file():
                continue

            try:

                text = file.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )

            except Exception:
                continue

            for lineno, line in enumerate(
                text.splitlines(),
                start=1,
            ):

                if pattern in line:

                    results.append({
                        "file": str(file),
                        "line": lineno,
                        "text": line.strip(),
                    })

        return {
            "pattern": pattern,
            "matches": len(results),
            "results": results[:500],
        }

class GlobTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "Glob"
        self.description = (
            "Find files by glob pattern"
        )

        self.arguments = {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string"
                },
                "path": {
                    "type": "string",
                    "default": "."
                }
            },
            "required": ["pattern"]
        }

    def execute(self, args):

        pattern = args["pattern"]

        root = Path(
            args.get("path", ".")
        )

        files = []

        for file in root.rglob(pattern):

            if file.is_file():

                files.append(
                    str(file)
                )

        return {
            "pattern": pattern,
            "count": len(files),
            "files": files[:1000],
        }

class PDFTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "PDF"
        self.description = "Read text from PDF file"

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                },
                "pages": {
                    "type": "array",
                    "items": {
                        "type": "integer"
                    }
                }
            },
            "required": ["path"]
        }

    def execute(self, args):

        if PdfReader is None:
            return {
                "error": (
                    "pypdf is not installed. "
                    "Run: pip install pypdf"
                )
            }

        path = Path(args["path"])

        if not path.exists():
            return {
                "error": "File not found",
                "path": str(path)
            }

        try:

            reader = PdfReader(str(path))

            page_filter = args.get("pages")

            pages = []
            text_parts = []

            for idx, page in enumerate(reader.pages):

                page_num = idx + 1

                if (
                    page_filter is not None
                    and page_num not in page_filter
                ):
                    continue

                text = page.extract_text() or ""

                pages.append(page_num)
                text_parts.append(text)

            return {
                "path": str(path),
                "pages": pages,
                "page_count": len(reader.pages),
                "text": "\n\n".join(text_parts)
            }

        except Exception as e:
            return {
                "error": str(e),
                "path": str(path)
            }