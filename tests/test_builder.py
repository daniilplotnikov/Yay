"""Tests for build_agent builder function."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from yay.builder import build_agent
from yay.tools import ToolsManager, ToolExecutor


@pytest.fixture
def bus():
    bus = AsyncMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def provider():
    provider = AsyncMock()
    provider.get_models = AsyncMock(return_value=["model-a", "model-b"])
    return provider


@pytest.fixture
def tools_manager():
    return ToolsManager()


@pytest.mark.asyncio
async def test_build_agent_creates_agent(bus, provider, tools_manager):
    from yay.agent import Agent
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
    )
    assert isinstance(agent, Agent)


@pytest.mark.asyncio
async def test_build_agent_with_model(bus, provider, tools_manager):
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
        model="custom-model",
    )
    assert provider.model == "custom-model"


@pytest.mark.asyncio
async def test_build_agent_sets_first_model(bus, provider, tools_manager):
    provider.model = ""
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
    )
    # Should set to first model from get_models()
    assert provider.model == "model-a"


@pytest.mark.asyncio
async def test_build_agent_no_models_sets_none(bus, provider, tools_manager):
    provider.get_models = AsyncMock(return_value=[])
    provider.model = ""
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
    )
    # model should remain empty


@pytest.mark.asyncio
async def test_build_agent_with_context_length(bus, provider, tools_manager):
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
        context_length=4096,
    )
    assert provider.context_length == 4096


@pytest.mark.asyncio
async def test_build_agent_creates_tool_executor(bus, provider, tools_manager):
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
    )
    assert agent.tool_executor is not None
    assert isinstance(agent.tool_executor, ToolExecutor)


@pytest.mark.asyncio
async def test_build_agent_with_approve_mode(bus, provider, tools_manager):
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
        approve_mode="always",
    )
    assert agent.approve_mode == "always"


@pytest.mark.asyncio
async def test_build_agent_with_workspace_loader(bus, provider, tools_manager):
    loader = AsyncMock()
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
        workspace_loader=loader,
    )
    loader.assert_called_once_with(agent)


@pytest.mark.asyncio
async def test_build_agent_with_mcp_manager(bus, provider, tools_manager):
    mcp = AsyncMock()
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
        mcp_manager=mcp,
    )
    mcp.fetch_all.assert_called_once()


@pytest.mark.asyncio
async def test_build_agent_sets_compression_callback(bus, provider, tools_manager):
    agent = await build_agent(
        bus=bus,
        tools_manager=tools_manager,
        provider=provider,
    )
    assert agent.context.compression_callback is not None
