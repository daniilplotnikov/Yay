import os
from rich.console import Console
from .agent import Agent
from .provider import NonSelectedProvider
from .workspace import Context, load_workspace
from .sysprompt import SystemPromptBuilder
from .config import load_config
from .mcp import MCPClient
from .managers import ToolsManager, ProviderManager

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
        or os.getenv("API_KEY", "")
    )


def build_agent(tools_manager: ToolsManager, providers_manager: ProviderManager):

    cfg = load_config()

    for server_url in cfg.get(
        "mcp_servers",
        [],
    ):
        try:
            client = MCPClient(server_url)
            mcp_tools = client.fetch_tools()
            tools_manager.register_many(mcp_tools)
        except Exception as e:
            continue

    provider_name = (
        cfg.get("provider")
        or ""
    ).lower()

    provider = NonSelectedProvider()

    provider_cls = next(
        (
            cls
            for cls in providers_manager.get_providers().values()
            if getattr(
                cls,
                "name",
                "",
            ).lower()
            == provider_name
        ),
        None,
    )

    if provider_cls:
        try:
            provider = provider_cls(
                api_key=get_provider_api_key(
                    cfg,
                    provider_name,
                ),
                model=cfg.get(
                    "model",
                    "",
                ),
                base_url=cfg.get(
                    "base_url",
                    getattr(
                        provider_cls,
                        "default_base_url",
                        "",
                    ),
                ),
                tools_manager=tools_manager,
            )

        except Exception as e:
            provider = (
                NonSelectedProvider()
            )

    try:
        models = provider.get_models()
        if (
            isinstance(models, list)
            and models
        ):
            provider.model = (
                cfg.get("model")
                or models[0]
            )

    except Exception:
        pass

    agent = Agent(
        provider=provider,
        context=Context(
            provider=provider,
            system_prompt=SystemPromptBuilder().build()
        ),
        tools_manager=tools_manager,
        approve_mode="safe"
    )

    load_workspace(agent)

    return agent