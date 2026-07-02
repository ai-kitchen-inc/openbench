"""
OpenBench - The Open Source Agentic AI Workbench

Build. Orchestrate. Export. Scale.
"""

# isort: skip_file
# ChatLayer must be imported after core to avoid circular imports.

from openbench._version import __version__ as __version__
from openbench.core.context import ProjectContext, get_project_registry
from openbench.core.layers import DataLayer, IntelligenceLayer, OutputLayer
from openbench.core.storage import LocalStorageBackend, StorageBackend
from openbench.chat.layer import ChatLayer
from openbench.workflows.workflow import Workflow

__all__ = [
    "DataLayer",
    "IntelligenceLayer",
    "OutputLayer",
    "ChatLayer",
    "Workflow",
    "ProjectContext",
    "get_project_registry",
    "LocalStorageBackend",
    "StorageBackend",
    "get_default_storage",
    "set_default_storage",
]


# ---------------------------------------------------------------------------
# Module-level default StorageBackend.
#
# Applications that want zero-config persistence call
# ``openbench.set_default_storage(LocalStorageBackend())`` once at startup,
# or read the current default via ``openbench.get_default_storage()``.
# ``ChatEngine`` and ``BaseAgent`` never touch this implicitly — explicit
# construction is required — so running demos do not silently write to
# disk just by importing the package.
# ---------------------------------------------------------------------------

_default_storage: StorageBackend | None = None


def get_default_storage() -> StorageBackend | None:
    """Return the process-wide default :class:`StorageBackend`, if set.

    Returns ``None`` when no default has been configured. Callers that
    want a "Just Works" fallback should instantiate
    :class:`LocalStorageBackend` themselves, or call
    :func:`set_default_storage` once at application startup.
    """
    return _default_storage


def set_default_storage(backend: StorageBackend | None) -> None:
    """Set (or clear) the process-wide default :class:`StorageBackend`.

    Pass ``None`` to clear any previously set default — useful in tests
    that create a backend per-case.

    Args:
        backend: A backend instance (or ``None`` to unset).
    """
    global _default_storage
    _default_storage = backend
