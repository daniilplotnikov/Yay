from dataclasses import dataclass
from typing import Optional

@dataclass
class Task:
    prompt: str
    task_id: str
    metadata: Optional[dict] = None