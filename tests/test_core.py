import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
import numpy as np

from src.core import (
    ChunkRange,
    WhisperEngine,
    build_chunk_ranges,
    format_timestamp,
    prepare_audio_source,
    resolve_transcribe_initial_prompt,
    _needs_aac_remux,
    transcribe_file_chunked,
)


class FakeEngine:
    def __init__(self, oom_above=None, empty_from=None):
        self.oom_above = oom_above
        self.empty_from = empty_from
        self.calls = []

    def transcribe_range(
        self, audio_path, owner, total_duration, language, initial_prompt, stage_callback=None
    ):
        self.calls.append(owner)
        if stage_callback:
            stage_callback("transcribing")
        if self.oom_above and owner.owner_end - owner.owner_start > self.oom_above:
            raise torch.cuda.OutOfMemoryError("test")
        if self.empty_from is not None and owner.owner_start >= self.empty_from:
            raise RuntimeError("音频分块解码结果为空")
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
    def test_auto_detection_has_no_builtin_prompt(self):
        self.assertIsNone(resolve_transcribe_initial_prompt(None, None))

    def test_explicit_prompt_is_kept_during_auto_detection(self):
        self.assertEqual("custom", resolve_transcribe_initial_prompt(None, " custom "))

    def test_detected_language_selects_matching_prompt(self):
        self.assertIn("welcome", resolve_transcribe_initial_prompt("en", None).lower())
        self.assertIn("直播间", resolve_transcribe_initial_prompt("zh", None))

    def test_timestamp_rounding_carries_into_next_minute(self):
        self.assertEqual("00:01:00.00", format_timestamp(59.999))

    def test_builds_hour_ranges_and_short_tail(self):
        ranges = build_chunk_ranges(10 * 3600 + 123)
        self.assertEqual(11, len(ranges))
        self.assertEqual(ChunkRange(0.0, 3600.0), ranges[0])
        self.assertEqual(10 * 3600, ranges[-1].owner_start)
        self.assertEqual(10 * 3600 + 123, ranges[-1].owner_end)

    @patch("src.core.probe_audio_info", return_value=(7200.0, "mp3"))
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
    @patch("src.core.probe_audio_info", return_value=(3600.0, "mp3"))
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

    @patch("src.core.probe_audio_info", return_value=(7200.0, "mp3"))
    def test_skips_empty_decode_after_first_chunk(self, _probe):
        engine = FakeEngine(empty_from=3600.0)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            result = Path(directory) / "result.txt"
            metadata = transcribe_file_chunked(
                engine,
                "ignored.mp3",
                str(result),
                None,
                "en",
                None,
            )
            self.assertEqual("chunk-0", result.read_text(encoding="utf-8").strip())
            self.assertEqual(2, metadata["chunks_processed"])
            self.assertEqual(
                ["分片2解码结果为空(3600.00-7200.00)"],
                metadata["chunk_warnings"],
            )
            self.assertEqual(1, len(metadata["skipped_chunks"]))
            self.assertEqual(2, metadata["skipped_chunks"][0]["chunk"])

    @patch("src.core.probe_audio_info", return_value=(3600.0, "mp3"))
    def test_empty_first_chunk_still_fails(self, _probe):
        engine = FakeEngine(empty_from=0.0)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            with self.assertRaisesRegex(RuntimeError, "音频分块解码结果为空"):
                transcribe_file_chunked(
                    engine,
                    "ignored.mp3",
                    str(Path(directory) / "result.txt"),
                    None,
                    "en",
                    None,
                )

    def test_needs_aac_remux_by_suffix_and_format(self):
        self.assertTrue(_needs_aac_remux("a.aac", "mp3"))
        self.assertTrue(_needs_aac_remux("a.bin", "aac"))
        self.assertFalse(_needs_aac_remux("a.m4a", "mov,mp4,m4a,3gp,3g2,mj2"))
        self.assertFalse(_needs_aac_remux("a.mp3", "mp3"))

    @patch("src.core.probe_audio_duration", return_value=18300.0)
    @patch("src.core.remux_aac_to_m4a")
    @patch("src.core.probe_audio_info", return_value=(19020.0, "aac"))
    def test_prepare_audio_source_remuxes_raw_aac(self, _info, remux, _duration):
        path, duration, cleanup = prepare_audio_source("live.aac")
        self.assertTrue(path.endswith(".m4a"))
        self.assertEqual(18300.0, duration)
        self.assertEqual(path, cleanup)
        remux.assert_called_once()
        if cleanup:
            Path(cleanup).unlink(missing_ok=True)

    @patch("src.core.probe_audio_duration", return_value=18300.0)
    @patch("src.core.remux_aac_to_m4a")
    @patch("src.core.probe_audio_info", return_value=(None, "aac"))
    def test_prepare_audio_source_remuxes_when_duration_missing(self, _info, remux, _duration):
        path, duration, cleanup = prepare_audio_source("live.aac")
        self.assertTrue(path.endswith(".m4a"))
        self.assertEqual(18300.0, duration)
        remux.assert_called_once()
        if cleanup:
            Path(cleanup).unlink(missing_ok=True)

    @patch("src.core.probe_audio_info", return_value=(None, "mp3"))
    def test_prepare_audio_source_rejects_missing_duration_for_non_aac(self, _info):
        with self.assertRaisesRegex(RuntimeError, "无法读取有效音频时长"):
            prepare_audio_source("live.mp3")

    @patch("src.core.os.unlink")
    @patch("src.core._pcm_file_to_float32", return_value=np.zeros(16000, dtype=np.float32))
    @patch("src.core._extract_pcm", return_value="fake.pcm")
    def test_overlap_segments_use_absolute_owner_range(self, _extract, _pcm, _unlink):
        class Model:
            def transcribe(self, audio, **kwargs):
                self.kwargs = kwargs
                return {
                    "language": "en",
                    "segments": [
                        {"start": 0, "end": 5, "text": "previous"},
                        {"start": 8, "end": 12, "text": "boundary"},
                        {"start": 20, "end": 30, "text": "current"},
                    ],
                }

        engine = WhisperEngine.__new__(WhisperEngine)
        model = Model()
        engine.model = model
        segments, _ = engine.transcribe_range(
            "ignored.mp3", ChunkRange(3600, 7200), 7200, None, None
        )
        self.assertEqual(["boundary", "current"], [item["text"] for item in segments])
        self.assertEqual(3600, segments[0]["start"])
        self.assertEqual(3602, segments[0]["end"])
        self.assertNotIn("initial_prompt", model.kwargs)


if __name__ == "__main__":
    unittest.main()
