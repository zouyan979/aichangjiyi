@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo ========================================
echo   Memoria Desktop Builder
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python 3.10+
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

echo [1/3] Installing dependencies...
%PYTHON% -m pip install -r backend\requirements.txt pywebview pyinstaller --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

echo [2/3] Building... (first time takes 2-5 min)
pyinstaller memoria_desktop.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] Build failed
    pause
    exit /b 1
)

echo [3/3] Done!
echo.
echo Output: dist\Memoria.exe
echo.
echo Usage:
echo   1. Copy dist\Memoria.exe to any folder
echo   2. Double-click to run
echo   3. Data saved in data\ folder next to the exe
echo.
pause
