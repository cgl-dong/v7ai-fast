"""Tool framework — Day2 Function Calling integration.

BaseTool abstract class + ToolRegistry for the v7ai-fast agent.
Each tool declares an OpenAI-compatible schema (name/description/parameters)
and an async `execute(**kwargs)` implementation.

Message roles (OpenAI convention):
  system    — persona / global rules
  user      — user input
  assistant — model answer OR model's tool-call request
  tool      — tool execution result fed back into context
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Base class for a callable agent tool.

    Subclasses must set: name, description, parameters (JSON Schema dict),
    and implement async execute(**kwargs) -> str.
    """

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    def schema(self) -> Dict[str, Any]:
        """OpenAI-compatible tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool with validated kwargs. Return result text."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<Tool {self.name}>"


class ToolRegistry:
    """Registry of all agent tools. Singleton per process."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def all_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def schemas(self) -> List[Dict[str, Any]]:
        """OpenAI tools array for the LLM request."""
        return [t.schema() for t in self._tools.values()]

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# Global singleton
registry = ToolRegistry()
