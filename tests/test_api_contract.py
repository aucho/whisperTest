import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from src import api
from src.api import _make_task_payload, _prepare_async_task_dir, _safe_upload_name, health_check


class ApiContractTests(unittest.TestCase):
    def test_requested_model_is_preserved_but_effective_model_is_turbo(self):
        task = _make_task_payload(
            "task-1",
            Path("tasks/task-1"),
            Path("tasks/task-1/source.mp3"),
            "unknown-old-model",
            None,
            False,
            None,
            True,
        )
        self.assertEqual("unknown-old-model", task["requested_model_name"])
        self.assertEqual("turbo", task["effective_model_name"])

    def test_upload_name_cannot_overwrite_task_metadata(self):
        self.assertEqual("source-status.json", _safe_upload_name("status.json"))
        self.assertEqual("source-audio.mp3", _safe_upload_name("../audio.mp3"))

    def test_health_exposes_faster_whisper_runtime_settings(self):
        snapshot = {
            "worker_alive": True,
            "worker_ready": True,
            "model_loaded": True,
            "worker_stage": "idle",
            "queue_depth": 0,
            "queue_capacity": 5,
            "current_task_id": None,
            "start_error": None,
        }
        with patch("src.api.coordinator.snapshot", return_value=snapshot):
            response = asyncio.run(health_check())
        payload = json.loads(response.body)
        self.assertEqual("faster-whisper", payload["backend"])
        self.assertEqual("float16", payload["compute_type"])
        self.assertEqual(0, payload["device_index"])
        self.assertTrue(payload["vad_enabled"])

    def test_completed_async_task_id_can_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            task_root = Path(directory)
            task_dir = task_root / "repeatable-task"
            task_dir.mkdir()
            (task_dir / "status.json").write_text(
                json.dumps({"status": "completed"}), encoding="utf-8"
            )
            (task_dir / "result.txt").write_text("old result", encoding="utf-8")

            with (
                patch.object(api, "TASK_DIR", task_root),
                patch.object(api.coordinator, "known_ids", set()),
                patch.object(api.coordinator, "has_capacity", return_value=True),
            ):
                api.TASK_STATUS.pop("repeatable-task", None)
                prepared = _prepare_async_task_dir("repeatable-task")

            self.assertEqual(task_dir, prepared)
            self.assertFalse(task_dir.exists())

    def test_active_async_task_id_still_rejects_concurrent_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            task_root = Path(directory)
            task_dir = task_root / "active-task"
            task_dir.mkdir()
            (task_dir / "status.json").write_text(
                json.dumps({"status": "processing"}), encoding="utf-8"
            )

            with (
                patch.object(api, "TASK_DIR", task_root),
                patch.object(api.coordinator, "known_ids", set()),
            ):
                api.TASK_STATUS.pop("active-task", None)
                with self.assertRaises(HTTPException) as context:
                    _prepare_async_task_dir("active-task")

            self.assertEqual(409, context.exception.status_code)
            self.assertTrue(task_dir.exists())


if __name__ == "__main__":
    unittest.main()
