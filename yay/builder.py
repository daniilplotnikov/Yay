from .agent import Agent
from .provider import NonSelectedProvider
from .providers import OpenAICompatibleProvider
from .workspace import Context, load_workspace
from .config import load_config, save_config
from .tools.mcp import MCPClient
from .tools import (
    CMDTool,
    FinishTaskTool,
    CreateFileTool,
    RemoveFileTool,
    SearchTool,
    PatchFileTool,
    ListFilesTool,
    ReadFileTool,
    PDFTool,
    GetFileInfoTool,
    GrepTool,
    GlobTool,
    ThinkTool,
    CreateDirectoryTool,
    TreeTool
)

from rich.console import Console
import os

console = Console()

def get_provider_api_key(cfg, provider_name):
    if provider_name == "openai":
        return (
            cfg.get("openai_api_key")
            or os.getenv("OPENAI_API_KEY", "")
        )

    if provider_name == "openrouter":
        return (
            cfg.get("openrouter_api_key")
            or os.getenv("OPENROUTER_API_KEY", "")
        )

    return (
        cfg.get("api_key")
        or os.getenv("API_KEY", "dummy")
    )


def build_agent():
    tools = [
        CMDTool(),
        FinishTaskTool(),
        CreateFileTool(),
        RemoveFileTool(),
        SearchTool(),
        PatchFileTool(),
        ListFilesTool(),
        ReadFileTool(),
        PDFTool(),
        GetFileInfoTool(),
        GrepTool(),
        GlobTool(),
        ThinkTool(),
        CreateDirectoryTool(),
        TreeTool(),
    ]

    cfg = load_config()

    provider_name = cfg.get("provider")

    for server_url in cfg.get("mcp_servers", []):
        try:
            client = MCPClient(server_url)

            mcp_tools = client.fetch_tools()

            tools.extend(mcp_tools)

            console.print(
                f"[green]Loaded {len(mcp_tools)} MCP tools from {server_url}[/green]"
            )

        except Exception as e:
            console.print(
                f"[red]Failed to load MCP server {server_url}: {e}[/red]"
            )

    if not provider_name:
        provider = NonSelectedProvider()

    if provider_name == "openrouter":
        api_key = get_provider_api_key(cfg, "openrouter")
        if not api_key:
            provider = NonSelectedProvider()
        else:
            provider = OpenAICompatibleProvider(
                api_key=api_key,
                model=cfg.get("model", ""),
                base_url="https://openrouter.ai/api/v1",
                tools=tools,
            )

    elif provider_name == "openai":
        api_key = get_provider_api_key(cfg, "openai")
        if not api_key:
            provider = NonSelectedProvider()
        else:
            provider = OpenAICompatibleProvider(
                api_key=api_key,
                model=cfg.get("model", ""),
                base_url="https://api.openai.com/v1",
                tools=tools,
            )

    else:
        api_key = get_provider_api_key(cfg, provider_name)
        if not api_key or not cfg.get("base_url"):
            provider = NonSelectedProvider()
        else:
            provider = OpenAICompatibleProvider(
                api_key=api_key,
                model=cfg.get("model", ""),
                base_url=cfg.get("base_url"),
                tools=tools,
            )

    try:
        models = provider.get_models()
        if (
            isinstance(models, list)
            and models
        ):
            if not cfg["model"]:
                console.print(
                    "\n[cyan]Select model:[/cyan]"
                )
                for idx, model in enumerate(
                    models,
                    start=1,
                ):
                    console.print(
                        f"{idx}. {model}"
                    )
                while True:
                    try:
                        choice = int(
                            input(
                                "\nModel number: "
                            )
                        )
                        if (
                            1 <= choice <= len(models)
                        ):
                            break
                    except Exception:
                        pass
                provider.model = models[
                    choice - 1
                ]
                cfg["model"] = (
                    provider.model
                )
                save_config(cfg)
            else:
                provider.model = cfg["model"]

    except Exception:
        pass

    agent = Agent(
        provider=provider,
        context=Context(provider=provider),
        tools=tools,
        approve_mode="safe",
    )

    load_workspace(agent)

    return agent