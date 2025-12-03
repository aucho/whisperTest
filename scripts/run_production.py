"""
生产环境启动脚本
使用 Uvicorn workers 提供更好的性能和稳定性
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import uvicorn
from src.api import api_app

if __name__ == "__main__":
    # 生产环境配置
    uvicorn.run(
        api_app,
        host="0.0.0.0",  # 监听所有网络接口
        port=18000,
        workers=4,  # 根据 CPU 核心数调整，建议为 CPU 核心数
        log_level="info",
        access_log=True,
        # 超时设置（音频处理可能需要较长时间）
        timeout_keep_alive=300,
        timeout_graceful_shutdown=30,
    )

