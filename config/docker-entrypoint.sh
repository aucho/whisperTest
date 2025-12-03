#!/bin/bash
set -e

echo "Starting Whisper services..."

# 创建必要的目录
mkdir -p /app/logs /app/tmp

# 启动 API 服务（后台）
echo "Starting API service..."
cd /app
gunicorn -c config/gunicorn_config.py src.api:api_app &
API_PID=$!

# 等待 API 服务启动
echo "Waiting for API service to start..."
sleep 5

# 检查 API 服务是否运行
if ! kill -0 $API_PID 2>/dev/null; then
    echo "API service failed to start"
    exit 1
fi

# 启动 Gradio 服务（前台，保持容器运行）
echo "Starting Gradio service..."
python scripts/run_gradio_production.py &
GRADIO_PID=$!

# 等待进程
echo "Services started. API PID: $API_PID, Gradio PID: $GRADIO_PID"
wait $API_PID $GRADIO_PID

