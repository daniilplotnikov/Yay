from __future__ import annotations

import os
import time
import threading
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer, Input, Label, RichLog, Static,
    Button, Select, TabbedContent, TabPane, ListView, ListItem,
)
from textual.screen import ModalScreen
from textual.suggester import Suggester
from rich.text import Text
from rich.table import Table
from rich.markdown import Markdown
from .agent import Agent
from .llm import Context
from .providers.openai_compatible import OpenAICompatibleProvider
from .renderer import Renderer, C, _icon, _token_color
from .config import load_config, save_config
from .workspace import save_workspace
from pathlib import Path

BAR_WIDTH = 20

PROVIDER_DEFS: dict[str, dict] = {
    "openai": {
        "label":    "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_key":  "OPENAI_API_KEY",
        "cfg_key":  "openai_api_key",
        "fields": [
            {"id": "api_key",  "label": "API Key",   "password": True,  "cfg": "openai_api_key"},
            {"id": "model",    "label": "Model",      "password": False, "cfg": "model"},
        ],
    },
    "openrouter": {
        "label":    "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key":  "OPENROUTER_API_KEY",
        "cfg_key":  "openrouter_api_key",
        "fields": [
            {"id": "api_key",  "label": "API Key",   "password": True,  "cfg": "openrouter_api_key"},
            {"id": "model",    "label": "Model",      "password": False, "cfg": "model"},
        ],
    },
    "openai_compatible": {
        "label":    "OpenAI-Compatible",
        "base_url": "http://localhost:1234/v1/",
        "env_key":  "API_KEY",
        "cfg_key":  "api_key",
        "fields": [
            {"id": "base_url", "label": "Base URL",  "password": False, "cfg": "base_url"},
            {"id": "api_key",  "label": "API Key",   "password": True,  "cfg": "api_key"},
            {"id": "model",    "label": "Model",      "password": False, "cfg": "model"},
        ],
    },
    "ollama": {
        "label":    "Ollama",
        "base_url": "http://localhost:11434/v1/",
        "env_key":  "",
        "cfg_key":  "",
        "fields": [
            {"id": "base_url", "label": "Base URL",  "password": False, "cfg": "base_url"},
            {"id": "model",    "label": "Model",      "password": False, "cfg": "model"},
        ],
    },
    "lmstudio": {
        "label":    "LM Studio",
        "base_url": "http://localhost:1234/v1/",
        "env_key":  "",
        "cfg_key":  "",
        "fields": [
            {"id": "base_url", "label": "Base URL",  "password": False, "cfg": "base_url"},
            {"id": "model",    "label": "Model",      "password": False, "cfg": "model"},
        ],
    },
}

def _build_provider(name: str, cfg: dict, tools: list, current_model: str) -> OpenAICompatibleProvider:
    pdef = PROVIDER_DEFS.get(name, PROVIDER_DEFS["openai_compatible"])
    base_url = cfg.get("base_url", pdef["base_url"])
    api_key  = (
        cfg.get(pdef["cfg_key"])
        or (os.getenv(pdef["env_key"], "") if pdef["env_key"] else "")
        or cfg.get("api_key", "dummy")
        or "dummy"
    )
    model = cfg.get("model", current_model) or current_model
    return OpenAICompatibleProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        tools=tools,
    )




def _context_bar(usage: float) -> str:
    """
    Render a gradient-style context bar.
    Segments: green → yellow → red based on fill level.
    """
    usage  = max(0.0, min(100.0, usage))
    filled = round(BAR_WIDTH * usage / 100)
    empty  = BAR_WIDTH - filled

    if usage < 50:
        bar_color = "green"
    elif usage < 80:
        bar_color = "yellow"
    else:
        bar_color = "red"

    
    segments: list[str] = []
    remaining = filled
    bands = [
        (int(BAR_WIDTH * 0.50), "green"),
        (int(BAR_WIDTH * 0.30), "yellow"),
        (BAR_WIDTH,             "red"),
    ]
    pos = 0
    for band_end, color in bands:
        band_count = min(remaining, band_end - pos)
        if band_count > 0:
            segments.append(f"[{color}]{'█' * band_count}[/]")
            remaining -= band_count
        pos = band_end
        if remaining <= 0:
            break

    bar = "".join(segments) + f"[bright_black]{'░' * empty}[/]"
    return bar

