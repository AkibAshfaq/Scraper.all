from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Literal


class ChatError(Exception):
    """A chat request failed in a way the user should be told about."""


@dataclass
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


class ChatModel(ABC):
    """LLM port. `context` is large and identical across turns of one chat
    (the documents), so implementations should cache it; `instructions` is fixed."""

    @abstractmethod
    def stream(self, instructions: str, context: str, turns: list[ChatTurn]) -> Iterator[str]:
        """Yield the reply as text chunks. Raise ChatError on failure."""
