"""
Gradio Web 界面模块
提供图形化用户界面
"""
import sys
import os
import gradio as gr

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import process_audio


def _process_audio_for_gradio(audio_path, model_name, language_choice, verbose):
    plain_text, timestamped_text, _ = process_audio(
        audio_path,
        model_name=model_name,
        language_choice=language_choice,
        verbose=verbose,
    )
    return plain_text, timestamped_text


def create_gradio_app():
    """创建 Gradio 应用"""
    with gr.Blocks(title="音频文字提取工具") as app:
        gr.Markdown("# 音频文字提取工具")
        gr.Markdown("### Web 界面 | API 文档: http://127.0.0.1:18000/docs")

        with gr.Row():
            audio_input = gr.Audio(label="上传音频文件", type="filepath")
            model_dropdown = gr.Dropdown(
                choices=["tiny", "base", "small", "medium", "large"],
                value="base",
                label="选择模型"
            )
            language_dropdown = gr.Dropdown(
                choices=["自动检测", "英语", "西班牙语"],
                value="自动检测",
                label="选择语言"
            )
            verbose_checkbox = gr.Checkbox(value=True, label="控制台显示进度")
            process_btn = gr.Button("开始处理", variant="primary")

        with gr.Tab("纯文字结果"):
            output_text = gr.Textbox(lines=15, show_copy_button=True)

        with gr.Tab("带时间戳结果"):
            timestamped_output = gr.Textbox(lines=15, show_copy_button=True)

        process_btn.click(
            _process_audio_for_gradio,
            inputs=[audio_input, model_dropdown, language_dropdown, verbose_checkbox],
            outputs=[output_text, timestamped_output],
        )

    return app

