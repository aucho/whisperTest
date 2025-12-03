"""
核心音频处理模块
包含音频转文字的核心逻辑
"""
import whisper
import torch


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


def process_audio(audio_path, model_name="base", language_choice="自动检测", verbose=True):
    """处理音频文件的核心函数"""
    if audio_path is None:
        return "请上传音频文件", "", None

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(model_name, device=device)
    audio = whisper.load_audio(audio_path)

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

    # 提取纯文字结果
    plain_text = result["text"].strip()

    # 提取带时间戳的段落
    timestamped_text = ""
    if "segments" in result:
        for seg in result["segments"]:
            start = format_timestamp(seg["start"])
            end = format_timestamp(seg["end"])
            timestamped_text += f"[{start} --> {end}] {seg['text'].strip()}\n"

    detected_language = selected_language or result.get("language")

    return plain_text, timestamped_text.strip(), detected_language

