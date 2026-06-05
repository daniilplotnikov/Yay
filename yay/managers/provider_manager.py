import inspect
import importlib
import traceback
import pkgutil
from ..events import EventBus, ErrorEvent
from ..provider import Provider


class ProviderManager:
    def __init__(self, package, bus: EventBus):
        self.package = package
        self.bus = bus

        self._providers = {}
        self._enabled = set()

    def load(self):
        self._providers.clear()
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
                    source='ProviderManager',
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
                    not issubclass(cls, Provider)
                    or cls is Provider
                ):
                    continue

                if inspect.isabstract(cls):
                    continue

                name = getattr(
                    cls,
                    "provider_name",
                    cls.__name__,
                )

                self._providers[name] = cls
                self._enabled.add(name)

    def get_provider(self, name):
        return self._providers.get(name)

    def get_providers(self):
        return {
            name: cls
            for name, cls in self._providers.items()
            if name in self._enabled
        }

    def get_all_providers(self):
        return dict(self._providers)

    def enable(self, name):
        if name in self._providers:
            self._enabled.add(name)

    def disable(self, name):
        self._enabled.discard(name)

    def is_enabled(self, name):
        return name in self._enabled

    def find_by_name(
        self,
        provider_name,
    ):
        return self._providers.get(
            provider_name
        )

    def reload(self):
        self.load()