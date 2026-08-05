@echo off
chcp 65001 >nul
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo 启动失败。请确认已安装 Python，并且可以在命令行运行 python。
  echo 如果是第一次使用，请先运行: pip install -r requirements.txt
  pause
)
