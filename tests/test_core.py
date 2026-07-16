import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
import numpy as np

from src.core import ChunkRange, WhisperEngine, build_chunk_ranges, format_timestamp, transcribe_file_chunked


class FakeEngine:
    def __init__(self, oom_above=None):
        self.oom_above = oom_above
        self.calls = []

    def transcribe_range(
        self, audio_path, owner, total_duration, language, initial_prompt, stage_callback=None
    ):
        self.calls.append(owner)
        if stage_callback:
            stage_callback("transcribing")
        if self.oom_above and owner.owner_end - owner.owner_start > self.oom_above:
            raise torch.cuda.OutOfMemoryError("test")
        return (
            [
                {
                    "start": owner.owner_start,
                    "end": owner.owner_end,
                    "text": f"chunk-{owner.owner_start:.0f}",
                }
            ],
            language or "en",
        )


class CoreChunkTests(unittest.TestCase):
    def test_timestamp_rounding_carries_into_next_minute(self):
        self.assertEqual("00:01:00.00", format_timestamp(59.999))

    def test_builds_hour_ranges_and_short_tail(self):
        ranges = build_chunk_ranges(10 * 3600 + 123)
        self.assertEqual(11, len(ranges))
        self.assertEqual(ChunkRange(0.0, 3600.0), ranges[0])
        self.assertEqual(10 * 3600, ranges[-1].owner_start)
        self.assertEqual(10 * 3600 + 123, ranges[-1].owner_end)

    @patch("src.core.probe_audio_duration", return_value=7200.0)
    def test_incremental_results_have_monotonic_global_timestamps(self, _probe):
        engine = FakeEngine()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            result = Path(directory) / "result.txt"
            timestamps = Path(directory) / "timestamps.txt"
            metadata = transcribe_file_chunked(
                engine,
                "ignored.mp3",
                str(result),
                str(timestamps),
                None,
                None,
            )
            lines = timestamps.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(lines))
            self.assertIn("00:00:00.00 --> 01:00:00.00", lines[0])
            self.assertIn("01:00:00.00 --> 02:00:00.00", lines[1])
            self.assertEqual("en", metadata["language_detected"])

    @patch("src.core.torch.cuda.empty_cache")
    @patch("src.core.probe_audio_duration", return_value=3600.0)
    def test_oom_splits_hour_into_two_half_hours(self, _probe, empty_cache):
        engine = FakeEngine(oom_above=1800)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            metadata = transcribe_file_chunked(
                engine,
                "ignored.mp3",
                str(Path(directory) / "result.txt"),
                None,
                "en",
                None,
            )
        successful = [item for item in engine.calls if item.owner_end - item.owner_start <= 1800]
        self.assertEqual(2, len(successful))
        self.assertEqual(2, metadata["chunks_processed"])
        empty_cache.assert_called_once()

    @patch("src.core.os.unlink")
    @patch("src.core._pcm_file_to_float32", return_value=np.zeros(16000, dtype=np.float32))
    @patch("src.core._extract_pcm", return_value="fake.pcm")
    def test_overlap_segments_use_absolute_owner_range(self, _extract, _pcm, _unlink):
        class Model:
            def transcribe(self, audio, **kwargs):
                return {
                    "language": "en",
                    "segments": [
                        {"start": 0, "end": 5, "text": "previous"},
                        {"start": 8, "end": 12, "text": "boundary"},
                        {"start": 20, "end": 30, "text": "current"},
                    ],
                }

        engine = WhisperEngine.__new__(WhisperEngine)
        engine.model = Model()
        segments, _ = engine.transcribe_range(
            "ignored.mp3", ChunkRange(3600, 7200), 7200, None, None
        )
        self.assertEqual(["boundary", "current"], [item["text"] for item in segments])
        self.assertEqual(3600, segments[0]["start"])
        self.assertEqual(3602, segments[0]["end"])


if __name__ == "__main__":
    unittest.main()
