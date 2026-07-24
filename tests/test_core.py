import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.core import (
    ChunkRange,
    WhisperEngine,
    WHISPER_BEAM_SIZE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE_INDEX,
    WHISPER_VAD_MIN_SILENCE_MS,
    build_chunk_ranges,
    format_timestamp,
    is_cuda_oom_error,
    resolve_transcribe_initial_prompt,
    transcribe_file_chunked,
)


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
            raise RuntimeError("CUDA failed with error out of memory")
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
    def test_engine_loads_faster_whisper_with_fixed_gpu_settings(self):
        calls = []

        class Model:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

        module = types.ModuleType("faster_whisper")
        module.WhisperModel = Model
        with patch.dict(sys.modules, {"faster_whisper": module}):
            engine = WhisperEngine()

        self.assertEqual("turbo", engine.model_name)
        self.assertEqual(("turbo",), calls[0][0])
        self.assertEqual("cuda", calls[0][1]["device"])
        self.assertEqual(WHISPER_DEVICE_INDEX, calls[0][1]["device_index"])
        self.assertEqual(WHISPER_COMPUTE_TYPE, calls[0][1]["compute_type"])

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

    @patch("src.core.probe_audio_duration", return_value=7200.0)
    def test_incremental_results_have_monotonic_global_timestamps(self, _probe):
        engine = FakeEngine()
        with tempfile.TemporaryDirectory() as directory:
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

    @patch("src.core.probe_audio_duration", return_value=3600.0)
    def test_oom_splits_hour_into_two_half_hours(self, _probe):
        engine = FakeEngine(oom_above=1800)
        with tempfile.TemporaryDirectory() as directory:
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

    def test_cuda_oom_detection_handles_ctranslate2_errors_and_causes(self):
        self.assertTrue(is_cuda_oom_error(RuntimeError("CUDA failed with error out of memory")))
        try:
            try:
                raise RuntimeError("CUBLAS_STATUS_ALLOC_FAILED")
            except RuntimeError as exc:
                raise RuntimeError("推理失败") from exc
        except RuntimeError as wrapped:
            self.assertTrue(is_cuda_oom_error(wrapped))
        self.assertFalse(is_cuda_oom_error(RuntimeError("audio decode failed")))

    @patch("src.core.os.unlink")
    @patch("src.core._pcm_file_to_float32", return_value=np.zeros(16000, dtype=np.float32))
    @patch("src.core._extract_pcm", return_value="fake.pcm")
    def test_overlap_segments_use_absolute_owner_range(self, _extract, _pcm, _unlink):
        consumed = []

        class Model:
            def transcribe(self, audio, **kwargs):
                self.kwargs = kwargs

                def generate():
                    consumed.append(True)
                    yield SimpleNamespace(start=0, end=5, text="previous")
                    yield SimpleNamespace(start=8, end=12, text="boundary")
                    yield SimpleNamespace(start=20, end=30, text="current")

                return generate(), SimpleNamespace(language="en")

        engine = WhisperEngine.__new__(WhisperEngine)
        model = Model()
        engine.model = model
        segments, _ = engine.transcribe_range(
            "ignored.mp3", ChunkRange(3600, 7200), 7200, None, None
        )
        self.assertEqual(["boundary", "current"], [item["text"] for item in segments])
        self.assertEqual(3600, segments[0]["start"])
        self.assertEqual(3602, segments[0]["end"])
        self.assertTrue(consumed)
        self.assertNotIn("initial_prompt", model.kwargs)
        self.assertEqual(WHISPER_BEAM_SIZE, model.kwargs["beam_size"])
        self.assertTrue(model.kwargs["condition_on_previous_text"])
        self.assertTrue(model.kwargs["vad_filter"])
        self.assertEqual(
            WHISPER_VAD_MIN_SILENCE_MS,
            model.kwargs["vad_parameters"]["min_silence_duration_ms"],
        )

    @patch("src.core.WHISPER_VAD_ENABLED", False)
    @patch("src.core.os.unlink")
    @patch("src.core._pcm_file_to_float32", return_value=np.zeros(16000, dtype=np.float32))
    @patch("src.core._extract_pcm", return_value="fake.pcm")
    def test_vad_can_be_disabled_by_configuration(self, _extract, _pcm, _unlink):
        class Model:
            def transcribe(self, audio, **kwargs):
                self.kwargs = kwargs
                return iter(()), SimpleNamespace(language="en")

        engine = WhisperEngine.__new__(WhisperEngine)
        model = Model()
        engine.model = model
        engine.transcribe_range("ignored.mp3", ChunkRange(0, 10), 10, None, None)

        self.assertFalse(model.kwargs["vad_filter"])
        self.assertNotIn("vad_parameters", model.kwargs)


if __name__ == "__main__":
    unittest.main()
