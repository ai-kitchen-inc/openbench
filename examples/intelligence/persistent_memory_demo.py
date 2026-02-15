"""
Persistent Memory Demo - Cross-session conversation persistence with SQLite.

Demonstrates how PersistentMemory and SQLiteMemoryStore enable agents to
remember conversations across sessions (process restarts).

Three demos:
    1. SQLiteMemoryStore: Direct store operations (save, load, search)
    2. PersistentMemory: AgentMemory subclass with auto-persistence
    3. BaseAgent + memory_store: Agent that remembers across sessions

Usage:
    python examples/intelligence/persistent_memory_demo.py
    python examples/intelligence/persistent_memory_demo.py --demo 1
    python examples/intelligence/persistent_memory_demo.py --model gemini-2.5-pro
    python examples/intelligence/persistent_memory_demo.py --db /tmp/my_memory.db

Requires:
    - GOOGLE_API_KEY (required for demo 3)
"""

import argparse
import os
import sys
import tempfile

from openbench.intelligence.base import MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore

DEFAULT_MODEL = "gemini-2.5-flash"


def print_header(title: str):
    """Print formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_messages(messages, label: str = "Messages"):
    """Print messages in a formatted way."""
    print(f"\n  {label} ({len(messages)}):")
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "?")
            content = msg.get("content", "")
        else:
            role = msg.role.value if hasattr(msg.role, "value") else msg.role
            content = msg.content
        print(f"    [{role:>9}] {content[:80]}")


# --- Demo Functions ---


def demo_sqlite_store(db_path: str):
    """Demo 1: SQLiteMemoryStore direct usage.

    Shows the low-level store operations: save, load, search,
    list_sessions, and delete_session.
    """
    print_header("Demo 1: SQLiteMemoryStore")

    from openbench.intelligence.base import Message

    store = SQLiteMemoryStore(db_path=db_path)

    # Save messages to different sessions
    print("\n  Saving messages to 3 sessions...")

    store.save(
        "session-alpha",
        [
            Message(role=MessageRole.USER, content="What is Python used for?"),
            Message(
                role=MessageRole.ASSISTANT,
                content="Python is used for web dev, data science, AI, and automation.",
            ),
        ],
    )

    store.save(
        "session-beta",
        [
            Message(role=MessageRole.USER, content="Explain machine learning basics"),
            Message(
                role=MessageRole.ASSISTANT,
                content="ML is a subset of AI where models learn patterns from data.",
            ),
        ],
    )

    store.save(
        "session-gamma",
        [
            Message(role=MessageRole.USER, content="How to cook pasta?"),
            Message(
                role=MessageRole.ASSISTANT,
                content="Boil water, add salt, cook pasta 8-10 min, drain.",
            ),
        ],
    )

    # List sessions
    sessions = store.list_sessions()
    print(f"  Sessions: {sessions}")

    # Load specific session
    messages = store.load("session-alpha")
    print_messages(messages, "session-alpha")

    # Search across sessions
    print("\n  Searching for 'Python'...")
    results = store.search("Python")
    print_messages(results, "Search results")

    print("\n  Searching for 'learning'...")
    results = store.search("learning")
    print_messages(results, "Search results")

    # Delete a session
    print("\n  Deleting session-gamma...")
    store.delete_session("session-gamma")
    sessions = store.list_sessions()
    print(f"  Sessions after delete: {sessions}")

    # Append to existing session
    print("\n  Appending to session-alpha...")
    store.save(
        "session-alpha",
        [Message(role=MessageRole.USER, content="What about web frameworks?")],
    )
    messages = store.load("session-alpha")
    print_messages(messages, "session-alpha (updated)")

    print(f"\n  Database: {db_path}")


def demo_persistent_memory(db_path: str):
    """Demo 2: PersistentMemory (auto-persisting AgentMemory).

    Shows how PersistentMemory automatically saves every message to the
    store and loads previous conversations on initialization.
    """
    print_header("Demo 2: PersistentMemory")

    store = SQLiteMemoryStore(db_path=db_path)

    # Simulate Session 1
    print("\n  --- Session 1 (first conversation) ---")
    mem1 = PersistentMemory(store=store, session_id="chat-001")
    mem1.add_system("You are a helpful coding assistant.")
    mem1.add_user("How do I read a file in Python?")
    mem1.add_assistant("Use open() with a context manager: with open('file.txt') as f: ...")
    mem1.add_user("What about binary files?")
    mem1.add_assistant("Use 'rb' mode: with open('file.bin', 'rb') as f: ...")

    messages = mem1.get_messages()
    print_messages(messages, "Session 1 messages")
    print("  (all auto-persisted to SQLite)")

    # Simulate Session 2 (process restart)
    print("\n  --- Session 2 (simulating process restart) ---")
    print("  Creating new PersistentMemory with same session_id...")
    mem2 = PersistentMemory(store=store, session_id="chat-001")
    messages = mem2.get_messages()
    print_messages(messages, "Loaded from previous session")

    # Continue the conversation
    mem2.add_user("How about CSV files?")
    mem2.add_assistant("Use the csv module: import csv; reader = csv.reader(open('data.csv'))")
    messages = mem2.get_messages()
    print(f"\n  Total messages after continuation: {len(messages)}")

    # Different session is isolated
    print("\n  --- Different session (isolated) ---")
    mem3 = PersistentMemory(store=store, session_id="chat-002")
    mem3.add_user("This is a separate conversation")
    print(f"  chat-002 has {len(mem3.get_messages())} messages (isolated from chat-001)")

    # Search across sessions
    print("\n  --- Cross-session search ---")
    results = mem2.search_history("file")
    print_messages(results, "Search 'file' across all sessions")

    # Clear
    print("\n  --- Clear session ---")
    mem3.clear()
    loaded = store.load("chat-002")
    print(f"  chat-002 after clear: {len(loaded)} messages (deleted from store)")

    print(f"\n  Database: {db_path}")


def demo_agent_with_memory(model: str, db_path: str):
    """Demo 3: BaseAgent with persistent memory.

    Shows how BaseAgent uses memory_store + session_id to persist
    conversations and resume across agent instances.
    """
    print_header("Demo 3: BaseAgent + Persistent Memory")

    if not os.getenv("GOOGLE_API_KEY"):
        print("\n  Skipped: GOOGLE_API_KEY not set.")
        print("  Set it with: export GOOGLE_API_KEY=your-key")
        return

    from openbench.core.abstractions import ExecutionContext
    from openbench.core.providers import ProviderType, configure_provider
    from openbench.intelligence.base import BaseAgent
    from openbench.intelligence.llm_providers import GeminiLLMProvider  # noqa: F401

    configure_provider(
        name="gemini-default",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": os.getenv("GOOGLE_API_KEY")},
        settings={"model": model},
        is_default=True,
    )

    store = SQLiteMemoryStore(db_path=db_path)

    # Turn 1
    print(f"\n  Model: {model}")
    print("  Persistent memory: ENABLED")
    print("\n  --- Turn 1 ---")

    agent1 = BaseAgent(
        goal="You are a helpful assistant that remembers previous conversations.",
        model=model,
        temperature=0.3,
        memory_store=store,
        session_id="agent-session-1",
    )

    query1 = "My name is Alex and I work on machine learning projects."
    print(f"  User: {query1}")
    result1 = agent1.execute(ExecutionContext(goal=query1))
    print(f"  Agent: {result1.output[:120]}...")

    # Turn 2 (new agent instance, same session)
    print("\n  --- Turn 2 (new instance, same session) ---")

    agent2 = BaseAgent(
        goal="You are a helpful assistant that remembers previous conversations.",
        model=model,
        temperature=0.3,
        memory_store=store,
        session_id="agent-session-1",
    )

    # Verify memory loaded
    loaded_count = len(agent2.memory.messages)
    print(f"  Memory loaded: {loaded_count} messages from previous turn")

    query2 = "What is my name and what do I work on?"
    print(f"  User: {query2}")
    result2 = agent2.execute(ExecutionContext(goal=query2))
    print(f"  Agent: {result2.output[:200]}...")

    # Show sessions
    sessions = store.list_sessions()
    print(f"\n  Active sessions: {sessions}")
    print(f"  Database: {db_path}")


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Persistent Memory Demo - Cross-session conversation persistence",
    )
    parser.add_argument(
        "--demo",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Which demo to run (default: all)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Database path (default: temp file)",
    )
    args = parser.parse_args()

    # Use temp file if no db path specified
    if args.db:
        db_path = args.db
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115
        tmp.close()
        db_path = tmp.name

    print("=" * 60)
    print("  OpenBench: Persistent Memory Demo")
    print("=" * 60)
    print(f"\n  Database: {db_path}")
    print(f"  Model: {args.model}")
    print(f"  GOOGLE_API_KEY: {'set' if os.getenv('GOOGLE_API_KEY') else 'not set (optional)'}")

    try:
        if args.demo in ("1", "all"):
            demo_sqlite_store(db_path)

        if args.demo in ("2", "all"):
            demo_persistent_memory(db_path)

        if args.demo in ("3", "all"):
            demo_agent_with_memory(args.model, db_path)

        print(f"\n{'=' * 60}")
        print("  Done!")
        print(f"{'=' * 60}")

        # Clean up temp db
        if not args.db:
            os.unlink(db_path)
            print("  (temp database removed)")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
