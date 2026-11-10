@echo off
chcp 65001 >nul
echo ========================================
echo   物料管理系统 - 启动中...
echo ========================================
echo.

cd /d "%~dp0"

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

REM 首次运行安装依赖（仅在 flask 未安装时执行，避免每次启动都联网）
python -c "import flask, flask_cors" >nul 2>&1
if errorlevel 1 (
    echo [1/2] 首次运行，安装依赖包...
    pip install -r requirements.txt -q
) else (
    echo [1/2] 依赖已就绪，跳过安装
)

echo [2/2] 启动服务...
echo.
echo  访问地址：http://localhost:5000
echo  局域网访问：http://[本机IP]:5000
echo.
echo  默认管理员账号：admin / admin001
echo  （生产环境请首次登录后立即修改，并设置 WMS_SECRET_KEY 环境变量）
echo.
echo  按 Ctrl+C 停止服务
echo ========================================
python app.py
pause
