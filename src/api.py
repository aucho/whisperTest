"""
FastAPI HTTP API 模块
提供 RESTful API 接口
"""

from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import sys
import tempfile
from typing import Optional, Dict
import torch
import asyncio
import gc

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import process_audio, get_language_display

TASK_STATUS = {}
RUNNING_TASKS: Dict[str, asyncio.Task] = {}
TASK_DIR = Path("./storage/tasks")


def update_task_status(task_step_id: str, **fields):
    TASK_STATUS.setdefault(task_step_id, {})
    TASK_STATUS[task_step_id].update(fields)
    task_path = TASK_DIR / task_step_id
    task_path.mkdir(parents=True, exist_ok=True)
    (task_path / "status.json").write_text(
        json.dumps(TASK_STATUS[task_step_id], ensure_ascii=False), encoding="utf-8"
    )


def get_task_status(task_step_id: str) -> dict:
    """获取任务状态，优先从内存读取，如果不存在则从文件读取"""
    # 先尝试从内存读取
    if task_step_id in TASK_STATUS:
        return TASK_STATUS[task_step_id]

    # 从文件读取
    task_path = TASK_DIR / task_step_id
    status_file = task_path / "status.json"

    if status_file.exists():
        try:
            status_data = json.loads(status_file.read_text(encoding="utf-8"))
            # 更新内存中的状态
            TASK_STATUS[task_step_id] = status_data
            return status_data
        except Exception:
            pass

    # 如果都不存在，返回 None
    return None


async def run_transcribe_task(
    audio_path: str,
    task_step_id: str,
    model_name: str,
    language_choice: str,
    include_timestamps: bool,
):
    """后台任务：执行转录并保存结果"""
    try:
        # 更新状态为处理中
        update_task_status(
            task_step_id,
            status="processing",
            message="正在处理音频文件...",
        )

        # 在线程池中执行同步的转录任务，避免阻塞事件循环
        plain_text, timestamped_text, detected_language = await asyncio.to_thread(
            process_audio,
            audio_path,
            model_name=model_name,
            language_choice=language_choice,
            verbose=False,
        )

        # 保存结果到文件
        task_path = TASK_DIR / task_step_id
        task_path.mkdir(parents=True, exist_ok=True)

        # 保存纯文本
        (task_path / "result.txt").write_text(plain_text, encoding="utf-8")

        # 如果包含时间戳，保存带时间戳的文本
        if include_timestamps:
            (task_path / "result_with_timestamps.txt").write_text(
                timestamped_text, encoding="utf-8"
            )

        # 更新状态为完成
        update_task_status(
            task_step_id,
            status="completed",
            message="转录完成",
            # plain_text=plain_text,
            timestamped_text=timestamped_text if include_timestamps else None,
            language_detected=detected_language,
            language_detected_display=get_language_display(detected_language),
        )

    except asyncio.CancelledError:
        # 任务被取消，清理状态
        update_task_status(
            task_step_id,
            status="cancelled",
            message="任务已被终止",
        )
        raise
    except Exception as e:
        # 更新状态为失败
        update_task_status(
            task_step_id,
            status="failed",
            message=f"转录失败: {str(e)}",
            error=str(e),
        )
    finally:
        cleanup_resources()
        RUNNING_TASKS.pop(task_step_id, None)


def cleanup_resources():
    """清理内存和显存，避免资源泄漏"""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except AttributeError:
            pass


# 创建 FastAPI 应用
api_app = FastAPI(title="音频文字提取 API", description="Whisper 音频转文字 API 服务")

# 添加 CORS 支持
api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api_app.get("/")
async def root():
    """API 根路径，返回 API 信息"""
    return {
        "message": "音频文字提取 API",
        "version": "1.0",
        "endpoints": {
            "/transcribe": "POST - 上传音频文件进行转写",
            "/transcribe_start": "POST - 启动异步转录任务",
            "/task/{task_step_id}/status": "GET - 查询任务状态",
            "/task/{task_step_id}/cancel": "POST - 取消任务",
            "/task/{task_step_id}/download/{file_type}": "GET - 下载任务文件",
            "/health": "GET - 健康检查",
        },
    }


@api_app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "device": "cuda" if torch.cuda.is_available() else "cpu",
    }


