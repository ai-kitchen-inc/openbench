"""Tests for project context and registry."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from openbench.core.context import (
    ProjectContext,
    ProjectRegistry,
    generate_project_id,
    get_project_registry,
    reset_project_registry,
)


class TestGenerateProjectId(unittest.TestCase):
    """Tests for generate_project_id function."""

    def test_format(self):
        """Test project ID format."""
        project_id = generate_project_id()
        self.assertTrue(project_id.startswith("proj_"))
        self.assertEqual(len(project_id), 33)  # proj_ (5) + 12 + 16 = 33

    def test_uniqueness(self):
        """Test that generated IDs are unique."""
        ids = [generate_project_id() for _ in range(100)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_hex_characters(self):
        """Test that ID contains only valid hex characters after prefix."""
        project_id = generate_project_id()
        hex_part = project_id[5:]  # Remove 'proj_' prefix
        self.assertTrue(all(c in "0123456789abcdef" for c in hex_part))


class TestProjectContext(unittest.TestCase):
    """Tests for ProjectContext dataclass."""

    def test_creation_with_name(self):
        """Test creating project with just a name."""
        project = ProjectContext(name="Test Project")
        self.assertEqual(project.name, "Test Project")
        self.assertTrue(project.project_id.startswith("proj_"))
        self.assertEqual(project.user_id, "")
        self.assertIsNone(project.organization_id)

    def test_creation_with_all_fields(self):
        """Test creating project with all fields."""
        project = ProjectContext(
            name="Full Project",
            user_id="user123",
            organization_id="org456",
            description="A test project",
            settings={"key": "value"},
        )
        self.assertEqual(project.name, "Full Project")
        self.assertEqual(project.user_id, "user123")
        self.assertEqual(project.organization_id, "org456")
        self.assertEqual(project.description, "A test project")
        self.assertEqual(project.settings, {"key": "value"})

    def test_namespace_property(self):
        """Test namespace returns project_id."""
        project = ProjectContext(name="Test")
        self.assertEqual(project.namespace, project.project_id)

    def test_to_dict(self):
        """Test serialization to dict."""
        project = ProjectContext(name="Test Project")
        data = project.to_dict()
        self.assertEqual(data["name"], "Test Project")
        self.assertIn("project_id", data)
        self.assertIn("created_at", data)
        self.assertIsInstance(data["created_at"], str)  # ISO format

    def test_from_dict(self):
        """Test deserialization from dict."""
        original = ProjectContext(name="Original")
        data = original.to_dict()
        restored = ProjectContext.from_dict(data)
        self.assertEqual(restored.name, original.name)
        self.assertEqual(restored.project_id, original.project_id)

    def test_update(self):
        """Test updating project fields."""
        project = ProjectContext(name="Original")
        old_updated = project.updated_at
        project.update(name="Updated", description="New description")
        self.assertEqual(project.name, "Updated")
        self.assertEqual(project.description, "New description")
        self.assertGreaterEqual(project.updated_at, old_updated)

    def test_update_protected_fields(self):
        """Test that protected fields cannot be updated."""
        project = ProjectContext(name="Test")
        original_id = project.project_id
        original_created = project.created_at
        project.update(project_id="new_id", created_at=datetime.now())
        self.assertEqual(project.project_id, original_id)
        self.assertEqual(project.created_at, original_created)


class TestProjectRegistry(unittest.TestCase):
    """Tests for ProjectRegistry."""

    def setUp(self):
        """Create temporary storage for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = Path(self.temp_dir) / "projects.json"
        self.registry = ProjectRegistry(self.storage_path)

    def tearDown(self):
        """Clean up temporary storage."""
        if self.storage_path.exists():
            self.storage_path.unlink()

    def test_create_project(self):
        """Test creating a project."""
        project = self.registry.create(name="New Project")
        self.assertEqual(project.name, "New Project")
        self.assertTrue(project.project_id.startswith("proj_"))

    def test_create_project_with_fields(self):
        """Test creating project with all fields."""
        project = self.registry.create(
            name="Full Project",
            user_id="user123",
            organization_id="org456",
            description="Test",
            settings={"key": "value"},
        )
        self.assertEqual(project.user_id, "user123")
        self.assertEqual(project.organization_id, "org456")

    def test_get_project(self):
        """Test getting a project by ID."""
        created = self.registry.create(name="Test")
        retrieved = self.registry.get(created.project_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, created.name)

    def test_get_nonexistent(self):
        """Test getting nonexistent project returns None."""
        result = self.registry.get("nonexistent_id")
        self.assertIsNone(result)

    def test_get_by_name(self):
        """Test getting project by name."""
        self.registry.create(name="Unique Name")
        project = self.registry.get_by_name("Unique Name")
        self.assertIsNotNone(project)
        self.assertEqual(project.name, "Unique Name")

    def test_list_projects(self):
        """Test listing all projects."""
        self.registry.create(name="Project 1")
        self.registry.create(name="Project 2")
        self.registry.create(name="Project 3")
        projects = self.registry.list()
        self.assertEqual(len(projects), 3)

    def test_update_project(self):
        """Test updating a project."""
        project = self.registry.create(name="Original")
        self.registry.update(project.project_id, name="Updated")
        retrieved = self.registry.get(project.project_id)
        self.assertEqual(retrieved.name, "Updated")

    def test_delete_project(self):
        """Test deleting a project."""
        project = self.registry.create(name="To Delete")
        result = self.registry.delete(project.project_id)
        self.assertTrue(result)
        self.assertIsNone(self.registry.get(project.project_id))

    def test_delete_nonexistent(self):
        """Test deleting nonexistent project returns False."""
        result = self.registry.delete("nonexistent_id")
        self.assertFalse(result)

    def test_set_active(self):
        """Test setting active project."""
        project = self.registry.create(name="Active Project")
        result = self.registry.set_active(project.project_id)
        self.assertTrue(result)
        self.assertEqual(self.registry.active_project_id, project.project_id)

    def test_get_active(self):
        """Test getting active project."""
        project = self.registry.create(name="Active")
        self.registry.set_active(project.project_id)
        active = self.registry.get_active()
        self.assertIsNotNone(active)
        self.assertEqual(active.project_id, project.project_id)

    def test_first_project_becomes_active(self):
        """Test that first created project becomes active."""
        project = self.registry.create(name="First")
        self.assertEqual(self.registry.active_project_id, project.project_id)

    def test_delete_active_clears_active(self):
        """Test deleting active project clears active."""
        project = self.registry.create(name="Active")
        self.registry.delete(project.project_id)
        self.assertIsNone(self.registry.active_project_id)

    def test_persistence(self):
        """Test that projects persist across registry instances."""
        self.registry.create(name="Persistent")
        new_registry = ProjectRegistry(self.storage_path)
        projects = new_registry.list()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].name, "Persistent")

    def test_clear(self):
        """Test clearing all projects."""
        self.registry.create(name="Project 1")
        self.registry.create(name="Project 2")
        self.registry.clear()
        self.assertEqual(len(self.registry.list()), 0)
        self.assertIsNone(self.registry.active_project_id)


class TestProjectRegistrySingleton(unittest.TestCase):
    """Tests for singleton project registry."""

    def setUp(self):
        """Reset singleton before each test."""
        reset_project_registry()

    def tearDown(self):
        """Reset singleton after each test."""
        reset_project_registry()

    def test_get_project_registry(self):
        """Test getting singleton instance."""
        registry1 = get_project_registry()
        registry2 = get_project_registry()
        self.assertIs(registry1, registry2)

    def test_reset_project_registry(self):
        """Test resetting singleton."""
        registry1 = get_project_registry()
        reset_project_registry()
        registry2 = get_project_registry()
        self.assertIsNot(registry1, registry2)


if __name__ == "__main__":
    unittest.main()
