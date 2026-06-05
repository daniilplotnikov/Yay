import inspect
import importlib
import traceback
import pkgutil

from ..tool import Tool
from ..events import EventBus, ErrorEvent

class ToolsManager:
    def __init__(self, package, bus):
        self.package = package
        self.bus = bus

        self._tools = {}
        self._enabled = set()

    def load(self):
        self._tools.clear()
        self._enabled.clear()

        for _, module_name, _ in pkgutil.walk_packages(
            self.package.__path__,
            self.package.__name__ + ".",
        ):
            try:
                module = importlib.import_module(
                    module_name
                )

            except Exception as e:
                self.bus.emit(ErrorEvent(
                    source='ToolsManager',
                    message=f"Failed importing "
                    f"{module_name}: {e}",
                    traceback=traceback.format_exc()
                ))
                continue

            for _, cls in inspect.getmembers(
                module,
                inspect.isclass,
            ):

                if (
                    not issubclass(cls, Tool)
                    or cls is Tool
                ):
                    continue

                if inspect.isabstract(cls):
                    continue

                try:
                    tool = cls()

                    name = getattr(
                        tool,
                        "name",
                        cls.__name__,
                    )

                    self._tools[name] = tool
                    self._enabled.add(name)

                except Exception as e:
                    self.bus.emit(ErrorEvent(
                        source='ToolsManager',
                        message=f"Failed creating "
                        f"{cls.__name__}: {e}",
                        traceback=traceback.format_exc()
                    ))
                    continue

    def register(self, tool):
        name = tool.name
        self._tools[name] = tool
        self._enabled.add(name)

    def register_many(self, tools):
        for tool in tools:
            self.register(tool)

    def unregister(self, name):
        self._tools.pop(name, None)
        self._enabled.discard(name)

    def unregister_many(self, names):
        for name in names:
            self.unregister(name)

    def get_tool(self, name):
        return self._tools.get(name)

    def get_tools(self):
        return {
            name: tool
            for name, tool in self._tools.items()
            if name in self._enabled
        }

    def get_all_tools(self):
        return list(
            self._tools.values()
        )

    def enable(self, name):
        if name in self._tools:
            self._enabled.add(name)

    def disable(self, name):
        self._enabled.discard(name)

    def is_enabled(self, name):
        return name in self._enabled

    def reload(self):
        self.load()