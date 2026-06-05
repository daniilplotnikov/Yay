from dataclasses import dataclass
from typing import Any, Dict, Optional
from .base import Event

@dataclass
class ErrorEvent(Event):
    source: str
    message: str
    traceback: str | None = None

@dataclass
class TaskStartedEvent(Event):
    prompt: str

@dataclass
class TaskFinishedEvent(Event):
    result: Any

@dataclass
class TaskErrorEvent(Event):
    task_id: Optional[str]
    error: str

@dataclass
class ModelProcessingEvent(Event):
    pass

@dataclass
class StreamChunkEvent(Event):
    data: Any

@dataclass
class ProviderResponseEvent(Event):
    message: Any

@dataclass
class ToolCallEvent(Event):
    tool: str
    args: Dict[str, Any]

@dataclass
class ToolStartedEvent(Event):
    tool: str

@dataclass
class ToolFinishedEvent(Event):
    tool: str
    result: Any

@dataclass
class ToolErrorEvent(Event):
    tool: str
    error: str

@dataclass
class ApprovalRequestedEvent(Event):
    tool: str
    args: Dict[str, Any]

@dataclass
class ApprovalGrantedEvent(Event):
    tool: str

@dataclass
class ApprovalDeniedEvent(Event):
    tool: str

@dataclass
class QuestionRequestedEvent(Event):
    payload: Dict[str, Any]

@dataclass
class ContextCompressedEvent(Event):
    info: Dict[str, Any]

@dataclass
class ContextCompressionErrorEvent(Event):
    error: str

@dataclass
class AgentPausedEvent(Event):
    pass

@dataclass
class AgentResumedEvent(Event):
    pass

@dataclass
class ContextCompressionNeededEvent(Event):
    pass

@dataclass
class ContextCompressEvent(Event):
    pass