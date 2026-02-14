"""
Transport abstract base class.

Defines the interface for chat transport implementations (WebSocket, SSE, etc.).
"""
from __future__ import annotations


from abc import ABC, abstractmethod
from typing import Any


class ChatTransport(ABC):
    """Abstract base for chat transport implementations.

    Transport handles the connection lifecycle and message delivery
    between the chat UI client and the ChatEngine backend.
    """

    @abstractmethod
    async def handle(self, connection: Any) -> None:
        """Handle a connection lifecycle (accept, message loop, close).

        Args:
            connection: The transport-specific connection object
                        (e.g., FastAPI WebSocket).
        """

    @abstractmethod
    async def send(self, connection: Any, data: dict[str, Any]) -> None:
        """Send a message to the client.

        Args:
            connection: The transport-specific connection object.
            data: Message data to send (will be JSON-serialized).
        """

    @abstractmethod
    async def receive(self, connection: Any) -> dict[str, Any]:
        """Receive a message from the client.

        Args:
            connection: The transport-specific connection object.

        Returns:
            Parsed message data from the client.
        """
