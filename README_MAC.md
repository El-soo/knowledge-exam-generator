# macOS 安装与启动

## 1. 安装 Homebrew

打开终端执行：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## 2. 安装基础软件

```bash
brew install git python@3.12 node
brew install --cask ollama
```

检查安装结果：

```bash
git --version
python3.12 --version
node --version
npm --version
ollama --version
```

## 3. 下载项目

```bash
git clone https://github.com/gwen94426-bot/knowledge-exam-generator.git
cd knowledge-exam-generator
```

## 4. 创建 Python 虚拟环境

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

## 5. 安装后端依赖

```bash
cd backend
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
cd ..
```

## 6. 安装前端依赖

```bash
cd frontend
cp .env.example .env
npm install
cd ..
```

## 7. 下载 Ollama 模型

打开 Ollama 应用，然后在终端执行：

```bash
ollama pull qwen2.5:7b
ollama pull bge-m3
```

## 8. 一键启动项目

在项目根目录执行：

```bash
source .venv/bin/activate
chmod +x scripts/*.sh
./scripts/start_all.sh
```

启动成功后访问：

```text
前端页面：http://127.0.0.1:5173
后端接口：http://127.0.0.1:8000
健康检查：http://127.0.0.1:8000/api/v1/health/
Ollama：http://127.0.0.1:11434
```

## 9. 分别启动各项服务

终端 1，启动 Ollama：

```bash
ollama serve
```

终端 2，启动任务 Worker：

```bash
cd knowledge-exam-generator
source .venv/bin/activate
cd backend
python manage.py run_task_worker
```

终端 3，启动 Django 后端：

```bash
cd knowledge-exam-generator
source .venv/bin/activate
cd backend
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

终端 4，启动 Vue 前端：

```bash
cd knowledge-exam-generator/frontend
npm run dev
```

## 10. 再次启动

以后每次运行只需打开 Ollama，然后执行：

```bash
cd knowledge-exam-generator
source .venv/bin/activate
./scripts/start_all.sh
```
