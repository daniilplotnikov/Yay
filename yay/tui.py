import os

from rich.console import Console
from rich.table import Table

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.completion import FuzzyWordCompleter
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.document import Document

from .agent import Agent
from .llm import Context
from .providers.openai_compatible import OpenAICompatibleProvider
from .provider import NonSelectedProvider

from .config import (
    load_config,
    save_config,
)

from .workspace import save_workspace
from .tools_renderer import render_tool_result, render_tool_call
from .builder import build_agent

console = Console()

class AgentTUI:
    def __init__(self, agent: Agent):
        self.agent = agent
        self.streaming_enabled = True
        self._streaming_active = False
        self.refresh_completer()

        self.status_bar = Window(
            height=1,
            content=FormattedTextControl(self.get_status_text)
        )

        self.output = self.output = TextArea(
            scrollbar=True,
            focusable=True,  
            wrap_lines=True,
            height=Dimension(weight=1)
        )
        self.input = TextArea(height=1, prompt="❯ ", multiline=False, completer=self.completer,)
        self.header = Window(height=1, content=FormattedTextControl("Yet Another Yielder"))
        root = HSplit([
            self.output,
            self.status_bar,
            self.input,
        ])
        self.layout = Layout(container=root, focused_element=self.input)
        
        kb = KeyBindings()

        @kb.add("enter")
        def _(event):
            text = self.input.text.strip()
            if not text:
                return
            self.input.buffer.document = Document("")
            self.handle_command(text)

        @kb.add("pageup")
        def _(event):
            event.app.layout.focus(self.output)
            self.output.buffer.cursor_up(count=10)

        @kb.add("pagedown")
        def _(event):
            event.app.layout.focus(self.output)
            self.output.buffer.cursor_down(count=10)

        self.application = Application(
            layout=self.layout,
            key_bindings=kb,
            full_screen=True,
        )

        self.messages = []

    def append_output(self, text):
        self.messages.append(str(text))
        self.output.text = "\n".join(self.messages[-100:])
        self.output.buffer.cursor_position = len(self.output.text)
        self.application.invalidate()

    def refresh_completer(self):

        commands = [
            "/help",
            "?",
            "/tools",
            "/models",
            "/model",
            "/model next",
            "/reload",
            "/settings",
            "/context",
            "/history",
            "/reset",
            "/approve",
            "/approve safe",
            "/approve always",
            "/approve never",
            "/clear",
            "/cls",
            "/quit",
            "/provider",
            "/provider openai",
            "/provider openrouter",
            "/provider openai_compatible",
            "/provider reset",
            "/baseurl",
            "/set_context_length",
            "/compress_context",
            "/steer",         
            "/steer add",      
            "/steer clear",
            "/mcp",
            "/mcp add",
            "/mcp remove",
            "/mcp reload",
        ]

        try:
            models = self.agent.provider.get_models()

            if isinstance(models, list):
                commands.extend(
                    f"/model {m}"
                    for m in models
                )
        except Exception:
            pass

        self.completer = WordCompleter(
            commands,
            ignore_case=True,
            sentence=True,
        )

        if hasattr(self, "input"):
            self.input.buffer.completer = self.completer

    def event_handler(self, event, data):

        if event == "task_started":

            self.append_output(
                f"\n[Task]\n{data['prompt']}\n"
            )

        elif event == "model_processing":

            self.append_output("")
            self.append_output("Thinking...")
            self.append_output("")

        elif event == "stream_chunk":

            if data["type"] == "text":
                self._streaming_active = True

                self.output.text += data["content"]

                self.application.invalidate()

        elif event == "provider_response":
            msg = data["message"]

            if (
                hasattr(msg, "content")
                and hasattr(msg.content, "text")
                and msg.content.text
            ):
                if not self.streaming_enabled:

                    self.append_output(
                        f"\n[Assistant]\n{msg.content.text}\n"
                    )

        elif event == "tool_call":
            tool_name = data.get("tool")
            args = data.get("args", {})

            if not tool_name or tool_name == "FinishTaskTool":
                return

            if self._streaming_active:
                self._streaming_active = False
                self.append_output("")

            text = render_tool_call(tool_name, args)
            if text:
                self.append_output(text)

        elif event == "tool_started":
            pass

        elif event == "tool_finished":
            tool = data.get("tool")
            result = data.get("result")

            text = render_tool_result(tool, result)
            if text:
                self.append_output(text)

        elif event == "tool_error":

            self.append_output(
                f"\n[Tool Error] {data['error']}\n"
            )

        elif event == "approval_requested":
            tool_name = data.get("tool")
            self.append_output(f"\n[Approval Required] {tool_name}\n")

            choice = prompt(
                "Approve? [y]es / [n]o / [a]lways / [s]afe: "
            ).strip().lower()

            if choice in {"y", "yes"}:
                self.agent.resolve_approval(True)
            elif choice in {"n", "no"}:
                self.agent.resolve_approval(False)
            elif choice in {"a", "always"}:
                self.agent.approve_mode = "always"
                self.agent.resolve_approval(True)
            elif choice in {"s", "safe"}:
                self.agent.approve_mode = "safe"
                self.agent.resolve_approval(True)
            else:
                self.append_output("Invalid choice, rejecting by default")
                self.agent.resolve_approval(False)

        elif event == "context_compressed":

            before = data.get("before_tokens")
            after = data.get("after_tokens")

            self.append_output(
                f"\n[Context Compressed]\n"
                f"Before: {before} tokens\n"
                f"After:  {after} tokens\n"
            )

        elif event == "context_compression_error":

            self.append_output(
                f"\n[Compression Error]\n"
                f"{data['error']}\n"
            )

        elif event == "task_error":

            self.append_output(
                f"\n[Task {data['task_id']} Error]\n"
                f"{data['error']}\n"
            )

        elif event == "task_finished":
            if self._streaming_active:
                self.output.text += "\n"
                self._streaming_active = False

            save_workspace(self.agent)

    def show_help(self):
        self.append_output("""
    HELP

    /help                 Show help
    ?                     Show help
    /tools                Show tools
    /models               Show available models
    /model                Show current model
    /model <name>         Change model
    /model next           Next model
    /reload               Reload models
    /settings             Show settings
    /context              Context info
    /history              Show conversation history
    /reset                Reset context
    /approve              Show mode
    /approve safe
    /approve always
    /approve never
    /clear
    /cls
    /quit
    /provider             Show provider
    /provider openai
    /provider openrouter
    /baseurl              Show current base url
    /baseurl <url>        Change base url
    /set_context_length <tokens>
    /compress_context
    /steer
    /steer add
    /steer clear
    /mcp
    /mcp add <url>
    /mcp remove <index>
    /mcp reload
    """)

    def show_tools(self):
        tools = "\n".join(
            f"• {tool.name}"
            for tool in self.agent.tools.values()
        )

        self.append_output(
            f"TOOLS\n\n{tools}"
        )

    def show_models(self):
        models = self.agent.provider.get_models()

        if isinstance(models, dict):
            self.append_output(
                f"ERROR: {models.get('error')}"
            )
            return

        current = self.agent.provider.model

        rows = []

        for model in models:
            marker = "●" if model == current else "○"
            rows.append(f"{marker} {model}")

        self.append_output(
            "MODELS\n\n" +
            "\n".join(rows)
        )

    def pick_model(self):
        try:
            models = self.agent.provider.get_models()

            if not isinstance(models, list) or not models:
                self.append_output("No models available")
                return

            self.append_output("Available models:\n" + "\n".join(
                f"{i+1}: {m}" for i, m in enumerate(models)
            ))

            self.append_output(
                "To select a model, type: /model <model_name>"
            )

        except Exception as e:
            self.append_output(f"Error picking model: {e}")

    def set_model(self, model):
        models = self.agent.provider.get_models()

        if isinstance(models, list):
            if model not in models:
                self.append_output(
                    f"Unknown model: {model}"
                )
                return

        self.agent.provider.set_model(model)

        cfg = load_config()
        cfg["model"] = model

        save_config(cfg)
        save_workspace(self.agent)

        self.refresh_completer()

        self.append_output(
            f"Model changed: {model}"
        )

    def next_model(self):

        models = self.agent.provider.get_models()

        if not isinstance(models, list):
            return

        if not models:
            return

        current = self.agent.provider.model

        try:
            idx = models.index(current)
        except ValueError:
            idx = -1

        model = models[
            (idx + 1) % len(models)
        ]

        self.set_model(model)

    def reload_models(self):
        self.refresh_completer()

        self.append_output(
            "Models reloaded"
        )

    def show_context(self):
        self.append_output(
            f"Context messages: {len(self.agent.context.messages)}"
        )

    def show_history(self):
        messages = self.agent.context.messages

        if not messages:
            self.append_output("History is empty")
            return

        for idx, msg in enumerate(messages, start=1):
            content = msg.content

            if hasattr(content, "text"):
                content = content.text

            self.append_output(
                f"\n[{idx}] {msg.role}\n"
                f"{str(content)[:1500]}"
            )

    def reset_context(self):
        self.agent.context = Context(
            provider=self.agent.provider
        )

        self.agent.context.compression_callback = (
            self.agent._on_context_compressed
        )

        save_workspace(self.agent)

        self.append_output(
            "Context cleared"
        )

    def show_approval_mode(self):
        self.append_output(
            f"Approval mode: {self.agent.approve_mode}"
        )

    def show_provider(self):
        self.append_output(
            f"Provider: {self.agent.provider.__class__.__name__}"
        )

    def show_base_url(self):
        self.append_output(
            f"Base URL: "
            f"{getattr(self.agent.provider, 'base_url', 'N/A')}"
        )

    def set_base_url(self, url):

        provider = self.agent.provider

        if hasattr(provider, "set_base_url"):

            provider.set_base_url(url)

        elif hasattr(provider, "base_url"):

            provider.base_url = url

        self.refresh_completer()
        cfg = load_config()
        cfg["base_url"] = url

        save_config(cfg)
        save_workspace(self.agent)

        self.append_output(
            f"Base URL changed: {url}"
        )

    def set_context_length(self, length):
        
        provider = self.agent.provider

        provider.context_length = length

        self.refresh_completer()
        cfg = load_config()
        cfg["context_length"] = length

        save_config(cfg)
        save_workspace(self.agent)

        self.append_output(
            f"Context length: {length}"
        )

    def reset_provider(self):
        cfg = load_config()

        cfg.pop("provider", None)
        cfg.pop("model", None)

        self.agent.provider = NonSelectedProvider()

        save_config(cfg)
        save_workspace(self.agent)

        self.append_output(
            "Provider reset"
        )

    def switch_provider(self, provider_name):
        tools = list(self.agent.tools.values())

        current_model = self.agent.provider.model

        cfg = load_config()

        if provider_name == "openai":
            api_key = (
                cfg.get("openai_api_key")
                or os.getenv("OPENAI_API_KEY")
                or ""
            )

            if not api_key:
                api_key = prompt(
                    "OpenAI API key: ",
                    is_password=True,
                ).strip()

                cfg["openai_api_key"] = api_key
                save_config(cfg)

            provider = OpenAICompatibleProvider(
                api_key=api_key,
                model=current_model,
                base_url="https://api.openai.com/v1",
                tools=tools,
            )

        elif provider_name == "openrouter":

            api_key = (
                cfg.get("openrouter_api_key")
                or os.getenv("OPENROUTER_API_KEY")
                or ""
            )

            if not api_key:
                api_key = prompt(
                    "OpenRouter API key: ",
                    is_password=True,
                ).strip()

                cfg["openrouter_api_key"] = api_key
                save_config(cfg)

            provider = OpenAICompatibleProvider(
                api_key=api_key,
                model=current_model,
                base_url="https://openrouter.ai/api/v1",
                tools=tools,
            )

        else:
            api_key = (
                cfg.get("api_key")
                or os.getenv("API_KEY")
                or ""
            )

            if not api_key:
                api_key = prompt(
                    "API key: ",
                    is_password=True,
                ).strip()

                cfg["api_key"] = api_key

            base_url = (
                cfg.get("base_url")
                or os.getenv("BASE_URL")
                or ""
            )

            if not base_url:
                base_url = prompt(
                    "Base URL: "
                ).strip()

                base_url = base_url.rstrip("/")

                cfg["base_url"] = base_url

            save_config(cfg)

            provider = OpenAICompatibleProvider(
                api_key=api_key,
                model=current_model,
                base_url=base_url,
                tools=tools,
            )

        self.agent.provider = provider

        cfg["provider"] = provider_name

        save_config(cfg)
        save_workspace(self.agent)

        self.refresh_completer()

        self.append_output(
            f"Provider: {provider_name}"
        )

    def show_steering(self):
        instructions = self.agent.steering.instructions

        if not instructions:
            self.append_output(
                "No steering instructions"
            )
            return

        self.append_output(
            "STEERING\n\n" +
            "\n".join(
                f"• {x}"
                for x in instructions
            )
        )

    def add_steering(self, text):
        self.agent.add_instruction(text)
        save_workspace(self.agent)
        self.append_output(
            f"Instruction added: {text}"
        )

    def clear_steering(self):
        self.agent.clear_instructions()
        save_workspace(self.agent)
        self.append_output(
            "Steering cleared"
        )

    def show_mcp(self):
        cfg = load_config()

        servers = cfg.get("mcp_servers", [])

        if not servers:
            self.append_output(
                "No MCP servers"
            )
            return

        self.append_output(
            "\n".join(
                f"{i}: {s}"
                for i, s in enumerate(servers)
            )
        )

    def add_mcp(self, url):
        cfg = load_config()

        servers = cfg.setdefault(
            "mcp_servers",
            []
        )

        if url not in servers:
            servers.append(url)

        save_config(cfg)

        self.append_output(
            f"MCP added: {url}"
        )

    def remove_mcp(self, index):
        cfg = load_config()

        servers = cfg.get(
            "mcp_servers",
            []
        )

        if index < 0 or index >= len(servers):
            raise IndexError(
                "Invalid MCP index"
            )

        servers.pop(index)

        save_config(cfg)

        self.append_output(
            "MCP removed"
        )

    def reload_mcp(self):
        from .builder import build_agent

        new_agent = build_agent()

        self.agent.replace_tools(
            new_agent.tools.values()
        )

        self.append_output(
            "MCP tools reloaded"
        )

    def set_approval_mode(self, mode):

        self.agent.approve_mode = mode

        save_workspace(self.agent)

        self.append_output(
            f"Approval mode: {mode}"
        )

    def show_settings(self):
        provider = self.agent.provider

        self.append_output(
            "\n".join([
                "SETTINGS",
                "",
                f"Provider : {provider.__class__.__name__}",
                f"Model    : {provider.model}",
                f"Base URL : {getattr(provider, 'base_url', '-')}",
                f"Approval : {self.agent.approve_mode}",
                f"Messages : {len(self.agent.context.messages)}",
                f"Tools    : {len(self.agent.tools)}",
            ])
        )

    def clear_screen(self):

        os.system(
            "cls"
            if os.name == "nt"
            else "clear"
        )

    def handle_command(self, text):
        if not text:
            return

        if text == "/quit":
            self.append_output("Bye!")
            self.application.exit()
            return

        elif text in {"/help", "?"}:
            return self.show_help()

        elif text == "/tools":
            return self.show_tools()

        elif text == "/models":
            return self.show_models()

        elif text == "/model":
            return self.pick_model()

        elif text == "/model next":
            return self.next_model()

        elif text.startswith("/model "):
            model = text.split(maxsplit=1)[1].strip()
            return self.set_model(model)

        elif text == "/provider":
            return self.show_provider()

        elif text == "/provider openai":
            return self.switch_provider("openai")

        elif text == "/provider openrouter":
            return self.switch_provider("openrouter")

        elif text == "/provider openai_compatible":
            return self.switch_provider("openai_compatible")

        elif text == "/provider reset":
            return self.reset_provider()

        elif text == "/baseurl":
            return self.show_base_url()

        elif text.startswith("/baseurl "):
            url = text.split(maxsplit=1)[1].strip()
            return self.set_base_url(url)

        elif text == "/reload":
            return self.reload_models()

        elif text == "/settings":
            return self.show_settings()

        elif text == "/context":
            return self.show_context()

        elif text == "/history":
            return self.show_history()

        elif text == "/reset":
            return self.reset_context()

        elif text == "/approve":
            return self.show_approval_mode()

        elif text == "/compress_context":
            return self.agent.context.compress()

        elif text == "/steer":
            return self.show_steering()

        elif text.startswith("/steer add "):
            instruction = text[len("/steer add "):].strip()
            return self.add_steering(instruction)

        elif text == "/steer clear":
            return self.clear_steering()

        elif text.startswith("/approve "):
            mode = text.split(maxsplit=1)[1].strip()

            if mode not in {"safe", "always", "never"}:
                self.append_output(
                    "Use safe|always|never"
                )
                return

            return self.set_approval_mode(mode)

        elif text.startswith("/set_context_length "):
            length = text.split(maxsplit=1)[1].strip()

            if not length.isdigit():
                self.append_output(
                    "Please enter a valid number of tokens"
                )
                return

            return self.set_context_length(int(length))

        elif text == "/mcp":
            return self.show_mcp()

        elif text.startswith("/mcp add "):
            url = text[len("/mcp add "):].strip()

            if not url:
                self.append_output(
                    "Usage: /mcp add <url>"
                )
                return

            return self.add_mcp(url)

        elif text.startswith("/mcp remove "):
            index = text[len("/mcp remove "):].strip()

            if not index.isdigit():
                self.append_output(
                    "Usage: /mcp remove <index>"
                )
                return

            try:
                return self.remove_mcp(int(index))
            except (IndexError, ValueError):
                self.append_output(
                    "Invalid MCP index"
                )
                return

        elif text == "/mcp reload":
            return self.reload_mcp()

        elif text in {"/clear", "/cls"}:
            return self.clear_screen()

        self.agent.enqueue(
            prompt=text,
            task_id=self.agent.task_queue.qsize() + 1,
        )

        if not self.agent.running:
            self.agent.start_queue()

    def get_status_text(self):
        model = self.agent.provider.model.split("/")[-1]

        folder = os.path.basename(os.getcwd())

        tokens = self.agent.context.estimate_tokens()
        max_tokens = self.agent.context.max_tokens
        usage = self.agent.context.usage_percent()

        return (
            f"{model} "
            f"{folder} "
            f"[{tokens}/{max_tokens} | {usage:.0f}%]"
        )

    def run(self):
        try:
            self.application.run()

        except KeyboardInterrupt:
            self.append_output("\nInterrupted")

        except EOFError:
            self.append_output("\nBye!")

        except Exception as e:
            self.append_output(f"\nError: {e}")

def main():

    agent = build_agent()
        
    tui = AgentTUI(agent)

    agent.event_callback = tui.event_handler

    tui.append_output(
    """
 ██     ██        ██        ██     ██ 
 ██     ██       ████       ██     ██ 
  ██   ██       ██  ██       ██   ██
   ██ ██       ████████       ██ ██ 
    ███       ██      ██       ███ 
    ███       ██      ██       ███ 
    ███      ██        ██      ███ 

            Yet Another Yielder
    """
    )
    tui.run()