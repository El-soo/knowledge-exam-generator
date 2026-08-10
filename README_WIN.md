# 知识库智能出题与组卷系统（Windows）

本项目是一个本地运行的教师工作台。后端使用 Django、LangGraph、SQLite、ChromaDB 和 Ollama，前端使用 Vue 3、Vite、Element Plus 与 ECharts。

系统运行时包含以下服务：

| 服务 | 地址或命令 | 功能 |
|---|---|---|
| Ollama | `http://127.0.0.1:11434` | 本地大模型服务 |
| Django | `http://127.0.0.1:8000` | 后端接口 |
| Worker | `python manage.py run_task_worker` | 文件解析、向量化和 AI 任务 |
| Vue | `http://127.0.0.1:5173` | 系统操作页面 |

## 一、从零安装

### 1. 安装 Conda

安装 Miniconda 或 Anaconda：

- Miniconda：<https://www.anaconda.com/docs/getting-started/miniconda/install>
- Anaconda：<https://www.anaconda.com/download>

安装完成后，从开始菜单打开 **Anaconda Prompt**：

```bat
conda --version
```

### 2. 创建 Python 环境

在 Anaconda Prompt 中执行：

```bat
conda create -n exam_rag python=3.11 -y
conda activate exam_rag
python --version
where python
```

### 3. 设置项目目录

本文使用下面的示例路径表示项目根目录：

```text
D:\你的路径\knowledge_exam_generator
```

将命令中的示例路径替换为电脑中 `knowledge_exam_generator` 文件夹的实际路径：

```bat
cd /d "D:\你的路径\knowledge_exam_generator"
dir
```

项目根目录中应包含 `backend`、`frontend`、`scripts`、`README_MAC.md` 和 `README_WIN.md`。

### 4. 安装后端

```bat
conda activate exam_rag
cd /d "D:\你的路径\knowledge_exam_generator\backend"
python -m pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
```

可选安装演示数据：

```bat
python manage.py seed_demo
```

### 5. 安装 Node.js 和前端

从 <https://nodejs.org/> 安装 Windows 64 位 Node.js LTS，版本要求为 `20.19` 或更高。

重新打开 Anaconda Prompt，执行：

```bat
node --version
npm --version
cd /d "D:\你的路径\knowledge_exam_generator\frontend"
copy .env.example .env
npm ci
```

### 6. 安装 Ollama 和模型

从 <https://ollama.com/download/windows> 安装 Windows 版 Ollama。启动 Ollama 后执行：

```bat
ollama --version
ollama pull qwen2.5:7b
ollama pull bge-m3
ollama list
```

`qwen2.5:7b` 用于出题、答案校验和质量审核，`bge-m3` 用于知识库文本向量化。

## 二、首次启动项目

### 方式一：一键启动

#### 第 1 步：启动 Ollama

从 Windows 开始菜单打开 Ollama，然后在 Anaconda Prompt 中检查服务：

```bat
curl http://127.0.0.1:11434/api/tags
ollama list
```

#### 第 2 步：打开 Anaconda Prompt

激活项目环境：

```bat
conda activate exam_rag
```

#### 第 3 步：进入项目根目录

```bat
cd /d "D:\你的路径\knowledge_exam_generator"
dir backend frontend scripts
```

#### 第 4 步：运行一键启动脚本

```bat
scripts\start_all.bat
```

脚本会依次完成以下操作：

1. 读取后端和前端 `.env` 配置；
2. 执行数据库迁移；
3. 打开“任务Worker”窗口；
4. 打开“Django后端”窗口；
5. 在当前窗口启动 Vue 前端。

启动后会看到三个命令窗口：

| 窗口 | 运行内容 |
|---|---|
| 当前 Anaconda Prompt | Vue 前端 |
| Django后端 | Django 接口服务 |
| 任务Worker | 文件处理和 AI 任务服务 |

启动成功后打开浏览器访问：

<http://127.0.0.1:5173>

可通过以下地址查看各服务：

| 内容 | 地址 |
|---|---|
| 系统页面 | <http://127.0.0.1:5173> |
| 后端健康检查 | <http://127.0.0.1:8000/api/v1/health/> |
| Ollama 模型列表 | <http://127.0.0.1:11434/api/tags> |

### 方式二：分别启动

分别启动时共使用四个程序或命令窗口。

#### 窗口 1：Ollama

从 Windows 开始菜单打开 Ollama。

也可以在一个命令窗口中运行：

```bat
ollama serve
```

#### 窗口 2：Django 后端

打开 Anaconda Prompt：

```bat
conda activate exam_rag
cd /d "D:\py project\基于大模型与RAG的知识库智能出题与组卷系统\knowledge_exam_generator\backend"
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

后端地址：<http://127.0.0.1:8000>

#### 窗口 3：后台 Worker

再打开一个 Anaconda Prompt：

```bat
conda activate exam_rag
cd /d "D:\py project\基于大模型与RAG的知识库智能出题与组卷系统\knowledge_exam_generator\backend"
python manage.py run_task_worker
```

Worker 负责文件解析、知识库向量化、AI 出题和多智能体任务。

#### 窗口 4：Vue 前端

再打开一个 Anaconda Prompt：

```bat
cd /d "D:\py project\基于大模型与RAG的知识库智能出题与组卷系统\knowledge_exam_generator\frontend"
npm run dev
```

前端地址：<http://127.0.0.1:5173>

## 三、以后启动项目

以后启动时执行以下流程：

1. 从开始菜单打开 Ollama；
2. 打开 Anaconda Prompt；
3. 运行下面的命令。

```bat
conda activate exam_rag
cd /d "D:\你的路径\knowledge_exam_generator"
scripts\start_all.bat
```

浏览器访问：<http://127.0.0.1:5173>

## 四、使用单独脚本启动

只启动 Django 后端：

```bat
conda activate exam_rag
cd /d "D:\你的路径\knowledge_exam_generator"
scripts\start_backend.bat
```

只启动 Vue 前端：

```bat
cd /d "D:\你的路径\knowledge_exam_generator"
scripts\start_frontend.bat
```

单独启动后端时，Worker 使用下面的命令启动：

```bat
conda activate exam_rag
cd /d "D:\你的路径\knowledge_exam_generator\backend"
python manage.py run_task_worker
```

## 五、停止项目

一键启动模式下，在 Vue、Django 和 Worker 三个窗口中分别按 `Ctrl+C`，然后关闭对应窗口。Ollama 可从 Windows 系统托盘退出。

分别启动模式下，在 Django、Worker、Vue 对应的窗口中分别按 `Ctrl+C`，然后退出 Ollama。

## 六、项目验证

后端检查与测试：

```bat
conda activate exam_rag
cd /d "D:\你的路径\knowledge_exam_generator\backend"
python manage.py check
python manage.py test
```

前端构建：

```bat
cd /d "D:\你的路径\knowledge_exam_generator\frontend"
npm run build
```

## 七、数据目录

| 内容 | 路径 |
|---|---|
| SQLite 数据库 | `backend\db.sqlite3` |
| 上传资料 | `backend\media\knowledge_files\` |
| 导出文件 | `backend\media\exports\` |
| Chroma 向量索引 | `backend\data\chroma\` |
| 多智能体断点 | `backend\data\agent_checkpoints.sqlite3` |
| 应用日志 | `backend\logs\app.log` |
| Worker 日志 | `backend\logs\task_worker.log` |
