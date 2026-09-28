@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Zipka] Не найден .venv\Scripts\python.exe
  echo Создай venv и поставь зависимости: pip install -r requirements.txt
  pause
  exit /b 1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo [Zipka] Запуск Web UI...
echo Открой в браузере: http://127.0.0.1:8765
echo Закрой это окно, чтобы остановить сервер.
echo.

".venv\Scripts\python.exe" -m zipka.main web
if errorlevel 1 pause
