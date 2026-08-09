#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"
cd "$FRONTEND_DIR"
command -v npm >/dev/null 2>&1 || { echo "未找到npm，请先安装Node.js 20或更高版本。"; exit 1; }
if [ ! -f .env ]; then cp .env.example .env; echo "已从.env.example创建.env"; fi
if [ ! -d node_modules ]; then echo "首次运行，正在安装前端依赖..."; npm install; fi
if lsof -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then echo "端口5173已被占用，请关闭占用程序后重试。"; exit 1; fi
echo "前端地址：http://127.0.0.1:5173"
npm run dev
