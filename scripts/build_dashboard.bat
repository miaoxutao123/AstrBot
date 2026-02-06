@echo off
REM Dashboard 前端构建脚本 (Windows)
REM 使用方法: build_dashboard.bat [--dev | --clean | --no-install | --no-deploy]

cd /d "%~dp0\.."
python scripts\build_dashboard.py %*