class CommandSuggester(Suggester):
    COMMANDS = [
        "/help", "/tools",
        "/settings", "/provider",
        "/context", "/history", "/reset", "/clear", "/quit",
        "/approve", "/approve never", "/approve safe", "/approve always",
        "/baseurl", "/set_context_length", "/compress_context",
        "/pause", "/resume",
        "/steer", "/steer clear",
        "/queue",
    ]

    def __init__(self, app_ref: "AgentTUI") -> None:
        super().__init__(use_cache=False)
        self._app = app_ref

    async def get_suggestion(self, value: str) -> str | None:
        v = value.lstrip()
        if not v:
            return None
        parts = v.split()
        if len(parts) == 1 and v.startswith("/"):
            for cmd in self.COMMANDS:
                if cmd.startswith(v) and cmd != v:
                    return cmd
            return None
        if len(parts) == 2 and parts[0] == "/model":
            try:
                models = self._app.agent.provider.get_models()
                if isinstance(models, list):
                    for m in models:
                        if m.startswith(parts[1]):
                            return f"/model {m}"
            except Exception:
                pass
        if len(parts) == 2 and parts[0] == "/approve":
            for mode in ("never", "safe", "always"):
                if mode.startswith(parts[1]):
                    return f"/approve {mode}"
        if len(parts) == 2 and parts[0] == "/steer":
            if "clear".startswith(parts[1]):
                return "/steer clear"
        return None




