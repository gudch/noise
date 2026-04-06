@echo off
chcp 65001 >nul 2>&1
echo.
echo ================================================
echo   NoiseGuard 噪音监测系统
echo ================================================
echo.
echo   正在启动后端服务...
echo   启动后请用浏览器打开：
echo.
echo      http://127.0.0.1:8899
echo.
echo   按 Ctrl+C 可停止服务
echo ================================================
echo.
cd /d "%~dp0"
call .venv\Scripts\activate.bat 2>nul
python server.py
pause
