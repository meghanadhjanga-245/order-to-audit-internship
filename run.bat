@echo off
REM One command to run the Order-to-Audit prototype on Windows.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || goto :error
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\python -m pip install --quiet -r requirements.txt || goto :error
)

echo Applying migrations...
.venv\Scripts\python manage.py migrate --noinput || goto :error

echo Loading benchmark data (skipped if already present)...
.venv\Scripts\python manage.py seed_benchmark

echo.
echo   Open http://127.0.0.1:8000/  - password for every demo login is benchmark123
echo.
.venv\Scripts\python manage.py runserver 8000
goto :eof

:error
echo.
echo Setup failed. Check the messages above.
exit /b 1
