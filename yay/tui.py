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
    Button, Select, TabbedContent, TabPane, ListView, ListItem, DataTable,
)
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.events import Key
from rich.text import Text
from rich.table import Table
from rich.markdown import Markdown
from pathlib import Path

from .agent import Agent
from .llm import Context
from .renderer import Renderer, C, _icon, _token_color
from .config import load_config, save_config
from .workspace import save_workspace
from .managers import ProviderManager, ToolsManager
from .mcp import MCPManager
from .events import (
    EventBus,
    TaskStartedEvent, ModelProcessingEvent, ApprovalRequestedEvent,
    StreamChunkEvent, ProviderResponseEvent, TaskFinishedEvent, TaskErrorEvent,
    ToolCallEvent, ToolFinishedEvent, ContextCompressedEvent, ErrorEvent,
    ApprovalGrantedEvent, ApprovalDeniedEvent, ToolErrorEvent,
    QuestionRequestedEvent, ContextCompressionErrorEvent,
    AgentPausedEvent, AgentResumedEvent, ToolStartedEvent,
)

BAR_WIDTH = 20

def _build_provider_from_providers_manager(
    providers_manager, tools_manager, name, cfg, tools, current_model, bus
):
    import inspect
    cls = providers_manager.get_provider(name)
    if cls is None:
        raise ValueError(f"Provider '{name}' not found in ProviderManager")
    sig    = inspect.signature(cls.__init__)
    params = set(sig.parameters.keys()) - {"self"}
    kwargs: dict[str, Any] = {}
    if "api_key" in params:
        kwargs["api_key"] = cfg.get("api_key", cfg.get("openai_api_key", "dummy")) or "dummy"
    if "model" in params:
        kwargs["model"] = cfg.get("model", current_model) or current_model
    if "tools_manager" in params:
        kwargs["tools_manager"] = tools_manager
    if "base_url" in params:
        base_url = cfg.get("base_url")
        if base_url:
            kwargs["base_url"] = base_url
    if "tools" in params:
        kwargs["tools"] = tools
    kwargs["bus"] = bus
    for key, val in cfg.items():
        if key in params and key not in kwargs and val:
            kwargs[key] = val
    return cls(**kwargs)

def _context_bar(usage: float) -> str:
    usage  = max(0.0, min(100.0, usage))
    filled = round(BAR_WIDTH * usage / 100)
    empty  = BAR_WIDTH - filled
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
    return "".join(segments) + f"[bright_black]{'░' * empty}[/]"

def _mcp_n(mcp_manager: MCPManager | None) -> int:
    if mcp_manager is None:
        return 0
    return len(mcp_manager._configs)

def _mcp_keys(mcp_manager: MCPManager) -> list[str]:
    return list(mcp_manager._configs.keys())

def _mcp_key_by_index(mcp_manager: MCPManager, idx: int) -> str | None:
    keys = _mcp_keys(mcp_manager)
    if 0 <= idx < len(keys):
        return keys[idx]
    return None

