#!/bin/bash
# 部署脚本 - 用于快速部署到生产环境（使用 Conda）

set -e

echo "=========================================="
echo "Whisper API 部署脚本 (使用 Conda)"
echo "=========================================="

# 配置变量（根据实际情况修改）
PROJECT_DIR="/opt/whisperTest"
SERVICE_USER="www-data"
CONDA_ENV_NAME="whisper-api"
PYTHON_VERSION="3.10"
CONDA_INSTALL_DIR="/opt/conda"

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then 
    echo "请使用 root 权限运行此脚本"
    exit 1
fi

# 函数：检查 conda 是否已安装
check_conda() {
    if command -v conda &> /dev/null; then
        echo "✓ Conda 已安装: $(conda --version)"
        return 0
    elif [ -f "$CONDA_INSTALL_DIR/bin/conda" ]; then
        echo "✓ Conda 已安装在 $CONDA_INSTALL_DIR"
        export PATH="$CONDA_INSTALL_DIR/bin:$PATH"
        return 0
    else
        return 1
    fi
}

# 函数：安装 Miniconda
install_conda() {
    echo "正在安装 Miniconda..."
    
    # 下载 Miniconda
    MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    MINICONDA_INSTALLER="/tmp/miniconda.sh"
    
    echo "下载 Miniconda 安装包..."
    wget -q $MINICONDA_URL -O $MINICONDA_INSTALLER
    
    echo "安装 Miniconda 到 $CONDA_INSTALL_DIR..."
    bash $MINICONDA_INSTALLER -b -p $CONDA_INSTALL_DIR
    
    # 初始化 conda
    $CONDA_INSTALL_DIR/bin/conda init bash
    
    # 添加到 PATH
    export PATH="$CONDA_INSTALL_DIR/bin:$PATH"
    
    # 清理安装包
    rm -f $MINICONDA_INSTALLER
    
    echo "✓ Miniconda 安装完成"
}

# 1. 创建项目目录
echo "创建项目目录..."
mkdir -p $PROJECT_DIR
mkdir -p $PROJECT_DIR/logs
mkdir -p $PROJECT_DIR/tmp

# 2. 安装系统依赖
echo "安装系统依赖..."
apt-get update
apt-get install -y wget bzip2
apt-get install -y ffmpeg nginx supervisor

# 3. 检查并安装 Conda
echo "检查 Conda 安装..."
if ! check_conda; then
    echo "Conda 未安装，开始安装..."
    install_conda
    # 重新检查
    if ! check_conda; then
        echo "错误: Conda 安装失败"
        exit 1
    fi
fi

# 确保 conda 在 PATH 中
if [ -f "$CONDA_INSTALL_DIR/bin/conda" ]; then
    export PATH="$CONDA_INSTALL_DIR/bin:$PATH"
fi

# 初始化 conda（如果还没有）
eval "$(conda shell.bash hook)"

# 4. 创建 Conda 虚拟环境
echo "创建 Conda 虚拟环境: $CONDA_ENV_NAME..."
cd $PROJECT_DIR

# 检查环境是否已存在
if conda env list | grep -q "^$CONDA_ENV_NAME "; then
    # 检查是否为交互式终端
    if [ -t 0 ]; then
        echo "环境 $CONDA_ENV_NAME 已存在，是否删除并重新创建? (y/N)"
        read -r response
        if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
            conda env remove -n $CONDA_ENV_NAME -y
        else
            echo "使用现有环境"
            conda activate $CONDA_ENV_NAME
        fi
    else
        # 非交互模式，使用现有环境
        echo "环境 $CONDA_ENV_NAME 已存在，使用现有环境"
        conda activate $CONDA_ENV_NAME
    fi
fi

# 创建新环境（如果不存在）
if ! conda env list | grep -q "^$CONDA_ENV_NAME "; then
    conda create -n $CONDA_ENV_NAME python=$PYTHON_VERSION -y
fi

# 激活环境
conda activate $CONDA_ENV_NAME

# 5. 安装 Python 依赖
echo "安装 Python 依赖..."
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# 6. 复制项目文件
echo "复制项目文件..."
# 假设当前目录是项目根目录
cp -r src scripts config services docs examples $PROJECT_DIR/ 2>/dev/null || true
cp requirements.txt $PROJECT_DIR/

# 7. 设置权限
echo "设置文件权限..."
chown -R $SERVICE_USER:$SERVICE_USER $PROJECT_DIR
chmod +x $PROJECT_DIR/*.py

# 8. 更新 systemd 服务文件中的 conda 路径
echo "配置 systemd 服务..."
CONDA_PYTHON="$CONDA_INSTALL_DIR/envs/$CONDA_ENV_NAME/bin/python"
CONDA_GUNICORN="$CONDA_INSTALL_DIR/envs/$CONDA_ENV_NAME/bin/gunicorn"

# 创建临时服务文件
sed "s|/opt/whisperTest/venv/bin|$CONDA_INSTALL_DIR/envs/$CONDA_ENV_NAME/bin|g" services/whisper-api.service > /tmp/whisper-api.service
sed "s|/opt/whisperTest/venv/bin|$CONDA_INSTALL_DIR/envs/$CONDA_ENV_NAME/bin|g" services/whisper-gradio.service > /tmp/whisper-gradio.service

# 添加 conda 初始化到服务文件
sed -i "1a\Environment=\"PATH=$CONDA_INSTALL_DIR/bin:$CONDA_INSTALL_DIR/envs/$CONDA_ENV_NAME/bin\"" /tmp/whisper-api.service
sed -i "1a\Environment=\"PATH=$CONDA_INSTALL_DIR/bin:$CONDA_INSTALL_DIR/envs/$CONDA_ENV_NAME/bin\"" /tmp/whisper-gradio.service

# 复制服务文件
cp /tmp/whisper-api.service /etc/systemd/system/
cp /tmp/whisper-gradio.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable whisper-api.service
systemctl enable whisper-gradio.service

# 9. 配置 Nginx
echo "配置 Nginx..."
cp config/nginx.conf /etc/nginx/sites-available/whisper-api
ln -sf /etc/nginx/sites-available/whisper-api /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx

# 10. 启动服务
echo "启动服务..."
systemctl start whisper-api.service
systemctl start whisper-gradio.service

# 11. 检查服务状态
echo "检查服务状态..."
sleep 3
systemctl status whisper-api.service --no-pager
systemctl status whisper-gradio.service --no-pager

echo "=========================================="
echo "部署完成！"
echo "=========================================="
echo "Conda 环境: $CONDA_ENV_NAME"
echo "Conda 路径: $CONDA_INSTALL_DIR"
echo "API 服务: http://localhost:18000"
echo "Gradio 界面: http://localhost:17000"
echo "API 文档: http://localhost:18000/docs"
echo ""
echo "管理命令:"
echo "  激活环境: conda activate $CONDA_ENV_NAME"
echo "  查看状态: systemctl status whisper-api"
echo "  查看日志: journalctl -u whisper-api -f"
echo "  重启服务: systemctl restart whisper-api"
echo "=========================================="

