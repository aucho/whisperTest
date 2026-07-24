"""Faster-Whisper 核心处理：固定 turbo 常驻、按区间解码并增量输出。"""

from __future__ import annotations

import gc
import json
import logging
import math
import os
import subprocess
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)
WHISPER_SAMPLE_RATE = 16000


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


EFFECTIVE_MODEL_NAME = os.environ.get("WHISPER_MODEL", "turbo") or "turbo"
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cuda").lower()
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "float16") or "float16"
WHISPER_DEVICE_INDEX = _env_int("WHISPER_DEVICE_INDEX", 0, 0)
WHISPER_BEAM_SIZE = _env_int("WHISPER_BEAM_SIZE", 5, 1)
WHISPER_VAD_ENABLED = _env_bool("WHISPER_VAD_ENABLED", True)
WHISPER_VAD_MIN_SILENCE_MS = _env_int("WHISPER_VAD_MIN_SILENCE_MS", 2000, 0)
WHISPER_MODEL_CACHE_DIR = os.environ.get("WHISPER_MODEL_CACHE_DIR", "").strip()
WHISPER_BACKEND = "faster-whisper"
CHUNK_SECONDS = _env_int("WHISPER_CHUNK_SECONDS", 3600, 900)
CHUNK_OVERLAP_SECONDS = _env_int("WHISPER_CHUNK_OVERLAP_SECONDS", 10, 0)
FFMPEG_TIMEOUT_SECONDS = _env_int("WHISPER_AUDIO_LOAD_TIMEOUT", 1800)
MIN_CHUNK_SECONDS = 900

LANGUAGE_DISPLAY_MAP = {"en": "英语", "es": "西班牙语"}
TRANSCRIBE_INITIAL_PROMPTS = {
    "en": (
        "Hey everyone, welcome to the live stream! Today we have an exclusive deal — "
        "originally $29.99, now only $14.99! Tap the yellow cart to order, limited stock! "
        "Drop your questions in the chat, we'll answer right away."
    ),
    "es": (
        "¡Hola a todos, bienvenidos al directo! Hoy tenemos una oferta exclusiva: "
        "antes 29,99 €, ¡ahora solo 14,99 €! Toca el carrito para comprar, ¡stock limitado! "
        "Deja tus preguntas en el chat, te respondemos al momento."
    ),
}
DEFAULT_TRANSCRIBE_INITIAL_PROMPT = (
    "家人们，欢迎来到直播间！今天这款宝贝限时秒杀，原价九十九元，现价只要四十九块九！"
    "喜欢的宝宝赶紧拍，库存不多，手慢无！有问题可以在评论区留言，主播马上回复。"
)

CUDA_OOM_MARKERS = (
    "cuda out of memory",
    "cuda error: out of memory",
    "cuda failed with error out of memory",
    "cuda oom",
    "cublas_status_alloc_failed",
)


def format_timestamp(seconds: float) -> str:
    total_centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(total_centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def get_language_display(language_code: Optional[str]) -> str:
    if not language_code:
        return "未知"
    return LANGUAGE_DISPLAY_MAP.get(language_code, language_code)


def resolve_transcribe_initial_prompt(
    language: Optional[str], initial_prompt: Optional[str] = None
) -> Optional[str]:
    if initial_prompt and initial_prompt.strip():
        return initial_prompt.strip()
    # 自动检测的首块尚不知道语言，此时不注入任何内置语言提示词，
    # 防止中文示例把英文 hello 等短词偏置成中文输出。
    if language is None:
        return None
    return TRANSCRIBE_INITIAL_PROMPTS.get(language, DEFAULT_TRANSCRIBE_INITIAL_PROMPT)


def is_cuda_oom_error(exc: BaseException) -> bool:
    """识别 CTranslate2 及兼容层抛出的 CUDA 显存不足错误。"""
    current: Optional[BaseException] = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).lower()
        if any(marker in message for marker in CUDA_OOM_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


def _run_process(command: list[str], timeout: int, capture_stdout: bool = False) -> bytes:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.communicate()
        raise RuntimeError(f"外部音频工具执行超时（>{timeout}s）") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"外部音频工具执行失败，exit code={proc.returncode}")
    return stdout or b""


def probe_audio_duration(audio_path: str) -> float:
    """使用 ffprobe 读取时长；输出很小，可以安全捕获。"""
    output = _run_process(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            audio_path,
        ],
        timeout=min(120, FFMPEG_TIMEOUT_SECONDS),
        capture_stdout=True,
    )
    try:
        payload = json.loads(output.decode("utf-8"))
        if not any(s.get("codec_type") == "audio" for s in payload.get("streams", [])):
            raise ValueError("没有音轨")
        duration = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("无法读取有效音频时长或文件没有音轨") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("音频时长无效")
    return duration


