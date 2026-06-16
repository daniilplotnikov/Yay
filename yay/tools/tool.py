from abc import ABC, abstractmethod
from typing import Any, Dict
import inspect

class Tool(ABC):
    def __init__(self):
        self.name: str = self.__class__.__name__
        self.description: str = ""
        self.is_safe: bool = True

        self.arguments: Dict[str, Any] = {}

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.arguments,
        }

    def validate(self, args: Dict[str, Any]) -> None:
        required = self.arguments.get("required", [])

        for r in required:
            if r not in args:
                raise ValueError(f"Missing required argument: {r}")

    async def run(self, args: Dict[str, Any]) -> Any:
        self.validate(args)

        result = self.execute(args)

        if inspect.isawaitable(result):
            return await result

        return result

    @abstractmethod
    def execute(
        self,
        args: Dict[str, Any],
    ) -> Any:
        pass