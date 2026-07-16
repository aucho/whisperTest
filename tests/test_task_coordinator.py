import tempfile
import unittest
from pathlib import Path

from src.task_coordinator import DuplicateTaskError, QueueFullError, TaskCoordinator


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.statuses = {}

        def update(task_id, **fields):
            self.statuses.setdefault(task_id, {}).update(fields)

        self.coordinator = TaskCoordinator(update, queue_limit=2)

    def task(self, task_id):
        directory = Path(tempfile.gettempdir()) / task_id
        return {"task_id": task_id, "cancel_path": str(directory / ".cancel"), "attempt": 1}

    def test_queue_limit_counts_waiting_tasks(self):
        self.coordinator.enqueue(self.task("one"))
        self.coordinator.enqueue(self.task("two"))
        with self.assertRaises(QueueFullError):
            self.coordinator.enqueue(self.task("three"))

    def test_duplicate_task_is_rejected(self):
        self.coordinator.enqueue(self.task("one"))
        with self.assertRaises(DuplicateTaskError):
            self.coordinator.enqueue(self.task("one"))

    def test_queued_task_can_be_cancelled(self):
        self.coordinator.enqueue(self.task("one"))
        self.assertEqual("cancelled", self.coordinator.cancel("one"))
        self.assertEqual(0, self.coordinator.capacity_used())

    def test_worker_crash_requeues_once_then_fails(self):
        task = self.task("one")
        self.coordinator.current = task
        self.coordinator.known_ids.add("one")
        self.coordinator._requeue_current_or_fail("crash")
        self.assertEqual(2, self.coordinator.pending[0]["attempt"])
        self.coordinator.current = self.coordinator.pending.popleft()
        self.coordinator._requeue_current_or_fail("crash again")
        self.assertEqual("failed", self.statuses["one"]["status"])
        self.assertEqual(0, self.coordinator.capacity_used())

    def test_terminal_event_releases_worker_for_next_task(self):
        task = self.task("one")
        self.coordinator.current = task
        self.coordinator.known_ids.add("one")
        self.coordinator._handle_event(
            {"type": "task_completed", "task_id": "one", "metadata": {"language_detected": "en"}}
        )
        self.assertTrue(self.coordinator.worker_ready)
        self.assertIsNone(self.coordinator.current)
        self.assertEqual("completed", self.statuses["one"]["status"])


if __name__ == "__main__":
    unittest.main()