def _extract_pcm(audio_path: str, start: float, end: float) -> str:
    fd, pcm_path = tempfile.mkstemp(suffix=".pcm")
    os.close(fd)
    try:
        _run_process(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-y",
                "-loglevel",
                "error",
                "-nostats",
                "-ss",
                f"{start:.3f}",
                "-i",
                audio_path,
                "-t",
                f"{max(0.001, end - start):.3f}",
                "-f",
                "s16le",
                "-ac",
                "1",
                "-acodec",
                "pcm_s16le",
                "-ar",
                str(WHISPER_SAMPLE_RATE),
                pcm_path,
            ],
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
        if os.path.getsize(pcm_path) < 2:
            raise RuntimeError("音频分块解码结果为空")
        return pcm_path
    except Exception:
        try:
            os.unlink(pcm_path)
        except OSError:
            pass
        raise


def _pcm_file_to_float32(pcm_path: str) -> np.ndarray:
    file_size = os.path.getsize(pcm_path)
    if file_size < 2 or file_size % 2:
        raise RuntimeError("PCM 文件为空或损坏")
    sample_count = file_size // 2
    audio = np.empty(sample_count, dtype=np.float32)
    block_samples = 30 * WHISPER_SAMPLE_RATE
    offset = 0
    with open(pcm_path, "rb") as source:
        while offset < sample_count:
            count = min(block_samples, sample_count - offset)
            raw = source.read(count * 2)
            if len(raw) != count * 2:
                raise RuntimeError("PCM 文件提前结束")
            values = np.frombuffer(raw, dtype=np.int16)
            audio[offset : offset + count] = values.astype(np.float32) / 32768.0
            offset += count
    return audio


@dataclass(frozen=True)
class ChunkRange:
    owner_start: float
    owner_end: float


def build_chunk_ranges(duration: float, chunk_seconds: int = CHUNK_SECONDS) -> list[ChunkRange]:
    ranges: list[ChunkRange] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + chunk_seconds)
        ranges.append(ChunkRange(start, end))
        start = end
    return ranges


class WhisperEngine:
    """固定 turbo 的 Faster-Whisper 引擎，生命周期等同于 Worker 生命周期。"""

    def __init__(self, model_name: str = EFFECTIVE_MODEL_NAME, device: str = WHISPER_DEVICE):
        if model_name != "turbo":
            logger.warning("WHISPER_MODEL=%s 被忽略，固定使用 turbo", model_name)
        if device != "cuda":
            raise RuntimeError("生产推理固定要求 WHISPER_DEVICE=cuda")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("未安装 faster-whisper，无法启动推理Worker") from exc
        self.model_name = "turbo"
        self.device = "cuda"
        self.compute_type = WHISPER_COMPUTE_TYPE
        self.device_index = WHISPER_DEVICE_INDEX
        download_root = (
            str(Path(WHISPER_MODEL_CACHE_DIR).expanduser().resolve())
            if WHISPER_MODEL_CACHE_DIR
            else None
        )
        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            device_index=self.device_index,
            compute_type=self.compute_type,
            download_root=download_root,
        )

    def transcribe_range(
        self,
        audio_path: str,
        owner: ChunkRange,
        total_duration: float,
        language: Optional[str],
        initial_prompt: Optional[str],
        verbose: bool = False,
        stage_callback: Optional[Callable[[str], None]] = None,
    ) -> tuple[list[dict], Optional[str]]:
        extract_start = max(0.0, owner.owner_start - CHUNK_OVERLAP_SECONDS)
        extract_end = min(total_duration, owner.owner_end + CHUNK_OVERLAP_SECONDS)
        pcm_path: Optional[str] = None
        audio = None
        result_segments = None
        info = None
        try:
            if stage_callback:
                stage_callback("decoding")
            pcm_path = _extract_pcm(audio_path, extract_start, extract_end)
            audio = _pcm_file_to_float32(pcm_path)
            kwargs = {
                "beam_size": WHISPER_BEAM_SIZE,
                "condition_on_previous_text": True,
                "vad_filter": WHISPER_VAD_ENABLED,
                "log_progress": verbose,
            }
            if WHISPER_VAD_ENABLED:
                kwargs["vad_parameters"] = {
                    "min_silence_duration_ms": WHISPER_VAD_MIN_SILENCE_MS
                }
            resolved_prompt = resolve_transcribe_initial_prompt(language, initial_prompt)
            if resolved_prompt:
                kwargs["initial_prompt"] = resolved_prompt
            if language:
                kwargs["language"] = language
            if stage_callback:
                stage_callback("transcribing")
            result_segments, info = self.model.transcribe(audio, **kwargs)
            accepted: list[dict] = []
            # faster-whisper 的 segments 是惰性生成器，必须完整迭代才会执行推理。
            for segment in result_segments:
                raw_start = extract_start + float(segment.start)
                raw_end = extract_start + float(segment.end)
                midpoint = (raw_start + raw_end) / 2
                is_last = math.isclose(owner.owner_end, total_duration)
                if midpoint < owner.owner_start:
                    continue
                if midpoint >= owner.owner_end and not (is_last and midpoint <= owner.owner_end):
                    continue
                start = max(owner.owner_start, min(total_duration, raw_start))
                end = min(owner.owner_end, total_duration, raw_end)
                text = str(segment.text).strip()
                if text and start <= end:
                    accepted.append({"start": start, "end": end, "text": text})
            detected = language or getattr(info, "language", None)
            return accepted, detected
        finally:
            if result_segments is not None:
                del result_segments
            if info is not None:
                del info
            if audio is not None:
                del audio
            if pcm_path:
                try:
                    os.unlink(pcm_path)
                except OSError:
                    pass


