import requests
from ..tool import Tool

class MCPToolAdapter(Tool):
    def __init__(self, name, description, arguments, is_safe=True):
        super().__init__()
        self.name = name
        self.description = description
        self.arguments = arguments
        self.is_safe = is_safe

    def execute(self, args):
        url = f"{self.mcp_base_url}/tool/{self.name}/execute"
        try:
            response = requests.post(
                url,
                json=args,
                timeout=15
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "tool": self.name}


class MCPClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.tools = []

    def fetch_tools(self):
        try:
            resp = requests.get(f"{self.base_url}/tools", timeout=15)
            resp.raise_for_status()
            tool_list = resp.json()  
        except Exception as e:
            raise RuntimeError(f"Failed to fetch tools from MCP: {e}")

        self.tools = []
        for t in tool_list:
            name = t.get("name")
            description = t.get("description", "")
            arguments = t.get("arguments", {"type": "object", "properties": {}})
            is_safe = t.get("is_safe", True)

            adapter = MCPToolAdapter(
                name=name,
                description=description,
                arguments=arguments,
                is_safe=is_safe
            )

            adapter.mcp_base_url = self.base_url
            self.tools.append(adapter)

        return self.tools

class MCPManager:
    def __init__(self):
        self.servers = []

    def add(self, url):
        self.servers.append({
            "url": url,
            "enabled": True
        })

    def remove(self, index):
        del self.servers[index]

    def enable(self, index):
        self.servers[index]["enabled"] = True

    def disable(self, index):
        self.servers[index]["enabled"] = False