# 短的转写 一次生成并返回结果
@api_app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(..., description="音频文件"),
    model_name: str = Form(
        "base", description="模型名称: tiny, base, small, medium, large"
    ),
    language: Optional[str] = Form(
        None, description="语言代码: en(英语), es(西班牙语), 或留空自动检测"
    ),
    include_timestamps: bool = Form(False, description="是否包含时间戳"),
):
    """
    转写音频文件为文字

    参数:
    - file: 音频文件 (支持 mp3, wav, m4a 等格式)
    - model_name: Whisper 模型名称 (tiny, base, small, medium, large)
    - language: 语言代码 (en, es 等)，留空则自动检测
    - include_timestamps: 是否在结果中包含时间戳信息
    """
    try:
        # 验证模型名称
        valid_models = ["tiny", "base", "small", "medium", "large"]
        if model_name not in valid_models:
            raise HTTPException(
                status_code=400,
                detail=f"无效的模型名称。可选值: {', '.join(valid_models)}",
            )

        # 保存上传的文件到临时目录
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=os.path.splitext(file.filename)[1]
        ) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name

        try:
            # 将语言代码转换为中文选项（用于 process_audio 函数）
            language_map_reverse = {
                "en": "英语",
                "es": "西班牙语",
            }
            language_choice = (
                "自动检测"
                if language is None
                else language_map_reverse.get(language, "自动检测")
            )

            # 处理音频
            plain_text, timestamped_text, detected_language = process_audio(
                tmp_path,
                model_name=model_name,
                language_choice=language_choice,
                verbose=False,
            )

            # 构建响应
            response = {
                "success": True,
                "text": plain_text,
                "language_detected": detected_language,
                "language_detected_display": get_language_display(detected_language),
            }

            if include_timestamps:
                response["text_with_timestamps"] = timestamped_text

            return JSONResponse(content=response)

        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理音频时出错: {str(e)}")


# 调用后开始转写 并保存结果到本地文件 长转写
@api_app.post("/transcribe_start")
async def transcribe_start(
    file: UploadFile = File(..., description="音频文件"),
    model_name: str = Form(
        "base", description="模型名称: tiny, base, small, medium, large"
    ),
    language: Optional[str] = Form(
        None, description="语言代码: en(英语), es(西班牙语), 或留空自动检测"
    ),
    include_timestamps: bool = Form(False, description="是否包含时间戳"),
    task_step_id: str = Form(..., description="任务步骤ID 用于查询文件保存路径"),
):
    """
    启动异步转录任务

    调用后立即返回，转录任务在后台执行。
    可以通过 task_step_id 查询任务状态和结果。
    """
    try:
        # 验证模型名称
        valid_models = ["tiny", "base", "small", "medium", "large"]
        if model_name not in valid_models:
            raise HTTPException(
                status_code=400,
                detail=f"无效的模型名称。可选值: {', '.join(valid_models)}",
            )

        # 创建任务目录
        task_path = TASK_DIR / task_step_id
        task_path.mkdir(parents=True, exist_ok=True)

        # 保存上传的文件到任务目录
        audio_path = task_path / file.filename
        content = await file.read()
        audio_path.write_bytes(content)

        # 将语言代码转换为中文选项（用于 process_audio 函数）
        language_map_reverse = {
            "en": "英语",
            "es": "西班牙语",
        }
        language_choice = (
            "自动检测"
            if language is None
            else language_map_reverse.get(language, "自动检测")
        )

        # 初始化任务状态
        update_task_status(
            task_step_id,
            status="pending",
            message="任务已创建，等待处理...",
            model_name=model_name,
            language=language or "auto",
            language_display=language_choice,
        )

        # 将转录任务添加到事件循环
        task = asyncio.create_task(
            run_transcribe_task(
                str(audio_path),
                task_step_id,
                model_name,
                language_choice,
                include_timestamps,
            )
        )
        RUNNING_TASKS[task_step_id] = task

        # 立即返回响应
        return JSONResponse(
            content={
                "success": True,
                "task_step_id": task_step_id,
                "message": "转录任务已启动",
                "status": "pending",
                "language": language or "auto",
                "language_display": language_choice,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动转录任务时出错: {str(e)}")


@api_app.get("/task/{task_step_id}/status")
async def get_task_status_endpoint(task_step_id: str):
    """
    查询任务状态

    参数:
    - task_step_id: 任务步骤ID

    返回:
    - status: 任务状态 (pending, processing, completed, failed)
    - message: 状态消息
    - 其他任务相关信息
    """
    task_status = get_task_status(task_step_id)

    if task_status is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_step_id} 不存在")

    # 检查任务目录是否存在
    task_path = TASK_DIR / task_step_id
    if not task_path.exists():
        raise HTTPException(status_code=404, detail=f"任务 {task_step_id} 不存在")

    # 构建响应，包含文件信息
    response = {"task_step_id": task_step_id, **task_status}

    # 添加文件列表信息
    files = []
    if (task_path / "result.txt").exists():
        files.append(
            {
                "name": "result.txt",
                "type": "result",
                "description": "转录结果（纯文本）",
            }
        )
    if (task_path / "result_with_timestamps.txt").exists():
        files.append(
            {
                "name": "result_with_timestamps.txt",
                "type": "result_with_timestamps",
                "description": "转录结果（带时间戳）",
            }
        )

    # 查找原始音频文件
    audio_files = [
        f
        for f in task_path.iterdir()
        if f.is_file()
        and f.suffix.lower() in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4"]
    ]
    for audio_file in audio_files:
        files.append(
            {"name": audio_file.name, "type": "audio", "description": "原始音频文件"}
        )

    response["files"] = files

    return JSONResponse(content=response)


@api_app.post("/task/{task_step_id}/cancel")
async def cancel_task(task_step_id: str):
    """
    取消正在进行的任务，并尝试释放资源
    """
    task_status = get_task_status(task_step_id)

    if task_status is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_step_id} 不存在")

    current_status = task_status.get("status")
    if current_status in {"completed", "failed", "cancelled"}:
        return JSONResponse(
            content={
                "success": False,
                "task_step_id": task_step_id,
                "status": current_status,
                "message": "任务已结束，无法取消",
            }
        )

    task = RUNNING_TASKS.get(task_step_id)
    if task is None:
        # 没有记录运行中的任务，直接标记为已取消
        update_task_status(
            task_step_id,
            status="cancelled",
            message="任务状态已更新为已取消",
        )
        cleanup_resources()
        return JSONResponse(
            content={
                "success": True,
                "task_step_id": task_step_id,
                "status": "cancelled",
                "message": "任务已取消",
            }
        )

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    RUNNING_TASKS.pop(task_step_id, None)
    cleanup_resources()

    updated_status = get_task_status(task_step_id) or {}
    return JSONResponse(
        content={
            "success": True,
            "task_step_id": task_step_id,
            "status": updated_status.get("status", "cancelled"),
            "message": updated_status.get("message", "任务已取消"),
        }
    )


