#!/bin/bash
echo ""
echo "================================================"
echo "  NoiseGuard 噪音监测系统"
echo "================================================"
echo ""
echo "  正在启动后端服务..."
echo "  启动后请用浏览器打开："
echo ""
echo "     http://127.0.0.1:8899"
echo ""
echo "  按 Ctrl+C 可停止服务"
echo "================================================"
echo ""
cd "$(dirname "$0")"
source .venv/bin/activate
python server.py
