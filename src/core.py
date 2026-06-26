"""
核心音频处理模块
包含音频转文字的核心逻辑
"""
import gc
import os
import subprocess
import sys
import tempfile
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


def _read_text_tail(path: str, max_bytes: int = 4096) -> str:
    """读取文件末尾若干字节，避免一次性把大文件读进内存。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            return f.read().decode(errors="ignore").strip()
    except OSError:
        return ""


def _run_ffmpeg(cmd: list[str], timeout: int) -> int:
    """运行 ffmpeg，stdin/stdout/stderr 全部丢弃，绝不创建 PIPE 读线程。"""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as e:
        proc.kill()
        proc.wait()
        raise e
    return proc.returncode


def _pcm_file_to_float32(pcm_path: str) -> np.ndarray:
    """分块把 PCM int16 文件转成 float32，避免整段 int16 数组再占一份内存。"""
    file_size = os.path.getsize(pcm_path)
    if file_size < 2 or file_size % 2 != 0:
        raise RuntimeError("音频解码结果无效（PCM 文件为空或损坏）")

    n_samples = file_size // 2
    audio = np.empty(n_samples, dtype=np.float32)
    # 每次约 30 秒 16kHz 单声道，控制临时缓冲区大小
    chunk_samples = 30 * _WHISPER_SAMPLE_RATE
    offset = 0
    with open(pcm_path, "rb") as pcm_f:
        while offset < n_samples:
            count = min(chunk_samples, n_samples - offset)
            raw = pcm_f.read(count * 2)
            if len(raw) < count * 2:
                raise RuntimeError("音频解码结果无效（PCM 文件提前结束）")
            chunk = np.frombuffer(raw, dtype=np.int16)
            audio[offset : offset + count] = chunk.astype(np.float32) / 32768.0
            offset += count
    return audio


def _load_audio_with_timeout(file: str, sr: int = _WHISPER_SAMPLE_RATE):
    """带超时的音频解码（等价于 whisper.load_audio）。

    关键点：ffmpeg 的 stdout/stderr 都不走内存管道（subprocess.PIPE）。
    whisper 默认 load_audio 用 capture_output=True，长音频会在 _readerthread 里
    fh.read() 整段 stdout，极易 MemoryError；这里改为：
    - PCM 由 ffmpeg 直接写临时文件；
    - 子进程三流全部 DEVNULL，由 Popen.wait 等待，可超时 kill；
    - 失败时再用 -logfile 写盘读尾部错误信息（仍不走 PIPE）。
  """
    fd, pcm_path = tempfile.mkstemp(suffix=".pcm")
    os.close(fd)
    err_path = None
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-nostats",
        "-threads",
        "0",
        "-i",
        file,
        "-f",
        "s16le",
        "-ac",
        "1",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sr),
        pcm_path,
    ]
    try:
        returncode = _run_ffmpeg(cmd, AUDIO_LOAD_TIMEOUT)
        if returncode != 0:
            err_fd, err_path = tempfile.mkstemp(suffix=".log")
            os.close(err_fd)
            retry_cmd = [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-y",
                "-loglevel",
                "error",
                "-nostats",
                "-logfile",
                err_path,
                "-i",
                file,
                "-f",
                "null",
                "-",
            ]
            _run_ffmpeg(retry_cmd, min(120, AUDIO_LOAD_TIMEOUT))
            detail = _read_text_tail(err_path) or f"ffmpeg exit code {returncode}"
            raise RuntimeError(f"音频解码失败: {detail}")

        return _pcm_file_to_float32(pcm_path)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"音频解码超时（>{AUDIO_LOAD_TIMEOUT}s），文件可能过大或已损坏"
        ) from e
    finally:
        for _p in (pcm_path, err_path):
            if _p and os.path.exists(_p):
                try:
                    os.unlink(_p)
                except OSError:
                    pass


def _patch_whisper_load_audio():
    """防止库内部或其它代码路径仍调用默认的 pipe 版 load_audio。"""
    try:
        import whisper.audio as whisper_audio

        whisper_audio.load_audio = _load_audio_with_timeout
    except Exception:
        pass


_patch_whisper_load_audio()


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

