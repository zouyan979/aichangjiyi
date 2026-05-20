@echo off
chcp 65001 >nul
echo ========================================
echo   Memoria Desktop 打包工具
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: Install dependencies
echo [1/3] 安装依赖...
pip install -r backend\requirements.txt pywebview pyinstaller --quiet
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

:: Build
echo [2/3] 打包中... (首次约需2-5分钟)
pyinstaller memoria_desktop.spec --clean --noconfirm
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

:: Done
echo [3/3] 打包完成！
echo.
echo 输出文件: dist\Memoria.exe
echo.
echo 使用说明:
echo   1. 将 dist\Memoria.exe 复制到任意文件夹
echo   2. 双击运行即可
echo   3. 数据保存在 exe 同目录的 data\ 文件夹中
echo.
pause