class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    """

    def refresh_status(
        self,
        model: str,
        provider_name: str,
        cwd: str,
        tokens: int,
        max_tokens: int,
        usage: float,
        paused: bool,
    ) -> None:
        project = Path(cwd).name or cwd
        bar     = _context_bar(usage)
        pause   = " [yellow]⏸[/]" if paused else ""
        pcolor  = "bright_cyan" if provider_name != "?" else "grey50"
        self.update(
            f"[{pcolor}]{provider_name}[/]"
            f"  [cyan]{model}[/]"
            f"{pause}"
            f"  [bold]{project}[/]"
            f"  {bar}"
            f" [bright_black]{usage:.0f}%[/]"
            f"  [bright_black]{tokens:,}/{max_tokens:,}[/]"
        )




class ProviderPickerModal(ModalScreen):
    """
    Step 1: choose provider type.
    Step 2: fill in provider-specific fields.
    Returns (provider_name, updated_cfg) or None.
    """

    CSS = """
    ProviderPickerModal {
        align: center middle;
    }
    ProviderPickerModal > Vertical {
        width: 68;
        height: auto;
        max-height: 85%;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    .modal-title  { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    .subtitle     { text-align: center; color: $text-muted; margin-bottom: 1; }
    .provider-btn { width: 1fr; margin: 0 1; }
    .btn-grid     { layout: horizontal; height: 3; margin-bottom: 1; }
    .field-row    { height: 3; layout: horizontal; align: left middle; margin-bottom: 1; }
    .field-label  { width: 20; color: $text-muted; }
    .field-input  { width: 1fr; border: solid $accent; }
    .btn-row      { layout: horizontal; height: 3; align: right middle; margin-top: 1; }
    .step2-title  { color: $accent; text-style: bold; margin-bottom: 1; }
    #step1        { }
    #step2        { display: none; }
    """

    def __init__(self, agent: "Agent") -> None:
        super().__init__()
        self.agent          = agent
        self._cfg           = load_config()
        self._chosen_name   = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("⬡  Select Provider", classes="modal-title")
            yield Label("Choose a provider to connect to", classes="subtitle")

            
            with Vertical(id="step1"):
                rows: list[list[str]] = [
                    ["openai",            "openrouter"],
                    ["openai_compatible", "ollama"],
                    ["lmstudio"],
                ]
                for row in rows:
                    with Horizontal(classes="btn-grid"):
                        for name in row:
                            label = PROVIDER_DEFS[name]["label"]
                            yield Button(label, id=f"pick-{name}", classes="provider-btn")
                yield Button("Cancel", variant="default", id="btn-cancel-step1")

            
            with Vertical(id="step2"):
                yield Label("", id="step2-title", classes="step2-title")
                yield Vertical(id="fields-container")
                with Horizontal(classes="btn-row"):
                    yield Button("Back", variant="default", id="btn-back")
                    yield Button("Connect", variant="success", id="btn-connect")

    def on_button_pressed(self, event: Button.Pressed) -> None:  
        bid = event.button.id or ""

        if bid == "btn-cancel-step1":
            self.dismiss(None)
            return

        if bid.startswith("pick-"):
            name = bid[len("pick-"):]
            self._chosen_name = name
            self._show_step2(name)
            return

        if bid == "btn-back":
            self.query_one("#step1").styles.display = "block"
            self.query_one("#step2").styles.display = "none"
            return

        if bid == "btn-connect":
            self._do_connect()
            return

    def _show_step2(self, name: str) -> None:
        pdef = PROVIDER_DEFS[name]

        
        self.query_one("#step2-title", Label).update(
            f"Configure  {pdef['label']}"
        )

        
        container = self.query_one("#fields-container", Vertical)
        container.remove_children()

        for field in pdef["fields"]:
            fid      = field["id"]
            flabel   = field["label"]
            password = field.get("password", False)
            cfg_key  = field.get("cfg", fid)

            
            if fid == "base_url":
                default = self._cfg.get("base_url", pdef["base_url"])
            elif fid == "model":
                default = self._cfg.get("model", self.agent.provider.model)
            elif fid == "api_key":
                env_key  = pdef.get("env_key", "")
                cfg_key2 = pdef.get("cfg_key", "api_key")
                default  = (
                    self._cfg.get(cfg_key2)
                    or self._cfg.get("api_key", "")
                    or (os.getenv(env_key, "") if env_key else "")
                )
            else:
                default = self._cfg.get(cfg_key, "")

            row = Horizontal(classes="field-row")
            row.compose_add_child(Label(f"{flabel}:", classes="field-label"))
            inp = Input(
                value=str(default or ""),
                password=password,
                id=f"field-{fid}",
                classes="field-input",
            )
            row.compose_add_child(inp)
            container.mount(row)

        self.query_one("#step1").styles.display = "none"
        self.query_one("#step2").styles.display = "block"

    def _do_connect(self) -> None:
        name = self._chosen_name
        pdef = PROVIDER_DEFS.get(name, PROVIDER_DEFS["openai_compatible"])
        cfg  = load_config()

        collected: dict[str, str] = {}
        for field in pdef["fields"]:
            fid     = field["id"]
            cfg_key = field.get("cfg", fid)
            try:
                val = self.query_one(f"#field-{fid}", Input).value.strip()
            except Exception:
                val = ""
            collected[fid] = val
            if val and cfg_key:
                cfg[cfg_key] = val

        
        if "base_url" in collected and collected["base_url"]:
            cfg["base_url"] = collected["base_url"]
        if "model" in collected and collected["model"]:
            cfg["model"] = collected["model"]
        if "api_key" in collected and collected["api_key"]:
            cfg["api_key"] = collected["api_key"]
            cfg[pdef.get("cfg_key", "api_key")] = collected["api_key"]

        cfg["provider"] = name
        save_config(cfg)

        self.dismiss((name, cfg))




class SettingsModal(ModalScreen):
    CSS = """
    SettingsModal {
        align: center middle;
    }
    SettingsModal > Vertical {
        width: 72;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    .modal-title { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    .field-row   { height: 3; layout: horizontal; align: left middle; margin-bottom: 1; }
    .field-label { width: 22; color: $text-muted; }
    .field-input { width: 1fr; border: solid $accent; }
    .btn-row     { layout: horizontal; height: 3; align: right middle; margin-top: 1; }
    """

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self.agent = agent
        self._cfg  = load_config()

    def compose(self) -> ComposeResult:
        p = self.agent.provider
        with Vertical():
            yield Label("⚙  Settings", classes="modal-title")
            with TabbedContent():
                with TabPane("General"):
                    with Horizontal(classes="field-row"):
                        yield Label("Approval mode:", classes="field-label")
                        yield Select(
                            [
                                ("safe (default)", "safe"),
                                ("never",              "never"),
                                ("always",         "always"),
                            ],
                            value=self.agent.approve_mode,
                            id="sel-approve",
                        )
                    with Horizontal(classes="field-row"):
                        yield Label("Context length:", classes="field-label")
                        yield Input(
                            value=str(self.agent.context.max_tokens),
                            id="inp-ctx-len",
                            classes="field-input",
                        )
                with TabPane("Provider"):
                    
                    pname = self._cfg.get("provider", "openai_compatible")
                    pdef  = PROVIDER_DEFS.get(pname, PROVIDER_DEFS["openai_compatible"])
                    yield Label(f"Provider:  {pdef['label']}", classes="field-label")
                    yield Static("")
                    for field in pdef["fields"]:
                        fid      = field["id"]
                        flabel   = field["label"]
                        password = field.get("password", False)
                        cfg_key  = field.get("cfg", fid)

                        if fid == "base_url":
                            default = self._cfg.get("base_url", pdef["base_url"])
                        elif fid == "model":
                            default = self._cfg.get("model", p.model)
                        elif fid == "api_key":
                            env_key  = pdef.get("env_key", "")
                            cfg_key2 = pdef.get("cfg_key", "api_key")
                            default  = (
                                self._cfg.get(cfg_key2)
                                or self._cfg.get("api_key", "")
                                or (os.getenv(env_key, "") if env_key else "")
                            )
                        else:
                            default = self._cfg.get(cfg_key, "")

                        with Horizontal(classes="field-row"):
                            yield Label(f"{flabel}:", classes="field-label")
                            yield Input(
                                value=str(default or ""),
                                password=password,
                                id=f"prov-field-{fid}",
                                classes="field-input",
                            )
                with TabPane("About"):
                    pname = self._cfg.get("provider", "?")
                    yield Static(
                        f"[bold cyan]Model:[/bold cyan]     {p.model}\n"
                        f"[bold cyan]Provider:[/bold cyan]  {pname}  ({p.__class__.__name__})\n"
                        f"[bold cyan]Tools:[/bold cyan]     {len(self.agent.tools)}\n"
                        f"[bold cyan]Messages:[/bold cyan]  {len(self.agent.context.messages)}\n"
                        f"[bold cyan]CWD:[/bold cyan]       {os.getcwd()}",
                        markup=True,
                    )
            with Horizontal(classes="btn-row"):
                yield Button("Save", variant="success", id="btn-save")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return

        cfg = load_config()
        pname = cfg.get("provider", "openai_compatible")
        pdef  = PROVIDER_DEFS.get(pname, PROVIDER_DEFS["openai_compatible"])

        
        try:
            v = self.query_one("#sel-approve", Select).value
            if v and v != Select.BLANK:
                self.agent.approve_mode = v
                cfg["approve_mode"] = v
        except Exception:
            pass
        try:
            n = int(self.query_one("#inp-ctx-len", Input).value)
            self.agent.context.max_tokens = n
            self.agent.provider.context_length = n
            cfg["context_length"] = n
        except Exception:
            pass

        
        for field in pdef["fields"]:
            fid     = field["id"]
            cfg_key = field.get("cfg", fid)
            try:
                val = self.query_one(f"#prov-field-{fid}", Input).value.strip()
                if val:
                    cfg[cfg_key] = val
                    if fid == "base_url":
                        p = self.agent.provider
                        if hasattr(p, "set_base_url"):
                            p.set_base_url(val)
                        elif hasattr(p, "base_url"):
                            p.base_url = val
                    elif fid == "model":
                        try:
                            self.agent.provider.set_model(val)
                        except Exception:
                            pass
            except Exception:
                pass

        save_config(cfg)
        save_workspace(self.agent)
        self.dismiss("saved")




class ModelPickerModal(ModalScreen):
    CSS = """
    ModelPickerModal {
        align: center middle;
    }
    ModelPickerModal > Vertical {
        width: 62; height: 80%;
        background: $surface; border: round $accent; padding: 1 2;
    }
    .modal-title   { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    #model-search  { border: solid $accent; margin-bottom: 1; }
    #model-list    { height: 1fr; border: solid $panel; }
    """

    def __init__(self, models: list[str], current: str) -> None:
        super().__init__()
        self._all = models
        self._cur = current

    def _make_items(self, q: str = "") -> list[ListItem]:
        filtered = [m for m in self._all if q.lower() in m.lower()]
        items = []
        for m in filtered:
            marker = "[bold green]●[/bold green]" if m == self._cur else "[dim]○[/dim]"
            items.append(ListItem(Label(f"{marker}  {m}", markup=True), name=m))
        return items

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("⬡  Select Model", classes="modal-title")
            yield Input(placeholder="Filter…", id="model-search")
            yield ListView(*self._make_items(), id="model-list")
            yield Button("Cancel", variant="default", id="btn-cancel")

    def on_input_changed(self, event: Input.Changed) -> None:
        lv = self.query_one("#model-list", ListView)
        lv.clear()
        for item in self._make_items(event.value):
            lv.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.name)

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss(None)

class StreamView(Static):
    DEFAULT_CSS = """
    StreamView {
        height: auto;
        max-height: 60%;
        padding: 0 2;
        background: $background;
        overflow-y: auto;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__("", *args, **kwargs)

        self._lines: list[str] = []
        self._partial: str = ""

        self._lock = threading.Lock()
        self._streaming = False

    def push_chunk(self, text: str) -> None:
        with self._lock:
            self._partial += text

            while "\n" in self._partial:
                line, self._partial = self._partial.split("\n", 1)
                self._lines.append(line)

            self._streaming = True

        self.app.call_from_thread(self._update_display)

    def _update_display(self):
        with self._lock:
            content = "\n".join(self._lines)

            if self._partial:
                if content:
                    content += "\n"
                content += self._partial

            streaming = self._streaming

        if streaming:
            self.styles.border = ("solid", "blue")
        else:
            self.styles.border = None

        super().update(
            Markdown(
                content,
                code_theme="monokai",
            )
        )

    def commit(self) -> str:
        with self._lock:
            if self._partial:
                self._lines.append(self._partial)
                self._partial = ""

            full = "\n".join(self._lines)

            self._lines = []
            self._streaming = False

        self.app.call_from_thread(self._update_display)

        return full

    def cancel(self) -> str:
        return self.commit()

class AgentTUI(App):
    CSS = """
    Screen { layers: base; }
    #log {
        height: 1fr;
        border: none;
        padding: 0 2;
        scrollbar-gutter: stable;
    }
    StreamView {
        height: auto;
        max-height: 60%;
        padding: 0 2;
        background: $background;
    }
    #input-bar {
        height: 3;
        border-top: solid $accent;
        background: $surface;
        padding: 0 1;
        layout: horizontal;
        align: left middle;
    }
    #prompt-label {
        width: auto;
        color: $accent;
        padding: 0 1 0 0;
        content-align: left middle;
    }
    #prompt-label.question-mode { color: yellow; }
    #cmd-input {
        height: 1;
        width: 1fr;
        border: none;
        background: transparent;
    }
    #cmd-input:focus { border: none; }
    Footer { height: 1; }
    """

    BINDINGS = [
        Binding("ctrl+p", "toggle_pause",      "Pause/Resume"),
        Binding("ctrl+c", "do_interrupt",       "Interrupt"),
        Binding("ctrl+s", "open_settings",      "Settings"),
        Binding("ctrl+m", "open_model_picker",  "Models"),
        Binding("ctrl+r", "open_provider_picker", "Provider"),
    ]

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self.agent = agent
        self._R    = Renderer()

        self._approval_needed = threading.Event()
        self._approval_done   = threading.Event()
        self._approval_tool   = ""

        self._question_needed       = threading.Event()
        self._question_done         = threading.Event()
        self._question_suggestions: list[str] = []
        self._question_answer_ref:  list[str] = []

        self._streaming = False

    def compose(self) -> ComposeResult:
        yield StatusBar(id="statusbar")
        yield RichLog(id="log", highlight=False, markup=False, wrap=True)
        yield StreamView(id="stream-view")
        with Horizontal(id="input-bar"):
            yield Label("❯", id="prompt-label")
            yield Input(
                placeholder="Type a task or /help…",
                id="cmd-input",
                suggester=CommandSuggester(self),
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#cmd-input", Input).focus()
        self._tick_status()
        self.set_interval(2, self._tick_status)

    def _tick_status(self) -> None:
        try:
            p    = self.agent.provider
            cfg  = load_config()
            pname = cfg.get("provider", p.__class__.__name__.replace("Provider", "").lower())
            pdef  = PROVIDER_DEFS.get(pname, {})
            plabel = pdef.get("label", pname)
            self.query_one(StatusBar).refresh_status(
                model         = p.model.split("/")[-1],
                provider_name = plabel,
                cwd           = os.getcwd(),
                tokens        = self.agent.context.estimate_tokens(),
                max_tokens    = self.agent.context.max_tokens,
                usage         = self.agent.context.usage_percent(),
                paused        = self.agent.is_paused,
            )
        except Exception:
            pass

    def _write(self, renderable: Any) -> None:
        def _do():
            self.query_one("#log", RichLog).write(renderable)
        try:
            self.call_from_thread(_do)
        except Exception:
            _do()

    def _write_many(self, items: list) -> None:
        for r in items:
            self._write(r)

    def _sv(self) -> StreamView:
        return self.query_one("#stream-view", StreamView)

    def _stream_chunk(self, text: str) -> None:
        if not self._streaming:
            self._streaming = True
        self._sv().push_chunk(text)

    def _stream_close(self) -> None:
        if not self._streaming:
            return
        self._streaming = False
        sv        = self._sv()
        full_text = sv.commit()
        if full_text.strip():
            def _commit():
                log = self.query_one("#log", RichLog)
                log.write(Text(""))
                log.write(
                    Markdown(
                        full_text,
                        code_theme="monokai",
                    )
                )
                log.write(Text(""))
            try:
                self.call_from_thread(_commit)
            except Exception:
                _commit()

    def _stream_cancel(self) -> None:
        if not self._streaming:
            return
        self._streaming = False
        sv      = self._sv()
        partial = sv.cancel()
        if partial.strip():
            def _commit():
                log = self.query_one("#log", RichLog)
                log.write(Text(""))
                log.write(
                    Markdown(
                        partial,
                        code_theme="monokai",
                    )
                )
                t = Text()
                t.append("  … interrupted", style=C.WARN)
                log.write(t)
            try:
                self.call_from_thread(_commit)
            except Exception:
                _commit()

    

    def _enter_question_mode(self, suggestions: list[str]) -> None:
        self._question_suggestions = suggestions
        label = self.query_one("#prompt-label", Label)
        label.update("?›")
        label.add_class("question-mode")
        self.query_one("#cmd-input", Input).placeholder = (
            "Type answer" + (f" or 1–{len(suggestions)}" if suggestions else "") + "…"
        )

    def _leave_question_mode(self) -> None:
        self._question_suggestions = []
        label = self.query_one("#prompt-label", Label)
        label.update("❯")
        label.remove_class("question-mode")
        self.query_one("#cmd-input", Input).placeholder = "Type a task or /help…"

    

    def event_handler(self, event: str, data: dict) -> None:  

        if event == "task_started":
            self._write_many(self._R.task_started(data["prompt"]))

        elif event == "model_processing":
            self._write_many(self._R.thinking())

        elif event == "stream_chunk":
            if data.get("type") == "text":
                self._stream_chunk(data["content"])

        elif event == "provider_response":
            self._stream_close()

        elif event == "tool_call":
            tool = data.get("tool", "")
            if not tool or tool in {"FinishTask", "FinishTaskTool", "Question", "QuestionTool"}:
                return
            self._stream_close()
            self._write_many(self._R.tool_call(tool, data.get("args", {})))

        elif event == "tool_finished":
            self._stream_close()
            tool = data.get("tool", "")
            if tool not in {"Question", "QuestionTool"}:
                self._write_many(self._R.tool_result(tool, data.get("result")))

        elif event == "tool_error":
            self._stream_close()
            self._write_many(self._R.tool_error(
                data.get("tool", "?"), data.get("error", "unknown error")
            ))

        elif event == "approval_requested":
            self._stream_close()
            self._approval_tool = data["tool"]
            self._approval_done.clear()
            self._approval_needed.set()
            self._write_many(self._R.approval_request(data["tool"]))
            self._approval_done.wait()

        elif event == "approval_denied":
            self._write_many(self._R.approval_result(False, data.get("tool", "")))

        elif event == "approval_granted":
            self._write_many(self._R.approval_result(True, data.get("tool", "")))

        elif event == "context_compressed":
            self._write_many(self._R.context_compressed(
                data.get("before_tokens", 0), data.get("after_tokens", 0)
            ))

        elif event == "context_compression_error":
            self._write_many(self._R.task_error(data.get("error", "")))

        elif event == "task_error":
            self._stream_close()
            self._write_many(self._R.task_error(data.get("error", "")))

        elif event == "question_requested":
            self._stream_close()
            question    = data.get("question", "")
            context     = data.get("context", "")
            suggestions = data.get("suggestions", [])

            self._write_many(self._R.question_request(question, context, suggestions))

            self._question_answer_ref.clear()
            self._question_done.clear()
            self._question_needed.set()
            try:
                self.call_from_thread(self._enter_question_mode, suggestions)
            except Exception:
                self._enter_question_mode(suggestions)

            self._question_done.wait()

            answer = self._question_answer_ref[0] if self._question_answer_ref else ""
            self._write_many(self._R.question_answer(answer))
            self.agent.resolve_question(answer)

        elif event == "task_finished":
            self._stream_close()
            save_workspace(self.agent)
            try:
                self.call_from_thread(self._tick_status)
            except Exception:
                pass

    

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        if self._approval_needed.is_set():
            self._approval_needed.clear()
            ans = text.lower()
            if ans == "a":
                self.agent.approve_mode = "always"
                self.agent.resolve_approval(True)
            elif ans in {"y", "yes"}:
                self.agent.resolve_approval(True)
            else:
                self.agent.resolve_approval(False)
            self._approval_done.set()
            return

        if self._question_needed.is_set():
            self._question_needed.clear()
            suggestions = self._question_suggestions
            answer = text
            if text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(suggestions):
                    answer = suggestions[idx]
            self._question_answer_ref.clear()
            self._question_answer_ref.append(answer)
            try:
                self.call_from_thread(self._leave_question_mode)
            except Exception:
                self._leave_question_mode()
            self._question_done.set()
            return

        self._dispatch(text)

    

    def _dispatch(self, text: str) -> None:  
        t = text.strip()

        def info(msg: str) -> None:
            r = Text(); r.append("  "); r.append(msg, style=C.DIM); self._write(r)

        def ok(msg: str) -> None:
            r = Text(); r.append("  ✓ ", style=C.OK); r.append(msg, style=C.DIM); self._write(r)

        def err(msg: str) -> None:
            r = Text(); r.append("  ✗ ", style=C.ERR); r.append(msg); self._write(r)

        if t in {"/quit", "/exit"}:
            self.exit()

        elif t in {"/help", "?"}:
            tbl = Table(border_style="grey30", show_header=False, padding=(0, 2),
                        box=None, pad_edge=False)
            tbl.add_column("cmd",  style="bold cyan", no_wrap=True, min_width=32)
            tbl.add_column("desc", style="grey62")
            rows = [
                ("/help",                                    "This help"),
                ("/tools",                                   "List tools"),
                ("/model-picker  (Ctrl+M)",                  "Model picker"),
                ("/provider  (Ctrl+R)",                      "Provider picker"),
                ("/settings  (Ctrl+S)",                      "Settings modal"),
                ("/context",                                 "Token usage"),
                ("/history",                                 "Message history"),
                ("/reset",                                   "Clear context"),
                ("/approve [never|safe|always]","Approval mode"),
                ("/baseurl [url]",                           "Show / set base URL"),
                ("/set_context_length <n>",                  "Max tokens"),
                ("/compress_context",                        "Compress now"),
                ("/pause  /resume  Ctrl+P",                  "Pause / resume"),
                ("/steer [text|clear]",                      "Steering instructions"),
                ("/queue",                                   "Task queue"),
                ("/clear",                                   "Clear log"),
                ("/quit",                                    "Exit"),
            ]
            for cmd, desc in rows:
                tbl.add_row(cmd, desc)
            self._write(Text(""))
            self._write(tbl)
            self._write(Text(""))

        elif t == "/tools":
            names = sorted(
                self.agent.tools.keys()
                if isinstance(self.agent.tools, dict)
                else self.agent.tools
            )
            self._write(Text(""))
            for n in names:
                r = Text()
                r.append(f"  {_icon(n)} ", style=C.TOOL_ICON)
                r.append(n, style=C.TOOL_NAME)
                self._write(r)
            self._write(Text(""))

        elif t == "/settings":
            self.action_open_settings()

        elif t == "/provider":
            self.action_open_provider_picker()

        elif t == "/context":
            tok   = self.agent.context.estimate_tokens()
            max_t = self.agent.context.max_tokens
            use   = self.agent.context.usage_percent()
            col   = _token_color(use)
            r = Text()
            r.append("  Messages: ", style=C.MUTED)
            r.append(f"{len(self.agent.context.messages)}", style="white")
            r.append("   Tokens: ", style=C.MUTED)
            r.append(f"{tok:,} / {max_t:,}", style=col)
            r.append(f"  ({use:.0f}%)", style=col)
            r.append(f"  {_context_bar(use)}", style="")
            self._write(r)

        elif t == "/history":
            msgs = self.agent.context.messages
            if not msgs:
                info("History is empty")
                return
            for i, msg in enumerate(msgs, 1):
                content = msg.content
                if hasattr(content, "text"):
                    content = content.text
                preview = str(content)[:300].replace("\n", " ")
                r = Text()
                r.append(f"  {i:3}  ", style=C.MUTED)
                r.append(f"{msg.role:<12}", style="bold cyan" if msg.role == "assistant" else "bold white")
                r.append(preview, style=C.DIM)
                self._write(r)

        elif t == "/reset":
            self.agent.context = Context(provider=self.agent.provider)
            self.agent.context.compression_callback = self.agent._on_context_compressed
            self.agent.context.set_system_prompt(self.agent._system_prompt)
            save_workspace(self.agent)
            ok("Context cleared")
            self._tick_status()

        elif t == "/clear":
            self.query_one("#log", RichLog).clear()

        elif t == "/approve":
            info(f"Approval mode: {self.agent.approve_mode}")

        elif t.startswith("/approve "):
            mode = t.split(maxsplit=1)[1].strip()
            if mode not in {"never", "safe", "always"}:
                err("Valid: never | safe | always")
                return
            self.agent.approve_mode = mode
            cfg = load_config(); cfg["approve_mode"] = mode
            save_config(cfg); save_workspace(self.agent)
            ok(f"Approval → {mode}")

        elif t == "/baseurl":
            info(f"Base URL: {getattr(self.agent.provider, 'base_url', 'N/A')}")

        elif t.startswith("/baseurl "):
            url = t.split(maxsplit=1)[1].strip()
            p = self.agent.provider
            if hasattr(p, "set_base_url"):
                p.set_base_url(url)
            elif hasattr(p, "base_url"):
                p.base_url = url
            cfg = load_config(); cfg["base_url"] = url
            save_config(cfg); save_workspace(self.agent)
            ok(f"Base URL → {url}")

        elif t.startswith("/set_context_length "):
            val = t.split(maxsplit=1)[1].strip()
            if not val.isdigit():
                err("Usage: /set_context_length <n>")
                return
            n = int(val)
            self.agent.provider.context_length = n
            cfg = load_config(); cfg["context_length"] = n
            save_config(cfg); save_workspace(self.agent)
            ok(f"Context length → {n:,}")
            self._tick_status()

        elif t == "/compress_context":
            info("Compressing context…")
            self.agent.context.compress()

        elif t == "/pause":
            self.agent.pause()
            r = Text(); r.append("  ⏸ Paused", style=C.WARN)
            self._write(r); self._tick_status()

        elif t == "/resume":
            self.agent.resume()
            r = Text(); r.append("  ▶ Resumed", style=C.OK)
            self._write(r); self._tick_status()

        elif t == "/steer":
            instrs = getattr(self.agent.steering, "instructions", [])
            if not instrs:
                info("No steering instructions")
            else:
                for i, s in enumerate(instrs, 1):
                    r = Text()
                    r.append(f"  {i}. ", style=C.MUTED)
                    r.append(s, style="white")
                    self._write(r)

        elif t == "/steer clear":
            self.agent.clear_instructions()
            ok("Steering cleared")

        elif t.startswith("/steer "):
            instr = t[len("/steer "):]
            self.agent.add_instruction(instr)
            ok(f"Steering: {instr}")

        elif t == "/queue":
            items = list(self.agent.task_queue.queue)
            cur   = self.agent.current_task
            if not cur and not items:
                info("Queue empty")
                return
            if cur:
                r = Text()
                r.append("  ▶ ", style="bold cyan")
                r.append(cur.prompt[:80], style="white")
                self._write(r)
            for task in items:
                r = Text()
                r.append("  ○ ", style=C.MUTED)
                r.append(task.prompt[:80], style=C.DIM)
                self._write(r)

        elif t.startswith("/"):
            err(f"Unknown: {t}  (/help)")

        else:
            self.agent.enqueue(prompt=t, task_id=str(time.time()))

    

    def _set_model(self, model: str) -> None:
        try:
            models = self.agent.provider.get_models()
            if isinstance(models, list) and model not in models:
                r = Text(); r.append("  ✗ ", style=C.ERR); r.append(f"Unknown model: {model}")
                self._write(r); return
        except Exception:
            pass
        try:
            self.agent.provider.set_model(model)
        except Exception as e:
            r = Text(); r.append("  ✗ ", style=C.ERR); r.append(str(e))
            self._write(r); return
        cfg = load_config(); cfg["model"] = model
        save_config(cfg); save_workspace(self.agent)
        r = Text(); r.append("  ✓ ", style=C.OK); r.append(f"Model → {model}", style=C.DIM)
        self._write(r); self._tick_status()

    def _apply_provider_result(self, result) -> None:
        if result is None:
            return
        name, cfg = result
        tools = (
            list(self.agent.tools.values())
            if isinstance(self.agent.tools, dict)
            else self.agent.tools
        )
        try:
            new_provider = _build_provider(name, cfg, tools, self.agent.provider.model)
            self.agent.provider = new_provider
            save_workspace(self.agent)
            r = Text()
            r.append("  ✓ ", style=C.OK)
            pdef = PROVIDER_DEFS.get(name, {})
            r.append(f"Provider → {pdef.get('label', name)}", style=C.DIM)
            self._write(r)
            self._tick_status()
        except Exception as e:
            r = Text(); r.append("  ✗ ", style=C.ERR); r.append(f"Provider error: {e}")
            self._write(r)

    def action_toggle_pause(self) -> None:
        if self.agent.is_paused:
            self.agent.resume()
            r = Text(); r.append("  ▶ Resumed", style=C.OK); self._write(r)
        else:
            self.agent.pause()
            r = Text(); r.append("  ⏸ Paused", style=C.WARN); self._write(r)
        self._tick_status()

    def action_do_interrupt(self) -> None:
        self._stream_cancel()

    def action_open_settings(self) -> None:
        def _cb(result):
            if result == "saved":
                r = Text(); r.append("  ✓ ", style=C.OK)
                r.append("Settings saved", style=C.DIM); self._write(r)
                self._tick_status()
        self.push_screen(SettingsModal(self.agent), _cb)

    def action_open_provider_picker(self) -> None:
        self.push_screen(ProviderPickerModal(self.agent), self._apply_provider_result)

    def action_open_model_picker(self) -> None:
        try:
            models = self.agent.provider.get_models()
        except Exception:
            r = Text(); r.append("  ✗ ", style=C.ERR)
            r.append("Could not fetch models"); self._write(r); return
        if not isinstance(models, list) or not models:
            r = Text(); r.append("  ", style=""); r.append("No models available", style=C.MUTED)
            self._write(r); return
        self.push_screen(
            ModelPickerModal(models, self.agent.provider.model),
            lambda m: m and self._set_model(m),
        )

    def run_tui(self) -> None:
        self.run()