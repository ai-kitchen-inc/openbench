"""Tests for AGUIHandler dynamic step events."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import MagicMock

from openbench.intelligence.base import (
    BaseAgent,
    MessageRole,
    ProgressEvent,
)


class FakeEncoder:
    """Fake AG-UI event encoder that returns event type strings."""

    def encode(self, event: Any) -> str:
        cls_name = type(event).__name__
        # Include relevant attributes for assertion
        if hasattr(event, "step_name"):
            return f"{cls_name}:{event.step_name}"
        if hasattr(event, "delta"):
            return f"{cls_name}:{event.delta}"
        if hasattr(event, "message_id") and hasattr(event, "role"):
            return f"{cls_name}:start"
        if cls_name == "TextMessageEndEvent":
            return f"{cls_name}:end"
        if cls_name == "RunStartedEvent":
            return "RunStartedEvent"
        if cls_name == "RunFinishedEvent":
            return "RunFinishedEvent"
        if cls_name == "RunErrorEvent":
            return f"RunErrorEvent:{event.message}"
        if cls_name == "CustomEvent":
            return f"CustomEvent:{event.name}"
        return cls_name


class TestAGUIHandlerProgressEvents(unittest.TestCase):
    """Test that ProgressEvents in the queue produce correct step events."""

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_progress_events_produce_step_pairs(self):
        """Test that ProgressEvent in queue produces StepStarted/StepFinished events."""
        events: list[str] = []

        async def simulate_queue_consumer():
            """Simulate the AGUIHandler queue consumer logic."""

            queue: asyncio.Queue[str | ProgressEvent | None] = asyncio.Queue()

            # Simulate agent emitting progress + text
            await queue.put(ProgressEvent(phase="Thinking"))
            await queue.put("Hello ")
            await queue.put("world")
            await queue.put(ProgressEvent(phase="Running search_web"))
            await queue.put(ProgressEvent(phase="Analyzing results"))
            await queue.put("Final answer")
            await queue.put(None)

            current_step: str | None = None
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, ProgressEvent):
                    if current_step:
                        events.append(f"StepFinished:{current_step}")
                    current_step = item.phase
                    events.append(f"StepStarted:{current_step}")
                else:
                    events.append(f"TextDelta:{item}")

            if current_step:
                events.append(f"StepFinished:{current_step}")

        self._run_async(simulate_queue_consumer())

        self.assertEqual(
            events,
            [
                "StepStarted:Thinking",
                "TextDelta:Hello ",
                "TextDelta:world",
                "StepFinished:Thinking",
                "StepStarted:Running search_web",
                "StepFinished:Running search_web",
                "StepStarted:Analyzing results",
                "TextDelta:Final answer",
                "StepFinished:Analyzing results",
            ],
        )

    def test_no_progress_events_fallback(self):
        """Test that no progress events still works (text-only stream)."""
        events: list[str] = []

        async def simulate_no_progress():
            queue: asyncio.Queue[str | ProgressEvent | None] = asyncio.Queue()

            # Only text, no ProgressEvents
            await queue.put("Just text")
            await queue.put(None)

            current_step: str | None = None
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, ProgressEvent):
                    if current_step:
                        events.append(f"StepFinished:{current_step}")
                    current_step = item.phase
                    events.append(f"StepStarted:{current_step}")
                else:
                    events.append(f"TextDelta:{item}")

            if current_step:
                events.append(f"StepFinished:{current_step}")

        self._run_async(simulate_no_progress())

        # Should only have the text delta, no step events
        self.assertEqual(events, ["TextDelta:Just text"])

    def test_multiple_progress_events_correct_sequence(self):
        """Test multiple progress events produce correct step sequence."""
        events: list[str] = []

        async def simulate_full_sequence():
            queue: asyncio.Queue[str | ProgressEvent | None] = asyncio.Queue()

            await queue.put(ProgressEvent(phase="Planning approach"))
            await queue.put(ProgressEvent(phase="Searching knowledge"))
            await queue.put(ProgressEvent(phase="Thinking"))
            await queue.put("Response text")
            await queue.put(ProgressEvent(phase="Running search_web, calculate"))
            await queue.put(ProgressEvent(phase="Analyzing results"))
            await queue.put("Final text")
            await queue.put(None)

            current_step: str | None = None
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, ProgressEvent):
                    if current_step:
                        events.append(f"StepFinished:{current_step}")
                    current_step = item.phase
                    events.append(f"StepStarted:{current_step}")
                else:
                    events.append(f"TextDelta:{item}")

            if current_step:
                events.append(f"StepFinished:{current_step}")

        self._run_async(simulate_full_sequence())

        expected = [
            "StepStarted:Planning approach",
            "StepFinished:Planning approach",
            "StepStarted:Searching knowledge",
            "StepFinished:Searching knowledge",
            "StepStarted:Thinking",
            "TextDelta:Response text",
            "StepFinished:Thinking",
            "StepStarted:Running search_web, calculate",
            "StepFinished:Running search_web, calculate",
            "StepStarted:Analyzing results",
            "TextDelta:Final text",
            "StepFinished:Analyzing results",
        ]
        self.assertEqual(events, expected)


class TestAGUIHandlerSessionIsolation(unittest.TestCase):
    """Test AGUIHandler session isolation."""

    def test_get_or_create_session(self):
        """Test session creation and retrieval."""
        from openbench.chat.transport.agui import AGUIHandler

        engine = MagicMock()
        handler = AGUIHandler(engine=engine)

        session1 = handler._get_or_create_session("session-1")
        session2 = handler._get_or_create_session("session-1")
        session3 = handler._get_or_create_session("session-2")

        self.assertIs(session1, session2)
        self.assertIsNot(session1, session3)

    def test_create_request_agent_copies_base_agent(self):
        """Test that request agent is a copy with fresh memory."""
        from openbench.chat.transport.agui import AGUIHandler

        engine = MagicMock()
        original_agent = BaseAgent(goal="Test agent")
        original_agent.memory.add_user("Previous message")
        engine.agent = original_agent

        handler = AGUIHandler(engine=engine)
        request_agent = handler._create_request_agent()

        # Should be a different object
        self.assertIsNot(request_agent, original_agent)
        # Fresh memory should only have system prompt
        self.assertEqual(len(request_agent.memory.messages), 1)
        self.assertEqual(request_agent.memory.messages[0].role, MessageRole.SYSTEM)

    def test_create_request_agent_non_base_returns_same(self):
        """Test that non-BaseAgent is returned as-is."""
        from openbench.chat.transport.agui import AGUIHandler

        engine = MagicMock()
        engine.agent = MagicMock()  # Not a BaseAgent

        handler = AGUIHandler(engine=engine)
        request_agent = handler._create_request_agent()

        self.assertIs(request_agent, engine.agent)


if __name__ == "__main__":
    unittest.main()
