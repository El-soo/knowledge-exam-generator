#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR/backend"
if [ ! -f .env ]; then cp .env.example .env; fi
python -c "import django, rest_framework" 2>/dev/null || { echo "后端依赖未安装。请先激活 exam_rag，再进入 backend 执行: python -m pip install -r requirements.txt"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "未找到npm，请先安装Node.js。"; exit 1; }
for port in 8000 5173; do if lsof -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then echo "端口$port已被占用，请先关闭占用程序。"; exit 1; fi; done
python manage.py migrate
python manage.py run_task_worker & WORKER_PID=$!
python manage.py runserver 127.0.0.1:8000 & BACKEND_PID=$!
cd "$PROJECT_DIR/frontend"
if [ ! -f .env ]; then cp .env.example .env; fi
if [ ! -d node_modules ]; then npm install; fi
echo "系统正在启动：前端 http://127.0.0.1:5173，后端 http://127.0.0.1:8000，Ollama http://127.0.0.1:11434"
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || echo "提醒：Ollama 尚未连接。请运行 open -a Ollama，或在单独终端运行 ollama serve。"
trap 'kill $WORKER_PID $BACKEND_PID 2>/dev/null || true' EXIT INT TERM
npm run dev
