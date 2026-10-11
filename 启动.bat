@echo off
chcp 65001 >nul
title 期货数据工作台
cd /d "%~dp0"

set PY=
where python >nul 2>nul && set PY=python
if "%PY%"=="" (
  if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set PY="%LocalAppData%\Programs\Python\Python313\python.exe"
)
if "%PY%"=="" (
  echo [错误] 未找到 Python，请先安装 Python 3.9+ 并加入 PATH。
  pause
  exit /b 1
)

echo ==========================================================
echo   期货数据工作台 · 国内全品种全合约日K抓取与分析
echo   浏览器将自动打开 http://127.0.0.1:8770
echo   关闭本窗口即停止服务
echo ==========================================================
echo.

%PY% -c "import flask" 2>nul
if errorlevel 1 (
  echo 正在安装依赖，请稍候...
  %PY% -m pip install -r requirements.txt
  echo.
)

%PY% app.py
pause
