import unittest
from pathlib import Path

from src.api import _make_task_payload, _safe_upload_name


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


if __name__ == "__main__":
    unittest.main()
