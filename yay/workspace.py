from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path

from .llm import Context, Message, Content
from .config import load_config, save_config
from .events import ErrorEvent

WORKSPACE_FILE = ".yay_workspace.json"


def workspace_path() -> Path:
    return Path.cwd() / WORKSPACE_FILE

def save_workspace(agent) -> None:
    cfg = load_config()

    provider_name = cfg.get("provider", agent.provider.__class__.__name__)

    data: dict = {
        "version":        3,
        "provider":       provider_name,
        "model":          getattr(agent.provider, "model",          ""),
        "base_url":       getattr(agent.provider, "base_url",       ""),
        "context_length": getattr(agent.provider, "context_length", 0),
        "approve_mode":   agent.approve_mode,
        "messages":       [],
    }

    for msg in agent.context.messages:
        try:
            content = msg.content
            text    = content.text if content else ""
            data["messages"].append({
                "role":         msg.role,
                "content":      text,
                "tool":         msg.tool,
                "tool_call_id": getattr(msg, "tool_call_id", None),
                "tool_calls":   getattr(msg, "tool_calls",   []),
                "time":         msg.time.isoformat(),
            })
        except Exception:
            pass

    workspace_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def load_workspace(agent) -> bool:
    path = workspace_path()
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        agent.bus.emit(ErrorEvent(
            source="LoadWorkspace",
            message=f"Can't parse workspace file: {e}",
            traceback=traceback.format_exc(),
        ))
        return False

    try:
        model = data.get("model", "")
        if model:
            agent.provider.model = model

        base_url = data.get("base_url", "")
        if base_url and hasattr(agent.provider, "base_url"):
            agent.provider.base_url = base_url

        ctx_length = data.get("context_length", 0)
        if ctx_length and hasattr(agent.provider, "context_length"):
            try:
                agent.provider.context_length = int(ctx_length)
            except (ValueError, TypeError):
                pass

        agent.approve_mode = data.get("approve_mode", "safe")

        cfg = load_config()
        cfg["approve_mode"] = agent.approve_mode
        if model:
            cfg["model"] = model
        if base_url:
            cfg["base_url"] = base_url
        if ctx_length:
            cfg["context_length"] = ctx_length
        save_config(cfg)

        existing_system = getattr(agent.context, "system_prompt", None)

        context = Context(
            provider=agent.provider,
            system_prompt=existing_system,
            bus=agent.bus,
        )
        context.compression_callback = agent._on_context_compressed

        for item in data.get("messages", []):
            try:
                msg = Message(
                    role=item.get("role", "user"),
                    content=Content(item.get("content", "")),
                    tool=item.get("tool"),
                    tool_call_id=item.get("tool_call_id"),
                    tool_calls=item.get("tool_calls", []),
                )
                if item.get("time"):
                    try:
                        msg.time = datetime.fromisoformat(item["time"])
                    except Exception:
                        pass
                context.append(msg)
            except Exception:
                pass

        agent.context = context
        return True

    except Exception as e:
        agent.bus.emit(ErrorEvent(
            source="LoadWorkspace",
            message=f"Can't restore workspace state: {e}",
            traceback=traceback.format_exc(),
        ))
        return False

def clear_workspace() -> None:
    path = workspace_path()
    if path.exists():
        path.unlink()


def workspace_exists() -> bool:
    return workspace_path().exists()