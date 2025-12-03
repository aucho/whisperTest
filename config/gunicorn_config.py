"""
Gunicorn 配置文件
用于生产环境部署 FastAPI 应用
"""
import multiprocessing
import os

# 服务器配置
bind = "0.0.0.0:18000"
workers = multiprocessing.cpu_count() * 2 + 1  # 推荐公式
worker_class = "uvicorn.workers.UvicornWorker"  # 使用 Uvicorn worker
worker_connections = 1000
max_requests = 1000  # 每个 worker 处理请求数后重启，防止内存泄漏
max_requests_jitter = 50
timeout = 300  # 超时时间（秒），音频处理可能需要较长时间
keepalive = 5
graceful_timeout = 30

# 日志配置
accesslog = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "gunicorn_access.log")
errorlog = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "gunicorn_error.log")
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 进程命名
proc_name = "whisper_api"

# 预加载应用（提高性能，但会增加内存使用）
preload_app = True

# 用户和组（生产环境建议设置）
# user = "www-data"
# group = "www-data"

# 临时文件目录
tmp_upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tmp")
os.makedirs(tmp_upload_dir, exist_ok=True)


