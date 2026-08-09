# Windows 安装与启动

## 1. 安装基础软件

安装以下软件：

- Git
- Anaconda 或 Miniconda
- Node.js 20 或更高版本
- Ollama

安装完成后打开 Anaconda Prompt 或 PowerShell，检查命令：

```powershell
git --version
conda --version
node --version
npm --version
ollama --version
```

## 2. 下载项目

```powershell
git clone https://github.com/gwen94426-bot/knowledge-exam-generator.git
cd knowledge-exam-generator
```

## 3. 创建 Python 环境

```powershell
conda create -n exam_rag python=3.12 -y
conda activate exam_rag
```

## 4. 安装后端依赖

```powershell
cd backend
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
cd ..
```

## 5. 安装前端依赖

```powershell
cd frontend
copy .env.example .env
npm install
cd ..
```

## 6. 下载 Ollama 模型

先启动 Ollama，然后在 PowerShell 中执行：

```powershell
ollama pull qwen2.5:7b
ollama pull bge-m3
```

## 7. 一键启动项目

在项目根目录执行：

```powershell
conda activate exam_rag
.\scripts\start_all.bat
```

启动成功后访问：

```text
前端页面：http://127.0.0.1:5173
后端接口：http://127.0.0.1:8000
健康检查：http://127.0.0.1:8000/api/v1/health/
Ollama：http://127.0.0.1:11434
```

## 8. 分别启动各项服务

终端 1，启动 Ollama：

```powershell
ollama serve
```

终端 2，启动任务 Worker：

```powershell
conda activate exam_rag
cd backend
python manage.py run_task_worker
```

终端 3，启动 Django 后端：

```powershell
conda activate exam_rag
cd backend
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

终端 4，启动 Vue 前端：

```powershell
cd frontend
npm run dev
```

## 9. 再次启动

以后每次运行只需打开 Ollama，然后执行：

```powershell
cd knowledge-exam-generator
conda activate exam_rag
.\scripts\start_all.bat
```
