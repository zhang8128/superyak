"""Task context — swappable working memory, separate from identity."""

import uuid
import pytest
from storage import Storage


@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"), migrations_dir="migrations")
    yield s
    s.conn.close()


class TestTaskContextCRUD:
    """Basic create, read, update, archive operations."""

    def test_no_active_context_initially(self, storage):
        assert storage.get_active_task_context() is None

    def test_set_creates_active_context(self, storage):
        storage.set_task_context("t1", "test-task", "# Test\nDoing things.")
        ctx = storage.get_active_task_context()
        assert ctx is not None
        assert ctx["name"] == "test-task"
        assert ctx["status"] == "active"
        assert "Doing things" in ctx["content"]

    def test_set_archives_previous_active(self, storage):
        storage.set_task_context("t1", "first", "First task")
        storage.set_task_context("t2", "second", "Second task")
        ctx = storage.get_active_task_context()
        assert ctx["name"] == "second"
        # First should be archived
        old = storage.get_task_context_by_name("first")
        assert old["status"] == "archived"

    def test_update_changes_content(self, storage):
        storage.set_task_context("t1", "task", "v1")
        storage.update_task_context("v2 — updated")
        ctx = storage.get_active_task_context()
        assert "v2" in ctx["content"]

    def test_update_returns_none_when_no_active(self, storage):
        assert storage.update_task_context("orphan") is None

    def test_archive_deactivates(self, storage):
        storage.set_task_context("t1", "task", "content")
        archived = storage.archive_task_context()
        assert archived["name"] == "task"
        assert storage.get_active_task_context() is None

    def test_archive_returns_none_when_no_active(self, storage):
        assert storage.archive_task_context() is None

    def test_resume_by_name(self, storage):
        storage.set_task_context("t1", "governor-build", "Building governor")
        storage.archive_task_context()
        assert storage.get_active_task_context() is None
        # Resume: set_task_context with same id reactivates
        old = storage.get_task_context_by_name("governor-build")
        storage.set_task_context(old["id"], old["name"], old["content"])
        ctx = storage.get_active_task_context()
        assert ctx["name"] == "governor-build"

    def test_get_by_name_returns_none_for_unknown(self, storage):
        assert storage.get_task_context_by_name("nonexistent") is None

    def test_upsert_updates_existing(self, storage):
        storage.set_task_context("t1", "task", "v1")
        storage.set_task_context("t1", "task", "v2")
        ctx = storage.get_active_task_context()
        assert "v2" in ctx["content"]
