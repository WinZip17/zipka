@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set WITH_LLAMA=0
set WITH_FINETUNE=0
set WITH_RAG=0
set SKIP_FRONTEND=0

:parse
if "%~1"=="" goto parsed
if /I "%~1"=="--with-llama" set WITH_LLAMA=1
if /I "%~1"=="--with-finetune" set WITH_FINETUNE=1
if /I "%~1"=="--with-rag" set WITH_RAG=1
if /I "%~1"=="--skip-frontend" set SKIP_FRONTEND=1
if /I "%~1"=="-h" goto help
if /I "%~1"=="--help" goto help
shift
goto parse

:help
echo Usage: setup_zipka.bat [--with-llama] [--with-finetune] [--with-rag] [--skip-frontend]
exit /b 0

:parsed
echo [Zipka setup] Проверка Python…

set "PY_LAUNCHER="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.11 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY_LAUNCHER=py -3.11"
)
if not defined PY_LAUNCHER (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_LAUNCHER=py -3"
  )
)
if not defined PY_LAUNCHER (
  where python >nul 2>&1
  if errorlevel 1 (
    echo [Zipka setup] ERROR: нужен Python 3.11+
    exit /b 1
  )
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
  if errorlevel 1 (
    echo [Zipka setup] ERROR: нужен Python 3.11+
    exit /b 1
  )
  set "PY_LAUNCHER=python"
)

echo [Zipka setup] Using: %PY_LAUNCHER%
%PY_LAUNCHER% --version

if not exist ".venv\Scripts\python.exe" (
  echo [Zipka setup] Создаю .venv …
  %PY_LAUNCHER% -m venv .venv
  if errorlevel 1 exit /b 1
)

set "PY=.venv\Scripts\python.exe"
set "PIP=.venv\Scripts\pip.exe"

echo [Zipka setup] Обновляю pip …
"%PY%" -m pip install -U pip setuptools wheel
if errorlevel 1 exit /b 1

echo [Zipka setup] Ставлю requirements.txt …
"%PIP%" install -r requirements.txt
if errorlevel 1 exit /b 1

echo [Zipka setup] Ставлю пакет zipka ^(editable^) …
"%PIP%" install -e .
if errorlevel 1 exit /b 1

if "%WITH_FINETUNE%"=="1" (
  echo [Zipka setup] Ставлю extras [finetune] …
  "%PIP%" install -e ".[finetune]"
  if errorlevel 1 exit /b 1
)
if "%WITH_RAG%"=="1" (
  echo [Zipka setup] Ставлю extras [rag] …
  "%PIP%" install -e ".[rag]"
  if errorlevel 1 exit /b 1
)

if "%WITH_LLAMA%"=="1" (
  echo [Zipka setup] Ставлю llama-cpp-python ^(CPU wheel^) …
  "%PIP%" install llama-cpp-python --only-binary=:all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
  if errorlevel 1 echo [Zipka setup] WARN: llama-cpp-python не установился
) else (
  "%PY%" -c "import llama_cpp" >nul 2>&1
  if errorlevel 1 echo [Zipka setup] llama-cpp-python не найден. Позже: setup_zipka.bat --with-llama
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [Zipka setup] Создан .env из .env.example
  )
) else (
  echo [Zipka setup] .env уже есть
)

if "%SKIP_FRONTEND%"=="1" goto skip_fe
where npm >nul 2>&1
if errorlevel 1 (
  echo [Zipka setup] ERROR: npm не найден — поставь Node.js 18+
  exit /b 1
)
echo [Zipka setup] Node/npm найдены
pushd web\frontend
echo [Zipka setup] npm install …
call npm install
if errorlevel 1 (
  popd
  exit /b 1
)
if not exist "dist\index.html" (
  echo [Zipka setup] npm run build …
  call npm run build
  if errorlevel 1 (
    popd
    exit /b 1
  )
) else (
  echo [Zipka setup] web\frontend\dist уже собран
)
popd
goto after_fe

:skip_fe
echo [Zipka setup] Frontend пропущен

:after_fe
if not exist "data\models" mkdir "data\models"
if not exist "data\settings" mkdir "data\settings"

echo [Zipka setup] Готово.
echo Запуск Web UI:  start_zipka.bat
echo IDE: Run → Zipka: Web UI ^(Windows^)  или  Zipka: Web UI
echo URL: http://127.0.0.1:8765
exit /b 0
