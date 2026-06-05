from dataclasses import dataclass, field
import time
import uuid

@dataclass(kw_only=True)
class Event:
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)