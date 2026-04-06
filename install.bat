@echo off
chcp 65001 >nul 2>&1
echo.
echo ================================================
echo   NoiseGuard 安装向导
echo ================================================
echo.

python --version >nul 2>&1
if %errorlevel%==0 (
    echo [√] 已检测到 Python:
    python --version
    echo.
) else (
    echo [×] 未检测到 Python！
    echo.
    echo    请先安装 Python:
    echo    https://www.python.org/downloads/
    echo.
    echo    安装时务必勾选 "Add Python to PATH"！
    echo.
    pause
    exit /b 1
)

echo [1/3] 创建虚拟环境...
if not exist ".venv" (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo 创建虚拟环境失败！
        pause
        exit /b 1
    )
    echo       完成
) else (
    echo       已存在，跳过
)

echo [2/3] 安装依赖包 (可能需要几分钟)...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo 安装依赖失败！请检查网络连接。
    pause
    exit /b 1
)
echo       完成

echo [3/3] 安装完成！
echo.
echo ================================================
echo   安装成功！
echo.
echo   启动方式: 双击 start.bat
echo   然后浏览器打开 http://127.0.0.1:8899
echo ================================================
echo.
pause
