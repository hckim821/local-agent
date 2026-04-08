from abc import ABC, abstractmethod
from typing import Any


class SkillBase(ABC):
    name: str
    description: str
    parameters: dict  # JSON Schema for parameters

    @abstractmethod
    async def run(self, **kwargs) -> dict:
        """Execute the skill and return result dict"""
        pass

    def to_tool_definition(self) -> dict:
        """Convert to OpenAI tool format"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
