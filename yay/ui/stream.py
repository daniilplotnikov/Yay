from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog

from .log import LogWriter
from .renderer import C

if TYPE_CHECKING:
    from textual.app import App
    from .tui import StreamView

class StreamController:

    def __init__(self, app: "App", log: LogWriter) -> None:
        self._app        = app
        self._log        = log
        self._streaming  = False
        self._interrupted = False
        self._interrupt_flag = threading.Event()

    def _sv(self) -> "StreamView":
        from .tui import StreamView as _SV
        return self._app.query_one("#stream-view", _SV)

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def is_interrupted(self) -> bool:
        return self._interrupted

    @property
    def interrupt_flag(self) -> threading.Event:
        return self._interrupt_flag

    def push_chunk(self, text: str) -> None:
        self._streaming = True
        self._sv().push_chunk(text)

    def close(self) -> None:
        """Фиксирует стрим в RichLog и очищает StreamView."""
        if not self._streaming:
            return
        self._streaming = False
        sv        = self._sv()
        full_text = sv.commit()

        if not full_text.strip():
            return

        def _commit() -> None:
            try:
                log = self._app.query_one("#log", RichLog)
                log.write(Text(""))
                log.write(Markdown(full_text, code_theme="monokai"))
                log.write(Text(""))
            except Exception:
                pass

        try:
            self._app.call_from_thread(_commit)
        except RuntimeError:
            _commit()

    def cancel(self) -> None:
        if self._streaming:
            self._streaming = False
            partial = self._sv().cancel()
            if partial.strip():
                def _commit() -> None:
                    try:
                        log = self._app.query_one("#log", RichLog)
                        log.write(Text(""))
                        log.write(Markdown(partial, code_theme="monokai"))
                        t = Text()
                        t.append("  … interrupted", style=C.WARN)
                        log.write(t)
                    except Exception:
                        pass
                try:
                    self._app.call_from_thread(_commit)
                except RuntimeError:
                    _commit()

        self._interrupt_flag.set()
        self._interrupted = True

    def clear_interrupt(self) -> None:
        self._interrupt_flag.clear()
        self._interrupted = False