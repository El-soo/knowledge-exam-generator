#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
cd "$BACKEND_DIR"
if [ ! -f .env ]; then cp .env.example .env; echo "已从.env.example创建.env"; fi
python -c "import django, rest_framework" 2>/dev/null || { echo "后端依赖未安装。请先激活 exam_rag，再进入 backend 执行: python -m pip install -r requirements.txt"; exit 1; }
if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then echo "端口8000已被占用，请关闭占用程序后重试。"; exit 1; fi
python manage.py migrate
echo "后端地址：http://127.0.0.1:8000"
python manage.py runserver 127.0.0.1:8000
