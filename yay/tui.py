import os

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.completion import FuzzyWordCompleter

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

    def event_handler(self, event, data):

        if event == "task_started":

            console.print(
                Panel(
                    data["prompt"],
                    title="Task",
                    border_style="blue",
                )
            )

        elif event == "model_processing":

            console.print(
                "[yellow]Thinking...[/yellow]"
            )

        elif event == "stream_chunk":
            if data["type"] == "text":
                self._streaming_active = True
                print(data["content"], end="", flush=True)

        elif event == "provider_response":
            msg = data["message"]

            if hasattr(msg, "content") and hasattr(msg.content, "text") and msg.content.text:
                if not getattr(self, "streaming_enabled", False):
                    console.print(
                        Panel(
                            msg.content.text,
                            title="Assistant",
                            border_style="green",
                        )
                    )

        elif event == "tool_call":
            tool_name = data.get("tool")
            args = data.get("args", {})

            if not tool_name or tool_name == "FinishTaskTool":
                return

            if self._streaming_active:
                self._streaming_active = False

            render_tool_call(tool_name, args)

        elif event == "tool_started":
            pass

        elif event == "tool_finished":
            tool = data["tool"]
            result = data.get("result")

            render_tool_result(
                tool,
                result,
            )

        elif event == "tool_error":

            console.print(
                f"[red]Error[/red]: {data['error']}"
            )

        elif event == "approval_requested":
            answer = prompt(
                f"\nAllow tool {data['tool']}? [y/N/a]: "
            ).strip().lower()

            if answer == "a":
                self.agent.approve_mode = "always"
                self.agent.resolve_approval(True)
            elif answer in {"y", "yes"}:
                self.agent.resolve_approval(True)
            else:
                self.agent.resolve_approval(False)

        elif event == "context_compressed":

            before = data.get("before_tokens")
            after = data.get("after_tokens")

            console.print(
                Panel(
                    (
                        f"Before: {before} tokens\n"
                        f"After:  {after} tokens"
                    ),
                    title="Context Compressed",
                    border_style="yellow",
                )
            )

        elif event == "context_compression_error":
            console.print(
                Panel(
                    data["error"],
                    title="Compression Error",
                    border_style="red",
                )
            )

        elif event == "task_error":
            console.print(
                Panel(
                    data["error"],
                    title=f"Task {data['task_id']} Error",
                    border_style="red",
                )
            )

        elif event == "task_finished":
            self._streaming_active = False
            save_workspace(self.agent)

    def show_help(self):

        console.print(
            Panel.fit(
                """
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
/set_context_length <tokens>  Set max context length
/compress_context
/steer,          
/steer add,    
/steer clear",
/mcp                  Show MCP servers
/mcp add <url>        Add MCP server
/mcp remove <index>   Remove MCP server
/mcp reload           Reload MCP tools
                """.strip(),
                title="Help",
                border_style="blue",
            )
        )

    def show_tools(self):

        tools = []

        for tool in self.agent.tools.values():
            tools.append(tool.name)

        console.print(
            Panel(
                "\n".join(
                    f"• {tool}"
                    for tool in tools
                ),
                title="Tools",
                border_style="cyan",
            )
        )

    def show_models(self):

        models = self.agent.provider.get_models()

        if isinstance(models, dict):

            console.print(
                f"[red]{models.get('error')}[/red]"
            )

            return

        current = self.agent.provider.model

        rows = []

        for model in models:

            marker = (
                "●"
                if model == current
                else "○"
            )

            rows.append(
                f"{marker} {model}"
            )

        console.print(
            Panel(
                "\n".join(rows),
                title=f"Models ({len(models)})",
                border_style="magenta",
            )
        )

    def pick_model(self):
        try:
            models = self.agent.provider.get_models()
            if not isinstance(models, list) or not models:
                console.print("[red]No models available[/red]")
                return

            selected = prompt(
                "Search model: ",
                completer=FuzzyWordCompleter(models),
                complete_while_typing=True,
            ).strip()

            if selected in models:
                self.set_model(selected)
            else:
                console.print(f"[red]Unknown model:[/red] {selected}")

        except Exception as e:
            console.print(f"[red]Error picking model:[/red] {e}")

    def set_model(self, model):

        models = self.agent.provider.get_models()

        if isinstance(models, list):

            if model not in models:

                console.print(
                    f"[red]Unknown model:[/red] {model}"
                )

                return

        self.agent.provider.set_model(model)

        cfg = load_config()

        cfg["model"] = model

        save_config(cfg)

        save_workspace(self.agent)

        self.refresh_completer()

        console.print(
            f"[green]Model changed:[/green] {model}"
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

        console.print(
            "[green]Models reloaded[/green]"
        )

    def show_context(self):

        messages = self.agent.context.messages

        console.print(
            Panel(
                f"Messages: {len(messages)}",
                title="Context",
                border_style="yellow",
            )
        )

    def show_history(self):

        messages = self.agent.context.messages

        if not messages:

            console.print(
                "[yellow]History is empty[/yellow]"
            )

            return

        for idx, msg in enumerate(
            messages,
            start=1,
        ):

            content = msg.content

            if hasattr(content, "text"):
                content = content.text

            console.print(
                Panel(
                    str(content)[:1500],
                    title=f"{idx}. {msg.role}",
                )
            )

    def reset_context(self):

        self.agent.context = Context(provider=self.agent.provider)

        self.agent.context.compression_callback = (
            self.agent._on_context_compressed
        )

        save_workspace(self.agent)

        console.print(
            "[green]Context cleared[/green]"
        )

    def show_approval_mode(self):

        console.print(
            Panel(
                self.agent.approve_mode,
                title="Approval Mode",
                border_style="cyan",
            )
        )

    def show_provider(self):

        console.print(
            Panel(
                self.agent.provider.__class__.__name__,
                title="Provider",
                border_style="cyan",
            )
        )

    def show_base_url(self):

        console.print(
            Panel(
                getattr(
                    self.agent.provider,
                    "base_url",
                    "N/A"
                ),
                title="Base URL",
                border_style="cyan",
            )
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

        console.print(
            f"[green]Base URL:[/green] {url}"
        )

    def set_context_length(self, length):
        
        provider = self.agent.provider

        provider.context_length = length

        self.refresh_completer()
        cfg = load_config()
        cfg["context_length"] = length

        save_config(cfg)
        save_workspace(self.agent)

        console.print(
            f"[green]Context Length:[/green] {length} tokens"
        )

    def reset_provider(self):
        cfg = load_config()

        cfg.pop("provider", None)
        cfg.pop("model", None)

        self.agent.provider = NonSelectedProvider()

        save_config(cfg)
        save_workspace(self.agent)

        console.print(
            "[green]Provider reset.[/green]\n"
            "Model and API keys removed."
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

        console.print(
            f"[green]Provider:[/green] {provider_name}"
        )

    def show_steering(self):
        instructions = self.agent.steering.instructions
        if not instructions:
            console.print("[yellow]No steering instructions[/yellow]")
            return
        console.print(Panel("\n".join(f"• {x}" for x in instructions), title="Steering", border_style="cyan"))

    def add_steering(self, text):
        self.agent.add_instruction(text)
        save_workspace(self.agent)
        console.print(f"[green]Instruction added:[/green] {text}")

    def clear_steering(self):
        self.agent.clear_instructions()
        save_workspace(self.agent)
        console.print("[green]Steering cleared[/green]")

    def show_mcp(self):
        cfg = load_config()

        servers = cfg.get("mcp_servers", [])

        if not servers:
            console.print("[yellow]No MCP servers[/yellow]")
            return

        for idx, server in enumerate(servers):
            console.print(f"{idx}: {server}")

    def add_mcp(self, url):
        cfg = load_config()

        servers = cfg.setdefault(
            "mcp_servers",
            []
        )

        if url not in servers:
            servers.append(url)

        save_config(cfg)

        console.print(
            f"[green]MCP added:[/green] {url}"
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

        console.print(
            "[green]MCP removed[/green]"
        )

    def reload_mcp(self):
        from .builder import build_agent

        new_agent = build_agent()

        self.agent.replace_tools(
            new_agent.tools.values()
        )

        console.print(
            "[green]MCP tools reloaded[/green]"
        )

    def set_approval_mode(self, mode):

        self.agent.approve_mode = mode

        save_workspace(self.agent)

        console.print(
            f"[green]Approval mode:[/green] {mode}"
        )

    def show_settings(self):

        provider = self.agent.provider

        table = Table(
            title="Settings"
        )

        table.add_column(
            "Key",
            style="cyan"
        )

        table.add_column(
            "Value"
        )

        table.add_row(
            "Provider",
            provider.__class__.__name__
        )

        table.add_row(
            "Model",
            provider.model
        )

        table.add_row(
            "Base URL",
            getattr(
                provider,
                "base_url",
                "-"
            )
        )

        table.add_row(
            "Approval",
            self.agent.approve_mode
        )

        table.add_row(
            "Messages",
            str(
                len(
                    self.agent.context.messages
                )
            )
        )

        table.add_row(
            "Tools",
            str(
                len(
                    self.agent.tools
                )
            )
        )

        console.print(table)

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
            console.print("[blue]Bye![/blue]")
            raise EOFError

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
                console.print("[red]Use safe|always|never[/red]")
                return

            return self.set_approval_mode(mode)

        elif text.startswith("/set_context_length "):
            length = text.split(maxsplit=1)[1].strip()

            if not length.isdigit():
                console.print(
                    "[red]Please enter a valid number of tokens.[/red]"
                )
                return

            return self.set_context_length(int(length))

        elif text == "/mcp":
            return self.show_mcp()

        elif text.startswith("/mcp add "):
            url = text[len("/mcp add "):].strip()

            if not url:
                console.print(
                    "[red]Usage: /mcp add <url>[/red]"
                )
                return

            return self.add_mcp(url)

        elif text.startswith("/mcp remove "):
            index = text[len("/mcp remove "):].strip()

            if not index.isdigit():
                console.print(
                    "[red]Usage: /mcp remove <index>[/red]"
                )
                return

            try:
                return self.remove_mcp(int(index))
            except (IndexError, ValueError):
                console.print(
                    "[red]Invalid MCP index[/red]"
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

    def run(self):
        while True:
            try:
                model_name = (
                    self.agent.provider.model
                    .split("/")[-1]
                )

                cwd = os.getcwd()
                folder = os.path.basename(cwd)
                
                usage = self.agent.context.usage_percent()

                tokens = self.agent.context.estimate_tokens()
                max_tokens = self.agent.context.max_tokens
                usage = self.agent.context.usage_percent()

                if usage < 50:
                    color = "ansigreen"
                elif usage < 80:
                    color = "ansiyellow"
                else:
                    color = "ansired"

                text = prompt(
                    HTML(
                        f"<ansiblue>{model_name}</ansiblue> "
                        f"<ansigreen>{folder}</ansigreen> "
                        f"<{color}>[{tokens}/{max_tokens} | {usage:.0f}%]</{color}> "
                        "<ansicyan>❯ </ansicyan>"
                    ),
                    completer=self.completer,
                    complete_while_typing=True,
                ).strip()

                self.handle_command(text)

            except KeyboardInterrupt:
                console.print(
                    "\n[yellow]Interrupted[/yellow]"
                )

            except EOFError:
                console.print(
                    "\n[blue]Bye![/blue]"
                )
                break

            except Exception as e:
                console.print(
                    f"[red]{e}[/red]"
                )

def main():

    agent = build_agent()
        
    tui = AgentTUI(agent)

    agent.event_callback = tui.event_handler

    console.print(
        Panel.fit(
            f"""  
██     ██        ██        ██     ██ 
██     ██       ████       ██     ██ 
 ██   ██       ██  ██       ██   ██
  ██ ██       ████████       ██ ██ 
   ███       ██      ██       ███ 
   ███       ██      ██       ███ 
   ███      ██        ██      ███ 

        Yet Another Yielder

            """.strip(),
            border_style="blue",
        )
    )

    tui.run()