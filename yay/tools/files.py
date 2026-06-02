from ..tool import Tool
import os
import time

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
                "path": {"type": "string"},
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "find": {"type": "string"},
                            "replace": {"type": "string"}
                        },
                        "required": ["find", "replace"]
                    }
                }
            },
            "required": ["path", "changes"]
        }

    def execute(self, args):
        path = args["path"]
        changes = args["changes"]

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        for c in changes:
            content = content.replace(c["find"], c["replace"])

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Patched file: {path}"

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