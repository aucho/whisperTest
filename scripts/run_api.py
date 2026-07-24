"""
API 启动脚本（支持端口参数）
用于 Windows NSSM 服务部署
"""
import sys
import os
import argparse
import uvicorn

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.api import api_app


def main():
    """主函数：启动 FastAPI 服务"""
    parser = argparse.ArgumentParser(description='启动 Whisper API 服务')
    parser.add_argument(
        '--port',
        type=int,
        default=18000,
        help='服务端口号（默认: 18000）'
    )
    parser.add_argument(
        '--host',
        type=str,
        default='127.0.0.1',
        help='服务监听地址（默认: 127.0.0.1）'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='info',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        help='日志级别（默认: info）'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"FastAPI 服务启动中... (端口: {args.port})")
    print("=" * 60)
    print(f"FastAPI HTTP API: http://{args.host}:{args.port}")
    print(f"API 文档 (Swagger): http://{args.host}:{args.port}/docs")
    print(f"API 文档 (ReDoc): http://{args.host}:{args.port}/redoc")
    print("=" * 60)
    
    uvicorn.run(
        api_app,
        host=args.host,
        port=args.port,
        log_level=args.log_level
    )


if __name__ == "__main__":
    main()

