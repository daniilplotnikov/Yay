import json
from pathlib import Path
from datetime import datetime

from .llm import (
    Context,
    Message,
    Content,
)

WORKSPACE_FILE = ".yay_workspace.json"


def workspace_path():
    return Path.cwd() / WORKSPACE_FILE


def save_workspace(agent):

    data = {
        "version": 2,
        "provider": agent.provider.__class__.__name__,
        "model": getattr(
            agent.provider,
            "model",
            "",
        ),
        "base_url": getattr(
            agent.provider,
            "base_url",
            "",
        ),
        "approve_mode": agent.approve_mode,
        "messages": [],
    }

    for msg in agent.context.messages:

        data["messages"].append(
            {
                "role": msg.role,
                "content": (
                    msg.content.text
                    if msg.content
                    else ""
                ),
                "tool": msg.tool,
                "tool_call_id": getattr(
                    msg,
                    "tool_call_id",
                    None,
                ),
                "tool_calls": getattr(
                    msg,
                    "tool_calls",
                    [],
                ),
                "time": msg.time.isoformat(),
            }
        )

    workspace_path().write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_workspace(agent):

    path = workspace_path()

    if not path.exists():
        return False

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if data.get("model"):
            agent.provider.model = data[
                "model"
            ]

        if (
            data.get("base_url")
            and hasattr(
                agent.provider,
                "base_url"
            )
        ):
            agent.provider.base_url = data[
                "base_url"
            ]

        agent.approve_mode = data.get(
            "approve_mode",
            "safe",
        )

        context = Context(provider=agent.provider)

        for item in data.get(
            "messages",
            [],
        ):

            msg = Message(
                role=item.get(
                    "role",
                    "user",
                ),
                content=Content(
                    item.get(
                        "content",
                        "",
                    )
                ),
                tool=item.get(
                    "tool"
                ),
                tool_call_id=item.get(
                    "tool_call_id"
                ),
                tool_calls=item.get(
                    "tool_calls",
                    [],
                ),
            )

            if item.get("time"):

                try:

                    msg.time = (
                        datetime.fromisoformat(
                            item["time"]
                        )
                    )

                except Exception:
                    pass

            context.append(msg)

        agent.context = context

        return True

    except Exception as e:

        print(
            f"Workspace load error: {e}"
        )

        return False


def clear_workspace():

    path = workspace_path()

    if path.exists():
        path.unlink()


def workspace_exists():

    return workspace_path().exists()