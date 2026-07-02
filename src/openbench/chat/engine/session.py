"""Session persistence + aborted-turn placeholder helpers for ChatEngine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openbench.chat.engine.defaults import (
    _PLACEHOLDER_TURN_INTERRUPTED,
    _placeholder_on_abort_enabled,
)

if TYPE_CHECKING:
    from openbench.chat.session import ChatSession

logger = logging.getLogger(__name__)


class _SessionMixin:
    """Mixin for ChatEngine; not instantiated directly."""

    def _clear_render_items(self) -> None:
        """Invoke the clear-render-items callback if configured.

        Called at the start of every request to drop any render items left
        over from a previous turn (visualization tool queues are typically
        process-global, so without this they leak across sessions).
        """
        if self._clear_render_items_fn is None:
            return
        try:
            self._clear_render_items_fn()
        except Exception as e:
            logger.warning(f"clear_render_items_fn raised: {e}")

    def _write_aborted_placeholder(
        self,
        session: ChatSession | None,
        exc: BaseException,
    ) -> None:
        """Append a placeholder assistant message after a failed turn.

        Called from the ``except`` branch of :meth:`invoke`, :meth:`stream`,
        :meth:`async_stream`, and the AG-UI transport so the session
        always ends on an assistant turn — even if that turn is just
        "please retry". The placeholder's metadata carries
        ``aborted: True`` plus the short-form error, which transport
        layers can surface as a retry affordance.

        Args:
            session: The :class:`ChatSession` to mutate. Pass ``None``
                to default to ``self.session`` (used by ``invoke`` and
                ``stream``). Transport handlers that hold a
                per-request session pass it explicitly.
            exc: The exception that caused the abort — its str form is
                truncated and stored in metadata for debugging.

        Gated by :func:`_placeholder_on_abort_enabled` so tests and
        operators can disable it. The persist step uses the same
        best-effort wrapper as every other save — a storage failure
        here is logged but never re-raised (the original exception is
        still propagating up the stack).
        """
        if not _placeholder_on_abort_enabled():
            return
        target = session if session is not None else self.session
        try:
            target.add_assistant_message(
                content=_PLACEHOLDER_TURN_INTERRUPTED,
                metadata={"aborted": True, "error": str(exc)[:200]},
            )
            if self.session_store is not None:
                self.session_store.save(target)
        except Exception:
            logger.exception(
                "Failed to write aborted-turn placeholder for session_id=%s",
                getattr(target, "session_id", "<unknown>"),
            )

    def _persist_session(self) -> None:
        """Save the current session to ``session_store`` if configured.

        Called after each user and assistant message append. Swallows
        exceptions so a transient storage failure (disk full, DB lock)
        does not break the live chat turn — the in-memory session
        remains the source of truth until the next save succeeds.
        """
        if self.session_store is None:
            logger.debug("_persist_session: no session_store wired, skipping")
            return
        try:
            self.session_store.save(self.session)
            logger.info(
                "session saved: session_id=%s, messages=%d, store=%s",
                self.session.session_id,
                len(self.session.messages),
                type(self.session_store).__name__,
            )
        except Exception:
            logger.exception(
                "session_store.save failed for session_id=%s",
                self.session.session_id,
            )
