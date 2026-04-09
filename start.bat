@echo off
chcp 65001 >nul
echo ========================================
echo   物料管理系统 - 启动中...
echo ========================================
echo.

cd /d "%~dp0"

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

REM 安装依赖
echo [1/2] 安装依赖包...
pip install flask flask-cors -q

echo [2/2] 启动服务...
echo.
echo  访问地址：http://localhost:5000
echo  局域网访问：http://[本机IP]:5000
echo.
echo  默认管理员账号：shangtai / st999777
echo.
echo  按 Ctrl+C 停止服务
echo ========================================
python app.py
pause
