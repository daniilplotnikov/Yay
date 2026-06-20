from .events import EventBus
from .llm import Context
from .tools import ToolsManager, ToolExecutor
from .provider import Provider
from .sysprompt import SystemPromptBuilder


async def build_agent(
    *,
    bus: EventBus,
    tools_manager: ToolsManager,
    provider: Provider,
    model: str | None = None,
    context_length: int | None = None,
    approve_mode: str = "safe",
    workspace_loader=None,
    mcp_manager=None,
):
    from .agent import Agent

    if mcp_manager is not None:
        await mcp_manager.fetch_all()

    if model:
        try:
            provider.model = model
        except Exception:
            pass
    else:
        try:
            models = await provider.get_models()
            if models:
                provider.model = models[0]
        except Exception:
            pass

    if context_length is not None:
        try:
            provider.context_length = context_length
        except Exception:
            pass

    tool_executor = ToolExecutor(tools_manager=tools_manager, bus=bus)

    agent = Agent(
        bus=bus,
        provider=provider,
        context=Context(
            provider=provider,
            system_prompt=SystemPromptBuilder().build(),
            bus=bus,
        ),
        tools_manager=tools_manager,
        tool_executor=tool_executor,
        approve_mode=approve_mode,
    )

    if workspace_loader is not None:
        await workspace_loader(agent)

    return agent