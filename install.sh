#!/bin/bash
echo ""
echo "================================================"
echo "  NoiseGuard 安装向导"
echo "================================================"
echo ""

# 检查 Python
if command -v python3 &>/dev/null; then
    echo "[√] 已检测到 Python:"
    python3 --version
    echo ""
else
    echo "[×] 未检测到 Python3！"
    echo ""
    echo "   请先安装 Python:"
    echo "   brew install python3"
    echo ""
    exit 1
fi

cd "$(dirname "$0")"

echo "[1/3] 创建虚拟环境..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "创建虚拟环境失败！"
        exit 1
    fi
    echo "      完成"
else
    echo "      已存在，跳过"
fi

echo "[2/3] 安装依赖包 (可能需要几分钟)..."
source .venv/bin/activate
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "安装依赖失败！请检查网络连接。"
    exit 1
fi
echo "      完成"

echo "[3/3] 安装完成！"
echo ""
echo "================================================"
echo "  安装成功！"
echo ""
echo "  启动方式: ./start.sh"
echo "  然后浏览器打开 http://127.0.0.1:8899"
echo "================================================"
echo ""
