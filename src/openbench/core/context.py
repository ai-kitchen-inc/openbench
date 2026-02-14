"""Project context for multi-tenant data isolation."""
from __future__ import annotations


import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def generate_project_id() -> str:
    """Generate a unique project ID using timestamp + random bytes.

    Format: proj_<timestamp_hex><random_hex> (31 chars total)
    Example: proj_018d4f5a7b3c9e8d7f6a5b4c3d2
    """
    timestamp_ms = int(time.time() * 1000)
    timestamp_hex = format(timestamp_ms, "012x")
    random_hex = secrets.token_hex(8)
    return f"proj_{timestamp_hex}{random_hex}"


@dataclass
class ProjectContext:
    """Context for a project, providing multi-tenant data isolation.

    Attributes:
        project_id: Unique identifier for the project (auto-generated if not provided)
        name: Human-readable project name
        user_id: Optional user identifier for user-level isolation
        organization_id: Optional organization identifier
        description: Optional project description
        settings: Additional project-specific settings
        created_at: Timestamp when project was created
        updated_at: Timestamp when project was last updated
    """

    name: str
    project_id: str = field(default_factory=generate_project_id)
    user_id: str = ""
    organization_id: str | None = None
    description: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def namespace(self) -> str:
        """Return namespace for vector store isolation (e.g., Pinecone)."""
        return self.project_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectContext":
        """Create from dictionary."""
        data = data.copy()
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)

    def update(self, **kwargs: Any) -> None:
        """Update project fields."""
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in ("project_id", "created_at"):
                setattr(self, key, value)
        self.updated_at = datetime.now()


class ProjectRegistry:
    """Registry for managing projects with persistence.

    Projects are stored in ~/.openbench/projects.json
    """

    DEFAULT_PATH = Path.home() / ".openbench" / "projects.json"

    def __init__(self, storage_path: Path | None = None):
        """Initialize registry with optional custom storage path."""
        self.storage_path = storage_path or self.DEFAULT_PATH
        self._projects: dict[str, ProjectContext] = {}
        self._active_project_id: str | None = None
        self._load()

    def _ensure_directory(self) -> None:
        """Ensure storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Load projects from storage."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path) as f:
                    data = json.load(f)
                    self._projects = {
                        k: ProjectContext.from_dict(v) for k, v in data.get("projects", {}).items()
                    }
                    self._active_project_id = data.get("active_project_id")
            except (json.JSONDecodeError, KeyError):
                self._projects = {}
                self._active_project_id = None

    def _save(self) -> None:
        """Save projects to storage."""
        self._ensure_directory()
        data = {
            "projects": {k: v.to_dict() for k, v in self._projects.items()},
            "active_project_id": self._active_project_id,
        }
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def create(
        self,
        name: str,
        user_id: str = "",
        organization_id: str | None = None,
        description: str = "",
        settings: dict[str, Any] | None = None,
    ) -> ProjectContext:
        """Create a new project."""
        project = ProjectContext(
            name=name,
            user_id=user_id,
            organization_id=organization_id,
            description=description,
            settings=settings or {},
        )
        self._projects[project.project_id] = project

        # Set as active if first project
        if len(self._projects) == 1:
            self._active_project_id = project.project_id

        self._save()
        return project

    def get(self, project_id: str) -> ProjectContext | None:
        """Get a project by ID."""
        return self._projects.get(project_id)

    def get_by_name(self, name: str) -> ProjectContext | None:
        """Get a project by name (returns first match)."""
        for project in self._projects.values():
            if project.name == name:
                return project
        return None

    def list(self) -> list[ProjectContext]:
        """List all projects."""
        return list(self._projects.values())

    def update(self, project_id: str, **kwargs: Any) -> ProjectContext | None:
        """Update a project."""
        project = self._projects.get(project_id)
        if project:
            project.update(**kwargs)
            self._save()
        return project

    def delete(self, project_id: str) -> bool:
        """Delete a project."""
        if project_id in self._projects:
            del self._projects[project_id]
            if self._active_project_id == project_id:
                self._active_project_id = None
            self._save()
            return True
        return False

    def set_active(self, project_id: str) -> bool:
        """Set the active project."""
        if project_id in self._projects:
            self._active_project_id = project_id
            self._save()
            return True
        return False

    def get_active(self) -> ProjectContext | None:
        """Get the currently active project."""
        if self._active_project_id:
            return self._projects.get(self._active_project_id)
        return None

    @property
    def active_project_id(self) -> str | None:
        """Get the active project ID."""
        return self._active_project_id

    def clear(self) -> None:
        """Clear all projects (useful for testing)."""
        self._projects = {}
        self._active_project_id = None
        self._save()


# Singleton instance
_project_registry: ProjectRegistry | None = None


def get_project_registry(storage_path: Path | None = None) -> ProjectRegistry:
    """Get the singleton project registry instance."""
    global _project_registry
    if _project_registry is None:
        _project_registry = ProjectRegistry(storage_path)
    return _project_registry


def reset_project_registry() -> None:
    """Reset the singleton instance (useful for testing)."""
    global _project_registry
    _project_registry = None
