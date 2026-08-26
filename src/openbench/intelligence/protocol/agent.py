"""ProtocolAgent — identity, confidence, and escalation wrapper.

Wraps a configured inner agent so the chat pipeline gets:

- identity metadata on every result (which agent answered),
- a live "Agen: <name>" progress step,
- optional low-confidence escalation to a stronger fallback agent.

Escalation trade-off (v1, deliberate): when a fallback is configured the
primary answer is executed *buffered* (no token streaming) so the user
never watches a weak answer get retracted; the stripped text is replayed
through ``on_chunk`` in one piece when it passes the threshold. Profiles
without a fallback keep full live streaming. Progress events stream live
in both modes. A future tail-hold optimization can restore token
streaming for the escalation path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult
from openbench.intelligence.agent_config import ProgressEvent
from openbench.intelligence.protocol.envelope import AgentResponse
from openbench.intelligence.protocol.escalation import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    extract_confidence,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from openbench.intelligence.protocol.descriptor import AgentDescriptor

logger = logging.getLogger(__name__)

AGENT_STEP_LABEL = "Agen: {name}"
ESCALATION_STEP_LABEL = "Eskalasi ke {name}"


class ProtocolAgent(Agent):
    """Identity + escalation wrapper around one configured agent.

    Args:
        inner: The primary agent (anything with a
            ``execute(context, on_chunk=..., on_progress=...)`` method,
            typically a :class:`~openbench.intelligence.base.BaseAgent`).
        descriptor: The primary agent's protocol descriptor.
        fallback: Optional stronger agent to escalate to when the primary
            self-reports confidence below ``confidence_threshold``.
        fallback_descriptor: Descriptor of the fallback agent (required
            when ``fallback`` is given — used for labels and metadata).
        confidence_threshold: Escalate strictly below this value.
    """

    def __init__(
        self,
        inner: Any,
        descriptor: AgentDescriptor,
        *,
        fallback: Any | None = None,
        fallback_descriptor: AgentDescriptor | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        if fallback is not None and fallback_descriptor is None:
            raise ValueError("fallback_descriptor is required when fallback is provided")
        self.inner = inner
        self.descriptor = descriptor
        self.fallback = fallback
        self.fallback_descriptor = fallback_descriptor
        self.confidence_threshold = confidence_threshold

    @property
    def agent_type(self) -> str:
        return "protocol"

    def estimate_cost(self, context: ExecutionContext) -> float:
        estimate = getattr(self.inner, "estimate_cost", None)
        return float(estimate(context)) if callable(estimate) else 0.0

    def execute(
        self,
        context: ExecutionContext,
        on_chunk: Callable[[str], None] | None = None,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> ExecutionResult:
        """Run the primary agent; escalate on self-reported low confidence."""
        if on_progress:
            on_progress(ProgressEvent(phase=AGENT_STEP_LABEL.format(name=self.descriptor.name)))
        if self.fallback is None:
            return self._execute_passthrough(context, on_chunk, on_progress)
        return self._execute_with_escalation(context, on_chunk, on_progress)

    # ------------------------------------------------------------------
    # Execution paths
    # ------------------------------------------------------------------

    def _execute_passthrough(
        self,
        context: ExecutionContext,
        on_chunk: Callable[[str], None] | None,
        on_progress: Callable[[ProgressEvent], None] | None,
    ) -> ExecutionResult:
        """No fallback: live streaming, identity metadata only."""
        result = self._run(self.inner, context, on_chunk=on_chunk, on_progress=on_progress)
        # Insurance: strip a stray marker even though this profile has no
        # escalation (e.g. persona copied from an escalation-enabled one).
        text, confidence = extract_confidence(self._output_text(result))
        if confidence is not None:
            result.output = text
        response = AgentResponse(
            text=text,
            agent_id=self.descriptor.id,
            agent_name=self.descriptor.name,
            confidence=confidence,
        )
        result.metadata.update(response.to_metadata())
        return result

    def _execute_with_escalation(
        self,
        context: ExecutionContext,
        on_chunk: Callable[[str], None] | None,
        on_progress: Callable[[ProgressEvent], None] | None,
    ) -> ExecutionResult:
        """Buffered primary run; replay on pass, escalate on low confidence."""
        assert self.fallback_descriptor is not None  # enforced in __init__
        pre_len = self._memory_length(self.inner)
        result = self._run(self.inner, context, on_chunk=None, on_progress=on_progress)
        text, confidence = extract_confidence(self._output_text(result))

        if confidence is None or confidence >= self.confidence_threshold:
            result.output = text
            if on_chunk and text:
                on_chunk(text)
            response = AgentResponse(
                text=text,
                agent_id=self.descriptor.id,
                agent_name=self.descriptor.name,
                confidence=confidence,
            )
            result.metadata.update(response.to_metadata())
            return result

        if on_progress:
            on_progress(
                ProgressEvent(
                    phase=ESCALATION_STEP_LABEL.format(name=self.fallback_descriptor.name)
                )
            )
        self._rollback_memory(self.inner, pre_len)
        # Single hop by construction: the fallback runs live-streamed and
        # its own confidence marker is stripped but never acted on.
        fallback_result = self._run(
            self.fallback, context, on_chunk=on_chunk, on_progress=on_progress
        )
        fallback_text, _ = extract_confidence(self._output_text(fallback_result))
        fallback_result.output = fallback_text
        response = AgentResponse(
            text=fallback_text,
            agent_id=self.fallback_descriptor.id,
            agent_name=self.fallback_descriptor.name,
            confidence=confidence,
            escalated=True,
            escalated_from=self.descriptor.id,
        )
        fallback_result.metadata.update(response.to_metadata())
        return fallback_result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run(
        agent: Any,
        context: ExecutionContext,
        on_chunk: Callable[[str], None] | None,
        on_progress: Callable[[ProgressEvent], None] | None,
    ) -> ExecutionResult:
        """Call ``agent.execute`` with the same tiered-kwargs fallback the
        chat engine uses, so any Agent implementation slots in."""
        kwargs: dict[str, Any] = {}
        if on_chunk:
            kwargs["on_chunk"] = on_chunk
        if on_progress:
            kwargs["on_progress"] = on_progress
        if kwargs:
            try:
                return agent.execute(context, **kwargs)
            except TypeError:
                if on_chunk:
                    try:
                        return agent.execute(context, on_chunk=on_chunk)
                    except TypeError:
                        pass
        return agent.execute(context)

    @staticmethod
    def _output_text(result: ExecutionResult) -> str:
        return result.output if isinstance(result.output, str) else str(result.output or "")

    @staticmethod
    def _memory_length(agent: Any) -> int | None:
        memory = getattr(agent, "memory", None)
        messages = getattr(memory, "messages", None)
        return len(messages) if isinstance(messages, list) else None

    @staticmethod
    def _rollback_memory(agent: Any, pre_len: int | None) -> None:
        """Best-effort removal of the discarded primary turn from memory.

        Worst case (no ``truncate_to`` or it raises) the weak turn lingers
        in the primary agent's memory — harmless duplication, never a
        failed chat turn.
        """
        if pre_len is None:
            return
        memory = getattr(agent, "memory", None)
        truncate = getattr(memory, "truncate_to", None)
        if not callable(truncate):
            return
        try:
            truncate(pre_len)
        except Exception:
            logger.warning("Escalation memory rollback failed", exc_info=True)