@api_app.get("/task/{task_step_id}/download/{file_type}")
async def download_task_file(task_step_id: str, file_type: str):
    """
    下载任务文件

    参数:
    - task_step_id: 任务步骤ID
    - file_type: 文件类型
        - "result": 下载 result.txt（纯文本结果）
        - "result_with_timestamps": 下载 result_with_timestamps.txt（带时间戳的结果）
        - "audio": 下载原始音频文件（如果有多个，返回第一个）
        - 或者直接指定文件名

    返回:
    - 文件内容
    """
    task_path = TASK_DIR / task_step_id

    if not task_path.exists():
        raise HTTPException(status_code=404, detail=f"任务 {task_step_id} 不存在")

    file_path = None
    filename = None

    # 根据文件类型确定文件路径
    if file_type == "result":
        file_path = task_path / "result.txt"
        filename = "result.txt"
    elif file_type == "result_with_timestamps":
        file_path = task_path / "result_with_timestamps.txt"
        filename = "result_with_timestamps.txt"
    elif file_type == "audio":
        # 查找音频文件
        audio_files = [
            f
            for f in task_path.iterdir()
            if f.is_file()
            and f.suffix.lower() in [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4"]
        ]
        if not audio_files:
            raise HTTPException(
                status_code=404, detail=f"任务 {task_step_id} 中没有找到音频文件"
            )
        file_path = audio_files[0]
        filename = file_path.name
    else:
        # 直接使用 file_type 作为文件名
        file_path = task_path / file_type
        filename = file_type

        # 安全检查：确保文件路径在任务目录内，防止路径遍历攻击
        try:
            file_path.resolve().relative_to(task_path.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的文件路径")

    # 检查文件是否存在
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")

    # 返回文件
    return FileResponse(
        path=str(file_path), filename=filename, media_type="application/octet-stream"
    )
