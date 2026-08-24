"""Message envelopes for agent-to-agent handoff.

:class:`AgentRequest` describes work handed to an agent (by the user or by
another agent); :class:`AgentResponse` is the structured reply. The
response's :meth:`AgentResponse.to_metadata` is the single source of the
camelCase metadata keys the chat pipeline and UI consume — keep any new
key here, not scattered at call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRequest:
    """Work handed to an agent.

    Attributes:
        message: The task or user message text.
        sender: Originating agent id, or ``"user"``.
        recipient: Target agent id (empty = undirected, router decides).
        metadata: Free-form context that rides along with the request.
    """

    message: str
    sender: str = "user"
    recipient: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """Structured reply from an agent.

    Attributes:
        text: The answer text (confidence marker already stripped).
        agent_id: Id of the agent that produced ``text``.
        agent_name: Display name of that agent.
        confidence: Self-reported confidence in [0, 1], or None when the
            agent did not report one.
        escalated: True when ``text`` came from an escalation fallback.
        escalated_from: Id of the original agent when ``escalated``.
        metadata: Free-form extras.
    """

    text: str
    agent_id: str
    agent_name: str = ""
    confidence: float | None = None
    escalated: bool = False
    escalated_from: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """CamelCase metadata dict for chat message pipelines.

        Only meaningful keys are emitted so merging into an existing
        metadata dict never overwrites unrelated values with blanks.
        """
        result: dict[str, Any] = {
            "agentId": self.agent_id,
            "agentName": self.agent_name or self.agent_id,
        }
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.escalated:
            result["escalated"] = True
            if self.escalated_from:
                result["escalatedFrom"] = self.escalated_from
        return result
