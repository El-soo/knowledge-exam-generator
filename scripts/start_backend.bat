@echo off
setlocal
cd /d "%~dp0\..\backend"
if not exist .env copy .env.example .env >nul
python -c "import django, rest_framework" 2>nul || (echo 后端依赖未安装，请先运行 pip install -r backend\requirements.txt & exit /b 1)
netstat -ano | findstr ":8000 .*LISTENING" >nul && (echo 端口8000已被占用。 & exit /b 1)
python manage.py migrate || exit /b 1
echo 后端地址：http://127.0.0.1:8000
python manage.py runserver 127.0.0.1:8000
