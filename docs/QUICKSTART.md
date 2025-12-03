# 快速开始指南

## 使用 Conda 部署（推荐）

### 一键部署

```bash
# 1. 克隆项目
git clone <your-repo>
cd whisperTest

# 2. 运行部署脚本（会自动安装 Conda 和所有依赖）
chmod +x deploy.sh
sudo ./deploy.sh
```

部署脚本会自动：
- ✅ 检查并安装 Conda（如果未安装）
- ✅ 创建 Conda 虚拟环境 `whisper-api`
- ✅ 安装所有 Python 依赖
- ✅ 配置 systemd 服务
- ✅ 配置 Nginx 反向代理
- ✅ 启动所有服务

### 手动部署

#### 1. 安装 Conda

```bash
# 使用安装脚本
chmod +x install_conda.sh
sudo ./install_conda.sh

# 或手动安装
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/conda
export PATH="/opt/conda/bin:$PATH"
```

#### 2. 创建环境并安装依赖

```bash
# 初始化 conda
eval "$(conda shell.bash hook)"

# 创建环境
conda create -n whisper-api python=3.10 -y
conda activate whisper-api

# 安装依赖
pip install -r requirements.txt
pip install gunicorn
```

#### 3. 配置服务

```bash
# 复制服务文件
sudo cp whisper-api.service /etc/systemd/system/
sudo cp whisper-gradio.service /etc/systemd/system/

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable whisper-api whisper-gradio
sudo systemctl start whisper-api whisper-gradio
```

## 验证部署

```bash
# 检查服务状态
sudo systemctl status whisper-api
sudo systemctl status whisper-gradio

# 测试 API
curl http://localhost:18000/health

# 访问 Web 界面
# 浏览器打开: http://localhost:17000

# 查看 API 文档
# 浏览器打开: http://localhost:18000/docs
```

## 常用命令

```bash
# 激活 Conda 环境
conda activate whisper-api

# 查看服务日志
sudo journalctl -u whisper-api -f
sudo journalctl -u whisper-gradio -f

# 重启服务
sudo systemctl restart whisper-api
sudo systemctl restart whisper-gradio

# 停止服务
sudo systemctl stop whisper-api
sudo systemctl stop whisper-gradio
```

## 故障排查

### Conda 未找到

```bash
# 添加 Conda 到 PATH
export PATH="/opt/conda/bin:$PATH"

# 或添加到 ~/.bashrc
echo 'export PATH="/opt/conda/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 服务启动失败

```bash
# 查看详细错误日志
sudo journalctl -u whisper-api -n 50 --no-pager

# 检查 Conda 环境路径
ls -la /opt/conda/envs/whisper-api/bin/

# 手动测试
conda activate whisper-api
python -c "import fastapi; print('OK')"
```

### 端口被占用

```bash
# 检查端口占用
sudo netstat -tulpn | grep :18000
sudo netstat -tulpn | grep :17000

# 修改端口（编辑服务文件）
sudo nano /etc/systemd/system/whisper-api.service
```

## 更多信息

详细部署文档请参考 [DEPLOYMENT.md](DEPLOYMENT.md)


