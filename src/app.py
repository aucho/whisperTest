"""
主启动文件
同时启动 FastAPI 和 Gradio 服务
"""
import sys
import os
import uvicorn

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api import api_app

def main():
    """主函数：仅启动 FastAPI 服务"""
    uvicorn.run(api_app, host="127.0.0.1", port=18000, log_level="info")


if __name__ == "__main__":
    print("=" * 60)
    print("FastAPI 服务启动中...")
    print("=" * 60)
    print("🔌 FastAPI HTTP API: http://127.0.0.1:18000")
    print("📚 API 文档 (Swagger): http://127.0.0.1:18000/docs")
    print("📖 API 文档 (ReDoc): http://127.0.0.1:18000/redoc")
    print("=" * 60)
    main()
