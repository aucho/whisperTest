"""
核心音频处理模块
包含音频转文字的核心逻辑
"""
import gc
import os
import subprocess
import sys
import threading
from collections import OrderedDict

import numpy as np
import whisper
import torch

try:
    from whisper.audio import SAMPLE_RATE as _WHISPER_SAMPLE_RATE
except Exception:  # pragma: no cover - 兜底，正常 whisper 安装都有该常量
    _WHISPER_SAMPLE_RATE = 16000


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """安全读取整型环境变量，非法值回退到默认，避免导入期崩溃。"""
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


# 同时常驻内存/显存的最大模型数量；超过后按 LRU 淘汰最久未使用的模型。
# 默认 1，避免请求多种模型时把所有模型一起常驻导致内存只增不减。
MAX_CACHED_MODELS = _env_int("WHISPER_MAX_CACHED_MODELS", 1)

# 音频解码超时（秒）。超时则判定文件过大/损坏并报错，避免 ffmpeg 管道挂起导致任务永久卡住。
AUDIO_LOAD_TIMEOUT = _env_int("WHISPER_AUDIO_LOAD_TIMEOUT", 1800)

_model_cache: "OrderedDict[str, object]" = OrderedDict()
_model_lock = threading.Lock()
# 序列化推理：Whisper 模型对象非线程安全，避免同进程并发推理导致结果错乱/崩溃，
# 同时也限制了同时进行的转录数量，降低峰值内存。
_inference_lock = threading.Lock()


def format_timestamp(seconds: float) -> str:
    """格式化时间戳为 00:00:00.00"""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"


LANGUAGE_DISPLAY_MAP = {
    "en": "英语",
    "es": "西班牙语",
}


def get_language_display(language_code: str | None) -> str:
    if not language_code:
        return "未知"
    return LANGUAGE_DISPLAY_MAP.get(language_code, language_code)


def _get_device():
    return "cuda" if torch.cuda.is_available() else "cpu"


def _evict_until_within_limit():
    """在持有 _model_lock 的前提下调用：淘汰超出上限的最久未使用模型并释放资源。"""
    while len(_model_cache) > MAX_CACHED_MODELS:
        _, old_model = _model_cache.popitem(last=False)
        del old_model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _load_model_cached(model_name: str):
    device = _get_device()
    cache_key = f"{model_name}_{device}"
    with _model_lock:
        if cache_key in _model_cache:
            # 命中缓存，标记为最近使用
            _model_cache.move_to_end(cache_key)
            return _model_cache[cache_key]
        model = whisper.load_model(model_name, device=device)
        _model_cache[cache_key] = model
        _model_cache.move_to_end(cache_key)
        _evict_until_within_limit()
        return model


def _trim_process_memory():
    """把已释放的内存尽量归还操作系统。

    仅靠 gc/free 在 Windows 上不会让进程工作集下降（CRT 堆不还给 OS），
    因此显式裁剪工作集；Linux 上调用 malloc_trim。
    """
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except AttributeError:
            pass
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # (SIZE_T)-1, (SIZE_T)-1 让系统将工作集裁剪到最小
            kernel32.SetProcessWorkingSetSize(
                ctypes.c_void_p(kernel32.GetCurrentProcess()),
                ctypes.c_size_t(-1),
                ctypes.c_size_t(-1),
            )
        elif sys.platform.startswith("linux"):
            import ctypes

            ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        # 内存裁剪是尽力而为，失败不影响主流程
        pass


def release_model(model_name: str = None):
    with _model_lock:
        if model_name is None:
            _model_cache.clear()
        else:
            device = _get_device()
            cache_key = f"{model_name}_{device}"
            _model_cache.pop(cache_key, None)
    _trim_process_memory()


def _cleanup_cuda():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _load_audio_with_timeout(file: str, sr: int = _WHISPER_SAMPLE_RATE):
    """带超时的音频解码（等价于 whisper.load_audio）。

    whisper 原生 load_audio 在 ffmpeg 读取线程 OOM 时会让 communicate() 永久挂起，
    导致后台任务卡在 processing。这里加 timeout，将挂起转为可捕获的异常。
    """
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-threads", "0",
        "-i", file,
        "-f", "s16le",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        "-ar", str(sr),
        "-",
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            timeout=AUDIO_LOAD_TIMEOUT,
        ).stdout
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"音频解码超时（>{AUDIO_LOAD_TIMEOUT}s），文件可能过大或已损坏"
        ) from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="ignore") if e.stderr else ""
        raise RuntimeError(f"音频解码失败: {stderr}") from e

    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0


def process_audio(audio_path, model_name="base", language_choice="自动检测", verbose=True):
    """处理音频文件的核心函数"""
    if audio_path is None:
        return "请上传音频文件", "", None

    model = _load_model_cached(model_name)

    device = _get_device()

    language_map = {
        "自动检测": None,
        "英语": "en",
        "西班牙语": "es",
    }
    selected_language = language_map.get(language_choice)

    transcribe_kwargs = {
        "verbose": verbose,
        "fp16": device == "cuda",
    }
    if selected_language:
        transcribe_kwargs["language"] = selected_language

    # 解码与推理一起串行化：保证同进程同一时刻只有一段音频驻留内存，
    # 避免并发任务同时解码大音频导致内存峰值叠加 -> MemoryError。
    with _inference_lock:
        audio = _load_audio_with_timeout(audio_path)
        try:
            result = model.transcribe(
                audio,
                **transcribe_kwargs,
            )
        finally:
            # 尽快释放解码后的大数组
            del audio

    plain_text = result["text"].strip()

    timestamped_text = ""
    if "segments" in result:
        for seg in result["segments"]:
            start = format_timestamp(seg["start"])
            end = format_timestamp(seg["end"])
            timestamped_text += f"[{start} --> {end}] {seg['text'].strip()}\n"

    detected_language = selected_language or result.get("language")

    if device == "cuda":
        _cleanup_cuda()

    return plain_text, timestamped_text.strip(), detected_language

