"""Agent communication protocol — descriptors, routing, and escalation.

Framework-agnostic primitives for coordinating multiple configured agents:

- :class:`AgentDescriptor` / :class:`AgentDirectory` — who the agents are
  and how to build them (lazily).
- :class:`AgentRequest` / :class:`AgentResponse` — the handoff envelope.

Applications register their configured agents in a directory, route
incoming messages to the best specialist, and escalate low-confidence
answers to a stronger agent.
"""

from openbench.intelligence.protocol.descriptor import AgentDescriptor, AgentDirectory
from openbench.intelligence.protocol.envelope import AgentRequest, AgentResponse

__all__ = [
    "AgentDescriptor",
    "AgentDirectory",
    "AgentRequest",
    "AgentResponse",
]
