"""FastAPI 主进程中的持久任务队列与 Worker 监督器。"""

from __future__ import annotations

import asyncio
import multiprocessing
import queue
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional

from src.inference_worker import worker_main


class QueueFullError(RuntimeError):
    pass


class DuplicateTaskError(RuntimeError):
    pass


class TaskCoordinator:
    def __init__(
        self,
        update_status: Callable[..., None],
        queue_limit: int = 5,
        chunk_timeout: int = 7200,
        rss_growth_limit_mb: int = 2048,
    ) -> None:
        self.update_status = update_status
        self.queue_limit = queue_limit
        self.chunk_timeout = chunk_timeout
        self.rss_growth_limit_mb = rss_growth_limit_mb
        self.pending: deque[dict] = deque()
        self.current: Optional[dict] = None
        self.futures: dict[str, asyncio.Future] = {}
        self.known_ids: set[str] = set()
        self.worker = None
        self.command_queue = None
        self.event_queue = None
        self.worker_ready = False
        self.worker_stage = "stopped"
        self.model_loaded = False
        self.start_error: Optional[str] = None
        self.current_chunk_started_at: Optional[float] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._stopping = False
        self._ctx = multiprocessing.get_context("spawn")

    async def start(self) -> None:
        self._stopping = False
        self._spawn_worker()
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def wait_until_ready(self, timeout: int) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.worker_ready:
                return
            if self.start_error:
                raise RuntimeError(f"Whisper Worker 启动失败: {self.start_error}")
            await asyncio.sleep(0.25)
        raise RuntimeError(f"Whisper Worker 在 {timeout} 秒内未完成模型加载")

    async def stop(self) -> None:
        self._stopping = True
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self._terminate_worker(graceful=True)

    def _spawn_worker(self) -> None:
        self.command_queue = self._ctx.Queue(maxsize=1)
        self.event_queue = self._ctx.Queue()
        self.worker = self._ctx.Process(
            target=worker_main,
            args=(self.command_queue, self.event_queue, self.rss_growth_limit_mb),
            name="WhisperTurboWorker",
            daemon=True,
        )
        self.worker.start()
        self.worker_ready = False
        self.model_loaded = False
        self.worker_stage = "starting"
        self.start_error = None

    def _terminate_worker(self, graceful: bool = False) -> None:
        worker = self.worker
        if worker is None:
            return
        if graceful and worker.is_alive() and self.command_queue is not None:
            try:
                self.command_queue.put_nowait({"type": "shutdown"})
                worker.join(timeout=5)
            except (queue.Full, OSError):
                pass
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=5)
        self.worker = None
        self.worker_ready = False
        self.model_loaded = False
        self.worker_stage = "stopped"
        for process_queue in (self.command_queue, self.event_queue):
            if process_queue is None:
                continue
            try:
                process_queue.cancel_join_thread()
                process_queue.close()
            except (OSError, ValueError):
                pass
        self.command_queue = None
        self.event_queue = None

    def capacity_used(self) -> int:
        return len(self.pending) + (1 if self.current else 0)

    def has_capacity(self) -> bool:
        return self.capacity_used() < self.queue_limit

    def enqueue(self, task: dict, wait_for_result: bool = False) -> Optional[asyncio.Future]:
        task_id = task["task_id"]
        if task_id in self.known_ids:
            raise DuplicateTaskError(task_id)
        if not self.has_capacity():
            raise QueueFullError("Whisper任务队列已满")
        task.setdefault("attempt", 1)
        self.known_ids.add(task_id)
        self.pending.append(task)
        future = None
        if wait_for_result:
            future = asyncio.get_running_loop().create_future()
            self.futures[task_id] = future
        self._refresh_queue_positions()
        return future

    def recover(self, task: dict) -> bool:
        task["attempt"] = int(task.get("attempt", 1)) + 1
        if task["attempt"] > 2 or not self.has_capacity():
            return False
        self.known_ids.add(task["task_id"])
        self.pending.append(task)
        self._refresh_queue_positions()
        return True

    def cancel(self, task_id: str) -> str:
        for task in list(self.pending):
            if task["task_id"] == task_id:
                self.pending.remove(task)
                self._finish_future(task_id, {"status": "cancelled"})
                self.known_ids.discard(task_id)
                self._refresh_queue_positions()
                return "cancelled"
        if self.current and self.current["task_id"] == task_id:
            Path(self.current["cancel_path"]).touch()
            return "cancelling"
        return "not_found"

    def snapshot(self) -> dict:
        return {
            "worker_alive": bool(self.worker and self.worker.is_alive()),
            "worker_ready": self.worker_ready,
            "model_loaded": self.model_loaded,
            "worker_stage": self.worker_stage,
            "queue_depth": len(self.pending),
            "queue_capacity": self.queue_limit,
            "current_task_id": self.current["task_id"] if self.current else None,
            "start_error": self.start_error,
        }

    async def _monitor_loop(self) -> None:
        while not self._stopping:
            self._drain_events()
            if self.worker is not None and not self.worker.is_alive():
                self._handle_worker_exit()
            if (
                self.current
                and self.current_chunk_started_at
                and time.time() - self.current_chunk_started_at > self.chunk_timeout
            ):
                task_id = self.current["task_id"]
                self.update_status(
                    task_id,
                    status="queued",
                    stage="worker_timeout",
                    message=f"当前分块处理超过 {self.chunk_timeout} 秒，正在重启推理Worker",
                )
                self._terminate_worker()
                self._requeue_current_or_fail("推理Worker超时")
                self._spawn_worker()
            if self.worker_ready and self.current is None and self.pending:
                self._dispatch_next()
            await asyncio.sleep(0.25)

    def _drain_events(self) -> None:
        if self.event_queue is None:
            return
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                return
            self._handle_event(event)

    def _handle_event(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "worker_stage":
            self.worker_stage = event.get("stage", "starting")
        elif event_type == "worker_ready":
            self.worker_ready = True
            self.model_loaded = True
            self.worker_stage = "idle"
        elif event_type == "worker_start_failed":
            self.start_error = event.get("error")
            self.worker_stage = "start_failed"
        elif event_type == "task_started":
            if self.current and self.current["task_id"] == event.get("task_id"):
                self.worker_stage = "processing"
                self.update_status(
                    event["task_id"],
                    status="processing",
                    stage="probing",
                    message="正在读取音频并准备分块",
                    attempt=self.current.get("attempt", 1),
                )
        elif event_type == "task_progress":
            if not self.current or self.current["task_id"] != event.get("task_id"):
                return
            fields = {k: v for k, v in event.items() if k not in {"type", "task_id", "event_at"}}
            if fields.get("stage") == "transcribing":
                self.current_chunk_started_at = event.get("event_at", time.time())
                fields["current_chunk_started_at"] = self.current_chunk_started_at
            self.worker_stage = fields.get("stage", self.worker_stage)
            self.update_status(event["task_id"], status="processing", **fields)
        elif event_type in {"task_completed", "task_failed", "task_cancelled"}:
            self._handle_task_terminal(event)
        elif event_type == "worker_recycle_requested":
            self.worker_ready = False
            self.worker_stage = "recycling"

    def _handle_task_terminal(self, event: dict) -> None:
        task_id = event.get("task_id")
        if not self.current or self.current["task_id"] != task_id:
            return
        if event["type"] == "task_completed":
            metadata = event.get("metadata", {})
            self.update_status(
                task_id,
                status="completed",
                stage="completed",
                progress=100.0,
                message="转录完成",
                **metadata,
            )
            result = {"status": "completed", **metadata}
        elif event["type"] == "task_cancelled":
            self.update_status(task_id, status="cancelled", stage="cancelled", message="任务已取消")
            result = {"status": "cancelled"}
        else:
            error = event.get("error", "未知错误")
            self.update_status(task_id, status="failed", stage="failed", message=f"转录失败: {error}", error=error)
            result = {"status": "failed", "error": error}
        self._finish_future(task_id, result)
        self.known_ids.discard(task_id)
        self.current = None
        self.current_chunk_started_at = None
        self.worker_ready = True
        self.worker_stage = "idle"
        self._refresh_queue_positions()

    def _dispatch_next(self) -> None:
        task = self.pending.popleft()
        self.current = task
        self.current_chunk_started_at = None
        self.update_status(
            task["task_id"],
            status="processing",
            stage="dispatching",
            queue_position=0,
            message="任务已发送到推理Worker",
            attempt=task.get("attempt", 1),
        )
        self.command_queue.put_nowait({"type": "transcribe", "task": task})
        self.worker_ready = False
        self._refresh_queue_positions()

    def _handle_worker_exit(self) -> None:
        if self._stopping:
            return
        if self.start_error and self.current is None:
            self.worker_ready = False
            return
        self._requeue_current_or_fail(self.start_error or "推理Worker异常退出")
        self._terminate_worker()
        self._spawn_worker()

    def _requeue_current_or_fail(self, reason: str) -> None:
        task = self.current
        self.current = None
        self.current_chunk_started_at = None
        if task is None:
            return
        task["attempt"] = int(task.get("attempt", 1)) + 1
        if task["attempt"] <= 2:
            self.pending.appendleft(task)
            self.update_status(
                task["task_id"],
                status="queued",
                stage="recovered",
                message=f"{reason}，任务重新排队",
                attempt=task["attempt"],
            )
        else:
            self.update_status(task["task_id"], status="failed", stage="failed", message=reason, error=reason)
            self._finish_future(task["task_id"], {"status": "failed", "error": reason})
            self.known_ids.discard(task["task_id"])
        self._refresh_queue_positions()

    def _finish_future(self, task_id: str, result: dict) -> None:
        future = self.futures.pop(task_id, None)
        if future and not future.done():
            future.set_result(result)

    def _refresh_queue_positions(self) -> None:
        for index, task in enumerate(self.pending, start=1):
            self.update_status(task["task_id"], queue_position=index)