ProgressCallback = Callable[[dict], None]
CancelCallback = Callable[[], bool]


def transcribe_file_chunked(
    engine: WhisperEngine,
    audio_path: str,
    result_path: str,
    timestamp_path: Optional[str],
    language: Optional[str],
    initial_prompt: Optional[str],
    progress_callback: Optional[ProgressCallback] = None,
    cancel_callback: Optional[CancelCallback] = None,
) -> dict:
    duration = probe_audio_duration(audio_path)
    work = deque(build_chunk_ranges(duration))
    total_chunks = len(work)
    completed_duration = 0.0
    processed_chunks = 0
    detected_language = language
    previous_end = 0.0
    Path(result_path).write_text("", encoding="utf-8")
    if timestamp_path:
        Path(timestamp_path).write_text("", encoding="utf-8")

    while work:
        if cancel_callback and cancel_callback():
            raise InterruptedError("任务已取消")
        owner = work.popleft()
        chunk_status = {
            "current_chunk": processed_chunks + 1,
            "total_chunks": total_chunks,
            "chunk_owner_start": owner.owner_start,
            "chunk_owner_end": owner.owner_end,
            "duration": duration,
        }
        try:
            segments, chunk_language = engine.transcribe_range(
                audio_path,
                owner,
                duration,
                detected_language,
                initial_prompt,
                stage_callback=(
                    (lambda stage: progress_callback({"stage": stage, **chunk_status}))
                    if progress_callback
                    else None
                ),
            )
        except Exception as exc:
            if not is_cuda_oom_error(exc):
                raise
            owner_duration = owner.owner_end - owner.owner_start
            if owner_duration <= MIN_CHUNK_SECONDS + 0.001:
                raise RuntimeError("15分钟分块仍发生 CUDA OOM") from exc
            midpoint = owner.owner_start + owner_duration / 2
            work.appendleft(ChunkRange(midpoint, owner.owner_end))
            work.appendleft(ChunkRange(owner.owner_start, midpoint))
            total_chunks += 1
            logger.warning(
                "区间 %.2f-%.2f CUDA OOM，拆分为更小区间重试",
                owner.owner_start,
                owner.owner_end,
            )
            continue

        detected_language = detected_language or chunk_language
        processed_chunks += 1
        plain_lines: list[str] = []
        timestamp_lines: list[str] = []
        for segment in segments:
            start = max(previous_end, float(segment["start"]))
            end = float(segment["end"])
            if start > end:
                logger.warning("跳过倒退时间戳 segment: %s", segment)
                continue
            previous_end = end
            plain_lines.append(segment["text"])
            timestamp_lines.append(
                f"[{format_timestamp(start)} --> {format_timestamp(end)}] {segment['text']}"
            )
        if plain_lines:
            with open(result_path, "a", encoding="utf-8") as output:
                output.write(" ".join(plain_lines).strip() + "\n")
                output.flush()
        if timestamp_path and timestamp_lines:
            with open(timestamp_path, "a", encoding="utf-8") as output:
                output.write("\n".join(timestamp_lines) + "\n")
                output.flush()

        completed_duration += owner.owner_end - owner.owner_start
        if progress_callback:
            progress_callback(
                {
                    "stage": "writing",
                    "progress": min(100.0, completed_duration / duration * 100),
                    "current_chunk": processed_chunks,
                    "total_chunks": total_chunks,
                    "duration": duration,
                    "language_detected": detected_language,
                }
            )

    gc.collect()
    return {
        "duration": duration,
        "language_detected": detected_language,
        "chunks_processed": processed_chunks,
    }


_legacy_engine: Optional[WhisperEngine] = None


def process_audio(
    audio_path,
    model_name="turbo",
    language_choice="自动检测",
    verbose=True,
    initial_prompt: Optional[str] = None,
):
    """保留 Gradio 兼容入口；传入的模型名称被忽略。"""
    global _legacy_engine
    if not audio_path:
        return "请上传音频文件", "", None
    if _legacy_engine is None:
        _legacy_engine = WhisperEngine()
    language = {"英语": "en", "西班牙语": "es"}.get(language_choice)
    with tempfile.TemporaryDirectory() as temp_dir:
        result_path = os.path.join(temp_dir, "result.txt")
        timestamp_path = os.path.join(temp_dir, "result_with_timestamps.txt")
        metadata = transcribe_file_chunked(
            _legacy_engine,
            str(audio_path),
            result_path,
            timestamp_path,
            language,
            initial_prompt,
        )
        return (
            Path(result_path).read_text(encoding="utf-8").strip(),
            Path(timestamp_path).read_text(encoding="utf-8").strip(),
            metadata.get("language_detected"),
        )
