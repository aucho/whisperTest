"""
Gradio 生产环境启动脚本
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.gradio_app import create_gradio_app

if __name__ == "__main__":
    app = create_gradio_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=17000,
        share=False,
        show_error=True,
    )