class CommandSuggester(Suggester):
    COMMANDS = [
        "/help", "/tools",
        "/settings", "/provider",
        "/context", "/history", "/reset", "/clear", "/quit",
        "/approve", "/approve never", "/approve safe", "/approve always",
        "/baseurl", "/set_context_length", "/compress_context",
        "/pause", "/resume", "/interrupt",
        "/steer", "/steer clear",
        "/queue",
        "/mcp", "/mcp add", "/mcp remove", "/mcp enable", "/mcp disable",
        "/mcp reload", "/mcp ping", "/mcp list",
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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("Initializing…", *args, **kwargs)

    def refresh_status(self, model, provider_name, cwd, tokens,
                       max_tokens, usage, paused, interrupted, n_mcp=0) -> None:
        project  = Path(cwd).name or cwd
        bar      = _context_bar(usage)
        if interrupted:
            state = " [red]✗ interrupted[/]"
        elif paused:
            state = " [yellow]⏸ paused[/]"
        else:
            state = ""
        pcolor   = "bright_cyan" if provider_name != "?" else "grey50"
        mcp_info = f"  [grey50]mcp:{n_mcp}[/]" if n_mcp > 0 else ""

        if max_tokens > 0:
            token_str = f"[bright_black]{tokens:,}/{max_tokens:,}[/]"
            usage_str = f"[bright_black]{usage:.0f}%[/]"
        else:
            token_str = f"[bright_black]{tokens:,}[/]"
            usage_str = "[bright_black]?%[/]"

        self.update(
            f"[{pcolor}]{provider_name}[/]"
            f"  [cyan]{model}[/]"
            f"{state}"
            f"  [bold]{project}[/]"
            f"{mcp_info}"
            f"  {bar}"
            f" {usage_str}"
            f"  {token_str}"
        )

class MCPModal(ModalScreen):
    CSS = """
    MCPModal { align: center middle; }

    MCPModal > Vertical {
        width: 82;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }

    .modal-title  { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    .subtitle     { color: $text-muted; margin-bottom: 1; }

    #mcp-table    { height: auto; max-height: 16; border: solid $panel; margin-bottom: 1; }

    .add-row      { height: 3; layout: horizontal; align: left middle; margin-bottom: 1; }
    .add-input    { width: 1fr; border: solid $accent; }

    .btn-grid     { layout: vertical; height: auto; margin-bottom: 1; }

    .mcp-btn      { width: 100%; margin: 0 0 1 0; }

    .btn-row      { layout: horizontal; height: 3; align: right middle; margin-top: 1; }

    #mcp-status   { height: 1; color: $text-muted; margin-bottom: 1; }
    """

    def __init__(self, mcp_manager: MCPManager) -> None:
        super().__init__()
        self._mgr = mcp_manager

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("⬡  MCP Servers", classes="modal-title")
            yield Label(
                "Add / remove MCP servers. Tools are registered automatically.",
                classes="subtitle",
            )

            yield DataTable(id="mcp-table", cursor_type="row")
            yield Label("", id="mcp-status")

            with Horizontal(classes="add-row"):
                yield Input(
                    placeholder="http://localhost:8000 or stdio://npx -y @mcp/server",
                    id="inp-mcp-url",
                    classes="add-input",
                )
                yield Button("Add", variant="success", id="btn-mcp-add")

            with Vertical(classes="btn-grid"):
                yield Button("Enable", id="btn-mcp-toggle", classes="mcp-btn")
                yield Button("Remove", id="btn-mcp-remove", classes="mcp-btn", variant="error")
                yield Button("Reload ↺", id="btn-mcp-reload", classes="mcp-btn")
                yield Button("Ping", id="btn-mcp-ping", classes="mcp-btn")

            with Horizontal(classes="btn-row"):
                yield Button("Close", variant="default", id="btn-mcp-close")

    def on_mount(self) -> None:
        self._populate()
        self._refresh_buttons()

    def _set_status(self, msg: str, color: str = "grey50") -> None:
        try:
            self.query_one("#mcp-status", Label).update(f"[{color}]{msg}[/]")
        except Exception:
            pass

    def _selected_index(self) -> int | None:
        tbl = self.query_one("#mcp-table", DataTable)
        if tbl.row_count == 0:
            return None
        return tbl.cursor_row

    def _selected_key(self) -> str | None:
        idx = self._selected_index()
        if idx is None:
            return None
        rows = self._mgr.status_rows()
        if idx < 0 or idx >= len(rows):
            return None
        return rows[idx]["key"]

    def _is_enabled(self, key: str) -> bool:
        rows = self._mgr.status_rows()
        for r in rows:
            if r["key"] == key:
                return bool(r["enabled"])
        return False

    def _populate(self, extra_col: dict | None = None) -> None:
        tbl = self.query_one("#mcp-table", DataTable)
        tbl.clear(columns=True)

        cols = ["#", "Server", "Connected", "Enabled", "Tools", "Resources", "Prompts"]
        if extra_col:
            cols.append(extra_col["name"])

        tbl.add_columns(*cols)

        for row in self._mgr.status_rows():
            en_mark = "✓" if row["enabled"] else "✗"
            con_mark = "live" if row["connected"] else "—"
            display = row.get("url") or row.get("label") or row["key"]

            if len(display) > 48:
                display = display[:45] + "…"

            cells = [
                str(row["index"] + 1),
                display,
                con_mark,
                en_mark,
                str(row["n_tools"]),
                str(row["n_resources"]),
                str(row["n_prompts"]),
            ]

            if extra_col:
                cells.append(extra_col["data"].get(row["key"], "?"))

            tbl.add_row(*cells)

    def _refresh_buttons(self) -> None:
        btn = self.query_one("#btn-mcp-toggle", Button)

        key = self._selected_key()
        if not key:
            btn.label = "Enable"
            btn.variant = "default"
            return

        enabled = self._is_enabled(key)

        if enabled:
            btn.label = "Disable"
            btn.variant = "warning"
        else:
            btn.label = "Enable"
            btn.variant = "success"

    def _add_server(self, spec: str) -> None:
        spec = spec.strip()
        if not spec:
            return

        try:
            if spec.startswith("stdio://"):
                import shlex
                cmd = shlex.split(spec[len("stdio://"):].strip())
                self._mgr.add_stdio(cmd)
                key = f"stdio://{' '.join(cmd)}"
                self._mgr.connect(key)
            else:
                self._mgr.add(spec)
                self._mgr.connect(spec)

            self._set_status("Server added", "green")

        except Exception as e:
            self._set_status(f"Connect failed: {e}", "yellow")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id

        if bid == "btn-mcp-close":
            self.dismiss(None)

        elif bid == "btn-mcp-add":
            spec = self.query_one("#inp-mcp-url", Input).value.strip()
            if not spec:
                self._set_status("Enter URL or stdio:// command", "yellow")
                return

            self._add_server(spec)
            self.query_one("#inp-mcp-url", Input).value = ""
            self._populate()

        elif bid == "btn-mcp-toggle":
            key = self._selected_key()
            if not key:
                self._set_status("Select a server", "yellow")
                return

            if self._is_enabled(key):
                self._mgr.disable(key)
                self._set_status("Disabled", "grey50")
            else:
                self._mgr.enable(key)
                try:
                    self._mgr.connect(key)
                except Exception:
                    pass
                self._set_status("Enabled", "green")

            self._populate()
            self._refresh_buttons()

        elif bid == "btn-mcp-remove":
            key = self._selected_key()
            if key:
                self._mgr.remove(key)
                self._set_status("Removed", "grey50")

            self._populate()
            self._refresh_buttons()

        elif bid == "btn-mcp-reload":
            self._set_status("Reloading…", "grey50")
            results = self._mgr.reload_all()

            ok = sum(1 for r in results.values() if r.get("ok"))
            err = len(results) - ok

            self._set_status(
                f"Reloaded {ok} ok, {err} failed",
                "green" if err == 0 else "yellow",
            )

            self._populate()
            self._refresh_buttons()

        elif bid == "btn-mcp-ping":
            self._set_status("Pinging…", "grey50")

            statuses = self._mgr.ping_all()
            alive = sum(1 for v in statuses.values() if v)

            self._set_status(
                f"Ping: {alive}/{len(statuses)} alive",
                "green",
            )

            self._populate()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._refresh_buttons()

class ProviderPickerModal(ModalScreen):
    CSS = """
    ProviderPickerModal { align: center middle; }
    ProviderPickerModal > Vertical {
        width: 68; height: auto; max-height: 85%;
        background: $surface; border: round $accent; padding: 1 2;
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
    #step2        { display: none; }
    """

    _FIELD_HINTS: dict[str, dict] = {
        "api_key":            {"label": "API Key",    "password": True},
        "openai_api_key":     {"label": "API Key",    "password": True},
        "openrouter_api_key": {"label": "API Key",    "password": True},
        "base_url":           {"label": "Base URL",   "password": False},
        "model":              {"label": "Model",      "password": False},
        "context_length":     {"label": "Ctx Length", "password": False},
    }

    def __init__(self, agent: Agent, manager: ProviderManager) -> None:
        super().__init__()
        self.agent             = agent
        self.providers_manager = manager
        self._cfg              = load_config()
        self._chosen_name      = ""

    def _provider_fields(self, name: str) -> list[dict]:
        import inspect
        cls = self.providers_manager.get_provider(name)
        if cls is None:
            return []
        sig    = inspect.signature(cls.__init__)
        fields = []
        skip   = {"self", "tools", "kwargs", "args"}
        for param_name, param in sig.parameters.items():
            if param_name in skip:
                continue
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            hint = self._FIELD_HINTS.get(param_name, {})
            fields.append({
                "id":       param_name,
                "label":    hint.get("label", param_name.replace("_", " ").title()),
                "password": hint.get("password", False),
                "default":  (
                    "" if param.default is inspect.Parameter.empty
                    else ("" if param.default is None else str(param.default))
                ),
            })
        return fields

    def compose(self) -> ComposeResult:
        providers = self.providers_manager.get_providers()
        with Vertical():
            yield Label("⬡  Select Provider", classes="modal-title")
            yield Label("Choose a provider to connect to", classes="subtitle")
            with Vertical(id="step1"):
                names = list(providers.keys())
                for i in range(0, len(names), 2):
                    row_names = names[i:i + 2]
                    with Horizontal(classes="btn-grid"):
                        for n in row_names:
                            cls   = providers[n]
                            label = getattr(cls, "provider_name", n)
                            yield Button(label, id=f"pick-{n}", classes="provider-btn")
                yield Button("Cancel", variant="default", id="btn-cancel-step1")
            with Vertical(id="step2"):
                yield Label("", id="step2-title", classes="step2-title")
                yield Vertical(id="fields-container")
                with Horizontal(classes="btn-row"):
                    yield Button("Back",    variant="default", id="btn-back")
                    yield Button("Connect", variant="success", id="btn-connect")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-cancel-step1":
            self.dismiss(None)
        elif bid.startswith("pick-"):
            self._chosen_name = bid[len("pick-"):]
            self._show_step2(self._chosen_name)
        elif bid == "btn-back":
            self.query_one("#step1").styles.display = "block"
            self.query_one("#step2").styles.display = "none"
        elif bid == "btn-connect":
            self._do_connect()

    def _show_step2(self, name: str) -> None:
        cls   = self.providers_manager.get_provider(name)
        label = getattr(cls, "provider_name", name) if cls else name
        self.query_one("#step2-title", Label).update(f"Configure  {label}")
        container = self.query_one("#fields-container", Vertical)
        container.remove_children()
        for field in self._provider_fields(name):
            fid      = field["id"]
            flabel   = field["label"]
            password = field["password"]
            default  = (
                self._cfg.get(fid)
                or os.getenv(fid.upper(), "")
                or field["default"]
            )
            if fid == "model":
                default = self._cfg.get("model", self.agent.provider.model) or field["default"]
            row = Horizontal(classes="field-row")
            row.compose_add_child(Label(f"{flabel}:", classes="field-label"))
            row.compose_add_child(Input(
                value=str(default), password=password,
                id=f"field-{fid}", classes="field-input",
            ))
            container.mount(row)
        self.query_one("#step1").styles.display = "none"
        self.query_one("#step2").styles.display = "block"

    def _do_connect(self) -> None:
        name   = self._chosen_name
        fields = self._provider_fields(name)
        cfg    = load_config()
        for field in fields:
            fid = field["id"]
            try:
                val = self.query_one(f"#field-{fid}", Input).value.strip()
            except Exception:
                val = ""
            if val:
                cfg[fid] = val
        cfg["provider"] = name
        save_config(cfg)
        self.dismiss((name, cfg))

class SettingsModal(ModalScreen):
    CSS = """
    SettingsModal { align: center middle; }
    SettingsModal > Vertical {
        width: 72; height: auto; max-height: 80%;
        background: $surface; border: round $accent; padding: 1 2;
    }
    .modal-title { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    .field-row   { height: 3; layout: horizontal; align: left middle; margin-bottom: 1; }
    .field-label { width: 22; color: $text-muted; }
    .field-input { width: 1fr; border: solid $accent; }
    .btn-row     { layout: horizontal; height: 3; align: right middle; margin-top: 1; }
    """

    def __init__(
        self,
        agent: Agent,
        manager: ProviderManager,
        mcp_manager: MCPManager | None = None,
    ) -> None:
        super().__init__()
        self.agent             = agent
        self.providers_manager = manager
        self.mcp_manager       = mcp_manager
        self._cfg              = load_config()

    def _provider_fields(self, name: str) -> list[dict]:
        import inspect
        _HINTS = ProviderPickerModal._FIELD_HINTS
        cls = self.providers_manager.get_provider(name)
        if cls is None:
            return []
        sig    = inspect.signature(cls.__init__)
        fields = []
        skip   = {"self", "tools", "kwargs", "args"}
        for param_name, param in sig.parameters.items():
            if param_name in skip:
                continue
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            hint = _HINTS.get(param_name, {})
            fields.append({
                "id":       param_name,
                "label":    hint.get("label", param_name.replace("_", " ").title()),
                "password": hint.get("password", False),
                "default":  (
                    "" if param.default is inspect.Parameter.empty
                    else ("" if param.default is None else str(param.default))
                ),
            })
        return fields

    def compose(self) -> ComposeResult:
        p     = self.agent.provider
        pname = self._cfg.get("provider", "?")
        with Vertical():
            yield Label("⚙  Settings", classes="modal-title")
            with TabbedContent():
                with TabPane("General"):
                    with Horizontal(classes="field-row"):
                        yield Label("Approval mode:", classes="field-label")
                        yield Select(
                            [("safe (default)", "safe"), ("never", "never"), ("always", "always")],
                            value=self.agent.approve_mode,
                            id="sel-approve",
                        )
                    with Horizontal(classes="field-row"):
                        yield Label("Context length:", classes="field-label")
                        yield Input(
                            value=str(self.agent.context.max_tokens),
                            id="inp-ctx-len", classes="field-input",
                        )
                with TabPane("Provider"):
                    cls   = self.providers_manager.get_provider(pname)
                    label = getattr(cls, "provider_name", pname) if cls else pname
                    yield Label(f"Provider:  {label}", classes="field-label")
                    yield Static("")
                    for field in self._provider_fields(pname):
                        fid      = field["id"]
                        flabel   = field["label"]
                        password = field["password"]
                        default  = (
                            self._cfg.get(fid)
                            or os.getenv(fid.upper(), "")
                            or field["default"]
                        )
                        if fid == "model":
                            default = self._cfg.get("model", p.model) or field["default"]
                        with Horizontal(classes="field-row"):
                            yield Label(f"{flabel}:", classes="field-label")
                            yield Input(
                                value=str(default), password=password,
                                id=f"prov-field-{fid}", classes="field-input",
                            )
                with TabPane("MCP"):
                    if self.mcp_manager:
                        rows = self.mcp_manager.status_rows()
                        if rows:
                            lines = []
                            for row in rows:
                                st      = "✓" if row["connected"] else "○"
                                color   = "green" if row["connected"] else ("grey50" if row["enabled"] else "red")
                                en_note = "" if row["enabled"] else " [red](disabled)[/]"
                                display = row.get("url") or row.get("label") or row["key"]
                                lines.append(
                                    f"[{color}]{st}[/]  "
                                    f"{display}{en_note}  "
                                    f"[grey50]({row['n_tools']} tools)[/]"
                                )
                            yield Static("\n".join(lines), markup=True)
                        else:
                            yield Static(
                                "[grey50]No MCP servers configured.[/]\n"
                                "Use /mcp add <url> or Ctrl+E.",
                                markup=True,
                            )
                    else:
                        yield Static("[grey50]MCP manager not available.[/]", markup=True)
                with TabPane("About"):
                    all_providers = self.providers_manager.get_all_providers()
                    enabled       = self.providers_manager.get_providers()
                    ctx_display   = (
                        f"{self.agent.context.max_tokens:,}"
                        if self.agent.context.max_tokens > 0 else "N/A"
                    )
                    n_mcp = _mcp_n(self.mcp_manager)
                    yield Static(
                        f"[bold cyan]Model:[/bold cyan]      {p.model}\n"
                        f"[bold cyan]Provider:[/bold cyan]   {pname}  ({p.__class__.__name__})\n"
                        f"[bold cyan]Loaded:[/bold cyan]     {len(all_providers)} providers "
                        f"({len(enabled)} enabled)\n"
                        f"[bold cyan]Tools:[/bold cyan]      {len(self.agent.tools)}\n"
                        f"[bold cyan]MCP servers:[/bold cyan] {n_mcp}\n"
                        f"[bold cyan]Messages:[/bold cyan]   {len(self.agent.context.messages)}\n"
                        f"[bold cyan]Ctx len:[/bold cyan]    {ctx_display}\n"
                        f"[bold cyan]CWD:[/bold cyan]        {os.getcwd()}",
                        markup=True,
                    )
            with Horizontal(classes="btn-row"):
                yield Button("Save",   variant="success", id="btn-save")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        cfg   = load_config()
        pname = cfg.get("provider", "?")
        try:
            v = self.query_one("#sel-approve", Select).value
            if v and v != Select.BLANK:
                self.agent.approve_mode = v
                cfg["approve_mode"] = v
        except Exception:
            pass
        try:
            n = int(self.query_one("#inp-ctx-len", Input).value)
            if n > 0:
                self.agent.provider.context_length = n
                cfg["context_length"] = n
        except Exception:
            pass
        for field in self._provider_fields(pname):
            fid = field["id"]
            try:
                val = self.query_one(f"#prov-field-{fid}", Input).value.strip()
                if val:
                    cfg[fid] = val
                    prov = self.agent.provider
                    if fid == "base_url":
                        if hasattr(prov, "set_base_url"):
                            prov.set_base_url(val)
                        elif hasattr(prov, "base_url"):
                            prov.base_url = val
                    elif fid == "model":
                        try:
                            prov.set_model(val)
                        except Exception:
                            pass
            except Exception:
                pass
        save_config(cfg)
        save_workspace(self.agent)
        self.dismiss("saved")

class ModelPickerModal(ModalScreen):
    CSS = """
    ModelPickerModal { align: center middle; }
    ModelPickerModal > Vertical {
        width: 62; height: 80%;
        background: $surface; border: round $accent; padding: 1 2;
    }
    .modal-title  { text-align: center; color: $accent; text-style: bold; margin-bottom: 1; }
    #model-search { border: solid $accent; margin-bottom: 1; }
    #model-list   { height: 1fr; border: solid $panel; }
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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, **kwargs)
        self._lines:    list[str] = []
        self._partial:  str       = ""
        self._lock      = threading.Lock()
        self._streaming = False
        self._pending_update = False

    def push_chunk(self, text: str) -> None:

        with self._lock:
            self._partial += text
            while "\n" in self._partial:
                line, self._partial = self._partial.split("\n", 1)
                self._lines.append(line)
            self._streaming = True
            schedule = not self._pending_update
            if schedule:
                self._pending_update = True

        if schedule:
            self.app.call_from_thread(self._update_display)

    def _update_display(self) -> None:

        with self._lock:
            content = "\n".join(self._lines)
            if self._partial:
                content = (content + "\n" if content else "") + self._partial
            streaming = self._streaming
            self._pending_update = False

        if streaming:
            self.styles.border = ("solid", "blue")
        else:
            self.styles.border = None

        super().update(Markdown(content, code_theme="monokai") if content.strip() else "")

    def commit(self) -> str:

        with self._lock:
            if self._partial:
                self._lines.append(self._partial)
                self._partial = ""
            full = "\n".join(self._lines)
            self._lines     = []
            self._streaming = False
            self._pending_update = False

        try:
            self.app.call_from_thread(self._clear_display)
        except Exception:
            self._clear_display()

        return full

    def cancel(self) -> str:

        return self.commit()

    def _clear_display(self) -> None:
        self.styles.border = None
        super().update("")

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

    #prompt-label.question-mode   { color: yellow; }
    #prompt-label.approval-mode   { color: orange; }
    #prompt-label.interrupted     { color: red; }

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
        Binding("ctrl+p",     "toggle_pause",        "Pause/Resume"),
        Binding("ctrl+c",     "do_interrupt",         "Interrupt",   show=True),
        Binding("ctrl+s",     "open_settings",        "Settings"),
        Binding("ctrl+m",     "open_model_picker",    "Models"),
        Binding("ctrl+r",     "open_provider_picker", "Provider"),
        Binding("ctrl+e",     "open_mcp",             "MCP"),

        Binding("tab",        "accept_suggestion",    "Complete",    show=False),
    ]

    def __init__(
        self,
        bus: EventBus,
        agent: Agent,
        providers_manager: ProviderManager,
        tools_manager: ToolsManager,
        mcp_manager: MCPManager | None = None,
    ) -> None:
        super().__init__()
        self.agent             = agent
        self.providers_manager = providers_manager
        self.tools_manager     = tools_manager
        self.mcp_manager       = mcp_manager
        self._R                = Renderer()
        self.bus               = bus

        self._approval_pending  = threading.Event()
        self._approval_done     = threading.Event()
        self._approval_tool     = ""
        self._approval_result: bool | None = None

        self._question_pending           = threading.Event()
        self._question_done              = threading.Event()
        self._question_suggestions: list[str] = []
        self._question_answer: str       = ""

        self._streaming      = False
        self._interrupt_flag = threading.Event()
        self._interrupted    = False

        self._history:     list[str] = []
        self._history_idx: int       = -1
        self._history_draft: str     = ""

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
        self._register_event_handlers()
        self.call_after_refresh(self._tick_status)
        self.set_interval(2, self._tick_status)

    def on_key(self, event: Key) -> None:
        inp = self.query_one("#cmd-input", Input)
        if not inp.has_focus:
            return

        if event.key == "up":
            self._history_up()
            event.stop()
            event.prevent_default()
        elif event.key == "down":
            self._history_down()
            event.stop()
            event.prevent_default()

    def action_accept_suggestion(self) -> None:

        inp = self.query_one("#cmd-input", Input)
        if inp.has_focus and inp._suggestion:        
            inp.value    = inp._suggestion              
            inp.cursor_position = len(inp.value)

    def _history_up(self) -> None:
        if not self._history:
            return
        inp = self.query_one("#cmd-input", Input)
        if self._history_idx == -1:
            self._history_draft = inp.value
            self._history_idx   = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        inp.value           = self._history[self._history_idx]
        inp.cursor_position = len(inp.value)

    def _history_down(self) -> None:
        if self._history_idx == -1:
            return
        inp = self.query_one("#cmd-input", Input)
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            inp.value = self._history[self._history_idx]
        else:
            self._history_idx = -1
            inp.value         = self._history_draft
        inp.cursor_position = len(inp.value)

    def _tick_status(self) -> None:
        try:
            p             = self.agent.provider
            cfg           = load_config()
            provider_name = (
                cfg.get("provider")
                or getattr(p, "provider_name", None)
                or p.__class__.__name__
                or "?"
            )
            self.query_one(StatusBar).refresh_status(
                model         = p.model.split("/")[-1],
                provider_name = provider_name,
                cwd           = os.getcwd(),
                tokens        = self.agent.context.estimate_tokens(),
                max_tokens    = self.agent.context.max_tokens,
                usage         = self.agent.context.usage_percent(),
                paused        = self.agent.is_paused,
                interrupted   = self._interrupted,
                n_mcp         = _mcp_n(self.mcp_manager),
            )
        except Exception as e:
            try:
                self.query_one(StatusBar).update(f"[red]Status error: {e}[/]")
            except Exception:
                pass

    def _write(self, renderable: Any) -> None:
        def _do():
            try:
                self.query_one("#log", RichLog).write(renderable)
            except Exception:
                pass
        try:
            self.call_from_thread(_do)
        except RuntimeError:
            _do()

    def _write_many(self, items: list) -> None:
        for r in items:
            self._write(r)

    def _sv(self) -> StreamView:
        return self.query_one("#stream-view", StreamView)

    def _stream_chunk(self, text: str) -> None:

        self._streaming = True
        self._sv().push_chunk(text)

    def _stream_close(self) -> None:

        if not self._streaming:
            return
        self._streaming = False
        sv        = self._sv()
        full_text = sv.commit()  # clears StreamView

        if full_text.strip():
            def _commit():
                try:
                    log = self.query_one("#log", RichLog)
                    log.write(Text(""))
                    log.write(Markdown(full_text, code_theme="monokai"))
                    log.write(Text(""))
                except Exception:
                    pass
            try:
                self.call_from_thread(_commit)
            except RuntimeError:
                _commit()

    def _stream_cancel(self) -> None:

        if self._streaming:
            self._streaming = False
            partial = self._sv().cancel()
            if partial.strip():
                def _commit():
                    try:
                        log = self.query_one("#log", RichLog)
                        log.write(Text(""))
                        log.write(Markdown(partial, code_theme="monokai"))
                        t = Text()
                        t.append("  … interrupted", style=C.WARN)
                        log.write(t)
                    except Exception:
                        pass
                try:
                    self.call_from_thread(_commit)
                except RuntimeError:
                    _commit()

        self._interrupt_flag.set()
        self._interrupted = True

        if self._approval_pending.is_set():
            self._approval_result = False
            self._approval_done.set()
            self._approval_pending.clear()

        if self._question_pending.is_set():
            self._question_answer = ""
            self._question_done.set()
            self._question_pending.clear()

        try:
            self.call_from_thread(self._tick_status)
        except RuntimeError:
            self._tick_status()

    def _clear_interrupt(self) -> None:
        self._interrupt_flag.clear()
        self._interrupted = False

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

    def _enter_approval_mode(self, tool: str) -> None:
        label = self.query_one("#prompt-label", Label)
        label.update("y/n›")
        label.add_class("approval-mode")
        self.query_one("#cmd-input", Input).placeholder = (
            f"Approve tool '{tool}'?  y / n / a (always)"
        )

    def _leave_approval_mode(self) -> None:
        label = self.query_one("#prompt-label", Label)
        label.update("❯")
        label.remove_class("approval-mode")
        self.query_one("#cmd-input", Input).placeholder = "Type a task or /help…"

    def _register_event_handlers(self) -> None:

        @self.bus.subscribe(TaskStartedEvent)
        def _(e: TaskStartedEvent):
            self.call_from_thread(self._clear_interrupt)
            self._write_many(self._R.task_started(e.prompt))

        @self.bus.subscribe(TaskFinishedEvent)
        def _(e: TaskFinishedEvent):
            self._stream_close()
            save_workspace(self.agent)
            try:
                self.call_from_thread(self._tick_status)
            except Exception:
                pass

        @self.bus.subscribe(TaskErrorEvent)
        def _(e: TaskErrorEvent):
            self._stream_close()
            self._write_many(self._R.task_error(e.error))
            try:
                self.call_from_thread(self._tick_status)
            except Exception:
                pass

        @self.bus.subscribe(StreamChunkEvent)
        def _(e: StreamChunkEvent):
            if isinstance(e.data, dict) and e.data.get("type") == "text":
                self._stream_chunk(e.data["content"])

        @self.bus.subscribe(ModelProcessingEvent)
        def _(e):
            self._write_many(self._R.thinking())

        @self.bus.subscribe(ProviderResponseEvent)
        def _(e):
            self._stream_close()

        @self.bus.subscribe(ToolCallEvent)
        def _(e: ToolCallEvent):
            if not e.tool or e.tool in {"FinishTask", "FinishTaskTool", "Question", "QuestionTool"}:
                return
            self._stream_close()
            self._write_many(self._R.tool_call(e.tool, e.args))

        @self.bus.subscribe(ToolStartedEvent)
        def _(e: ToolStartedEvent):
            pass

        @self.bus.subscribe(ToolFinishedEvent)
        def _(e: ToolFinishedEvent):
            self._stream_close()
            if e.tool not in {"Question", "QuestionTool"}:
                self._write_many(self._R.tool_result(e.tool, e.result))

        @self.bus.subscribe(ToolErrorEvent)
        def _(e: ToolErrorEvent):
            self._stream_close()
            self._write_many(self._R.tool_error(e.tool, e.error))

        @self.bus.subscribe(ApprovalRequestedEvent)
        def _(e: ApprovalRequestedEvent):
            self._stream_close()
            self._approval_tool = e.tool
            self._approval_result = None
            self._approval_done.clear()
            self._approval_pending.set()

            self._write_many(self._R.approval_request(e.tool))
            try:
                self.call_from_thread(self._enter_approval_mode, e.tool)
            except Exception:
                pass

            self._approval_done.wait()
            try:
                self.call_from_thread(self._leave_approval_mode)
            except Exception:
                pass

        @self.bus.subscribe(ApprovalGrantedEvent)
        def _(e: ApprovalGrantedEvent):
            self._write_many(self._R.approval_result(True, e.tool))

        @self.bus.subscribe(ApprovalDeniedEvent)
        def _(e: ApprovalDeniedEvent):
            self._write_many(self._R.approval_result(False, e.tool))

        @self.bus.subscribe(QuestionRequestedEvent)
        def _(e: QuestionRequestedEvent):
            self._stream_close()
            question    = e.payload.get("question", "")
            context     = e.payload.get("context", "")
            suggestions = e.payload.get("suggestions", [])
            self._write_many(self._R.question_request(question, context, suggestions))

            self._question_answer = ""
            self._question_done.clear()
            self._question_pending.set()

            try:
                self.call_from_thread(self._enter_question_mode, suggestions)
            except Exception:
                self._enter_question_mode(suggestions)

            self._question_done.wait()

            answer = self._question_answer
            self._write_many(self._R.question_answer(answer))
            self.agent.resolve_question(answer)

            try:
                self.call_from_thread(self._leave_question_mode)
            except Exception:
                pass

        @self.bus.subscribe(ErrorEvent)
        def _(e: ErrorEvent):
            self._write_many(self._R.generic_error(e.source, e.message, e.traceback))

        @self.bus.subscribe(ContextCompressedEvent)
        def _(e: ContextCompressedEvent):
            self._write_many(self._R.context_compressed(
                e.info.get("before_tokens", 0),
                e.info.get("after_tokens", 0),
            ))

        @self.bus.subscribe(ContextCompressionErrorEvent)
        def _(e: ContextCompressionErrorEvent):
            self._stream_close()
            self._write_many(self._R.context_compression_error(e.error))

        @self.bus.subscribe(AgentPausedEvent)
        def _(e):
            try:
                self.call_from_thread(self._tick_status)
            except Exception:
                pass

        @self.bus.subscribe(AgentResumedEvent)
        def _(e):
            try:
                self.call_from_thread(self._tick_status)
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""

        self._history_idx   = -1
        self._history_draft = ""
        if not text:
            return

        if not self._history or self._history[-1] != text:
            self._history.append(text)

            if len(self._history) > 500:
                self._history = self._history[-500:]

        if self._approval_pending.is_set():
            self._approval_pending.clear()
            ans = text.lower()
            if ans == "a":
                self.agent.approve_mode = "always"
                self._approval_result = True
            elif ans in {"y", "yes"}:
                self._approval_result = True
            else:
                self._approval_result = False
            self.agent.resolve_approval(bool(self._approval_result))
            self._approval_done.set()
            return

        if self._question_pending.is_set():
            self._question_pending.clear()
            suggestions = self._question_suggestions
            answer = text
            if text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(suggestions):
                    answer = suggestions[idx]
            self._question_answer = answer
            self._question_done.set()
            return

        self._dispatch(text)

    def _dispatch(self, text: str) -> None:  
        t = text.strip()

        def info(msg: str) -> None:
            r = Text()
            r.append("  ")
            r.append(msg, style=C.DIM)
            self._write(r)

        def ok(msg: str) -> None:
            r = Text()
            r.append("  ✓ ", style=C.OK)
            r.append(msg, style=C.DIM)
            self._write(r)

        def err(msg: str) -> None:
            r = Text()
            r.append("  ✗ ", style=C.ERR)
            r.append(msg)
            self._write(r)

        def _require_mcp() -> bool:
            if self.mcp_manager is None:
                err("MCP manager not initialized")
                return False
            return True

        def _require_idx(val: str, cmd: str) -> int | None:
            if not val.isdigit():
                err(f"Usage: {cmd} <n>")
                return None
            idx = int(val) - 1
            key = _mcp_key_by_index(self.mcp_manager, idx)
            if key is None:
                err(f"No server #{int(val)}")
                return None
            return idx

        if t in {"/quit", "/exit"}:
            self.exit()

        elif t in {"/help", "?"}:
            tbl = Table(border_style="grey30", show_header=False, padding=(0, 2),
                        box=None, pad_edge=False)
            tbl.add_column("cmd",  style="bold cyan", no_wrap=True, min_width=34)
            tbl.add_column("desc", style="grey62")
            rows = [
                ("/help",                         "This help"),
                ("/tools",                        "List tools"),
                ("/model-picker  (Ctrl+M)",        "Model picker"),
                ("/provider  (Ctrl+R)",            "Provider picker"),
                ("/settings  (Ctrl+S)",            "Settings modal"),
                ("/mcp  (Ctrl+E)",                 "MCP server manager"),
                ("/mcp list",                      "List MCP servers inline"),
                ("/mcp add <url|stdio://cmd>",     "Add MCP server (URL or stdio)"),
                ("/mcp remove <n>",                "Remove server by index"),
                ("/mcp enable <n>",                "Enable server"),
                ("/mcp disable <n>",               "Disable server"),
                ("/mcp reload",                    "Reload tools from all servers"),
                ("/mcp ping",                      "Ping all servers"),
                ("/context",                       "Token usage"),
                ("/history",                       "Message history"),
                ("/reset",                         "Clear context"),
                ("/approve [never|safe|always]",   "Approval mode"),
                ("/baseurl [url]",                 "Show / set base URL"),
                ("/set_context_length <n>",        "Max tokens"),
                ("/compress_context",              "Compress now"),
                ("/pause  /resume  Ctrl+P",        "Pause / resume agent"),
                ("/interrupt  Ctrl+C",             "Interrupt current task"),
                ("Tab",                            "Accept autocomplete suggestion"),
                ("↑ / ↓",                          "Navigate input history"),
                ("/steer [text|clear]",            "Steering instructions"),
                ("/queue",                         "Task queue"),
                ("/clear",                         "Clear log"),
                ("/quit",                          "Exit"),
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

        elif t == "/mcp":
            self.action_open_mcp()

        elif t == "/mcp list":
            if not _require_mcp():
                return
            rows = self.mcp_manager.status_rows()
            if not rows:
                info("No MCP servers configured")
                return
            self._write(Text(""))
            for row in rows:
                r = Text()
                connected = row["connected"]
                enabled   = row["enabled"]
                icon  = "●" if connected else ("○" if enabled else "✗")
                color = "green" if connected else ("grey50" if enabled else "red")
                display = row.get("url") or row.get("label") or row["key"]
                r.append(f"  {row['index'] + 1}  ", style=C.MUTED)
                r.append(f"{icon} ", style=color)
                r.append(display, style="white" if connected else "grey50")
                r.append(
                    f"  {row['n_tools']}t {row['n_resources']}r {row['n_prompts']}p",
                    style=C.MUTED,
                )
                self._write(r)
            self._write(Text(""))

        elif t == "/mcp reload":
            if not _require_mcp():
                return
            info("Reloading all MCP servers…")

            def _do_reload():
                results = self.mcp_manager.reload_all()
                for key, res in results.items():
                    if res.get("error"):
                        err(f"{key}: {res['error']}")
                    else:
                        n = res.get("n_tools", len(res.get("tools", [])))
                        ok(f"{key}  ({n} tools)")
                self.call_from_thread(self._tick_status)

            threading.Thread(target=_do_reload, daemon=True).start()

        elif t == "/mcp ping":
            if not _require_mcp():
                return
            statuses = self.mcp_manager.ping_all()
            if not statuses:
                info("No servers configured")
                return
            for key, alive in statuses.items():
                r = Text()
                r.append("  ")
                r.append("● " if alive else "○ ", style="green" if alive else "red")
                r.append(key, style="white" if alive else "grey50")
                r.append("  alive" if alive else "  unreachable",
                          style="green" if alive else "red")
                self._write(r)

        elif t.startswith("/mcp add "):
            if not _require_mcp():
                return
            spec = t[len("/mcp add "):].strip()
            if not spec:
                err("Usage: /mcp add <url>  or  /mcp add stdio://cmd arg1 arg2")
                return

            def _do_add():
                if spec.startswith("stdio://"):
                    cmd_str = spec[len("stdio://"):].strip()
                    import shlex
                    try:
                        cmd = shlex.split(cmd_str)
                    except ValueError:
                        cmd = cmd_str.split()
                    derived_key = f"stdio://{cmd_str}"
                    self.mcp_manager.add_stdio(cmd)
                    try:
                        self.mcp_manager.connect(derived_key)
                        n = len(self.mcp_manager._tools.get(derived_key, []))
                        ok(f"Added stdio server  ({n} tools)")
                    except Exception as e:
                        err(f"Saved but connect failed: {e}")
                else:
                    self.mcp_manager.add(spec)
                    key = spec.rstrip("/")
                    try:
                        self.mcp_manager.connect(spec)
                        n = len(self.mcp_manager._tools.get(key, []))
                        ok(f"Added {spec!r}  ({n} tools)")
                    except Exception as e:
                        err(f"Saved {spec!r}, but couldn't connect: {e}")
                self.call_from_thread(self._tick_status)

            threading.Thread(target=_do_add, daemon=True).start()

        elif t.startswith("/mcp remove "):
            if not _require_mcp():
                return
            val = t[len("/mcp remove "):].strip()
            idx = _require_idx(val, "/mcp remove")
            if idx is None:
                return
            key = _mcp_key_by_index(self.mcp_manager, idx)
            self.mcp_manager.remove(key)
            ok(f"Removed {key!r}")
            self._tick_status()

        elif t.startswith("/mcp enable "):
            if not _require_mcp():
                return
            val = t[len("/mcp enable "):].strip()
            idx = _require_idx(val, "/mcp enable")
            if idx is None:
                return
            key = _mcp_key_by_index(self.mcp_manager, idx)
            self.mcp_manager.enable(key)

            def _do_enable():
                try:
                    self.mcp_manager.connect(key)
                    n = len(self.mcp_manager._tools.get(key, []))
                    ok(f"Enabled {key!r}  ({n} tools loaded)")
                except Exception as e:
                    err(f"Enabled but failed to connect: {e}")
                self.call_from_thread(self._tick_status)

            threading.Thread(target=_do_enable, daemon=True).start()

        elif t.startswith("/mcp disable "):
            if not _require_mcp():
                return
            val = t[len("/mcp disable "):].strip()
            idx = _require_idx(val, "/mcp disable")
            if idx is None:
                return
            key = _mcp_key_by_index(self.mcp_manager, idx)
            self.mcp_manager.disable(key)
            ok(f"Disabled {key!r}")
            self._tick_status()

        elif t == "/context":
            tok   = self.agent.context.estimate_tokens()
            max_t = self.agent.context.max_tokens
            use   = self.agent.context.usage_percent()
            col   = _token_color(use)
            r = Text()
            r.append("  Messages: ", style=C.MUTED)
            r.append(f"{len(self.agent.context.messages)}", style="white")
            r.append("   Tokens: ", style=C.MUTED)
            if max_t > 0:
                r.append(f"{tok:,} / {max_t:,}", style=col)
                r.append(f"  ({use:.0f}%)", style=col)
                r.append(f"  {_context_bar(use)}", style="")
            else:
                r.append(f"{tok:,}  (context length unknown)", style=C.MUTED)
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
                r.append(
                    f"{msg.role:<12}",
                    style="bold cyan" if msg.role == "assistant" else "bold white",
                )
                r.append(preview, style=C.DIM)
                self._write(r)

        elif t == "/reset":
            self.agent.context = Context(provider=self.agent.provider, bus=self.bus)
            self.agent.context.compression_callback = self.agent._on_context_compressed
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
                err("Valid modes: never | safe | always")
                return
            self.agent.approve_mode = mode
            cfg = load_config()
            cfg["approve_mode"] = mode
            save_config(cfg)
            save_workspace(self.agent)
            ok(f"Approval → {mode}")

        elif t == "/baseurl":
            info(f"Base URL: {getattr(self.agent.provider, 'base_url', 'N/A')}")

        elif t.startswith("/baseurl "):
            url  = t.split(maxsplit=1)[1].strip()
            prov = self.agent.provider
            if hasattr(prov, "set_base_url"):
                prov.set_base_url(url)
            elif hasattr(prov, "base_url"):
                prov.base_url = url
            cfg = load_config()
            cfg["base_url"] = url
            save_config(cfg)
            save_workspace(self.agent)
            ok(f"Base URL → {url}")

        elif t.startswith("/set_context_length "):
            val = t.split(maxsplit=1)[1].strip()
            if not val.isdigit():
                err("Usage: /set_context_length <n>")
                return
            n = int(val)
            if n <= 0:
                err("Context length must be positive")
                return
            self.agent.provider.context_length = n
            cfg = load_config()
            cfg["context_length"] = n
            save_config(cfg)
            save_workspace(self.agent)
            ok(f"Context length → {n:,}")
            self._tick_status()

        elif t == "/compress_context":
            info("Compressing context…")
            self.agent.context.compress()

        elif t == "/pause":
            if not self.agent.is_paused:
                self.agent.pause()
                r = Text()
                r.append("  ⏸ Paused", style=C.WARN)
                self._write(r)
                self._tick_status()
            else:
                info("Already paused  (/resume to continue)")

        elif t == "/resume":
            if self.agent.is_paused:
                self.agent.resume()
                r = Text()
                r.append("  ▶ Resumed", style=C.OK)
                self._write(r)
                self._tick_status()
            else:
                info("Not paused")

        elif t == "/interrupt":
            self._do_interrupt_command()

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
            err(f"Unknown command: {t}  (/help for list)")

        else:
            self._clear_interrupt()
            self.agent.enqueue(prompt=t, task_id=str(time.time()))

    def _do_interrupt_command(self) -> None:
        if self.agent.current_task is None and not self._streaming:
            r = Text()
            r.append("  ", style="")
            r.append("No task running", style=C.MUTED)
            self._write(r)
            return
        r = Text()
        r.append("  ✗ ", style=C.ERR)
        r.append("Interrupted by user", style=C.WARN)
        self._write(r)
        self._stream_cancel()
        self.agent.stop_queue()
        self.agent.start_queue()

    def action_toggle_pause(self) -> None:
        if self.agent.is_paused:
            self.agent.resume()
            r = Text()
            r.append("  ▶ Resumed", style=C.OK)
            self._write(r)
        else:
            self.agent.pause()
            r = Text()
            r.append("  ⏸ Paused", style=C.WARN)
            self._write(r)
        self._tick_status()

    def action_do_interrupt(self) -> None:

        if self.agent.current_task is None and not self._streaming:
            self.exit()
            return
        self._do_interrupt_command()

    def action_open_settings(self) -> None:
        def _cb(result):
            if result == "saved":
                r = Text()
                r.append("  ✓ ", style=C.OK)
                r.append("Settings saved", style=C.DIM)
                self._write(r)
                self._tick_status()
        self.push_screen(
            SettingsModal(self.agent, self.providers_manager, self.mcp_manager), _cb
        )

    def action_open_provider_picker(self) -> None:
        self.push_screen(
            ProviderPickerModal(self.agent, self.providers_manager),
            self._apply_provider_result,
        )

    def action_open_model_picker(self) -> None:
        try:
            models = self.agent.provider.get_models()
        except Exception:
            r = Text()
            r.append("  ✗ ", style=C.ERR)
            r.append("Could not fetch models")
            self._write(r)
            return
        if not isinstance(models, list) or not models:
            r = Text()
            r.append("  ")
            r.append("No models available", style=C.MUTED)
            self._write(r)
            return
        self.push_screen(
            ModelPickerModal(models, self.agent.provider.model),
            lambda m: m and self._set_model(m),
        )

    def action_open_mcp(self) -> None:
        if self.mcp_manager is None:
            r = Text()
            r.append("  ✗ ", style=C.ERR)
            r.append("MCP manager not available")
            self._write(r)
            return
        self.push_screen(MCPModal(self.mcp_manager), lambda _: self._tick_status())

    def _set_model(self, model: str) -> None:
        try:
            models = self.agent.provider.get_models()
            if isinstance(models, list) and model not in models:
                r = Text()
                r.append("  ✗ ", style=C.ERR)
                r.append(f"Unknown model: {model}")
                self._write(r)
                return
        except Exception:
            pass
        try:
            self.agent.provider.set_model(model)
        except Exception as e:
            r = Text()
            r.append("  ✗ ", style=C.ERR)
            r.append(str(e))
            self._write(r)
            return
        cfg = load_config()
        cfg["model"] = model
        save_config(cfg)
        save_workspace(self.agent)
        r = Text()
        r.append("  ✓ ", style=C.OK)
        r.append(f"Model → {model}", style=C.DIM)
        self._write(r)
        self._tick_status()

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
            new_provider = _build_provider_from_providers_manager(
                self.providers_manager, self.tools_manager,
                name, cfg, tools, self.agent.provider.model, self.bus
            )
            self.agent.provider = new_provider
            self.agent.context.provider = new_provider
            save_workspace(self.agent)
            cls   = self.providers_manager.get_provider(name)
            label = getattr(cls, "provider_name", name) if cls else name
            r = Text()
            r.append("  ✓ ", style=C.OK)
            r.append(f"Provider → {label}", style=C.DIM)
            self._write(r)
            self._tick_status()
        except Exception as e:
            r = Text()
            r.append("  ✗ ", style=C.ERR)
            r.append(f"Provider error: {e}")
            self._write(r)

    def run_tui(self) -> None:
        self.run()