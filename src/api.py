"""FastAPI 接口：文件持久化、有界队列及独立 Whisper Worker。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from src.core import get_language_display
from src.task_coordinator import DuplicateTaskError, QueueFullError, TaskCoordinator

UPLOAD_BLOCK_SIZE = 1024 * 1024
TASK_DIR = Path(os.environ.get("WHISPER_TASK_DIR", "./storage/tasks")).resolve()
STATUS_RETENTION_SECONDS = 3600
TASK_FILE_RETENTION_SECONDS = 86400
EFFECTIVE_MODEL_NAME = "turbo"
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


QUEUE_LIMIT = _env_int("WHISPER_QUEUE_MAX_TASKS", 5, 1)
CHUNK_TIMEOUT_SECONDS = _env_int("WHISPER_CHUNK_TIMEOUT_SECONDS", 7200, 60)
WORKER_START_TIMEOUT_SECONDS = _env_int("WHISPER_WORKER_START_TIMEOUT_SECONDS", 1800, 60)
MAX_UPLOAD_BYTES = _env_int("WHISPER_MAX_UPLOAD_BYTES", 20 * 1024**3, 1)
MIN_FREE_DISK_GB = _env_int("WHISPER_MIN_FREE_DISK_GB", 20, 0)
WORKER_MAX_RSS_GROWTH_MB = _env_int("WHISPER_WORKER_MAX_RSS_GROWTH_MB", 2048, 128)

TASK_STATUS: dict[str, dict] = {}
_STATUS_CLEANUP_SCHEDULED: set[str] = set()


def _sanitize_status(data: dict) -> dict:
    clean = dict(data)
    clean.pop("plain_text", None)
    clean.pop("timestamped_text", None)
    return clean


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def update_task_status(task_id: str, **fields) -> None:
    fields = _sanitize_status(fields)
    current = TASK_STATUS.setdefault(task_id, {})
    current.update(fields)
    current["updated_at"] = time.time()
    clean = _sanitize_status(current)
    TASK_STATUS[task_id] = clean
    _atomic_write_json(TASK_DIR / task_id / "status.json", clean)


def get_task_status(task_id: str) -> Optional[dict]:
    if task_id in TASK_STATUS:
        return _sanitize_status(TASK_STATUS[task_id])
    path = TASK_DIR / task_id / "status.json"
    if not path.exists():
        return None
    try:
        status = _sanitize_status(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None
    TASK_STATUS[task_id] = status
    _schedule_status_cleanup(task_id)
    return status


async def _cleanup_status_after(task_id: str) -> None:
    try:
        await asyncio.sleep(STATUS_RETENTION_SECONDS)
    finally:
        TASK_STATUS.pop(task_id, None)
        _STATUS_CLEANUP_SCHEDULED.discard(task_id)


def _schedule_status_cleanup(task_id: str) -> None:
    if task_id in _STATUS_CLEANUP_SCHEDULED:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _STATUS_CLEANUP_SCHEDULED.add(task_id)
    loop.create_task(_cleanup_status_after(task_id))


coordinator = TaskCoordinator(
    update_status=update_task_status,
    queue_limit=QUEUE_LIMIT,
    chunk_timeout=CHUNK_TIMEOUT_SECONDS,
    rss_growth_limit_mb=WORKER_MAX_RSS_GROWTH_MB,
)


def _validate_task_id(task_id: str) -> None:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise HTTPException(status_code=400, detail="task_step_id 只能包含字母、数字、点、下划线和横线，最长128字符")


def _safe_upload_name(filename: Optional[str]) -> str:
    name = Path(filename or "audio.bin").name
    return f"source-{name or 'audio.bin'}"


def _ensure_disk_space() -> None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(TASK_DIR).free
    if free < MIN_FREE_DISK_GB * 1024**3:
        raise HTTPException(status_code=503, detail=f"任务磁盘剩余空间不足 {MIN_FREE_DISK_GB}GB")


async def _save_upload(file: UploadFile, destination: Path) -> int:
    _ensure_disk_space()
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with open(destination, "wb") as output:
            while True:
                block = await file.read(UPLOAD_BLOCK_SIZE)
                if not block:
                    break
                written += len(block)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="上传文件超过服务限制")
                output.write(block)
                if written % (256 * 1024**2) < UPLOAD_BLOCK_SIZE:
                    _ensure_disk_space()
        return written
    except BaseException:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    finally:
        await file.close()


def _language_code(language: Optional[str]) -> Optional[str]:
    return language if language in {"en", "es"} else None


def _language_display(language: Optional[str]) -> str:
    return get_language_display(language) if language else "自动检测"


def _make_task_payload(
    task_id: str,
    task_dir: Path,
    audio_path: Path,
    requested_model: str,
    language: Optional[str],
    include_timestamps: bool,
    initial_prompt: Optional[str],
    async_task: bool,
) -> dict:
    return {
        "type": "transcribe",
        "task_id": task_id,
        "task_dir": str(task_dir),
        "audio_path": str(audio_path),
        "result_path": str(task_dir / "result.txt"),
        "timestamp_path": str(task_dir / "result_with_timestamps.txt") if include_timestamps else None,
        "cancel_path": str(task_dir / ".cancel"),
        "requested_model_name": requested_model,
        "effective_model_name": EFFECTIVE_MODEL_NAME,
        "language": _language_code(language),
        "include_timestamps": include_timestamps,
        "initial_prompt": initial_prompt,
        "async_task": async_task,
        "attempt": 1,
    }


def _persist_task(task: dict) -> None:
    _atomic_write_json(Path(task["task_dir"]) / "task.json", task)


async def _cleanup_sync_task_when_done(
    task_id: str, task_dir: Path, future: asyncio.Future
) -> None:
    try:
        await asyncio.shield(future)
    except (asyncio.CancelledError, Exception):
        pass
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)
        TASK_STATUS.pop(task_id, None)


async def _recover_tasks() -> None:
    if not TASK_DIR.exists():
        return
    for task_path in TASK_DIR.iterdir():
        if not task_path.is_dir():
            continue
        status_path = task_path / "status.json"
        payload_path = task_path / "task.json"
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not payload_path.exists():
            if status.get("status") in {"uploading", "pending", "queued", "processing"}:
                task_id = task_path.name
                update_task_status(
                    task_id,
                    status="failed",
                    stage="interrupted",
                    message="旧任务缺少持久化任务信息，无法在服务重启后恢复",
                )
            continue
        try:
            task = json.loads(payload_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task_id = task.get("task_id")
        if not task_id or status.get("status") not in {"queued", "processing", "uploading"}:
            continue
        if not task.get("async_task"):
            update_task_status(task_id, status="failed", stage="interrupted", message="同步请求因服务重启中断")
            continue
        task["attempt"] = int(status.get("attempt", task.get("attempt", 1)))
        if coordinator.recover(task):
            _persist_task(task)
            update_task_status(task_id, status="queued", stage="recovered", message="服务重启后任务已重新排队", attempt=task["attempt"])
        else:
            update_task_status(task_id, status="failed", stage="failed", message="任务已超过最大恢复次数或恢复队列已满")


async def _cleanup_old_tasks_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        if not TASK_DIR.exists():
            continue
        for task_path in TASK_DIR.iterdir():
            if not task_path.is_dir():
                continue
            try:
                status_path = task_path / "status.json"
                status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
                if status.get("status") in {"uploading", "queued", "processing"}:
                    continue
                if now - task_path.stat().st_mtime > TASK_FILE_RETENTION_SECONDS:
                    shutil.rmtree(task_path)
            except Exception:
                continue


api_app = FastAPI(title="音频文字提取 API", description="Whisper turbo 音频转文字 API")
api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api_app.on_event("startup")
async def startup_event() -> None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    await coordinator.start()
    await coordinator.wait_until_ready(WORKER_START_TIMEOUT_SECONDS)
    await _recover_tasks()
    asyncio.create_task(_cleanup_old_tasks_loop())


@api_app.on_event("shutdown")
async def shutdown_event() -> None:
    await coordinator.stop()


@api_app.get("/")
async def root():
    return {
        "message": "音频文字提取 API",
        "version": "2.0",
        "effective_model_name": EFFECTIVE_MODEL_NAME,
        "endpoints": {
            "/transcribe": "POST - 同步上传并等待转写",
            "/transcribe_start": "POST - 异步启动转写任务",
            "/task/{task_step_id}/status": "GET - 查询任务状态",
            "/task/{task_step_id}/cancel": "POST - 取消任务",
            "/task/{task_step_id}/download/{file_type}": "GET - 下载任务文件",
            "/health": "GET - 存活和Worker就绪状态",
        },
    }


@api_app.get("/health")
async def health_check():
    worker = coordinator.snapshot()
    ready = worker["worker_alive"] and worker["model_loaded"] and not worker["start_error"]
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "healthy" if ready else "not_ready", "device": "cuda", **worker},
    )


@api_app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(..., description="音频文件"),
    model_name: str = Form("turbo", description="兼容参数，实际固定使用 turbo"),
    language: Optional[str] = Form(None),
    include_timestamps: bool = Form(False),
    initial_prompt: Optional[str] = Form(None),
):
    if not coordinator.has_capacity():
        raise HTTPException(status_code=429, detail="Whisper任务队列已满")
    task_id = f"sync-{uuid.uuid4().hex}"
    task_dir = TASK_DIR / task_id
    audio_path = task_dir / _safe_upload_name(file.filename)
    future: Optional[asyncio.Future] = None
    deferred_cleanup = False
    update_task_status(task_id, status="uploading", stage="uploading", message="正在保存上传文件", async_task=False)
    try:
        await _save_upload(file, audio_path)
        task = _make_task_payload(task_id, task_dir, audio_path, model_name, language, include_timestamps, initial_prompt, False)
        _persist_task(task)
        update_task_status(
            task_id,
            status="queued",
            stage="queued",
            message="任务已进入队列",
            requested_model_name=model_name,
            effective_model_name=EFFECTIVE_MODEL_NAME,
            attempt=1,
            async_task=False,
        )
        future = coordinator.enqueue(task, wait_for_result=True)
        outcome = await asyncio.shield(future)
        if outcome.get("status") != "completed":
            raise HTTPException(status_code=500, detail=outcome.get("error", "转录未完成"))
        text = (task_dir / "result.txt").read_text(encoding="utf-8").strip()
        detected = outcome.get("language_detected")
        response = {
            "success": True,
            "text": text,
            "language_detected": detected,
            "language_detected_display": get_language_display(detected),
        }
        if include_timestamps:
            response["text_with_timestamps"] = (task_dir / "result_with_timestamps.txt").read_text(encoding="utf-8").strip()
        return JSONResponse(content=response)
    except (QueueFullError, DuplicateTaskError) as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except asyncio.CancelledError:
        if future is not None:
            coordinator.cancel(task_id)
            deferred_cleanup = True
            asyncio.create_task(_cleanup_sync_task_when_done(task_id, task_dir, future))
        raise
    finally:
        if not deferred_cleanup:
            shutil.rmtree(task_dir, ignore_errors=True)
            TASK_STATUS.pop(task_id, None)


@api_app.post("/transcribe_start")
async def transcribe_start(
    file: UploadFile = File(..., description="音频文件"),
    model_name: str = Form("turbo", description="兼容参数，实际固定使用 turbo"),
    language: Optional[str] = Form(None),
    include_timestamps: bool = Form(False),
    task_step_id: str = Form(...),
    initial_prompt: Optional[str] = Form(None),
):
    _validate_task_id(task_step_id)
    task_dir = TASK_DIR / task_step_id
    if task_dir.exists() or task_step_id in coordinator.known_ids:
        raise HTTPException(status_code=409, detail=f"任务 {task_step_id} 已存在")
    if not coordinator.has_capacity():
        raise HTTPException(status_code=429, detail="Whisper任务队列已满")
    audio_path = task_dir / _safe_upload_name(file.filename)
    update_task_status(task_step_id, status="uploading", stage="uploading", message="正在保存上传文件", async_task=True)
    try:
        size = await _save_upload(file, audio_path)
        task = _make_task_payload(task_step_id, task_dir, audio_path, model_name, language, include_timestamps, initial_prompt, True)
        _persist_task(task)
        update_task_status(
            task_step_id,
            status="queued",
            stage="queued",
            message="任务已进入队列",
            requested_model_name=model_name,
            effective_model_name=EFFECTIVE_MODEL_NAME,
            language=language or "auto",
            language_display=_language_display(language),
            upload_bytes=size,
            attempt=1,
            async_task=True,
        )
        coordinator.enqueue(task)
    except (QueueFullError, DuplicateTaskError) as exc:
        shutil.rmtree(task_dir, ignore_errors=True)
        TASK_STATUS.pop(task_step_id, None)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except asyncio.CancelledError:
        shutil.rmtree(task_dir, ignore_errors=True)
        TASK_STATUS.pop(task_step_id, None)
        raise
    except Exception:
        status = get_task_status(task_step_id) or {}
        if status.get("status") == "uploading":
            shutil.rmtree(task_dir, ignore_errors=True)
            TASK_STATUS.pop(task_step_id, None)
        raise
    return JSONResponse(
        content={
            "success": True,
            "task_step_id": task_step_id,
            "message": "转录任务已进入队列",
            "status": "queued",
            "language": language or "auto",
            "language_display": _language_display(language),
            "effective_model_name": EFFECTIVE_MODEL_NAME,
        }
    )


@api_app.get("/task/{task_step_id}/status")
async def get_task_status_endpoint(task_step_id: str):
    status = get_task_status(task_step_id)
    task_path = TASK_DIR / task_step_id
    if status is None or not task_path.exists():
        raise HTTPException(status_code=404, detail=f"任务 {task_step_id} 不存在")
    response = {"task_step_id": task_step_id, **status}
    files = []
    for name, kind, description in (
        ("result.txt", "result", "转录结果（纯文本）"),
        ("result_with_timestamps.txt", "result_with_timestamps", "转录结果（带时间戳）"),
    ):
        if (task_path / name).exists():
            files.append({"name": name, "type": kind, "description": description})
    audio_path = None
    payload_path = task_path / "task.json"
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        audio_path = Path(payload["audio_path"])
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    if audio_path and audio_path.exists():
        files.append({"name": audio_path.name, "type": "audio", "description": "原始音频文件"})
    response["files"] = files
    return JSONResponse(content=response)


@api_app.post("/task/{task_step_id}/cancel")
async def cancel_task(task_step_id: str):
    status = get_task_status(task_step_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_step_id} 不存在")
    if status.get("status") in {"completed", "failed", "cancelled"}:
        return JSONResponse(
            content={"success": False, "task_step_id": task_step_id, "status": status["status"], "message": "任务已结束，无法取消"}
        )
    outcome = coordinator.cancel(task_step_id)
    if outcome == "cancelled":
        update_task_status(task_step_id, status="cancelled", stage="cancelled", message="排队任务已取消")
    elif outcome == "cancelling":
        update_task_status(task_step_id, stage="cancelling", message="将在当前分块结束后取消")
    else:
        update_task_status(task_step_id, status="cancelled", stage="cancelled", message="任务已取消")
    return JSONResponse(content={"success": True, "task_step_id": task_step_id, "status": "cancelled" if outcome != "cancelling" else "processing", "message": "取消请求已接受"})


@api_app.get("/task/{task_step_id}/download/{file_type}")
async def download_task_file(task_step_id: str, file_type: str):
    task_path = TASK_DIR / task_step_id
    if not task_path.exists():
        raise HTTPException(status_code=404, detail=f"任务 {task_step_id} 不存在")
    if file_type == "result":
        file_path = task_path / "result.txt"
    elif file_type == "result_with_timestamps":
        file_path = task_path / "result_with_timestamps.txt"
    elif file_type == "audio":
        try:
            payload = json.loads((task_path / "task.json").read_text(encoding="utf-8"))
            file_path = Path(payload["audio_path"])
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail="原始音频不存在") from exc
    else:
        file_path = task_path / Path(file_type).name
        try:
            file_path.resolve().relative_to(task_path.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="无效文件路径") from exc
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"文件 {file_path.name} 不存在")
    return FileResponse(path=str(file_path), filename=file_path.name, media_type="application/octet-stream")
