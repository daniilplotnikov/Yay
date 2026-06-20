from __future__ import annotations

import asyncio
import inspect
import traceback
from collections import defaultdict
from typing import Callable, Type, Dict, List, TypeVar

from .base import Event
from .types import ErrorEvent


T = TypeVar("T", bound=Event)


class EventBus:
    def __init__(self) -> None:
        self._handlers: Dict[type[Event], List[Callable]] = defaultdict(list)

    def subscribe(self, event_type: Type[T]):
        def decorator(fn: Callable[[T], None]):
            self._handlers[event_type].append(fn)
            return fn
        return decorator

    async def emit(self, event: Event) -> None:
        if not isinstance(event, Event):
            raise TypeError(
                f"EventBus can only emit Event instances, got {type(event)}"
            )

        handlers = list(self._handlers.get(type(event), []))

        if not handlers:
            return

        results = await asyncio.gather(
            *[
                self._run_handler(handler, event)
                for handler in handlers
            ],
            return_exceptions=True
        )

        for result in results:
            if isinstance(result, Exception):
                # Avoid infinite recursion if the error event itself fails
                if isinstance(event, ErrorEvent):
                    continue
                tb = getattr(result, "__traceback__", None)
                error_event = ErrorEvent(
                    source="EventBus",
                    message=f"Handler error for {type(event).__name__}: {result}",
                    traceback=traceback.format_exception(type(result), result, tb) if tb else None,
                )
                # Fire-and-forget: don't await to avoid blocking
                asyncio.create_task(self._safe_emit(error_event))

    async def _safe_emit(self, event: Event) -> None:
        """Emit without raising — used for error reporting to avoid infinite loops."""
        try:
            await self.emit(event)
        except Exception:
            pass

    async def _run_handler(self, handler: Callable, event: Event) -> None:
        try:
            if inspect.iscoroutinefunction(handler):
                await handler(event)
            else:
                await asyncio.to_thread(handler, event)

        except Exception as e:
            if isinstance(event, ErrorEvent):
                return

            error_event = ErrorEvent(
                source="EventBus",
                message=str(e),
                traceback=traceback.format_exc(),
            )

            await self.emit(error_event)