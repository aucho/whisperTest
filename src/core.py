"""
核心音频处理模块
包含音频转文字的核心逻辑
"""
import gc
import whisper
import torch

_model_cache = {}
_model_lock = __import__('threading').Lock()


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


def _load_model_cached(model_name: str):
    device = _get_device()
    cache_key = f"{model_name}_{device}"
    with _model_lock:
        if cache_key not in _model_cache:
            _model_cache[cache_key] = whisper.load_model(model_name, device=device)
        return _model_cache[cache_key]


def release_model(model_name: str = None):
    with _model_lock:
        if model_name is None:
            _model_cache.clear()
        else:
            device = _get_device()
            cache_key = f"{model_name}_{device}"
            _model_cache.pop(cache_key, None)
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _cleanup_cuda():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def process_audio(audio_path, model_name="base", language_choice="自动检测", verbose=True):
    """处理音频文件的核心函数"""
    if audio_path is None:
        return "请上传音频文件", "", None

    model = _load_model_cached(model_name)
    audio = whisper.load_audio(audio_path)

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

    result = model.transcribe(
        audio,
        **transcribe_kwargs,
    )

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

