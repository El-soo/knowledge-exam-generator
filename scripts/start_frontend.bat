@echo off
setlocal
cd /d "%~dp0\..\frontend"
where npm >nul 2>nul || (echo 未找到npm，请先安装Node.js。 & exit /b 1)
if not exist .env copy .env.example .env >nul
if not exist node_modules npm install || exit /b 1
netstat -ano | findstr ":5173 .*LISTENING" >nul && (echo 端口5173已被占用。 & exit /b 1)
echo 前端地址：http://127.0.0.1:5173
npm run dev
