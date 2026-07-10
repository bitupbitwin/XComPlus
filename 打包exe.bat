@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在检查 PyInstaller...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    python -m pip install pyinstaller
)

echo 开始打包（首次约需几分钟）...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "X-COM+" --icon "assets\logo.ico" run.py

if errorlevel 1 (
    echo.
    echo 打包失败，请把上面的报错发给开发者
    pause
    exit /b 1
)

echo.
echo 打包完成！程序在 dist\X-COM+.exe，可复制到任意位置双击运行
pause
