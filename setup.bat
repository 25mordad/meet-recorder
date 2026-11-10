@echo off
rem One-time setup: creates .venv and installs dependencies. Needs Python 3.10+ from python.org.
cd /d "%~dp0"
py -3 -m venv .venv || python -m venv .venv || goto :error
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt || goto :error
echo.
echo Setup done. Run tests with:  test.bat
echo Record a meeting with:      record.bat
goto :eof
:error
echo Setup failed.
exit /b 1
