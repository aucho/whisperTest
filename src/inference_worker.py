"""独立 Whisper 推理 Worker。音频通过文件路径传递，避免跨进程复制。"""

from __future__ import annotations

import os
import time
import traceback
from multiprocessing.queues import Queue
from pathlib import Path

from src.core import (
    WHISPER_BACKEND,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE_INDEX,
    WHISPER_VAD_ENABLED,
    WhisperEngine,
    is_cuda_oom_error,
    transcribe_file_chunked,
)


def _rss_bytes() -> int:
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except Exception:
        return 0


def worker_main(command_queue: Queue, event_queue: Queue, rss_growth_limit_mb: int) -> None:
    try:
        event_queue.put({"type": "worker_stage", "stage": "model_loading"})
        engine = WhisperEngine()
        baseline_rss = _rss_bytes()
        event_queue.put(
            {
                "type": "worker_ready",
                "model_loaded": True,
                "effective_model_name": "turbo",
                "backend": WHISPER_BACKEND,
                "compute_type": WHISPER_COMPUTE_TYPE,
                "device_index": WHISPER_DEVICE_INDEX,
                "vad_enabled": WHISPER_VAD_ENABLED,
                "baseline_rss": baseline_rss,
            }
        )
    except Exception as exc:
        event_queue.put(
            {
                "type": "worker_start_failed",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        return

    while True:
        command = command_queue.get()
        if command is None or command.get("type") == "shutdown":
            return
        if command.get("type") != "transcribe":
            continue

        task = command["task"]
        task_id = task["task_id"]
        cancel_path = Path(task["cancel_path"])
        fatal_cuda_oom = False

        def report(fields: dict) -> None:
            event_queue.put(
                {
                    "type": "task_progress",
                    "task_id": task_id,
                    "event_at": time.time(),
                    **fields,
                }
            )

        try:
            cancel_path.unlink(missing_ok=True)
            event_queue.put(
                {
                    "type": "task_started",
                    "task_id": task_id,
                    "event_at": time.time(),
                }
            )
            metadata = transcribe_file_chunked(
                engine=engine,
                audio_path=task["audio_path"],
                result_path=task["result_path"],
                timestamp_path=task.get("timestamp_path"),
                language=task.get("language"),
                initial_prompt=task.get("initial_prompt"),
                progress_callback=report,
                cancel_callback=cancel_path.exists,
            )
            event_queue.put(
                {
                    "type": "task_completed",
                    "task_id": task_id,
                    "metadata": metadata,
                    "event_at": time.time(),
                }
            )
        except InterruptedError:
            event_queue.put(
                {"type": "task_cancelled", "task_id": task_id, "event_at": time.time()}
            )
        except Exception as exc:
            fatal_cuda_oom = is_cuda_oom_error(exc)
            event_queue.put(
                {
                    "type": "task_failed",
                    "task_id": task_id,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "event_at": time.time(),
                    "fatal_worker": fatal_cuda_oom,
                }
            )
        finally:
            cancel_path.unlink(missing_ok=True)

        if fatal_cuda_oom:
            event_queue.put({"type": "worker_recycle_requested", "reason": "CUDA OOM"})
            return

        rss = _rss_bytes()
        if baseline_rss and rss - baseline_rss > rss_growth_limit_mb * 1024 * 1024:
            event_queue.put(
                {
                    "type": "worker_recycle_requested",
                    "rss": rss,
                    "baseline_rss": baseline_rss,
                }
            )
            return
