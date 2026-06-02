from ..tool import Tool
import os
import time
from pathlib import Path

class CreateFileTool(Tool):
    def __init__(self):
        super().__init__()
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

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"File created: {path}"

class RemoveFileTool(Tool):
    def __init__(self):
        super().__init__()
        self.description = "Delete a file"

        self.arguments = {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }

        self.is_safe = False

    def execute(self, args):
        path = args["path"]

        if os.path.exists(path):
            os.remove(path)
            return f"Deleted: {path}"

        return f"File not found: {path}"

class ListFilesTool(Tool):
    def __init__(self):
        super().__init__()
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

        return {
            "status": "patched",
            "path": str(path),
            "results": results,
        }

class ReadFileTool(Tool):
    def __init__(self):
        super().__init__()
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

class GetFileInfoTool(Tool):
    def __init__(self):
        super().__init__()
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