from __future__ import annotations

import inspect
import os
import traceback

from .config import load_config
from .events import EventBus, ErrorEvent
from .llm import Context
from .managers import ProviderManager, ToolsManager
from .provider import NonSelectedProvider
from .sysprompt import SystemPromptBuilder
from .workspace import load_workspace

def _get_api_key(cfg: dict, provider_name: str) -> str:
    name = provider_name.lower()
    if "openai" in name:
        return cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "") or cfg.get("api_key", "")
    if "openrouter" in name:
        return cfg.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY", "") or cfg.get("api_key", "")
    return cfg.get("api_key") or os.getenv("API_KEY", "") or "dummy"

def _name_matches(cls, provider_name: str) -> bool:
    target = provider_name.strip().lower()
    if not target:
        return False
    candidates = [
        getattr(cls, "name", ""),
        getattr(cls, "provider_name", ""),
        cls.__name__,
    ]
    return any(c.strip().lower() == target for c in candidates if c)

def _instantiate_provider(cls, cfg: dict, provider_name: str,
                           tools_manager: ToolsManager, bus: EventBus):
    sig    = inspect.signature(cls.__init__)
    params = set(sig.parameters.keys()) - {"self"}

    kwargs: dict = {}

    if "api_key" in params:
        kwargs["api_key"] = _get_api_key(cfg, provider_name) or "dummy"
    if "model" in params:
        kwargs["model"] = cfg.get("model", "") or ""
    if "base_url" in params:
        base_url = cfg.get("base_url") or getattr(cls, "default_base_url", "")
        if base_url:
            kwargs["base_url"] = base_url
    if "tools_manager" in params:
        kwargs["tools_manager"] = tools_manager
    if "tools" in params:
        kwargs["tools"] = list(tools_manager.get_tools().values())
    if "bus" in params:
        kwargs["bus"] = bus

    SKIP = {"api_key", "openai_api_key", "openrouter_api_key",
            "model", "base_url", "tools_manager", "tools", "bus"}
    for key, val in cfg.items():
        if key in params and key not in SKIP and val is not None:
            kwargs[key] = val

    return cls(**kwargs)

def build_agent(
    bus: EventBus,
    tools_manager: ToolsManager,
    providers_manager: ProviderManager,
    mcp_manager=None,    
):
    from .agent import Agent

    cfg = load_config()

    if mcp_manager is not None:
        mcp_manager.fetch_all()
    else:
        mcp_servers = cfg.get("mcp_servers", [])
        if mcp_servers:
            try:
                from .mcp import MCPClient
                for item in mcp_servers:
                    url     = item if isinstance(item, str) else item.get("url", "")
                    enabled = True  if isinstance(item, str) else item.get("enabled", True)
                    if not url or not enabled:
                        continue
                    try:
                        tools_manager.register_many(MCPClient(url).fetch_tools())
                    except Exception as e:
                        bus.emit(ErrorEvent(
                            source="BuildAgent/MCP",
                            message=f"Can't load MCP server {url!r}: {e}",
                            traceback=traceback.format_exc(),
                        ))
            except ImportError:
                pass

    provider_name = cfg.get("provider", "").strip()
    provider      = NonSelectedProvider()

    if provider_name:
        provider_cls = next(
            (cls for cls in providers_manager.get_providers().values()
             if _name_matches(cls, provider_name)),
            None,
        )
        if provider_cls is None:
            bus.emit(ErrorEvent(
                source="BuildAgent",
                message=(
                    f"Provider {provider_name!r} not found. "
                    f"Available: {list(providers_manager.get_providers().keys())}"
                ),
                traceback="",
            ))
        else:
            try:
                provider = _instantiate_provider(
                    provider_cls, cfg, provider_name, tools_manager, bus
                )
            except Exception as e:
                bus.emit(ErrorEvent(
                    source="BuildAgent",
                    message=f"Can't instantiate provider {provider_name!r}: {e}",
                    traceback=traceback.format_exc(),
                ))
                provider = NonSelectedProvider()

    configured_model = cfg.get("model", "")
    if configured_model:
        try:
            provider.model = configured_model
        except Exception:
            pass
    else:
        try:
            models = provider.get_models()
            if isinstance(models, list) and models:
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

    load_workspace(agent)

    return agent