@echo off
setlocal
cd /d "%~dp0\..\backend"
if not exist .env copy .env.example .env >nul
python -c "import django, rest_framework" 2>nul || (echo 后端依赖未安装，请先运行 pip install -r requirements.txt & exit /b 1)
netstat -ano | findstr ":8000 .*LISTENING" >nul && (echo 端口8000已被占用。 & exit /b 1)
netstat -ano | findstr ":5173 .*LISTENING" >nul && (echo 端口5173已被占用。 & exit /b 1)
python manage.py migrate || exit /b 1
start "任务Worker" cmd /k "conda activate exam_rag && cd /d %CD% && python manage.py run_task_worker"
start "Django后端" cmd /k "conda activate exam_rag && cd /d %CD% && python manage.py runserver 127.0.0.1:8000"
cd /d "%~dp0\..\frontend"
if not exist .env copy .env.example .env >nul
if not exist node_modules npm install || exit /b 1
echo 前端：http://127.0.0.1:5173  后端：http://127.0.0.1:8000  Ollama：http://127.0.0.1:11434
npm run dev
