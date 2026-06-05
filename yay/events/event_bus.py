import traceback
from collections import defaultdict
from typing import Callable, Type

from .base import Event
from .types import ErrorEvent

class EventBus:
    def __init__(self):
        self._handlers = defaultdict(list)

    def subscribe(self, event_type: Type[Event]):
        def decorator(fn: Callable):
            self._handlers[event_type].append(fn)
            return fn
        return decorator

    def emit(self, event: Event):
        if not isinstance(event, Event):
            raise TypeError(
                f"EventBus can only emit Event instances, got {type(event)}"
            )

        event_type = type(event)

        for handler in self._handlers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                self.emit(ErrorEvent(
                    source='EventBus',
                    message=str(e),
                    traceback=traceback.format_exc()
                ))