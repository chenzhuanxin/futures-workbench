@echo off
chcp 65001 >nul
setlocal

echo ============================================================
echo   期货数据工作台 · 打包为单文件 exe
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/3] 检查 PyInstaller ...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
  echo       未安装，正在安装 ...
  python -m pip install pyinstaller
  if errorlevel 1 (
    echo.
    echo   [错误] PyInstaller 安装失败，请检查网络或 Python 环境。
    pause
    exit /b 1
  )
)
echo       已就绪。
echo.

echo [2/3] 清理旧产物 ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist FuturesWorkbench.spec del /q FuturesWorkbench.spec
echo       完成。
echo.

echo [3/3] 开始打包（首次约需 5~15 分钟，请勿关闭窗口）...
echo.
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name FuturesWorkbench ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "demo_data.json;." ^
  --add-data "_pickdir.py;." ^
  --collect-all akshare ^
  app.py

if errorlevel 1 (
  echo.
  echo   [错误] 打包失败，请查看上方日志。
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   打包完成！
echo   产物：%~dp0dist\FuturesWorkbench.exe
echo ============================================================
echo.
echo   提示：把 exe 放到任意目录双击即可运行。
echo   数据目录（期货日K数据 / 期货数据缓存）会生成在 exe 同目录下。
echo.
pause
