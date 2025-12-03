#!/bin/bash
# 独立的 Conda 安装脚本
# 如果只需要安装 Conda，可以单独运行此脚本

set -e

CONDA_INSTALL_DIR="${CONDA_INSTALL_DIR:-/opt/conda}"

echo "=========================================="
echo "Miniconda 安装脚本"
echo "=========================================="

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then 
    echo "请使用 root 权限运行此脚本"
    exit 1
fi

# 检查 conda 是否已安装
if command -v conda &> /dev/null; then
    echo "✓ Conda 已安装: $(conda --version)"
    echo "Conda 路径: $(which conda)"
    exit 0
fi

if [ -f "$CONDA_INSTALL_DIR/bin/conda" ]; then
    echo "✓ Conda 已安装在 $CONDA_INSTALL_DIR"
    echo "请运行: export PATH=\"$CONDA_INSTALL_DIR/bin:\$PATH\""
    exit 0
fi

# 安装系统依赖
echo "安装系统依赖..."
if command -v apt-get &> /dev/null; then
    apt-get update
    apt-get install -y wget bzip2
elif command -v yum &> /dev/null; then
    yum install -y wget bzip2
else
    echo "警告: 未检测到包管理器，请手动安装 wget 和 bzip2"
fi

# 下载 Miniconda
echo "下载 Miniconda 安装包..."
MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
MINICONDA_INSTALLER="/tmp/miniconda.sh"

# 检测架构
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh"
    echo "检测到 ARM 架构，使用 ARM 版本"
fi

wget -q --show-progress $MINICONDA_URL -O $MINICONDA_INSTALLER

# 安装 Miniconda
echo "安装 Miniconda 到 $CONDA_INSTALL_DIR..."
bash $MINICONDA_INSTALLER -b -p $CONDA_INSTALL_DIR

# 初始化 conda
echo "初始化 Conda..."
$CONDA_INSTALL_DIR/bin/conda init bash

# 添加到系统 PATH（可选，推荐在用户 .bashrc 中添加）
echo "添加 Conda 到 PATH..."
export PATH="$CONDA_INSTALL_DIR/bin:$PATH"

# 验证安装
if [ -f "$CONDA_INSTALL_DIR/bin/conda" ]; then
    echo "✓ Miniconda 安装成功！"
    echo ""
    echo "Conda 版本: $($CONDA_INSTALL_DIR/bin/conda --version)"
    echo "安装路径: $CONDA_INSTALL_DIR"
    echo ""
    echo "使用方法:"
    echo "  1. 重新加载 shell: source ~/.bashrc"
    echo "  2. 或手动添加 PATH: export PATH=\"$CONDA_INSTALL_DIR/bin:\$PATH\""
    echo "  3. 创建环境: conda create -n myenv python=3.10"
    echo "  4. 激活环境: conda activate myenv"
else
    echo "✗ 安装失败"
    exit 1
fi

# 清理安装包
rm -f $MINICONDA_INSTALLER

echo "=========================================="
echo "安装完成！"
echo "=========================================="


