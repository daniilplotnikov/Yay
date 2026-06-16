from .events import EventBus
from .llm import Context
from .managers import ToolsManager
from .provider import Provider
from .sysprompt import SystemPromptBuilder


async def build_agent(
    *,
    cfg: dict,
    bus: EventBus,
    tools_manager: ToolsManager,
    provider: Provider,
    workspace_loader=None,
    mcp_manager=None,
):
    from .agent import Agent

    if mcp_manager is not None:
        await mcp_manager.fetch_all()

    configured_model = cfg.get("model", "")
    if configured_model:
        try:
            provider.model = configured_model
        except Exception:
            pass
    else:
        try:
            models = provider.get_models()
            if models:
                provider.model = models[0]
        except Exception:
            pass

    ctx_length = cfg.get("context_length")
    if ctx_length:
        try:
            provider.context_length = int(ctx_length)
        except Exception:
            pass

    agent = Agent(
        bus=bus,
        provider=provider,
        context=Context(
            provider=provider,
            system_prompt=SystemPromptBuilder().build(),
            bus=bus,
        ),
        tools_manager=tools_manager,
        approve_mode=cfg.get("approve_mode", "safe"),
    )

    if workspace_loader is not None:
        await workspace_loader(agent)

    return agent