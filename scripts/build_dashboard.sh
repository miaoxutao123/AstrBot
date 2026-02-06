#!/bin/bash
# Dashboard 前端构建脚本 (Unix/macOS/Linux)
# 使用方法: ./build_dashboard.sh [--dev | --clean | --no-install | --no-deploy]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

python3 scripts/build_dashboard.py "$@"
