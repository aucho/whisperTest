import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.api import _make_task_payload, _safe_upload_name, health_check


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


if __name__ == "__main__":
    unittest.main()
