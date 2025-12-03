# 生产环境部署指南

本文档介绍如何稳定地部署 Whisper 音频转文字服务到生产环境。

## 目录

- [方案一：使用 Systemd + Nginx](#方案一使用-systemd--nginx)
- [方案二：使用 Supervisor + Nginx](#方案二使用-supervisor--nginx)
- [方案三：使用 Docker](#方案三使用-docker)
- [方案四：使用 Docker Compose](#方案四使用-docker-compose)
- [监控和维护](#监控和维护)

---

## 方案一：使用 Systemd + Nginx

### 1. 系统要求

- Ubuntu 20.04+ / Debian 11+ / CentOS 8+
- Python 3.10+
- 至少 4GB RAM（推荐 8GB+）
- 如果有 GPU，需要安装 CUDA

### 2. 快速部署（使用 Conda）

部署脚本会自动检查并安装 Conda（如果未安装），然后使用 Conda 创建虚拟环境。

```bash
# 1. 克隆或上传项目到服务器
cd /opt
git clone <your-repo> whisperTest
cd whisperTest

# 2. 运行自动部署脚本（会自动安装 Conda 和创建环境）
chmod +x deploy.sh
sudo ./deploy.sh
```

**注意**: 部署脚本会：
- 自动检查 Conda 是否已安装
- 如果未安装，自动下载并安装 Miniconda
- 使用 Conda 创建名为 `whisper-api` 的虚拟环境
- 自动配置 systemd 服务使用 Conda 环境

### 3. 手动安装 Conda（可选）

如果只想安装 Conda，可以单独运行：

```bash
chmod +x install_conda.sh
sudo ./install_conda.sh
```

### 4. 手动部署步骤

#### 4.1 安装 Conda（如果未安装）

```bash
# 方法 1: 使用安装脚本
chmod +x install_conda.sh
sudo ./install_conda.sh

# 方法 2: 手动安装
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/conda
export PATH="/opt/conda/bin:$PATH"
```

#### 4.2 创建 Conda 环境

```bash
# 初始化 conda
eval "$(conda shell.bash hook)"

# 创建环境
conda create -n whisper-api python=3.10 -y

# 激活环境
conda activate whisper-api
```

#### 4.3 安装依赖

```bash
# 安装系统依赖
sudo apt-get update
sudo apt-get install -y ffmpeg nginx

# 安装 Python 依赖
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

#### 4.4 配置 Systemd 服务

```bash
# 复制服务文件（已配置为使用 Conda）
sudo cp whisper-api.service /etc/systemd/system/
sudo cp whisper-gradio.service /etc/systemd/system/

# 如果 Conda 安装路径不同，需要修改服务文件
# 默认路径: /opt/conda/envs/whisper-api
sudo nano /etc/systemd/system/whisper-api.service

# 重新加载 systemd
sudo systemctl daemon-reload

# 启用并启动服务
sudo systemctl enable whisper-api.service
sudo systemctl enable whisper-gradio.service
sudo systemctl start whisper-api.service
sudo systemctl start whisper-gradio.service

# 检查状态
sudo systemctl status whisper-api.service
```

**注意**: 服务文件已配置为使用 Conda 环境。如果使用 venv，需要修改服务文件中的路径。

#### 4.5 配置 Nginx

```bash
# 复制配置文件
sudo cp nginx.conf /etc/nginx/sites-available/whisper-api

# 修改配置文件中的域名
sudo nano /etc/nginx/sites-available/whisper-api

# 创建软链接
sudo ln -s /etc/nginx/sites-available/whisper-api /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
```

### 4. 常用命令

```bash
# 查看服务状态
sudo systemctl status whisper-api
sudo systemctl status whisper-gradio

# 查看日志
sudo journalctl -u whisper-api -f
sudo journalctl -u whisper-gradio -f

# 重启服务
sudo systemctl restart whisper-api
sudo systemctl restart whisper-gradio

# 停止服务
sudo systemctl stop whisper-api
sudo systemctl stop whisper-gradio
```

---

## 方案二：使用 Supervisor + Nginx

Supervisor 是一个进程管理工具，适合需要更细粒度控制的场景。

### 1. 安装 Supervisor

```bash
# Ubuntu/Debian
sudo apt-get install supervisor

# CentOS/RHEL
sudo yum install supervisor
```

### 2. 配置 Supervisor

```bash
# 复制配置文件
sudo cp supervisor.conf /etc/supervisor/conf.d/whisper-api.conf

# 修改配置文件中的路径
sudo nano /etc/supervisor/conf.d/whisper-api.conf

# 重新加载配置
sudo supervisorctl reread
sudo supervisorctl update

# 启动服务
sudo supervisorctl start whisper-api:*
sudo supervisorctl start whisper-gradio:*
```

### 3. 管理命令

```bash
# 查看状态
sudo supervisorctl status

# 重启服务
sudo supervisorctl restart whisper-api:*

# 查看日志
sudo tail -f /opt/whisperTest/logs/api_supervisor.log
```

---

## 方案三：使用 Docker

### 1. 构建镜像

```bash
# 构建 Docker 镜像
docker build -t whisper-api:latest .

# 运行容器
docker run -d \
  --name whisper-api \
  -p 18000:18000 \
  -p 17000:17000 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/tmp:/app/tmp \
  whisper-api:latest
```

### 2. 查看日志

```bash
docker logs -f whisper-api
```

### 3. 停止和重启

```bash
docker stop whisper-api
docker start whisper-api
docker restart whisper-api
```

---

## 方案四：使用 Docker Compose

### 1. 启动服务

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 2. 更新服务

```bash
# 重新构建并启动
docker-compose up -d --build
```

---

## 监控和维护

### 1. 健康检查

```bash
# 检查 API 健康状态
curl http://localhost:18000/health

# 检查服务状态
systemctl status whisper-api
```

### 2. 日志管理

```bash
# 查看 API 日志
tail -f /opt/whisperTest/logs/gunicorn_access.log
tail -f /opt/whisperTest/logs/gunicorn_error.log

# 查看 Nginx 日志
tail -f /var/log/nginx/whisper_api_access.log
tail -f /var/log/nginx/whisper_api_error.log

# 使用 logrotate 管理日志（推荐）
sudo nano /etc/logrotate.d/whisper-api
```

### 3. 性能优化

#### 调整 Worker 数量

编辑 `gunicorn_config.py`:

```python
# 根据 CPU 核心数调整
workers = multiprocessing.cpu_count() * 2 + 1
```

#### 调整超时时间

如果处理大文件，增加超时时间：

```python
timeout = 600  # 10 分钟
```

#### 使用反向代理缓存

在 Nginx 配置中添加缓存：

```nginx
proxy_cache_path /var/cache/nginx/whisper levels=1:2 keys_zone=whisper_cache:10m max_size=1g;
```

### 4. 安全建议

1. **使用 HTTPS**: 配置 SSL 证书
2. **限制访问**: 使用防火墙规则
3. **API 密钥**: 添加认证中间件
4. **文件大小限制**: 在 Nginx 中设置 `client_max_body_size`
5. **CORS 配置**: 限制允许的源

### 5. 备份和恢复

```bash
# 备份配置
tar -czf whisper-backup-$(date +%Y%m%d).tar.gz \
  /opt/whisperTest \
  /etc/systemd/system/whisper-*.service \
  /etc/nginx/sites-available/whisper-api

# 恢复
tar -xzf whisper-backup-YYYYMMDD.tar.gz -C /
```

### 6. 故障排查

#### 服务无法启动

```bash
# 检查端口占用
sudo netstat -tulpn | grep :18000

# 检查权限
ls -la /opt/whisperTest

# 检查日志
journalctl -u whisper-api -n 50
```

#### 内存不足

```bash
# 减少 worker 数量
# 编辑 gunicorn_config.py
workers = 2  # 减少 worker 数
```

#### 处理速度慢

1. 使用更小的模型（tiny/base）
2. 启用 GPU 加速
3. 增加服务器资源

---

## 推荐配置

### 小型部署（< 100 请求/天）
- 2 CPU 核心
- 4GB RAM
- 1-2 workers
- 使用 base 模型

### 中型部署（100-1000 请求/天）
- 4 CPU 核心
- 8GB RAM
- 4 workers
- 使用 small 模型

### 大型部署（> 1000 请求/天）
- 8+ CPU 核心
- 16GB+ RAM
- 8+ workers
- 使用 GPU 加速
- 负载均衡（多个实例）

---

## 常见问题

### Q: 如何处理大文件上传？

A: 增加 Nginx 和 Gunicorn 的超时时间和文件大小限制。

### Q: 如何启用 GPU 加速？

A: 确保安装了 CUDA 和 PyTorch GPU 版本，系统会自动检测。

### Q: 如何添加 API 认证？

A: 在 `api.py` 中添加认证中间件。

### Q: 如何监控服务？

A: 使用 Prometheus + Grafana 或简单的健康检查脚本。

---

## 技术支持

如有问题，请查看日志文件或提交 Issue。

