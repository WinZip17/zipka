@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Zipka] Не найден .venv\Scripts\python.exe
  echo Сначала запусти setup_zipka.bat
  pause
  exit /b 1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo [Zipka] Чат в терминале. Выход: /quit
echo.
".venv\Scripts\python.exe" -m zipka.main chat
pause
